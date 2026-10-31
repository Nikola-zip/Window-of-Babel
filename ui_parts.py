# 巴別塔之窗：介面零件（由譯幕 p3_1_subtitle_bar.py 抽出嚟，字幕條本身唔要）
#
# 做咩：工具列嘅掣（IconButton、按住型 HoldButton、Toolbar）、程式圖示（make_icon）、字型、讀寫 settings.json。
# 點用：其他檔 import 呢度；呢個檔自己唔會開視窗。

import json
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QHBoxLayout, QWidget

SETTINGS = Path("settings.json")
CORNER_IDLE = 0.6   # 工具列平時幾透明；滑鼠移上去先變清楚。試過 0.35 加深灰色，用戶以為唔見咗
CHINESE_FONTS = ["Microsoft JhengHei UI", "Microsoft JhengHei"]


def make_font(families, size, bold=False):
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(size)
    font.setBold(bold)
    return font


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}   # 未有設定檔或者壞咗，就用預設


def save_settings(settings):
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


class IconButton(QWidget):
    """工具列入面嘅一粒掣（唔係獨立視窗，係工具列嘅一部分）。"""

    SIZE = 28

    def __init__(self, symbol, tip, on_click):
        super().__init__()
        self.symbol = symbol
        self.on_click = on_click    # 撳落去叫佢，會收到滑鼠位置（彈選單要用）
        self.active = False
        # 大細永遠唔變，所以用 setFixedSize 冇問題（字幕條先唔得，因為佢會變高）
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_active(self, on):
        """開關狀態：例如移動模式開咗，粒掣就變黃，工具列亦保持清楚。"""
        self.active = on
        self.update()
        if isinstance(self.parent(), Toolbar):
            self.parent().refresh()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.active:
            painter.setBrush(QColor("#f5c518"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 5, 5)
        painter.setPen(QColor("black") if self.active else QColor("white"))
        painter.setFont(make_font(["Segoe UI Symbol"], 13))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.symbol)

    def mousePressEvent(self, event):
        self.on_click(event.globalPosition().toPoint())

    def wheelEvent(self, event):
        # 工具列差唔多成條都係掣：喺掣上面轆都要交俾工具列（試過唔轉交，淨喺掣之間嘅空位轆先有反應）
        if isinstance(self.parent(), Toolbar):
            self.parent().wheelEvent(event)
        else:
            event.ignore()


class HoldButton(IconButton):
    """按住先生效、放手就停嘅掣（例如 👁 按住睇原文）：on_hold(True) 撳落，on_hold(False) 放手。"""

    def __init__(self, symbol, tip, on_hold):
        super().__init__(symbol, tip, lambda _: None)
        self.on_hold = on_hold

    def mousePressEvent(self, event):
        self.set_active(True)       # 變黃：知道而家睇緊原文
        self.on_hold(True)

    def mouseReleaseEvent(self, event):
        # 拖出粒掣外面先放手，Qt 都會將放手交返俾粒掣，唔會卡住喺原文
        self.set_active(False)
        self.on_hold(False)


class Toolbar(QWidget):
    """貼實字幕條右上角嘅細工具列：成條一齊透明、一齊變清楚，睇落係字幕條嘅一部分。"""

    def __init__(self, buttons):
        super().__init__()
        # 同字幕條一樣置頂、唔喺工作列、唔搶 focus；但唔穿透，先撳得到
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.buttons = buttons
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        for button in buttons:
            layout.addWidget(button)
        self.hovered = False
        self.on_wheel = None    # 用嘅地方想收滾輪就設（譯鏡：調譯文大細），收到 +1／-1 格
        self.wheel_left = 0     # 觸控板一次淨轆少少，儲夠一格（120）先算
        self.refresh()

    def wheelEvent(self, event):
        if self.on_wheel is None:
            event.ignore()
            return
        self.wheel_left += event.angleDelta().y()
        while abs(self.wheel_left) >= 120:
            step = 1 if self.wheel_left > 0 else -1
            self.wheel_left -= step * 120
            self.on_wheel(step)
        event.accept()

    def paintEvent(self, event):
        # 只有上面兩隻角係圓角，底部直接駁落字幕條，好似字幕條凸出嚟嘅分頁
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 6, 6)
        painter.drawRect(self.rect().adjusted(0, self.height() // 2, 0, 0))

    def refresh(self):
        """平時半透明唔搶眼；滑鼠移上去或者有掣開緊，就變清楚。"""
        clear = self.hovered or any(button.active for button in self.buttons)
        self.setWindowOpacity(1.0 if clear else CORNER_IDLE)

    def enterEvent(self, event):
        self.hovered = True
        self.refresh()

    def leaveEvent(self, event):
        self.hovered = False
        self.refresh()


# 圖示下面兩個對白框（2026-10-29 用戶揀 D2）：紅、黃兩種顏色＝唔同語言；（淺, 深）做 120° 輕漸變
ICON_BUBBLES = (("#ffb3a7", "#f06a5d"), ("#ffe08a", "#f5b83d"))
ICON_GLOW = "#4fc3f7"       # 頂嗰個對白框（窗）平時發藍光；狀態燈：灰等緊、紅出錯


def make_icon(color=ICON_GLOW, size=64):
    """巴別塔之窗圖示：三個對白框越上越細咁疊成塔，頂嗰個發光，就係「塔上面嗰扇窗」。

    唔用任何文字（Microsoft 圖示指引；用家講邊種語言都睇得明）。color 係頂嗰個框嘅光，
    即係狀態燈。直接用 size 畫（唔係畫大再縮），細圖先唔會矇。
    """
    s = size
    pixmap = QPixmap(s, s)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    layers = [QRectF(0.08 * s, 0.62 * s, 0.84 * s, 0.24 * s), QRectF(0.18 * s, 0.36 * s, 0.64 * s, 0.22 * s),
              QRectF(0.30 * s, 0.12 * s, 0.40 * s, 0.20 * s)]
    for i, rect in enumerate(layers):
        # 對白框：圓角方塊加一條細尾巴，尾巴左右交替，疊起嚟先似一座塔，唔似一棟聊天紀錄
        r = rect.height() * 0.38
        bubble = QPainterPath()
        bubble.addRoundedRect(rect, r, r)
        left = i % 2 == 0
        x, w = rect.left() + rect.width() * (0.22 if left else 0.78), rect.height() * 0.35
        tail = QPainterPath()
        tail.moveTo(x - w / 2, rect.bottom() - 1)
        tail.lineTo(x + w / 2, rect.bottom() - 1)
        tail.lineTo(x - w * (0.7 if left else -0.7), rect.bottom() + rect.height() * 0.32)
        tail.closeSubpath()
        bubble = bubble.united(tail)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawPath(bubble.translated(0, s * 0.025))     # 輕陰影：層與層分得開
        if i == len(layers) - 1:
            light = QRadialGradient(rect.center(), rect.width() * 0.7)
            light.setColorAt(0, QColor(color).lighter(175))
            light.setColorAt(1, QColor(color))
            p.setBrush(light)
        else:
            shade = QLinearGradient(rect.topLeft(), rect.bottomRight())     # 光由左上嚟
            shade.setColorAt(0, QColor(ICON_BUBBLES[i][0]))
            shade.setColorAt(1, QColor(ICON_BUBBLES[i][1]))
            p.setBrush(shade)
        p.drawPath(bubble)
        if i < len(layers) - 1:
            # 框入面兩行「字」用線代替：邊種語言都睇得明係「講嘢」
            p.setPen(QPen(QColor(0, 0, 0, 90), max(1.0, s * 0.04), cap=Qt.PenCapStyle.RoundCap))
            y1, y2 = rect.top() + rect.height() * 0.38, rect.top() + rect.height() * 0.64
            p.drawLine(QPointF(rect.left() + rect.width() * 0.2, y1), QPointF(rect.right() - rect.width() * 0.2, y1))
            p.drawLine(QPointF(rect.left() + rect.width() * 0.2, y2), QPointF(rect.right() - rect.width() * 0.4, y2))
    p.end()
    return QIcon(pixmap)
