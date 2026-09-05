# -*- coding: utf-8 -*-
"""浮窗UI专项测试：长文本滚动/高度限制/图钉/拖动"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import ui


def main():
    app = QApplication(sys.argv)
    p = ui.ResultPopup()

    # ---- 1) 超长文本：窗口不超屏、出滚动条 ----
    en = ("The weather is very nice today and we should go outside to play "
          "football with all of our friends in the park. ")
    long_text = en * 40
    p.show_loading(long_text, "划词")
    p.show_result({"text": long_text,
                   "translated": "今天天气非常好，我们应该和所有朋友去公园踢足球。" * 40,
                   "engine": "test", "is_word": False, "phonetic": None,
                   "meanings": [], "detected": "en", "way": "划词"})
    g = app.primaryScreen().availableGeometry()
    max_h = int(g.height() * 0.7)
    assert p.height() <= max_h + 2, "窗口高度超限: %d > %d" % (p.height(), max_h)
    assert p.width() <= 522, "宽度超限: %d" % p.width()
    sb = p.scroll.verticalScrollBar()
    print("高度=%d (上限%d) 宽度=%d 滚动条max=%d" % (p.height(), max_h, p.width(), sb.maximum()))
    assert sb.maximum() > 0, "长文本应出现滚动条"
    # 滚动到底再回顶
    sb.setValue(sb.maximum())
    assert p.scroll.verticalScrollBar().value() == sb.maximum()
    sb.setValue(0)

    # ---- 2) 短文本：不出现多余滚动条 ----
    p.show_result({"text": "apple", "translated": "苹果", "engine": "t",
                   "is_word": False, "phonetic": None, "meanings": [],
                   "detected": "en", "way": "划词"})
    print("短文本 高度=%d 滚动max=%d" % (p.height(), p.scroll.verticalScrollBar().maximum()))

    # ---- 3) 图钉 ----
    p.toggle_pin()
    assert p._pinned and p.btn_pin.text() == "📌 已钉"
    p.toggle_pin()
    assert not p._pinned and p.btn_pin.text() == "📌"
    print("图钉切换 OK")

    # ---- 3.5) 悬停暂停自动关闭 ----
    assert p._auto_timer.isActive(), "结果出来后自动关闭计时应在跑"
    p.enterEvent(QEvent(QEvent.Enter))   # 鼠标进入窗口
    assert not p._auto_timer.isActive(), "悬停时应暂停自动关闭"
    p.leaveEvent(QEvent(QEvent.Leave))   # 鼠标离开
    assert p._auto_timer.isActive(), "移开后应恢复自动关闭计时"
    p._schedule_auto_close(0)            # 设置为"不自动关闭"
    assert not p._auto_timer.isActive()
    p._schedule_auto_close(12)
    print("悬停暂停自动关闭 OK")

    # ---- 4) 拖动（QTest 模拟鼠标按住拖动，起点在标题栏空白处）----
    old = (p.x(), p.y())
    QTest.mousePress(p, Qt.LeftButton, pos=QPoint(260, 24))
    QTest.mouseMove(p, QTest.mouseMove and QPoint(310, 64))
    QTest.mouseRelease(p, Qt.LeftButton, pos=QPoint(310, 64))
    new = (p.x(), p.y())
    moved = (new[0] - old[0], new[1] - old[1])
    print("拖动位移:", moved)
    assert abs(moved[0]) > 20 and abs(moved[1]) > 20, "拖动未生效"

    print("POPUP_UI_ALL_OK")
    p.close()


main()
print("DONE")
