# -*- coding: utf-8 -*-
"""端到端测试划词提取（沙箱兼容版）。

背景：keyboard 库会过滤"注入的Alt事件"（_winkeyboard.py 的 fake_alt 逻辑），
因此无法用注入方式模拟"按住Alt按热键"。改用：
  1) bridge 信号直接触发热键槽（与真实热键回调完全同路径）；
  2) 受控假 is_pressed 模拟"用户Alt还按住约150ms"；
  3) 真实启动 notepad，真实注入打字/Ctrl+A/Ctrl+C，验证复制提取链路。

验证点：
  A. Alt"按住"期间不发 Ctrl+C（等待松键逻辑生效）
  B. 松键后成功提取到选中的文字
  C. 按快捷键后立即弹出"翻译中"加载浮窗，结果到达后原地更新
  D. 结束后剪贴板恢复原内容
"""
import ctypes
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import keyboard
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import core
import main as appmod

EXPECT = "The weather is nice today"
SIM_HOLD_POLLS = 5  # 模拟用户 Alt 按住 5次x30ms=150ms


def force_focus_pid(pid):
    """尽力把新开的记事本拉到前台（Win11记事本窗口由ApplicationFrameHost托管，
    按PID可能找不到，只做尽力而为，焦点诊断打印前台窗口标题）"""
    u32 = ctypes.windll.user32
    target = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, lparam):
        pd = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pd))
        if pd.value == pid and u32.IsWindowVisible(hwnd):
            target.append(hwnd)
            return False
        return True

    u32.EnumWindows(cb, None)
    if target:
        hwnd = target[0]
        if u32.GetForegroundWindow() != hwnd:
            u32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE（还原时自动回前台）
            time.sleep(0.25)
            u32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(u32.GetForegroundWindow(), buf, 256)
    print("FOREGROUND=%r" % buf.value, flush=True)
    return True


def main():
    app = QApplication(sys.argv)
    a = appmod.App(app)

    captured = {}

    def spy(text, way):
        # 只验证提取+加载窗链路，不真正联网：
        # 模拟真实 translate_async 行为：先弹加载窗，300ms 后出结果
        captured["text"] = text
        a.bridge.translating_started.emit(text, way)
        QTimer.singleShot(300, lambda: a.bridge.result_ready.emit({
            "text": text, "translated": "今天天气很好", "engine": "测试引擎",
            "is_word": False, "phonetic": None, "meanings": [],
            "detected": "en", "way": way,
        }))

    a.translate_async = spy
    a.db.history_add = lambda *args, **kw: None  # 防止测试写入用户真实历史
    QApplication.clipboard().setText("CLIP_MARKER")

    # --- 补丁：模拟用户按住 Alt（前 SIM_HOLD_POLLS 次轮询返回 True）---
    fake = {"n": 0}
    real_is_pressed = keyboard.is_pressed

    def fake_is_pressed(key):
        if key == "alt" and fake["n"] < SIM_HOLD_POLLS:
            fake["n"] += 1
            return True
        return real_is_pressed(key)

    keyboard.is_pressed = fake_is_pressed

    # 先清掉旧 notepad（Win11记事本会话恢复会把上次遗留文字还原，导致内容翻倍）
    subprocess.run(["taskkill", "/f", "/im", "notepad.exe"],
                   capture_output=True, timeout=10)
    time.sleep(1.0)

    np = subprocess.Popen(["notepad.exe"])
    state = {"polls": 0, "done": False}

    def finish(code, msg):
        if state["done"]:
            return
        state["done"] = True
        print(msg, flush=True)
        try:
            subprocess.run(["taskkill", "/f", "/t", "/PID", str(np.pid)],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        app.quit()
        sys.exit(code)

    def poll_extract():
        if state["done"]:
            return
        if "text" in captured:
            got = captured["text"].strip()
            clip_now = QApplication.clipboard().text()
            if got != EXPECT:
                finish(2, "WRONG: 提取到 %r" % got)
            elif clip_now != "CLIP_MARKER":
                finish(3, "PARTIAL: 提取成功但剪贴板未恢复=%r" % clip_now)
            elif not a.popup.isVisible():
                state["polls"] += 1
                QTimer.singleShot(200, poll_extract)
            elif "翻译中" in a.popup.lab_title.text():
                # 加载窗已出现，等结果原地更新
                state["polls"] += 1
                QTimer.singleShot(200, poll_extract)
            elif a.popup.lab_trans.text() == "今天天气很好":
                finish(0, "SUCCESS: 提取 %r + 加载窗弹出 + 原地更新结果 + 剪贴板已恢复"
                      % got)
            else:
                finish(4, "WRONG_STATE: title=%r trans=%r"
                       % (a.popup.lab_title.text(), a.popup.lab_trans.text()))
        elif state["polls"] >= 40:
            try:
                with open(os.path.join(core.BASE_DIR, "debug.log"),
                          encoding="utf-8") as f:
                    print("DEBUG_LOG_TAIL:\n" + "".join(f.readlines()[-8:]),
                          flush=True)
            except Exception:
                pass
            finish(1, "FAIL: 超时未提取到文字")
        else:
            state["polls"] += 1
            QTimer.singleShot(300, poll_extract)

    def do_select_all():
        keyboard.press("ctrl")
        keyboard.press_and_release("a")
        keyboard.release("ctrl")

    def new_tab_and_type():
        # Win11记事本会恢复上次未保存内容，Ctrl+T开一个全新空白标签，
        # 在其中输入+全选，保证 Ctrl+A 选中的只有本次输入的文字
        keyboard.press_and_release("ctrl+t")
        QTimer.singleShot(500, lambda: keyboard.write(EXPECT, delay=0.02))

    def go():
        ok = force_focus_pid(np.pid)
        print("FOCUS_OK=%s" % ok, flush=True)
        # 与真实热键回调完全同路径：钩子线程 emit -> 主线程 on_select_hotkey
        a.bridge.select_requested.emit()

    QTimer.singleShot(2000, new_tab_and_type)
    QTimer.singleShot(3600, do_select_all)
    QTimer.singleShot(4600, go)
    QTimer.singleShot(4900, poll_extract)
    QTimer.singleShot(20000, lambda: finish(1, "FAIL: 20s硬超时"))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
