# -*- coding: utf-8 -*-
"""界面：截图选区遮罩 / 翻译结果弹窗 / 主窗口"""
import re
import time

from PySide6.QtCore import Qt, QRect, QTimer, Signal, QPoint, QBuffer, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QImage, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QTabWidget, QComboBox, QCheckBox, QHeaderView,
    QAbstractItemView, QApplication, QFrame, QMessageBox,
    QLineEdit, QScrollArea, QButtonGroup,
)

import core

STYLE = """
QWidget { font-family: "Microsoft YaHei"; font-size: 13px; }
QPushButton { padding: 6px 14px; border: 1px solid #c8ccd4; border-radius: 4px;
              background: #f7f8fa; color: #2b2f36; }
QPushButton:hover { background: #e8ecf3; border-color: #9aa4b2; }
QPushButton:pressed { background: #dde3ec; }
QTableWidget { border: 1px solid #d8dce4; gridline-color: #e8ebf0; selection-background-color: #3b82f6; }
QHeaderView::section { background: #f0f2f6; border: none; border-bottom: 1px solid #d8dce4; padding: 6px; }
QComboBox { padding: 4px 8px; border: 1px solid #c8ccd4; border-radius: 4px; background: white; }
"""


_ZWSP = "\u200b"                        # 零宽空格：仅显示层用于折行，不改变文本内容
_LONG_TOKEN_RE = re.compile(r"\S{40,}")  # URL、Windows 路径等超长不可断词


def _soft_wrap(text):
    """给超长不可断词每隔 32 字符插入零宽空格，使其能在词内部折行。
    QLabel 的 wordWrap 不会在超长词内部断行：它把 sizeHint 宽度撑到整个词的长度、
    高度只算一行，布局于是给标签一小块高度，文字底部被裁剪（表现为“译文/原文
    显示到一半突然没了”）。插入断行点后高度计算恢复正常。"""
    if not text:
        return text or ""

    def _split(m):
        s = m.group(0)
        return _ZWSP.join(s[i:i + 32] for i in range(0, len(s), 32))

    return _LONG_TOKEN_RE.sub(_split, text)


def _strip_soft_wrap(text):
    """复制时还原：去掉显示层插入的零宽空格"""
    return (text or "").replace(_ZWSP, "")


def _format_orig(text):
    """原文直接完整展示，不再截断；原文区本身在滚动区域内，
    浮窗高度受 _fit_size 限制为屏幕 70%，超出可滚动查看。"""
    if not text:
        return "原文：（未识别到原文）"
    return "原文：" + _soft_wrap(text.strip())


# ================= 截图选区遮罩 =================
class Overlay(QWidget):
    """全屏遮罩：显示按下快捷键瞬间“冻结”的屏幕画面，鼠标框选后发出 selected(QImage)。

    冻结画面（而不是松手后实时抓屏）保证框选过程中桌面的任何变化——右键菜单消失、
    悬停高亮、视频走动——都不影响截图内容；松手后直接从冻结图裁剪，也省掉了延时。"""
    selected = Signal(QImage)
    canceled = Signal()

    def __init__(self, screen, frozen=None):
        super().__init__(None)
        self._screen = screen
        self._frozen = frozen  # QPixmap：按下快捷键瞬间抓下的整屏图（物理像素）
        self._origin = None  # QPoint
        self._cur = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)

    def paintEvent(self, _):
        p = QPainter(self)
        if self._frozen is not None and not self._frozen.isNull():
            # 整屏铺冻结画面并压暗，选区处再画一遍原亮度（等于“突出选区”）
            p.drawPixmap(self.rect(), self._frozen)
            p.fillRect(self.rect(), QColor(0, 0, 0, 110))
            if self._origin and self._cur:
                sel = QRect(self._origin, self._cur).normalized()
                p.save()
                p.setClipRect(sel)
                p.drawPixmap(self.rect(), self._frozen)
                p.restore()
                self._draw_selection_hint(p, sel)
            return
        # 兜底（没有冻结图）：半透明遮罩 + 清空选区露出真实屏幕
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._origin and self._cur:
            sel = QRect(self._origin, self._cur).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(sel, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            self._draw_selection_hint(p, sel)

    def _draw_selection_hint(self, p, sel):
        """选区绿框 + 尺寸提示"""
        p.setPen(QPen(QColor("#22c55e"), 2))
        p.drawRect(sel)
        p.setPen(QPen(QColor("#22c55e")))
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        p.drawText(sel.x(), max(18, sel.y() - 6),
                   "%d × %d  松开鼠标完成截图，右键/Esc取消" % (sel.width(), sel.height()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._cur = self._origin
            self.update()
        elif e.button() == Qt.RightButton:
            self._finish_cancel()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._origin is None:
            return
        sel = QRect(self._origin, e.position().toPoint()).normalized()
        self._origin = None
        if sel.width() < 8 or sel.height() < 8:  # 太小视为取消
            self._finish_cancel()
            return
        # 直接从冻结图裁剪：不依赖抓屏时机，桌面此刻怎么变都不影响结果
        self._crop_and_emit(sel)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._finish_cancel()

    def _finish_cancel(self):
        self.close()
        self.canceled.emit()

    def _crop_and_emit(self, sel_logical):
        """从冻结图按选区裁剪（物理像素）并发出 selected"""
        try:
            pm = self._frozen
            if pm is None or pm.isNull():
                pm = self._screen.grabWindow(0)  # 兜底：没有冻结图时退回现场抓屏
            dpr = pm.devicePixelRatio() or 1.0
            rect = QRect(int(sel_logical.x() * dpr), int(sel_logical.y() * dpr),
                         int(sel_logical.width() * dpr), int(sel_logical.height() * dpr))
            rect = rect.intersected(QRect(0, 0, pm.width(), pm.height()))
            crop = pm.copy(rect).toImage().convertToFormat(QImage.Format_RGBA8888)
            self.close()
            self.selected.emit(crop)
        except Exception:
            self.close()
            self.canceled.emit()


def qimage_to_png_bytes(img: QImage, max_side=1280) -> bytes:
    """截图 QImage → 等比缩放后编码为 PNG bytes（发给 Qwen 视觉模型用）。
    限制最长边以控制请求体积（4K 全屏原图有十几 MB，base64 后更大）"""
    if img.width() > max_side or img.height() > max_side:
        if img.width() >= img.height():
            img = img.scaledToWidth(max_side, Qt.SmoothTransformation)
        else:
            img = img.scaledToHeight(max_side, Qt.SmoothTransformation)
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


# ================= 翻译结果弹窗 =================
class ResultPopup(QWidget):
    """划词/截图翻译结果浮窗：不抢键盘焦点，可复制/朗读/固定/改翻译方向/手动调整大小"""
    request_speak = Signal(str, str)
    request_retranslate = Signal(str, str, str)  # (text, way, direction)：用户手动指定方向后重译
    MIN_W, MIN_H = 420, 110   # 用户手动调整窗口时的最小尺寸
    RESIZE_MARGIN = 6         # 窗口边缘的“拖拽调整大小”热区宽度

    def __init__(self, on_close_check=None):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._pinned = False
        self._data = {}
        self._loading = False
        self._auto_sizing = False  # _fit_size 自动调整中：用于区分用户手动改变窗口大小
        self._last_screen = None   # 上次所在屏幕：用于检测跨屏拖动
        self.setMouseTracking(True)  # 鼠标移到边缘时给出“可调整大小”的光标提示
        self._load_dots = 0
        self._load_seq = 0  # 加载代次：防止上一轮的30秒超时定时器误报本轮
        self._auto_sec = 12
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.auto_close)
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(400)
        self._load_timer.timeout.connect(self._animate_loading)
        self.build_ui()

    def build_ui(self):
        self.setStyleSheet("""
            #popup { background: #ffffff; border: 1px solid #d5dae2; border-radius: 10px; }
            QLabel#orig { color: #8a93a3; font-size: 12px; }
            QLabel#trans { color: #1f2937; font-size: 17px; font-weight: 600; }
            QLabel#meta { color: #a8b0bd; font-size: 11px; }
            QPushButton { border: none; background: transparent; color: #5b6472;
                          padding: 4px 8px; border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background: #eef2f8; color: #1d4ed8; }
            QPushButton#dirbtn { border: 1px solid #d5dae2; border-radius: 4px;
                                 padding: 2px 10px; font-size: 11px; background: #ffffff; }
            QPushButton#dirbtn:hover { background: #eef2f8; border-color: #9aa4b2; }
            QPushButton#dirbtn:checked { background: #2563eb; border-color: #2563eb;
                                         color: #ffffff; font-weight: bold; }
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
            QScrollBar::handle:vertical { background: #cfd6e0; border-radius: 4px; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: #aab4c4; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        panel = QFrame(objectName="popup")
        self.lay = lay = QVBoxLayout(panel)  # 保存引用：_fit_size 需要读它的边距/间距
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        # 顶部：标题（兼作拖动手柄） + 按钮
        top = QHBoxLayout()
        self.top_layout = top  # 保存引用：_fit_size 用它实测标题行高度
        self.lab_title = QLabel("翻译结果")
        self.lab_title.setStyleSheet("color:#94a3b8;font-size:12px;font-weight:bold;")
        self.lab_title.setCursor(Qt.SizeAllCursor)  # 提示此处可拖动
        top.addWidget(self.lab_title)
        top.addStretch(1)
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setToolTip("钉住：窗口不会自动消失，可一直留在屏幕上")
        self.btn_copy = QPushButton("复制")
        self.btn_speak = QPushButton("朗读")
        self.btn_close = QPushButton("关闭")
        for b in (self.btn_pin, self.btn_copy, self.btn_speak, self.btn_close):
            top.addWidget(b)
        lay.addLayout(top)

        # 可滚动内容区：文字再长也不会被裁掉
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        # 原文
        self.lab_orig = QLabel(objectName="orig")
        self.lab_orig.setWordWrap(True)
        self.lab_orig.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lab_orig.hide()
        cl.addWidget(self.lab_orig)

        # 译文
        self.lab_trans = QLabel(objectName="trans")
        self.lab_trans.setWordWrap(True)
        self.lab_trans.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lab_trans.setOpenExternalLinks(False)
        cl.addWidget(self.lab_trans)

        # 底部：翻译方向（默认自动；自动判定失误时点一下立即按新方向重译）
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        self._dir_keys = ["auto", "en", "zh"]  # 按钮序号 → 方向（en=中译英，zh=英译中）
        self._dir_buttons = {}
        self.dir_group = QButtonGroup(self)
        self.dir_group.setExclusive(True)
        dir_tips = {"auto": "自动识别中英文并选择翻译方向（默认）",
                    "en": "把中文翻译成英文", "zh": "把英文翻译成中文"}
        for i, (label, key) in enumerate(zip(("自动", "中译英", "英译中"), self._dir_keys)):
            b = QPushButton(label, objectName="dirbtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(dir_tips[key] + "；切换后立即按新方向重新翻译")
            self.dir_group.addButton(b, i)
            self._dir_buttons[key] = b
            bottom.addWidget(b)
        self.dir_group.idClicked.connect(self._on_dir_clicked)
        self._set_dir("auto")
        bottom.addStretch(1)
        self.lab_meta = QLabel(objectName="meta")
        bottom.addWidget(self.lab_meta)
        cl.addLayout(bottom)
        cl.addStretch(1)

        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll)
        root.addWidget(panel)

        self.btn_copy.clicked.connect(self.copy_trans)
        self.btn_speak.clicked.connect(self.do_speak)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.btn_close.clicked.connect(self.close)
        self._install_hover_tracking()

    # ---- 尺寸：宽度随内容自适应（上限522），高度实测，最多屏高70%，超出靠滚动 ----
    def _screen(self):
        """当前以哪块屏幕为基准：窗口所在屏幕优先（多显示器拖动后才对得上），
        窗口还没显示时退回光标所在屏幕，最后兜底主屏。"""
        if self.isVisible():
            s = QGuiApplication.screenAt(self.frameGeometry().center())
            if s is not None:
                return s
        return (QGuiApplication.screenAt(QCursor.pos())
                or QGuiApplication.primaryScreen())

    def _chrome(self):
        """非滚动部分（标题行 + 边距 + 间距）的高度：窗口高 = chrome + 滚动区高。

        标题行由顶部布局实测（按钮文字变了也能跟上），边距/间距直接取布局的实际设置值。"""
        self.top_layout.invalidate()
        m_root = self.layout().contentsMargins()
        m_panel = self.lay.contentsMargins()
        return (m_root.top() + m_root.bottom() + m_panel.top() + m_panel.bottom()
                + self.lay.spacing() + self.top_layout.sizeHint().height())

    def _measure_content(self, width):
        """按给定内容宽度试算所需高度（折行文本按 heightForWidth 精确算）"""
        self.content.setFixedWidth(width)
        self.content.adjustSize()
        return max(self.content.sizeHint().height(),
                   self.content.heightForWidth(width))

    def _fit_size(self):
        """弹窗尺寸自适应。

        高度 = “非滚动部分（标题行 + 边距 + 间距）+ 滚动区高度”，超过屏幕 70% 时
        只压滚动区——标题行和底部方向按钮永远完整可见，超出内容交给滚动条。

        注意：不能读窗口的 sizeHint / minimumSizeHint 来定高。QScrollArea 会缓存
        内容的 sizeHint，窗口已显示时（连续第二次翻译）读到的是上一轮的旧值，
        按上限截断就会失效，窗口被撑到内容全高、直接顶出屏幕。

        宽度分窄/宽两档：收窄后高度不变（内容本来不折行）就用窄窗口，
        查单词这类短内容不再留一大片空白。"""
        g = self._screen().availableGeometry()   # 按窗口所在屏幕定上限（多屏尺寸不同）
        inner_wide, inner_narrow = 480, 400  # 内容宽；窗口宽 = 内容宽 + 42（边距与滚动条）
        h_wide = self._measure_content(inner_wide)
        inner_w, ch = inner_wide, h_wide
        if self._measure_content(inner_narrow) <= h_wide:
            inner_w, ch = inner_narrow, h_wide   # 窄宽不增高 → 内容短，用窄的
        chrome = self._chrome()
        max_h = int(g.height() * 0.7)
        scroll_h = ch if ch + chrome <= max_h else max(60, max_h - chrome)
        self._auto_sizing = True   # 标记：这一轮尺寸变化是自动的，不是用户手动拖出来的
        try:
            self.content.setFixedWidth(inner_w)
            self.scroll.setFixedHeight(scroll_h)
            self.layout().invalidate()
            self.layout().activate()
            # 显式给最小尺寸：既限制用户能把窗口拖到多小，也让布局不再往窗口上写
            # 它自己的最小尺寸（SetDefaultConstraint 只在窗口没有最小尺寸时才覆盖）
            self.setMinimumSize(self.MIN_W, self.MIN_H)
            self.resize(inner_w + 42, max(self.MIN_H, min(ch + chrome, max_h)))
            # 兜底：布局的最小尺寸仍可能把窗口撑高（字体/DPI 差异），按实际高度再压一次
            over = self.height() - max_h
            if over > 0:
                self.scroll.setFixedHeight(max(60, self.scroll.height() - over))
                self.layout().invalidate()
                self.layout().activate()
                self.resize(inner_w + 42, max_h)
        finally:
            self._auto_sizing = False
        self._keep_on_screen()

    def _keep_on_screen(self):
        """把窗口平移回屏幕可用区域内（只挪位置，不改大小）。

        典型场景：按下快捷键时弹窗很小、落在光标下方，翻译完成时长译文填入、
        窗口突然变高，底部就被顶出屏幕之外——这里整体上移，贴住屏幕底边。
        窗口比屏幕还大时贴左上角，保证标题栏和底部方向按钮可见。"""
        scr = (QGuiApplication.screenAt(self.frameGeometry().center())
               or QGuiApplication.primaryScreen())
        g = scr.availableGeometry()
        max_x = max(g.left(), g.right() + 1 - self.width())
        max_y = max(g.top(), g.bottom() + 1 - self.height())
        x = min(max(self.x(), g.left()), max_x)
        y = min(max(self.y(), g.top()), max_y)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
        self._last_screen = scr   # 记录当前屏幕，避免紧接着的 moveEvent 重复触发一轮自适应

    # ---- 无边框窗口：边缘拖拽调整大小 + 空白处拖动移动 ----
    def _resize_edges(self, pos):
        """鼠标位置命中的窗口边缘（None 表示不在边缘），用于拖拽调整大小"""
        m = self.RESIZE_MARGIN
        near_l, near_r = pos.x() <= m, pos.x() >= self.width() - m
        near_t, near_b = pos.y() <= m, pos.y() >= self.height() - m
        edges = None
        if near_l:
            edges = Qt.LeftEdge
        elif near_r:
            edges = Qt.RightEdge
        if near_t:
            edges = Qt.TopEdge if edges is None else (edges | Qt.TopEdge)
        elif near_b:
            edges = Qt.BottomEdge if edges is None else (edges | Qt.BottomEdge)
        return edges

    def _update_resize_cursor(self, pos):
        """移到边缘时显示双向箭头，提示这里可以拖动调整窗口大小"""
        edges = self._resize_edges(pos) if self.rect().contains(pos) else None
        if edges is None:
            self.unsetCursor()
            return
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.SizeVerCursor)

    def _install_hover_tracking(self):
        """给所有子控件装鼠标移动过滤器。

        滚动区（QScrollArea）等子控件会接收并吃掉鼠标移动事件，不让它冒泡到窗口，
        导致窗口的 mouseMoveEvent 收不到——光标会一直停在“双向箭头”上不变回来
        （鼠标移到译文/按钮上也不恢复，只有移出整个窗口才恢复）。"""
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
            w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseMove:
            self._update_resize_cursor(
                self.mapFromGlobal(ev.globalPosition().toPoint()))
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            handle = self.windowHandle()
            edges = self._resize_edges(e.position().toPoint()) if handle is not None else None
            if edges is not None and handle.startSystemResize(edges):
                # 边缘按下：交给系统接管调整大小，手感和普通窗口拖边一样
                e.accept()
                return
            # 不在边缘（或系统不支持拖拽调整大小）时：退回拖动移动窗口
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        pos = getattr(self, "_drag_pos", None)
        if pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - pos)
            e.accept()
            return
        self._update_resize_cursor(e.position().toPoint())

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        self._update_resize_cursor(e.position().toPoint())

    def moveEvent(self, e):
        """窗口被拖到另一块显示器时按新屏幕重新自适应。

        两台显示器尺寸/缩放往往不同，继续沿用旧屏幕算出的高度可能直接超出新屏幕。"""
        super().moveEvent(e)
        scr = QGuiApplication.screenAt(self.frameGeometry().center())
        if scr is None or scr is self._last_screen:
            return
        self._last_screen = scr
        if self.isVisible() and not self._auto_sizing:
            self._fit_size()

    def resizeEvent(self, e):
        """用户拖边缘改变窗口大小：内容宽度跟着窗口走（文字重新折行），滚动区填满剩余高度。

        滚动区必须占满“窗口高 - 非滚动部分”：否则多余空间无处消化，
        布局会把标题行往下推、把内容撑散（标题行悬在中间、下方一大片空白）。
        这样多余空白只会留在滚动区内部，标题行贴顶、底部按钮跟在内容后面。
        _fit_size 自动调整时跳过——它已按内容算好尺寸，别覆盖。"""
        super().resizeEvent(e)
        if self._auto_sizing:
            return
        avail = max(200, self.width() - 42)
        if abs(self.content.width() - avail) > 1:
            self.content.setFixedWidth(avail)
        self.scroll.setFixedHeight(max(60, self.height() - self._chrome()))
        self._keep_on_screen()

    def show_loading(self, text, way="划词", direction="auto"):
        """按快捷键后立即弹出：显示原文 + 加载动画，翻译完成原地更新。
        direction 是本次请求的方向，用于同步底部按钮选中态（不触发重译）"""
        self._loading = True
        self._data = {"text": text, "way": way}
        self._set_dir(direction)
        self._pinned = False
        self.btn_pin.setText("📌")
        self.btn_pin.setStyleSheet("")
        self.btn_copy.setText("复制")
        self.lab_title.setText("%s · 翻译中" % way)
        if text:
            self.lab_orig.setText(_format_orig(text))
            self.lab_orig.setToolTip(text)
            self.lab_orig.show()
        else:
            self.lab_orig.setText("原文：（未识别到原文）")
            self.lab_orig.setToolTip("")
            self.lab_orig.show()
        self.lab_trans.setStyleSheet("color:#9aa3b2;font-size:14px;font-weight:normal;")
        self._load_dots = 0
        self._load_msg = ("正在识别并翻译截图，请稍候" if way == "截图"
                          else "正在翻译，请稍候")
        self.lab_trans.setText(self._load_msg)
        self.lab_meta.setText("")
        for b in (self.btn_copy, self.btn_speak):
            b.setEnabled(False)
        self.scroll.verticalScrollBar().setValue(0)
        self._fit_size()
        if not self.isVisible():
            self.place_near_cursor()
            self.show()
        self.raise_()
        self._load_timer.start()
        # 网络卡死兜底：加载超过30秒提示超时（记录代次，防止旧定时器误报新一轮）
        self._load_seq += 1
        seq = self._load_seq
        QTimer.singleShot(30000, lambda: self._loading_timeout(seq))

    def _animate_loading(self):
        if not self._loading:
            self._load_timer.stop()
            return
        self._load_dots = (self._load_dots + 1) % 4
        self.lab_trans.setText(self._load_msg + "·" * self._load_dots)

    def _loading_timeout(self, seq):
        if self._loading and self._load_seq == seq and self.isVisible():
            self.show_error("翻译超时，请检查网络后重试。")

    def show_error(self, msg):
        """加载中出错：错误直接显示在浮窗里"""
        self._loading = False
        self._load_timer.stop()
        self.lab_title.setText("翻译失败")
        self.lab_trans.setStyleSheet("color:#dc2626;font-size:14px;font-weight:normal;")
        self.lab_trans.setText(_soft_wrap(msg))
        self.lab_meta.setText("")
        for b in (self.btn_copy, self.btn_speak):
            b.setEnabled(False)
        self._fit_size()
        if not self.isVisible():
            self.place_near_cursor()
            self.show()
        self.raise_()
        self._schedule_auto_close(8)

    def _schedule_auto_close(self, seconds):
        """安排自动关闭；鼠标悬停在窗口上时暂停，移开后重新计时"""
        self._auto_sec = max(0, int(seconds))
        if self._auto_sec > 0:
            # 结果返回时鼠标可能已停在窗口上（enterEvent 不会再触发，没人停表），
            # 所以启动前先按坐标查一次：鼠标已就位就不启动，等 leaveEvent 再计时
            if self.isVisible() and self.rect().contains(self.mapFromGlobal(QCursor.pos())):
                return
            self._auto_timer.start(self._auto_sec * 1000)
        else:
            self._auto_timer.stop()

    def enterEvent(self, e):
        self._auto_timer.stop()  # 鼠标停在窗口上：不自动关闭，安心阅读
        e.accept()

    def leaveEvent(self, e):
        if self.isVisible() and not self._pinned and self._auto_sec > 0:
            self._auto_timer.start(self._auto_sec * 1000)
        e.accept()

    def _fill_result(self, data):
        """把翻译结果填充到浮窗（不含定位/显示/自动关闭）"""
        self._data = data
        self._pinned = False
        self.btn_pin.setText("📌")
        self.btn_pin.setStyleSheet("")
        text = data.get("text", "")
        trans = data.get("translated", "")
        self.lab_trans.setStyleSheet("")
        for b in (self.btn_copy, self.btn_speak):
            b.setEnabled(True)
        # 标题只体现方向，译文无论中译英还是英译中都必须写入，
        # 否则译文区会一直停在“正在翻译，请稍候···”
        self.lab_title.setText("中译英" if data.get("reverse") else "英译中")
        self.lab_trans.setText(_soft_wrap(trans or "（未获取到翻译）"))
        self.lab_orig.setText(_format_orig(text))
        self.lab_orig.setToolTip(text)
        self.lab_orig.show()

        self.lab_meta.setText("来源：%s" % data.get("engine", ""))

    def show_result(self, data, auto_close_sec=None):
        """data: text, translated, engine, detected, reverse, way, seq"""
        was_loading = self._loading
        self._fill_result(data)
        self._loading = False
        self._load_timer.stop()
        self._fit_size()
        if not self.isVisible():
            self.place_near_cursor()
            self.show()
        elif not was_loading:
            self.place_near_cursor()
        self.raise_()
        # 自动关闭计时（鼠标悬停时暂停；固定则不关；0=不自动关）
        # auto_close_sec 由调用方传入，避免每次翻译结果都重读一次配置文件
        if auto_close_sec is None:
            auto_close_sec = int(core.load_config().get("show_popup_seconds", 12))
        self._schedule_auto_close(auto_close_sec)

    def place_near_cursor(self):
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x, y = pos.x() + 14, pos.y() + 14
        if x + self.width() > g.right() - 8:
            x = g.right() - self.width() - 8
        if y + self.height() > g.bottom() - 8:
            y = pos.y() - self.height() - 14
            if y < g.top():
                y = g.top() + 8
        self.move(x, y)
        self._last_screen = screen

    def auto_close(self):
        if self._pinned or not self.isVisible():
            return
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            # 兜底：到点时鼠标仍悬停在窗口上（enterEvent 因故未触发/已过时），
            # 不关闭，改为重新倒计时，移开后正常关闭
            self._auto_timer.start(self._auto_sec * 1000)
            return
        self.close()

    def toggle_pin(self):
        """图钉：钉住后窗口不自动消失（窗口本来就置顶显示）"""
        self._pinned = not self._pinned
        if self._pinned:
            self.btn_pin.setText("📌 已钉")
            self.btn_pin.setStyleSheet("color:#1d4ed8;font-weight:bold;")
        else:
            self.btn_pin.setText("📌")
            self.btn_pin.setStyleSheet("")

    def copy_trans(self):
        QApplication.clipboard().setText(_strip_soft_wrap(self.lab_trans.text()))

    # ---- 翻译方向（自动判定失误时用户手动纠正）----
    def _set_dir(self, direction):
        """同步底部按钮选中态。
        用 idClicked 而非 toggled 连接重译，程序内 setChecked 不会触发信号，不会造成重译循环"""
        btn = self._dir_buttons.get(direction)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)

    def _on_dir_clicked(self, idx):
        """用户点“自动/中译英/英译中”：用同一段原文按指定方向重新翻译"""
        if not 0 <= idx < len(self._dir_keys):
            return
        text = (self._data.get("text") or "").strip()
        if not text:   # 截图没识别到文字等：没有原文可重译
            return
        self.request_retranslate.emit(text, self._data.get("way", "划词"),
                                      self._dir_keys[idx])

    def do_speak(self):
        text = self._data.get("text", "")
        lang = "en" if self._data.get("detected", "en").startswith("en") else "zh"
        self.request_speak.emit(text, lang)


# ================= 主窗口 =================
class MainWindow(QWidget):
    request_capture = Signal()   # 触发截图翻译（测试用）
    request_speak = Signal(str, str)
    config_changed = Signal()

    def __init__(self, cfg, db):
        super().__init__()
        self.cfg = cfg
        self.db = db
        self.setWindowTitle("英译通 EnglishHelper - 英文翻译")
        self.resize(760, 560)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.refresh_history()

    def build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ---- 使用帮助 ----
        help_w = QWidget()
        hl = QVBoxLayout(help_w)
        lab = QLabel(
            "<div style='line-height:180%'>"
            "<h3>怎么用（只要记住两个快捷键）</h3>"
            "<p><b>① 划词翻译：</b>在任何软件里用鼠标<b>选中英文</b>，然后按 "
            "<b style='color:#1d4ed8'>Alt+Q</b>——会先弹出“<b>正在翻译</b>”的小窗口，"
            "翻译好以后<b>原窗口直接变成中文结果</b>，不用等、不用再按。</p>"
            "<p><b>② 截图翻译：</b>如果文字<b>选不中</b>（在图片里、某些软件里），按 "
            "<b style='color:#1d4ed8'>Alt+W</b>，然后按住鼠标左键，<b>框住那块文字</b>，"
            "松开鼠标就会自动识别并翻译（也是先弹“正在翻译”窗口）。</p>"
            "<p><b>③ 朗读：</b>翻译弹窗上点【朗读】，电脑会读给你听；"
            "翻译历史里选中一行点【朗读选中】也可以复习发音。</p>"
            "<p><b>④ 小技巧：</b>划中文会自动<b>翻译成英文</b>——想写英文句子时，"
            "先在任意地方打好中文，选中按 Alt+Q 就得到英文表达。</p>"
            "<p><b>⑤ 方向判错了？</b>翻译弹窗底部有 <b>自动 / 中译英 / 英译中</b> 三个按钮，"
            "默认「自动」（程序自己判断中英文）。万一判错（比如中英混排的句子），"
            "点一下「中译英」或「英译中」，它会立刻按你选的方向<b>重新翻译</b>。</p>"
            "<p><b>⑥ 窗口太挤或太空？</b>鼠标移到弹窗<b>边缘</b>会出现双向箭头，"
            "按住拖动就能自己调整窗口大小；同时用两个显示器也没问题——"
            "窗口拖到哪块屏幕，就按哪块屏幕自动适配尺寸，不会跑到屏幕外面去。</p>"
            "<h3>遇到问题？</h3>"
            "<p>· 提示<b>“没有取到文字”</b>：重新选中文字再按一次 Alt+Q；"
            "如果那个软件是用<b>管理员身份</b>运行的，请在英译通图标上点右键→“以管理员身份运行”；"
            "实在选不中的文字就改用截图翻译 Alt+W。</p>"
            "<p>· <b>连续查多个词</b>：窗口永远显示<b>最后一次</b>查询的结果，"
            "前面没查完的不会来捣乱；网络太慢时窗口会提示“翻译超时”，重按快捷键即可。</p>"
            "<p style='color:#94a3b8'>小提示：软件在屏幕右下角托盘常驻（小图标），"
            "右键托盘图标可以退出或打开本窗口。翻译弹窗十几秒后自动消失"
            "（<b>鼠标停在弹窗上就不会消失</b>，可以慢慢看），点【📌】钉住可一直保留，"
            "自动关闭时长可在【设置】里改，按住弹窗顶部空白处可拖动位置。"
            "如果还有问题：程序文件夹里的 <b>debug.log</b> 文件记录了每次翻译的详细过程，"
            "把它发给懂电脑的人就能帮你排查。</p>"
            "</div>")
        lab.setWordWrap(True)
        hl.addWidget(lab)
        hl.addStretch(1)
        tabs.addTab(help_w, "使用帮助")

        # ---- 翻译历史 ----
        hist_w = QWidget()
        hlay = QVBoxLayout(hist_w)
        bar = QHBoxLayout()
        self.btn_hist_speak = QPushButton("朗读选中")
        self.btn_hist_del = QPushButton("删除选中")
        self.btn_hist_clear = QPushButton("清空历史")
        for b in (self.btn_hist_speak, self.btn_hist_del, self.btn_hist_clear):
            bar.addWidget(b)
        bar.addStretch(1)
        hlay.addLayout(bar)
        self.tbl_hist = QTableWidget(0, 4)
        self.tbl_hist.setHorizontalHeaderLabels(["原文", "译文", "方式", "时间"])
        self.tbl_hist.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_hist.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_hist.setWordWrap(True)
        hh = self.tbl_hist.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_hist.setColumnWidth(2, 60)
        self.tbl_hist.setColumnWidth(3, 130)
        hlay.addWidget(self.tbl_hist)
        tabs.addTab(hist_w, "翻译历史")
        self.btn_hist_del.clicked.connect(self.del_history)
        self.btn_hist_clear.clicked.connect(self.clear_history)
        self.btn_hist_speak.clicked.connect(self.speak_history_row)

        # ---- 设置 ----
        set_w = QWidget()
        sl = QVBoxLayout(set_w)
        sl.setSpacing(12)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("划词翻译快捷键："))
        self.cmb_hk1 = QComboBox()
        self.cmb_hk1.addItems(["alt+q", "alt+x", "alt+d", "ctrl+q", "f4"])
        row1.addWidget(self.cmb_hk1)
        row1.addStretch(1)
        sl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("截图翻译快捷键："))
        self.cmb_hk2 = QComboBox()
        self.cmb_hk2.addItems(["alt+w", "alt+s", "ctrl+alt+w", "f3"])
        row2.addWidget(self.cmb_hk2)
        row2.addStretch(1)
        sl.addLayout(row2)

        lab_qwen_tip = QLabel("翻译由通义千问 Qwen 大模型提供（阿里云百炼），"
                              "需要填写下面的 API Key 才能翻译")
        lab_qwen_tip.setStyleSheet("color:#2563eb;font-weight:bold;")
        sl.addWidget(lab_qwen_tip)

        row_qwen1 = QHBoxLayout()
        row_qwen1.addWidget(QLabel("百炼API Key："))
        self.edt_qwen_key = QLineEdit()
        self.edt_qwen_key.setEchoMode(QLineEdit.Password)
        self.edt_qwen_key.setPlaceholderText(
            "阿里云百炼 sk-开头密钥，bailian.console.aliyun.com 免费申请（Qwen AI翻译用）")
        row_qwen1.addWidget(self.edt_qwen_key, 1)
        sl.addLayout(row_qwen1)

        row_qwen2 = QHBoxLayout()
        row_qwen2.addWidget(QLabel("Qwen模型名："))
        self.edt_qwen_model = QLineEdit()
        self.edt_qwen_model.setPlaceholderText("默认 qwen3.7-flash，可换成百炼支持的其它模型")
        row_qwen2.addWidget(self.edt_qwen_model, 1)
        sl.addLayout(row_qwen2)

        self.ck_restore = QCheckBox("划词翻译后恢复原来的剪贴板内容")
        self.ck_autostart = QCheckBox("开机自动启动")
        self.ck_select = QCheckBox("启用划词翻译（关闭后 Alt+Q 无效）")
        self.ck_speak = QCheckBox("翻译完成后自动朗读英文")
        sl.addWidget(self.ck_select)
        sl.addWidget(self.ck_restore)
        sl.addWidget(self.ck_autostart)
        sl.addWidget(self.ck_speak)

        row6 = QHBoxLayout()
        row6.addWidget(QLabel("翻译弹窗自动关闭："))
        self.cmb_auto = QComboBox()
        for label, val in (("5秒", 5), ("12秒", 12), ("30秒", 30), ("60秒", 60), ("不自动关闭", 0)):
            self.cmb_auto.addItem(label, val)
        row6.addWidget(self.cmb_auto)
        row6.addWidget(QLabel("（鼠标停在弹窗上时不会关闭）"))
        row6.addStretch(1)
        sl.addLayout(row6)

        btn_save = QPushButton("保存设置")
        btn_save.setStyleSheet("background:#2563eb;color:white;border:none;padding:8px 20px;")
        btn_save.setFixedWidth(140)
        sl.addWidget(btn_save)
        sl.addStretch(1)
        tabs.addTab(set_w, "设置")
        btn_save.clicked.connect(self.save_settings)
        tabs.currentChanged.connect(self._on_tab_changed)

        self._fill_settings()

    # ---- 设置 ----
    def _fill_settings(self):
        self.cmb_hk1.setCurrentText(self.cfg.get("hotkey_select", "alt+q"))
        self.cmb_hk2.setCurrentText(self.cfg.get("hotkey_capture", "alt+w"))
        self.edt_qwen_key.setText(self.cfg.get("qwen_api_key", ""))
        self.edt_qwen_model.setText(self.cfg.get("qwen_model", "qwen3.7-flash"))
        self.ck_restore.setChecked(self.cfg.get("restore_clipboard", True))
        self.ck_autostart.setChecked(self.cfg.get("autostart", False))
        self.ck_select.setChecked(self.cfg.get("select_enabled", True))
        self.ck_speak.setChecked(self.cfg.get("auto_speak", False))
        idx_auto = self.cmb_auto.findData(int(self.cfg.get("show_popup_seconds", 12)))
        self.cmb_auto.setCurrentIndex(max(0, idx_auto))

    def save_settings(self):
        self.cfg["hotkey_select"] = self.cmb_hk1.currentText().strip()
        self.cfg["hotkey_capture"] = self.cmb_hk2.currentText().strip()
        self.cfg["qwen_api_key"] = self.edt_qwen_key.text().strip()
        self.cfg["qwen_model"] = self.edt_qwen_model.text().strip() or "qwen3.7-flash"
        self.cfg["restore_clipboard"] = self.ck_restore.isChecked()
        self.cfg["select_enabled"] = self.ck_select.isChecked()
        self.cfg["auto_speak"] = self.ck_speak.isChecked()
        self.cfg["show_popup_seconds"] = int(self.cmb_auto.currentData())
        old_auto = self.cfg.get("autostart", False)
        self.cfg["autostart"] = self.ck_autostart.isChecked()
        core.save_config(self.cfg)
        if old_auto != self.cfg["autostart"]:
            core.set_autostart(self.cfg["autostart"])
        QMessageBox.information(self, "已保存", "设置已保存，快捷键立即生效。")
        self.config_changed.emit()

    # ---- 历史 ----
    def refresh_history(self):
        rows = self.db.history_list()
        tw = self.tbl_hist
        # 批量填充期间禁止逐项重绘（几百行时能省下大量布局开销）
        tw.setUpdatesEnabled(False)
        try:
            tw.setRowCount(len(rows))
            for i, r in enumerate(rows):
                tw.setItem(i, 0, QTableWidgetItem(r["source"]))
                tw.setItem(i, 1, QTableWidgetItem(r["translated"]))
                tw.setItem(i, 2, QTableWidgetItem(r["way"]))
                tw.setItem(i, 3, QTableWidgetItem(
                    time.strftime("%m-%d %H:%M", time.localtime(r["created"]))))
        finally:
            tw.setUpdatesEnabled(True)
        tw.resizeRowsToContents()

    def del_history(self):
        rows = self.db.history_list()
        # 选中一行会有 4 个单元格 item，先按行去重再批量删除
        ids = {rows[it.row()]["id"] for it in self.tbl_hist.selectedItems()
               if it.row() < len(rows)}
        if ids:
            self.db.history_delete_many(list(ids))
        self.refresh_history()

    def clear_history(self):
        if QMessageBox.question(self, "确认", "确定清空全部翻译历史吗？") == QMessageBox.Yes:
            self.db.history_clear()
            self.refresh_history()

    def speak_history_row(self):
        rows = self.db.history_list()
        sel = self.tbl_hist.currentRow()
        if 0 <= sel < len(rows):
            self.request_speak.emit(rows[sel]["source"], "en")

    def refresh_all(self):
        self.refresh_history()

    def _on_tab_changed(self, idx):
        """切页时只刷新当前页数据（帮助=0 历史=1 设置=2）"""
        if idx == 1:
            self.refresh_history()

    def closeEvent(self, e):
        e.ignore()   # 点关闭=隐藏到托盘
        self.hide()
