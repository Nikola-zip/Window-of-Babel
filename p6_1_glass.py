# 譯幕 第6期第1步：譯鏡嘅玻璃
#
# 做咩：一塊浮喺最上面嘅玻璃，平時滑鼠穿透（撳落去等於撳下面），淨係見到幼幼嘅邊框；
#       撳 Ctrl+Alt+G 入調整模式：拖住搬位、拉四邊四角改大細（細至一個對白框、大至成頁），
#       雙擊或者右撳完成，位置大細記入 settings.json「譯鏡」。
#       截圖嗰陣 Windows 會當佢唔存在，第 2 關截玻璃底下先唔會截到自己。
# 點用：.venv\Scripts\python -W ignore p6_1_glass.py（示範；工作列圖示可以閂）
#       第 2、3 關會 import 呢度嘅 Glass。

import ctypes

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from ui_parts import CHINESE_FONTS, CORNER_IDLE, IconButton, Toolbar, load_settings, make_font, save_settings

user32 = ctypes.WinDLL("user32", use_last_error=True)
WDA_EXCLUDEFROMCAPTURE = 0x11   # Windows 10 2004 之後：截圖、錄影都當呢個視窗唔存在
EDGE = 12           # 離邊幾多像素以內算「捉住邊」
MIN_SIZE = (60, 40)
GLASS_COLOR = QColor(79, 195, 247)      # 淺藍：同字幕條嘅黃色分得開
HINT = "拖住搬位；拉邊或者角改大細\n雙擊或者右撳完成"


def exclude_from_capture(widget):
    """叫 Windows 截圖嗰陣當呢個視窗唔存在；成功回傳 True。"""
    # 改 window flag 會換過個 Windows 視窗（hwnd 會變），所以每次 show 都要重新設
    return bool(user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))


class WheelGauge(QWidget):
    """貼住塊鏡右邊、打直嘅「▲ 100% ▼」：一直睇到而家譯文幾大，撳 ▲▼ 或者喺度轆滾輪都調得。
    用戶話淨靠提示字好難知工具列轆得；打直擺似滾動條，一睇就知上下轆。"""

    SIZE = (40, 72)

    def __init__(self, on_step, text):
        super().__init__()
        # 同工具列一樣：置頂、唔喺工作列、唔搶 focus、唔穿透（先撳得到）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(*self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("譯文字大細：撳 ▲▼ 或者轆滾輪")
        self.on_step, self.text = on_step, text     # text()：而家顯示咩（例如「100%」）
        self.wheel_left = 0
        self.setWindowOpacity(CORNER_IDLE)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 200))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.setPen(QColor("white"))
        third = self.height() / 3
        p.setFont(make_font(["Segoe UI Symbol"], 11))
        p.drawText(QRectF(0, 0, self.width(), third), Qt.AlignmentFlag.AlignCenter, "▲")
        p.drawText(QRectF(0, third * 2, self.width(), third), Qt.AlignmentFlag.AlignCenter, "▼")
        p.setFont(make_font(CHINESE_FONTS, 8, bold=True))
        p.drawText(QRectF(0, third, self.width(), third), Qt.AlignmentFlag.AlignCenter, self.text())

    def mousePressEvent(self, event):
        y = event.position().y()
        if y < self.height() / 3:
            self.on_step(1)
        elif y > self.height() * 2 / 3:
            self.on_step(-1)
        self.update()

    def wheelEvent(self, event):
        self.wheel_left += event.angleDelta().y()      # 觸控板一次淨轆少少，儲夠一格（120）先算
        while abs(self.wheel_left) >= 120:
            step = 1 if self.wheel_left > 0 else -1
            self.wheel_left -= step * 120
            self.on_step(step)
        self.update()
        event.accept()

    def enterEvent(self, event):
        self.setWindowOpacity(1.0)      # 同工具列一樣：平時半透明，滑鼠移上去先清楚

    def leaveEvent(self, event):
        self.setWindowOpacity(CORNER_IDLE)


class Glass(QWidget):
    """譯鏡嘅玻璃：平時穿透，調整模式可以搬同改大細。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool                        # 唔喺工作列出現
            | Qt.WindowType.WindowTransparentForInput   # 平時穿透：睇漫畫照撳得到下一頁
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumSize(*MIN_SIZE)
        self.adjusting = False
        self.captured_ok = None     # 有冇成功設定「唔俾截圖」，俾人檢查
        self.toolbar = None
        self.gauge = None           # 譯文字大細指示（有 toolbar_wheel 先有）
        self.move_button = None
        self._restore()

    def add_toolbar(self, extra=(), menu=None):
        """喺塊鏡右上角加細工具列（同字幕條嗰個一樣）：✥ 調整、extra 嘅掣、⚙ 出 menu。

        遊戲入面熱鍵唔一定得（例如 LoL），有掣撳就唔受影響。extra 係 [(符號, 提示, 功能)]，
        或者整好咗嘅掣（例如按住型嘅 HoldButton）。
        """
        self.move_button = IconButton("✥", "調整窗：搬位、改大細（再撳一下完成）", lambda _: self.toggle_adjusting())
        buttons = [self.move_button]
        buttons += [item if isinstance(item, IconButton) else
                    IconButton(item[0], item[1], lambda _, action=item[2]: action()) for item in extra]
        if menu is not None:
            buttons.append(IconButton("⚙", "選單", menu.exec))
        self.toolbar = Toolbar(buttons)
        wheel = getattr(self, "toolbar_wheel", None)
        if wheel is not None:
            # 塊玻璃穿透，喺漫畫上面轆滾輪係俾網頁捲頁；工具列唔穿透，喺度轆先收到
            self.toolbar.on_wheel = wheel
            for button in buttons:
                button.setToolTip(button.toolTip() + "\n（喺工具列轆滾輪：調譯文大細）")
            self.gauge = WheelGauge(wheel, self.gauge_text)
        if self.isVisible():
            self._show_toolbar()

    def _show_toolbar(self):
        # 未顯示過嘅視窗大細係預設 640×480，計位置會飛去好遠；先叫佢按入面啲掣計好大細
        self.toolbar.adjustSize()
        self._place_toolbar()
        self.toolbar.show()
        self.toolbar.raise_()
        exclude_from_capture(self.toolbar)  # 工具列都唔好俾截到
        if self.gauge:
            self.gauge.show()
            self.gauge.raise_()
            exclude_from_capture(self.gauge)

    def _place_toolbar(self):
        """工具列貼喺塊鏡右上角外面；貼咗螢幕頂就擺返入面。"""
        if not self.toolbar:
            return
        g = self.geometry()
        top = self.screen().availableGeometry().top()
        y = g.top() - self.toolbar.height()
        self.toolbar.move(g.right() + 1 - self.toolbar.width(), y if y >= top else g.top())
        self.toolbar.raise_()
        if self.gauge:
            # 貼住塊鏡右邊、同塊鏡頂齊；貼咗螢幕右邊、出面冇位就擺返入塊鏡右上角（工具列擺咗入面就喺佢下面）
            x = g.right() + 2
            if x + self.gauge.width() <= self.screen().availableGeometry().right():
                self.gauge.move(x, g.top())
            else:
                self.gauge.move(g.right() + 1 - self.gauge.width(),
                                g.top() + (self.toolbar.height() if y < top else 0))
            self.gauge.raise_()

    # ---------- 位置大細：記「邊個螢幕＋比例」，同字幕條一樣，換解像度都唔會飛出界 ----------
    def _screen_named(self, name):
        for screen in QApplication.screens():
            if screen.name() == name:
                return screen
        return QApplication.primaryScreen()

    def _restore(self):
        saved = load_settings().get("譯鏡")
        screen = self._screen_named(saved["screen"]) if saved else QApplication.primaryScreen()
        area = screen.availableGeometry()
        if saved:
            rect = QRect(area.x() + round(saved["x"] * area.width()), area.y() + round(saved["y"] * area.height()),
                         round(saved["w"] * area.width()), round(saved["h"] * area.height()))
        else:
            # 第一次：主螢幕正中，大約一頁漫畫咁大
            w, h = round(area.width() * 0.3), round(area.height() * 0.6)
            rect = QRect(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2, w, h)
        self.setGeometry(rect.intersected(area) if rect.intersects(area) else QRect(area.topLeft(), rect.size()))

    def _remember(self):
        screen = QApplication.screenAt(self.geometry().center()) or self.screen()
        area = screen.availableGeometry()
        g = self.geometry()
        settings = load_settings()
        settings["譯鏡"] = {
            "screen": screen.name(),
            "x": (g.x() - area.x()) / area.width(),
            "y": (g.y() - area.y()) / area.height(),
            "w": g.width() / area.width(),
            "h": g.height() / area.height(),
        }
        save_settings(settings)
        print(f"窗位置記住咗：{screen.name()} {g.width()}×{g.height()}")

    # ---------- 調整模式 ----------
    def set_adjusting(self, on):
        """調整模式：暫時唔穿透、出把手；完成就記住位置，變返穿透。"""
        self.adjusting = on
        # 改 window flag 會令視窗收埋，要 show 返
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not on)
        self.show()
        if self.move_button:
            self.move_button.set_active(on)     # 變黃，話你知而家係調整模式
        if on:
            self.raise_()
            self.activateWindow()   # 要攞到焦點，雙擊、右撳先有反應
        else:
            self.unsetCursor()
            self._remember()
        self.update()

    def toggle_adjusting(self):
        if not self.isVisible():
            self.show()
        self.set_adjusting(not self.adjusting)

    def showEvent(self, event):
        self.captured_ok = exclude_from_capture(self)
        if self.toolbar:
            self._show_toolbar()

    def hideEvent(self, event):
        if self.toolbar:
            self.toolbar.hide()
        if self.gauge:
            self.gauge.hide()

    def moveEvent(self, event):
        self._place_toolbar()   # 拖緊都即刻跟住，好似塊鏡凸出嚟嘅分頁

    def resizeEvent(self, event):
        self._place_toolbar()

    def _edges(self, pos):
        """滑鼠喺邊個邊或者角：回傳 Qt.Edge 組合（喺中間就係空）。"""
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event):
        if not self.adjusting:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.set_adjusting(False)
        elif event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges(event.position().toPoint())
            # 交俾 Windows 自己搬、自己拉大細：同拉普通視窗嘅邊一樣順，唔使自己計座標
            if edges:
                self.windowHandle().startSystemResize(edges)
            else:
                self.windowHandle().startSystemMove()

    def mouseMoveEvent(self, event):
        if not self.adjusting or event.buttons():
            return
        edges = self._edges(event.position().toPoint())
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            # 左上同右下係「↖↘」，右上同左下係「↗↙」
            main = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if main else Qt.CursorShape.SizeBDiagCursor)
        elif horizontal:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif vertical:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseDoubleClickEvent(self, event):
        if self.adjusting:
            self.set_adjusting(False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.adjusting:
            # 調整模式：淺藍半透明填滿＋實線，四角四邊畫把手，話你知邊度捉得
            p.fillRect(rect, QColor(GLASS_COLOR.red(), GLASS_COLOR.green(), GLASS_COLOR.blue(), 45))
            p.setPen(QPen(GLASS_COLOR, 3))
            p.drawRect(rect)
            p.setBrush(QColor("white"))
            p.setPen(QPen(QColor("black"), 1.5))
            w, h, s = rect.width(), rect.height(), 10
            for x, y in [(0, 0), (w / 2, 0), (w, 0), (0, h / 2), (w, h / 2), (0, h), (w / 2, h), (w, h)]:
                p.drawRect(QRectF(rect.x() + x - s / 2, rect.y() + y - s / 2, s, s))
            p.setPen(QColor("black"))
            p.setFont(make_font(CHINESE_FONTS, 11, bold=True))
            box = p.fontMetrics().boundingRect(QRect(0, 0, 400, 100), Qt.AlignmentFlag.AlignCenter, HINT)
            box.moveCenter(self.rect().center())
            p.fillRect(QRectF(box).adjusted(-8, -5, 8, 5), QColor(255, 255, 255, 220))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, HINT)
        else:
            # 平時：淨係幼邊框同四角，知道塊鏡喺邊，又唔遮漫畫
            p.setPen(QPen(QColor(GLASS_COLOR.red(), GLASS_COLOR.green(), GLASS_COLOR.blue(), 150), 1.5))
            p.drawRect(rect)
            p.setPen(QPen(GLASS_COLOR, 4, cap=Qt.PenCapStyle.RoundCap))
            n = min(18, rect.width() / 4, rect.height() / 4)
            x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
            for ax, ay, dx, dy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
                p.drawLine(QPointF(ax, ay), QPointF(ax + dx * n, ay))
                p.drawLine(QPointF(ax, ay), QPointF(ax, ay + dy * n))
