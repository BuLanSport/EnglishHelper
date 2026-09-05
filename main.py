# -*- coding: utf-8 -*-
"""英译通 EnglishHelper - 主程序：托盘 + 全局热键 + 划词/截图翻译"""
import os
import sys
import time
import threading

import keyboard
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QLockFile
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
import ui

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def make_tray_icon():
    """程序图标：优先加载 assets/icon.ico（与 exe 图标统一），失败则代码绘制"""
    for path in (
        os.path.join(BASE_DIR, "assets", "icon.ico"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "assets", "icon.ico"),
    ):
        try:
            if path and os.path.exists(path):
                return QIcon(path)
        except Exception:
            pass
    # 回退：蓝底白色“译”字
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2563eb"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor("white"))
    p.setFont(QFont("Microsoft YaHei", 26, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "译")
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    """全局热键回调（键盘钩子线程）→ Qt 主线程 的信号桥"""
    select_requested = Signal()
    capture_requested = Signal()
    translating_started = Signal(str, str)  # (text, way)：立即弹"翻译中"浮窗
    result_ready = Signal(dict)
    task_failed = Signal(str)
    notify = Signal(str, str)  # 标题, 内容


def _make_tts():
    """Qt 内置 TTS（走系统 SAPI），朗读零进程开销、毫秒级响应；
    环境/打包缺 QtTextToSpeech 或系统无语音时返回 None，调用方退回 PowerShell 通道"""
    try:
        from PySide6.QtTextToSpeech import QTextToSpeech
        tts = QTextToSpeech()
        if not tts.availableVoices():
            return None
        return tts
    except Exception:
        return None


class App:
    def __init__(self, app: QApplication):
        self.app = app
        self.cfg = core.load_config()
        self.db = core.DB()
        self.bridge = Bridge()
        self.tray = QSystemTrayIcon(make_tray_icon())
        self.popup = ui.ResultPopup()
        self.mainwin = ui.MainWindow(self.cfg, self.db)
        self._tts = _make_tts()  # Qt TTS（SAPI），朗读不再每次启动 PowerShell
        self.overlay = None
        self._hotkeys = []
        self._busy = False  # 防止热键连按重复触发
        self._trans_seq = 0  # 翻译请求序号：慢的旧结果回来时不覆盖新结果

        self.bridge.select_requested.connect(self.on_select_hotkey)
        self.bridge.capture_requested.connect(self.on_capture_hotkey)
        self.bridge.translating_started.connect(self.on_translating)
        self.bridge.result_ready.connect(self.show_result)
        self.bridge.task_failed.connect(self.show_error)
        self.bridge.notify.connect(self.balloon)

        self.popup.request_speak.connect(self.speak)
        self.mainwin.request_speak.connect(self.speak)
        self.mainwin.config_changed.connect(self.rehook_hotkeys)

        self.build_tray_menu()
        self.rehook_hotkeys()
        self.tray.show()
        self.tray.showMessage(
            "英译通已启动",
            "选中英文按 %s 翻译；按 %s 框选文字截图翻译。\n点托盘图标打开历史记录和设置。"
            % (self.cfg["hotkey_select"].upper(), self.cfg["hotkey_capture"].upper()),
            QSystemTrayIcon.Information, 6000)

        # 后台预热OCR模型（第一次截图翻译就不用等）
        threading.Thread(target=core.warmup_ocr, daemon=True).start()

    # ---------- 托盘 ----------
    def build_tray_menu(self):
        menu = QMenu()
        act_open = QAction("打开主窗口（历史/设置）", menu)
        act_cap = QAction("截图翻译（%s）" % self.cfg["hotkey_capture"].upper(), menu)
        act_select = QAction("划词翻译（先选中文字再按 %s）" % self.cfg["hotkey_select"].upper(), menu)
        self.act_select_toggle = QAction("划词翻译：开", menu, checkable=True)
        self.act_select_toggle.setChecked(self.cfg.get("select_enabled", True))
        self.act_select_toggle.toggled.connect(self.toggle_select)
        act_quit = QAction("退出", menu)
        menu.addAction(act_open)
        menu.addAction(act_cap)
        menu.addAction(act_select)
        menu.addSeparator()
        menu.addAction(self.act_select_toggle)
        menu.addSeparator()
        menu.addAction(act_quit)
        act_open.triggered.connect(self.open_mainwin)
        act_cap.triggered.connect(self.on_capture_hotkey)
        act_select.triggered.connect(self.on_select_hotkey)
        act_quit.triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.open_mainwin() if r == QSystemTrayIcon.Trigger else None)

    def open_mainwin(self):
        self.mainwin.refresh_all()
        self.mainwin.show()
        self.mainwin.raise_()
        self.mainwin.activateWindow()

    def toggle_select(self, on):
        self.cfg["select_enabled"] = bool(on)
        self.act_select_toggle.setText("划词翻译：开" if on else "划词翻译：关")
        core.save_config(self.cfg)

    def balloon(self, title, body):
        self.tray.showMessage(title, body, QSystemTrayIcon.Information, 5000)

    # ---------- 全局热键 ----------
    def rehook_hotkeys(self):
        self.cfg = core.load_config()
        for h in self._hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._hotkeys = []
        try:
            self._hotkeys.append(keyboard.add_hotkey(
                self.cfg["hotkey_select"],
                lambda: self.bridge.select_requested.emit(), suppress=False))
            self._hotkeys.append(keyboard.add_hotkey(
                self.cfg["hotkey_capture"],
                lambda: self.bridge.capture_requested.emit(), suppress=False))
        except Exception as e:
            self.balloon("快捷键注册失败", "错误信息：%s\n请尝试以管理员身份运行本软件。" % e)

    # ---------- 划词翻译 ----------
    def _log(self, msg):
        """划词调试日志，写入程序目录 debug.log（超过100KB自动截断）"""
        try:
            path = os.path.join(core.BASE_DIR, "debug.log")
            if os.path.exists(path) and os.path.getsize(path) > 100 * 1024:
                with open(path, "w", encoding="utf-8"):
                    pass
            with open(path, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
        except Exception:
            pass

    def on_select_hotkey(self):
        if not self.cfg.get("select_enabled", True) or self._busy:
            return
        self._busy = True
        clip = QApplication.clipboard()
        backup = clip.text()
        self._log("划词触发, 剪贴板备份%d字" % len(backup))
        self._wait_mods_released(backup, 1)

    def _wait_mods_released(self, backup, attempt):
        """等用户物理松开 Alt 等修饰键后，再模拟 Ctrl+C。
        关键修复：热键触发时用户手指还按着 Alt（松手约需100~250ms），
        此时发出的 Ctrl+C 会被系统合成 Ctrl+Alt+C，应用不理睬，
        导致剪贴板永远为空、提示"没有取到文字"。"""
        polls = {"n": 0}

        def poll():
            pressed = [k for k in ("alt", "ctrl", "shift", "windows")
                       if keyboard.is_pressed(k)]
            polls["n"] += 1
            if not pressed:
                if polls["n"] > 1:
                    self._log("修饰键已松开(等待约%dms)" % (polls["n"] * 30))
                self._do_copy(backup, attempt)
            elif polls["n"] > 33:  # 约1秒兜底：等不到也硬试一次
                self._log("等待松键超时(%s)，强制尝试复制" % ",".join(pressed))
                self._do_copy(backup, attempt)
            else:
                QTimer.singleShot(30, poll)

        poll()

    def _do_copy(self, backup, attempt):
        clip = QApplication.clipboard()
        clip.clear()
        # 第3次换 Ctrl+Insert 兜底（个别软件拦 Ctrl+C 但认 Ctrl+Insert）
        keyboard.press_and_release("ctrl+insert" if attempt >= 3 else "ctrl+c")

        def warn_fail():
            self._busy = False
            self._log("划词失败, 共尝试%d次" % attempt)
            self.balloon("没有取到文字",
                         "请先选中英文再按快捷键。\n"
                         "· 若目标软件以管理员身份运行，请右键英译通→以管理员身份运行；\n"
                         "· 若这块文字本来就选不中，请改用截图翻译（%s）。"
                         % self.cfg["hotkey_capture"].upper())

        def finish(text):
            self._log("划词成功(attempt=%d): %r" % (attempt, text[:60]))
            try:
                self.translate_async(text, way="划词")
            finally:
                if self.cfg.get("restore_clipboard", True) and backup:
                    clip.setText(backup)
                self._busy = False

        def after_copy():
            text = clip.text().strip()
            if text:
                finish(text)
            elif attempt < 3:
                self._log("第%d次复制为空, 自动重试" % attempt)
                self._do_copy(backup, attempt + 1)
            else:
                warn_fail()

        # 轮询剪贴板：目标程序收到 Ctrl+C 后一般在 30~150ms 内写入，
        # 相比原来固定等 320ms 明显更快出结果；400ms 仍为空才判定失败/重试
        state = {"n": 0}

        def poll():
            state["n"] += 1
            text = clip.text().strip()
            if text:
                after_copy()
            elif state["n"] >= 16:  # 16 × 25ms ≈ 400ms
                after_copy()
            else:
                QTimer.singleShot(25, poll)

        poll()

    # ---------- 截图翻译 ----------
    def on_capture_hotkey(self):
        if self.overlay is not None:  # 已在截图模式
            return
        from PySide6.QtGui import QCursor, QGuiApplication
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or self.app.primaryScreen()
        self.overlay = ui.Overlay(screen)
        self.overlay.selected.connect(self.on_captured)
        self.overlay.canceled.connect(lambda: setattr(self, "overlay", None))
        self.overlay.setGeometry(screen.geometry())
        self.overlay.show()

    def on_captured(self, qimage):
        self.overlay = None
        arr = ui.qimage_to_rgb_array(qimage)
        self.balloon("正在识别文字", "已截取图片，正在识别并翻译，请稍候…")
        self._trans_seq += 1
        seq = self._trans_seq

        def worker():
            try:
                text = core.ocr_image(arr)
                if not text.strip():
                    self.bridge.task_failed.emit("没有识别到文字。\n提示：框选时尽量贴近文字、框大一点。")
                    return
                self.bridge.translating_started.emit(text, "截图")  # OCR完弹"翻译中"浮窗
                res = core.translate(text, self.cfg)
                self.bridge.result_ready.emit({
                    "text": text, "translated": res["translated"],
                    "engine": res["engine"], "is_word": False,
                    "phonetic": None, "meanings": [], "detected": res.get("detected", "en"),
                    "way": "截图", "seq": seq, "reverse": res.get("reverse", False),
                })
            except Exception as e:
                self.bridge.task_failed.emit("截图翻译失败：%s" % e)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 翻译 ----------
    def on_translating(self, text, way):
        """取到文字开始翻译时立即弹"翻译中"浮窗，让用户知道程序在工作"""
        self.popup.show_loading(text, way)

    def translate_async(self, text, way):
        self._trans_seq += 1
        seq = self._trans_seq

        def worker():
            try:
                self.bridge.translating_started.emit(text, way)  # 先弹加载窗
                reverse = core.is_mostly_chinese(text)
                is_word = core.is_single_word(text) and not reverse  # 中文不走英汉词典
                phonetic, meanings = (None, [])
                if is_word:
                    phonetic, meanings = core.lookup_word(text)
                res = core.translate(text, self.cfg)
                self.bridge.result_ready.emit({
                    "text": text, "translated": res["translated"],
                    "engine": res["engine"], "is_word": is_word,
                    "phonetic": phonetic, "meanings": meanings,
                    "detected": res.get("detected", "en"), "way": way,
                    "seq": seq, "reverse": res.get("reverse", False),
                })
            except Exception as e:
                self.bridge.task_failed.emit("翻译失败：%s" % e)

        threading.Thread(target=worker, daemon=True).start()

    def show_result(self, data):
        seq = data.get("seq")
        if seq is not None and seq != self._trans_seq:
            self._log("忽略过期翻译结果(seq=%s < %d): %r"
                      % (seq, self._trans_seq, str(data.get("text"))[:30]))
            return  # 用户又查了新词，慢的旧结果不覆盖
        self.popup.show_result(data, int(self.cfg.get("show_popup_seconds", 12)))
        self.db.history_add(data.get("text", ""), data.get("translated", ""), data.get("way", "划词"))
        if self.cfg.get("auto_speak") and data.get("text"):
            self.speak(data["text"], "en" if data.get("detected", "en").startswith("en") else "zh")

    def show_error(self, msg):
        if getattr(self.popup, "_loading", False):
            self.popup.show_error(msg)  # 正在加载的浮窗原地显示错误
        else:
            self.balloon("翻译出错了", msg)

    # ---------- 学习 ----------
    def speak(self, text, lang):
        """朗读。优先 Qt TTS（主线程、异步、约 1ms 内返回）；
        引擎不可用时退回旧通道：后台线程启动 PowerShell SAPI"""
        text = (text or "").strip()[:220]
        if not text:
            return
        if self._tts is not None:
            try:
                from PySide6.QtCore import QLocale
                self._tts.setLocale(QLocale("en_US" if lang.startswith("en") else "zh_CN"))
                self._tts.stop()  # 打断上一次朗读，避免连续点击时语音堆叠
                self._tts.say(text)
                return
            except Exception:
                pass  # 语音引擎异常时退回 PowerShell 通道
        threading.Thread(target=core.speak, args=(text, lang), daemon=True).start()

    # ---------- 退出 ----------
    def quit(self):
        for h in self._hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self.tray.hide()
        self.app.quit()


def main():
    # 打包(windowed)模式下异常默认被吞掉，写入日志文件便于排查
    log_dir = core.BASE_DIR
    try:
        import faulthandler, traceback
        logf = open(os.path.join(log_dir, "debug.log"), "a", encoding="utf-8")

        def _hook(t, v, tb):
            try:
                traceback.print_exception(t, v, tb, file=logf)
                logf.flush()
            except Exception:
                pass

        sys.excepthook = _hook
        faulthandler.enable(logf)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("EnglishHelper")
    app.setWindowIcon(make_tray_icon())  # 窗口/任务栏图标（否则显示 Qt 默认图）
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet("QWidget{font-family:'Microsoft YaHei';font-size:13px;}")

    # 单实例锁（放在程序目录，TempLocation在打包环境下不可靠）
    lock_path = os.path.join(core.BASE_DIR, "app.lock")
    lock = QLockFile(lock_path)
    if not lock.tryLock(200):
        QMessageBox.information(None, "英译通", "英译通已经在运行了（请看屏幕右下角托盘图标）。")
        return

    a = App(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
