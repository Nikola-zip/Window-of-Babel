# 巴別塔之窗：介面主題
#
# 做咩：所有設定類視窗用 Fluent 元件（PyQt6-Fluent-Widgets）；顏色集中喺呢度：
#   淺色＝「古卷」暖沙色、磚紅掣；深色＝「夜空」深藍底、金色掣（配圖示個夜空同亮燈嘅窗，2026-10-31 用戶揀）。
#   預設跟 Windows 自動轉，用家可以喺設定揀（settings.json「介面主題」）。
#   個窗（塊玻璃）同譯文唔跟呢度：佢要透明浮喺畫面上面。
# 點用：main.py 開機叫 setup_theme()；每個 Fluent 視窗開嘅時候叫 style_window(視窗)。

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import FluentWidget, SystemThemeListener, Theme, isDarkTheme, qconfig, setTheme, setThemeColor

from ui_parts import load_settings, save_settings, make_icon

CHOICES = {"跟系統": Theme.AUTO, "淺色": Theme.LIGHT, "深色": Theme.DARK}
LIGHT = {"背景": "#f5ecd9", "主色": "#b5532e"}      # 古卷
DARK = {"背景": "#16233a", "主色": "#ffc95c"}       # 夜空
_listener = None        # 要留住參照：佢係條背景線，聽 Windows 轉深淺色


def _accent():
    # 主色要跟深淺色轉：Fluent 嘅 setThemeColor 冇分深淺，所以每次轉模式都要重新設
    setThemeColor((DARK if isDarkTheme() else LIGHT)["主色"])


def set_choice(choice):
    """用家揀主題：即刻生效兼存檔。"""
    settings = load_settings()
    settings["介面主題"] = choice
    save_settings(settings)
    setTheme(CHOICES.get(choice, Theme.AUTO))
    _accent()


def current_choice():
    choice = load_settings().get("介面主題", "跟系統")
    return choice if choice in CHOICES else "跟系統"


def setup_theme(app):
    """開機叫一次：套用設定、開始聽 Windows 轉深淺色（用「跟系統」嗰陣先有反應）。"""
    global _listener
    setTheme(CHOICES[current_choice()])
    _accent()
    qconfig.themeChanged.connect(lambda _: _accent())
    _listener = SystemThemeListener(app)
    _listener.start()


def style_window(window):
    """Fluent 視窗用我哋嘅底色；閂 Mica：佢會透出桌面顏色，蓋過古卷、夜空嘅底色。"""
    window.setMicaEffectEnabled(False)
    window.setCustomBackgroundColor(QColor(LIGHT["背景"]), QColor(DARK["背景"]))


def stop_theme():
    """閂程式叫：聽 Windows 轉色嗰條線要收工，唔係 Qt 會報「線仲行緊就銷毀」。"""
    if _listener is not None:
        _listener.terminate()
        _listener.wait()


class ThemedWindow(FluentWidget):
    """冇導覽列嘅細視窗（第一次設定、歷史、改譯文、網上搵譯名）嘅共用底座：標題列、圖示、置頂、底色、邊距統一。
    內容加落 self.body；頂部留返標題列嘅高度。"""

    def __init__(self, title, width, height):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(make_icon())
        # 個窗係置頂嘅，呢啲視窗都要置頂，唔係會被遮住
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(width, height)
        style_window(self)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 52, 24, 20)
        self.body.setSpacing(12)
        self.titleBar.raise_()


def muted_color():
    """淡色字（說明、原文）：深淺色主題都要睇得清。"""
    return "#a9bdd6" if isDarkTheme() else "#7a6248"


def accent_color():
    return (DARK if isDarkTheme() else LIGHT)["主色"]
