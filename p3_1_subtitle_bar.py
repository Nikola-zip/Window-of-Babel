# 譯幕 第3期第1步：字幕條外觀
#
# 做咩：喺畫面底部開一條半透明、置頂、滑鼠穿透嘅字幕條，
#       用假字幕每 2.5 秒換一句，120 秒後自動閂。
#       第一次開會入「拖動模式」：拖去想要嘅位置，雙擊或者右撳完成，位置會記住。
# 點用：.venv\Scripts\python p3_1_subtitle_bar.py
#       工作列右下角有個「譯鏡」圖示（一塊分兩半嘅鏡），右撳可以搬位、還原預設位置、閂；
#       亦可以加 --move 一開就入拖動模式，或者喺 terminal 撳 Ctrl+C 閂。
# 第 2 關之後會 import 呢度嘅 SubtitleBar。

import json
import signal
import sys
from html import escape
from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QAction,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from p7_1_target import current
from p8_6_fonts import chosen, has_bold

MAX_SENTENCES = 2       # 規格：同時最多顯示兩句，再多會遮住畫面
BOTTOM_MARGIN = 40      # 離工作列幾多 pixel，費事遮住片嘅進度條
# 用戶可以喺 settings.json 嘅「字幕樣式」改；key 用中文，一睇就知改邊個
DEFAULT_STYLE = {
    "黑底深淺": 0.63,        # 0 = 完全透明，1 = 全黑；淡啲就透得到片入面本身嘅字
    "原文字體大細": 13,
    "譯文字體大細": 22,
    "闊度比例": 0.7,         # 佔螢幕闊度幾多；窄啲遮得少啲
    "字邊陰影": True,        # 每隻字外面一圈黑邊；黑底深淺設 0 都喺光畫面睇得清
    "顯示原文": True,        # 收起原文行就矮一半，遮少啲畫面（熱鍵 Ctrl+Alt+O）
    # 「貼字」：每行字後面一嚿啱啱包住佢嘅黑底（YouTube CC 咁），遮得最少；
    # 「成條」：成個闊度都係黑，配 100% 深淺可以蓋住片本身嘅字幕
    "黑底範圍": "貼字",
}
BOX_MODES = ("貼字", "成條")
BOX_PAD_X, BOX_PAD_Y = 8, 2     # 貼字黑底比啲字闊出幾多
OUTLINE = 2     # 字邊幾粗（pixel）；太粗啲字會黐埋一嚿
EDGE = 14       # 拖動模式下，離左右邊幾近當係「拉邊改闊度」
CORNER_GRIP = 24    # 角落可以捉嘅範圍；大過拉邊嗰個，因為打斜好難瞄得準
HANDLE = 12         # 角落把手畫幾大
CORNER_IDLE = 0.6   # 角落齒輪平時幾透明；滑鼠移上去先變清楚。試過 0.35 加深灰色，用戶以為唔見咗
# 調樣式時冇字幕顯示緊，就出呢句俾人睇住調
PREVIEW = ("ja", "プレビュー：字幕はこう見えます", "預覽：字幕會是這個樣子。")
# 舊嗰句啲字暗啲，一眼分到邊句係新。只係改字色，唔郁黑底：
# 黑底要跟足「黑底深淺」，100% 就係實色，片本身嘅字幕先唔會透出嚟
TEXT_COLORS = {
    False: ("#b8b8b8", "white"),        # 新句：（原文, 譯文）
    True: ("#7a7a7a", "#a8a8a8"),       # 舊句
}
GLOSSARY_COLOR = "#7CFC7C"  # 規格：跟詞庫譯嘅字用綠色，一眼知係指定譯名
PENDING = "⋯"          # 原文出咗、譯文未到嗰陣顯示
DEMO_SECONDS = 120
SETTINGS = Path("settings.json")    # 記住字幕條位置；之後熱鍵、詞庫揀選都可以放埋入去

# 原文按語言揀字型：日文漢字用中文字型，有啲字形會同日本寫法唔同
ORIGINAL_FONTS = {
    "ja": ["Yu Gothic UI", "Meiryo"],
    "ko": ["Malgun Gothic"],
    "en": ["Segoe UI"],
}
# 正黑體係 Windows 內置嘅繁體字型；揀唔到嘅字（例如假名）會順住清單搵落去
CHINESE_FONTS = ["Microsoft JhengHei UI", "Microsoft JhengHei"]

DEMO = [
    ("ja", "明日は早いので、もう寝ます", "明天要早起，我先去睡了。"),
    ("en", "No way, you've gotta be kidding me!", "不可能，你一定是在開玩笑吧！"),
    ("ja", "では、聞き耳判定をどうぞ。", "那麼，請進行聆聽判定吧。"),
    ("ko", "오늘은 여기까지 하고 내일 다시 이야기합시다.", "今天就到這裡吧，明天再繼續談吧。"),
    ("ja", "耳にまだ水が残っていたのか、あなたの聞き耳は働きませんでした。",
     "或許是耳朵裡還殘留著水，你的聆聽沒有發揮作用。"),
]


def make_font(families, size, bold=False):
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(size)
    font.setBold(bold)
    return font


class OutlinedLabel(QLabel):
    """會畫黑邊嘅 QLabel：先用黑色喺四周八個方向各畫一次，再喺正中畫原色。

    Qt 內置嘅陰影效果只得一層又一定係矇，喺光畫面睇唔清，所以自己畫。
    """

    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.outline = 0    # 0 = 唔畫邊
        self.box = None     # 「貼字」黑底嘅顏色；None = 唔畫（成條模式由外面嗰個框畫）
        # 留位俾黑邊同貼字黑底，費事頭尾被切走
        self.setContentsMargins(OUTLINE, OUTLINE, OUTLINE, OUTLINE)

    def paintEvent(self, event):
        if not self.outline and not self.box:
            return super().paintEvent(event)    # 兩樣都唔使，交返俾 QLabel 自己畫
        area = self.contentsRect()
        rich = self.textFormat() == Qt.TextFormat.RichText
        fill = self._document(area.width(), self.text(), rich)
        top = area.top() + (area.height() - fill.size().height()) / 2   # 上下置中，同 QLabel 一樣
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.box:
            # 貼字黑底：每一行字計返佢實際嘅位置同闊度，喺後面畫一嚿
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.box)
            for line in self._line_rects(fill):
                rect = line.translated(area.left(), top).adjusted(-BOX_PAD_X, -BOX_PAD_Y, BOX_PAD_X, BOX_PAD_Y)
                painter.drawRoundedRect(rect, 4, 4)
        if self.outline:
            # 黑邊用純文字：唔使理綠色，全部畫黑就得
            edge = self._document(area.width(), fill.toPlainText(), False)
            steps = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
            for dx, dy in steps:
                self._draw(painter, edge, area.left() + dx * self.outline, top + dy * self.outline, QColor("black"))
        self._draw(painter, fill, area.left(), top, self.color)

    @staticmethod
    def _line_rects(doc):
        """排好版之後，每一行字實際佔嘅長方形（已經計埋置中）。"""
        rects = []
        block = doc.begin()
        while block.isValid():
            layout = block.layout()
            origin = layout.position()
            for i in range(layout.lineCount()):
                rects.append(layout.lineAt(i).naturalTextRect().translated(origin))
            block = block.next()
        return rects

    def _document(self, width, text, rich):
        """用同 QLabel 一樣嘅字型、闊度、對齊同轉行方法排版，畫出嚟先唔會錯位。"""
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        option = QTextOption(self.alignment())
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        doc.setDefaultTextOption(option)
        if rich:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(width)
        return doc

    def _draw(self, painter, doc, x, y, color):
        painter.save()
        painter.translate(QPointF(x, y))
        context = QAbstractTextDocumentLayout.PaintContext()
        # 預設字色；HTML 入面寫明顏色嘅（綠色詞庫字）會蓋過佢
        context.palette.setColor(QPalette.ColorRole.Text, color)
        doc.documentLayout().draw(painter, context)
        painter.restore()


class SentenceView(QFrame):
    """一句字幕：上面細細行原文，下面大大行譯文。"""

    def __init__(self, lang, original, translation, style=DEFAULT_STYLE):
        super().__init__()
        self.setObjectName("sentence")
        self.lang = lang

        self.original = OutlinedLabel(TEXT_COLORS[False][0])
        # 原文係純文字：費事原文入面有 < 呢類符號被當成 HTML
        self.original.setTextFormat(Qt.TextFormat.PlainText)
        self.original.setText(f"{lang.upper()}　{original}")

        self.translation = OutlinedLabel(TEXT_COLORS[False][1])
        self.set_old(False)
        self.apply_style(style)
        # 用 rich text 先可以將詞庫詞染綠；所以譯文要先 escape，費事入面有 < > 被當成 HTML
        self.translation.setTextFormat(Qt.TextFormat.RichText)
        self.set_translation(translation)
        self.n = None   # 句子編號：譯文遲啲先到，靠佢搵返係邊句

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 10)
        layout.setSpacing(2)
        for label in (self.original, self.translation):
            label.setWordWrap(True)     # 長句自動轉行，唔好凸出畫面
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

    def set_old(self, old):
        """新句字光啲、舊句字暗啲；黑底唔郁。"""
        for label, color in zip((self.original, self.translation), TEXT_COLORS[old]):
            # 顏色要同時設兩度：stylesheet 係冇字邊時 QLabel 自己畫用，
            # .color 係有字邊時 OutlinedLabel 自己畫用
            label.color = QColor(color)
            label.setStyleSheet(f"color: {color};")
            label.update()

    def apply_style(self, style):
        """套用黑底深淺同字體大細；重新載入樣式時都會叫，所以獨立出嚟。"""
        # 半透明黑底：字幕要喺光暗唔同嘅畫面都睇得清，又唔好完全遮住
        alpha = round(255 * style["黑底深淺"])
        hug = style["黑底範圍"] == "貼字"
        # 成條：外面個框畫黑底；貼字：框透明，由每行字自己畫一嚿啱啱包住佢嘅黑底
        frame_alpha = 0 if hug else alpha
        self.setStyleSheet(f"#sentence {{ background: rgba(0, 0, 0, {frame_alpha}); border-radius: 10px; }}")
        for label in (self.original, self.translation):
            label.box = QColor(0, 0, 0, alpha) if hug and alpha else None
        self.original.setFont(make_font(ORIGINAL_FONTS.get(self.lang, []) + CHINESE_FONTS, style["原文字體大細"]))
        # 字型跟「譯做」嗰種語言（第 7 期）：正黑體冇韓文字，排後做後備
        # 揀咗嘅字幕字型排第一（第 8 期），冇嗰隻字就用後面嘅
        family = chosen("字幕")      # 冇真粗體嘅字型唔加粗（假粗體會糊）
        self.translation.setFont(make_font([family] + list(current().fonts) + CHINESE_FONTS,
                                           style["譯文字體大細"], bold=has_bold(family)))
        for label in (self.original, self.translation):
            label.outline = OUTLINE if style["字邊陰影"] else 0
            label.update()
        self.original.setVisible(style["顯示原文"])

    def set_original(self, original):
        """換原文行：6 秒切開嘅兩截合埋之後，原文要顯示成句。"""
        self.original.setText(f"{self.lang.upper()}　{original}")

    def set_translation(self, translation, terms=()):
        """換上譯文；terms 係 [(原文, 譯名)]，譯名用綠色。"""
        html = escape(translation)
        # 長嘅先換：「流動網絡」同「網絡」都有嘅話，先包住長嗰個
        for target in sorted({t for _, t in terms}, key=len, reverse=True):
            html = html.replace(escape(target), f'<span style="color:{GLOSSARY_COLOR};">{escape(target)}</span>')
        self.translation.setText(html)


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}   # 未有設定檔或者壞咗，就用預設


def save_settings(settings):
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_style():
    """讀「字幕樣式」；冇寫或者寫錯嘅項目用預設，再寫返入檔，等用戶知道有咩可以改。"""
    settings = load_settings()
    saved = settings.get("字幕樣式", {})
    style = {}
    for key, default in DEFAULT_STYLE.items():
        value = saved.get(key, default)
        if isinstance(default, bool):
            # 開關要真係 true／false；寫咗 "false" 呢類字串，bool() 會當咗係 True
            style[key] = value if isinstance(value, bool) else default
            continue
        try:
            style[key] = type(default)(value)
        except (TypeError, ValueError):
            style[key] = default    # 例如打錯咗字，唔好令成個程式死
    # 夾返喺合理範圍：太細睇唔到、太闊會出界
    style["黑底深淺"] = min(max(style["黑底深淺"], 0.0), 1.0)
    if style["黑底範圍"] not in BOX_MODES:
        style["黑底範圍"] = DEFAULT_STYLE["黑底範圍"]
    style["闊度比例"] = min(max(style["闊度比例"], 0.2), 1.0)
    for key in ("原文字體大細", "譯文字體大細"):
        style[key] = min(max(style[key], 6), 72)
    if saved != style:
        settings["字幕樣式"] = style
        save_settings(settings)
    return style


class SubtitleBar(QWidget):
    """置頂、穿透、唔搶 focus 嘅字幕條；拖動模式下可以搬位。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint           # 冇標題列同邊框
            | Qt.WindowType.WindowStaysOnTopHint        # 永遠喺其他視窗上面
            | Qt.WindowType.Tool                        # 唔喺工作列出現
            | Qt.WindowType.WindowTransparentForInput   # 滑鼠穿透：撳落去等於撳後面
        )
        # 視窗本身透明，只有字幕嗰嚿黑底先睇到
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 出新字幕都唔好搶走遊戲或者播放器嘅鍵盤
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)
        # 大細由 _place() 自己計同設定；唔畀 layout 再加限制，費事兩邊打交
        self.box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.views = []

        # 拖動模式先出嘅提示
        self.hint = QLabel("拖我去想要嘅位置；拉左右兩邊改闊度；捉四角成條縮放；雙擊或者右撳完成")
        self.hint.setFont(make_font(CHINESE_FONTS, 13, bold=True))
        self.hint.setStyleSheet("background: #f5c518; color: black; border-radius: 6px; padding: 4px;")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 要轉行：唔係提示最少要成行咁闊，會頂住字幕條，拉唔窄
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.box.addWidget(self.hint)
        # 狀態行（例如「翻譯斷咗」）：擺喺字幕上面。唔可以淨靠 Windows 通知，
        # 因為打機、全螢幕睇片時 Windows 會收埋通知，用戶望住嘅只有字幕條
        self.status = QLabel()
        self.status.setStyleSheet(
            "background: rgba(0, 0, 0, 200); color: #ffd54a; border-radius: 6px; padding: 3px 10px;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.hide()
        # 置中、跟字嘅長度，唔好成條咁闊遮住片
        self.box.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignHCenter)
        # 每類狀態（翻譯、聲源）各一行，費事「翻譯恢復」蓋走仲未解決嘅「聲源斷咗」
        self.statuses = {}
        self.status_timers = {}     # 「翻譯恢復」呢類好消息出幾秒就自己收，每類一個鐘
        # 移動模式先出嘅把手層：蓋喺最上面，畫把手兼接收所有滑鼠動作
        self.grips = GripOverlay(self)

        # 唔好叫 self.style：Qt 視窗本身有個 style() 方法，蓋咗會出怪錯
        self.look = load_style()
        self.paused = False     # 暫停時收埋，改設定都唔好自己彈返出嚟
        self.dragging = False
        self.drag_offset = QPoint()
        self.resizing = None    # 拉緊邊改闊度："left"、"right"；None = 唔係
        self.scaling = False    # 捉住角：闊度同字體一齊按比例變
        self.scale_from = None  # 捉角嗰刻嘅（闊度, 原文字體, 譯文字體），按佢計比例
        # 右上角嘅細工具列，由 make_tray() 開。字幕條要穿透，Windows 做唔到
        # 「同一個視窗一部分穿透、一部分撳得到」，所以工具列係另一個貼實嘅細視窗
        self.toolbar = None
        self.move_button = None # 「移動」掣：移動模式時要變黃
        # 位置記「邊個螢幕＋中間喺幾左＋底邊喺幾高（比例）」，唔記死 pixel：
        # 字幕條會隨句數變高，底邊固定，內容多就向上長，唔會跌出畫面
        self.anchor = load_settings().get("bar") or self._default_anchor()

    def refresh_fonts(self):
        """轉咗「譯做」語言：而家顯示緊嘅字幕換返啱嘅字型（唔使好似 set_look 咁存檔、出預覽句）。"""
        for view in self.views:
            view.apply_style(self.look)
        if self.views:
            self._refresh(self.views[-1])

    def set_look(self, look):
        """換樣式：存入 settings.json，即刻套落而家顯示緊嘅字幕。"""
        self.look = dict(look)
        settings = load_settings()
        settings["字幕樣式"] = self.look
        save_settings(settings)
        for view in self.views:
            view.apply_style(self.look)
        if self.views:
            self._refresh(self.views[-1])
        else:
            self.show_sentence(*PREVIEW)    # 冇字幕都要有嘢睇住調

    def set_paused(self, on):
        """暫停：收起字幕條；繼續：有字幕就擺返出嚟。"""
        self.paused = on
        if on:
            self.hide()
        elif self.views:
            self.show()

    def set_status(self, text, seconds=0, kind="翻譯"):
        """喺字幕上面顯示一類狀態（kind）；唔同類各佔一行。

        seconds 係 0 就一直顯示，直至同一類嘅下一個狀態；空字串就收起嗰行。
        """
        timer = self.status_timers.get(kind)
        if timer:
            timer.stop()
        if text:
            self.statuses[kind] = text
        else:
            self.statuses.pop(kind, None)
        if text and seconds:
            if not timer:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: self.set_status("", kind=kind))
                self.status_timers[kind] = timer
            timer.start(int(seconds * 1000))
        # 字體跟原文行：成條字幕放大縮細嗰陣，狀態行都跟住變
        self.status.setFont(make_font(CHINESE_FONTS, self.look["原文字體大細"], bold=True))
        self.status.setText("\n".join(self.statuses.values()))
        self.status.setVisible(bool(self.statuses))
        self.status.ensurePolished()
        self._place()
        if self.statuses and not self.paused:
            self.show()
        QTimer.singleShot(0, self._place)   # 同 _refresh 一樣，等 Qt 排好版再計多次高度

    def reload_style(self):
        """用戶手改咗 settings.json 之後，重新讀入嚟。"""
        self.set_look(load_style())
        print(f"樣式：{self.look}")

    def reset_position(self):
        """還原做主螢幕底部正中。"""
        self.anchor = self._default_anchor()
        settings = load_settings()
        settings["bar"] = self.anchor
        save_settings(settings)
        self._place()

    def _default_anchor(self):
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        return {"screen": screen.name(), "x": 0.5, "bottom": (area.height() - BOTTOM_MARGIN) / area.height()}

    def _screen(self):
        """搵返記住嗰個螢幕；拔咗嗰個螢幕就用主螢幕。"""
        for screen in QApplication.screens():
            if screen.name() == self.anchor["screen"]:
                return screen
        return QApplication.primaryScreen()

    def set_drag_mode(self, on):
        """拖動模式：暫時唔穿透、出提示；完成就記住位置，變返穿透。"""
        self.dragging = on
        self.hint.setVisible(on)
        if self.move_button:
            self.move_button.set_active(on)     # 變黃，話你知而家係移動模式
        # 把手層蓋住成條字幕：每句字都係獨立小元件，冇呢層嘅話，
        # 滑鼠喺字上面郁，字幕條收唔到，游標唔會轉，角落好難搵
        self.grips.setVisible(on)
        self.grips.raise_()
        self.unsetCursor()
        # 改 window flag 會令視窗收埋，要 show 返
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not on)
        if not on:
            settings = load_settings()
            settings["bar"] = self.anchor
            save_settings(settings)
            print(f"位置記住咗：{self.anchor}")
        self._place()
        self.show()

    def _grip_at(self, pos):
        """滑鼠捉住邊度：回傳（"left"／"right"／None, 係咪喺角, 係咪喺上面）。"""
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        near_left, near_right = x <= CORNER_GRIP, x >= w - CORNER_GRIP
        near_top, near_bottom = y <= CORNER_GRIP, y >= h - CORNER_GRIP
        # 角落優先，而且範圍大啲：打斜最難瞄
        if (near_left or near_right) and (near_top or near_bottom):
            return ("left" if near_left else "right"), True, near_top
        side = "left" if x <= EDGE else "right" if x >= w - EDGE else None
        return side, False, near_top

    def mousePressEvent(self, event):
        if not self.dragging:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.set_drag_mode(False)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.resizing, self.scaling, _ = self._grip_at(event.position())
            if self.scaling:
                self.scale_from = (self.width(), self.look["原文字體大細"], self.look["譯文字體大細"])
            # 記低撳落去嗰點離視窗左上角幾遠，拖嘅時候保持唔變，唔會跳位
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if not self.dragging:
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:
            # 未撳落去：按滑鼠喺邊轉游標，提你撳落去會做咩
            side, corner, top = self._grip_at(event.position())
            self.grips.set_hover(side, corner, top)     # 指住嗰個把手變白
            if corner:
                # 左上同右下係「↖↘」，右上同左下係「↗↙」
                main_diagonal = (side == "left") == top
                shape = Qt.CursorShape.SizeFDiagCursor if main_diagonal else Qt.CursorShape.SizeBDiagCursor
            elif side:
                shape = Qt.CursorShape.SizeHorCursor
            else:
                shape = Qt.CursorShape.SizeAllCursor
            self.setCursor(shape)
        elif self.resizing:
            self._resize_to(event.globalPosition().toPoint().x())
        else:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            self._remember_position()

    def _resize_to(self, mouse_x):
        """拉邊改闊度：拉緊嗰邊跟住滑鼠，另一邊唔郁。"""
        frame = self.geometry()
        area = self._screen().availableGeometry()
        left, right = frame.left(), frame.right()
        if self.resizing == "left":
            left = min(mouse_x, right - 200)    # 最少留 200 pixel，費事縮到冇咗
        else:
            right = max(mouse_x, left + 200)
        width = min(right - left, area.width())
        # 闊度同中間點都換算做比例，同樣式視窗嗰條「闊度」拉桿係同一個設定
        self.look["闊度比例"] = width / area.width()
        self.anchor["x"] = (left + width / 2 - area.x()) / area.width()
        if self.scaling:
            # 捉角：字體跟住闊度按同一個比例變，成條字幕放大縮細
            start_width, start_original, start_translation = self.scale_from
            factor = width / start_width
            self.look["原文字體大細"] = min(max(round(start_original * factor), 6), 72)
            self.look["譯文字體大細"] = min(max(round(start_translation * factor), 6), 72)
            for view in self.views:
                view.apply_style(self.look)
        self._place()

    def mouseReleaseEvent(self, event):
        if not self.dragging:
            return
        if self.resizing:
            self.resizing = None
            self.scaling = False
            self.set_look(self.look)    # 拉完先存檔，唔使拉一下存一次
        self._place()   # 拖去第二個螢幕嘅話，按嗰個螢幕重新計闊度

    def showEvent(self, event):
        # 工具列跟住字幕條一齊出、一齊收
        if self.toolbar:
            self._place_toolbar()
            self.toolbar.show()
            self.toolbar.raise_()

    def hideEvent(self, event):
        if self.toolbar:
            self.toolbar.hide()

    def moveEvent(self, event):
        # 字幕條每郁一下（拖緊、拉緊邊、換句變高）工具列都即刻跟，唔使等移動完成
        self._place_toolbar()

    def resizeEvent(self, event):
        if hasattr(self, "grips"):      # 視窗啱啱建立、把手層未開好時都可能觸發
            self.grips.setGeometry(self.rect())     # 把手層永遠蓋滿成條字幕
        self._place_toolbar()

    def _content_right(self):
        """字幕嘅字實際去到幾右（字幕條入面嘅 x）。

        成條模式黑底就係成條，用成條嘅右邊；貼字模式其他位係透明，
        用返成條嘅右邊會令齒輪浮喺離字好遠嘅空位，用戶以為唔見咗，所以要搵最闊嗰行字嘅右邊。
        """
        if self.look["黑底範圍"] != "貼字" or self.dragging:
            return self.width()
        right = None
        labels = [label for view in self.views for label in (view.original, view.translation)]
        for label in labels:
            if not label.isVisible():
                continue
            area = label.contentsRect()
            rich = label.textFormat() == Qt.TextFormat.RichText
            for line in label._line_rects(label._document(area.width(), label.text(), rich)):
                x = label.mapTo(self, QPoint(round(area.left() + line.right() + BOX_PAD_X), 0)).x()
                right = x if right is None else max(right, x)
        if self.status.isVisible():
            right = max(right or 0, self.status.geometry().right())
        # 乜嘢都未有（啱開機）：擺喺正中
        return right if right is not None else (self.width() + (self.toolbar.width() if self.toolbar else 0)) // 2

    def _place_toolbar(self):
        """工具列貼實字幕右上角上面，好似字幕凸出嚟嘅分頁；貼頂就擺返入面。"""
        if not self.toolbar:
            return
        frame = self.geometry()
        area = self._screen().availableGeometry()
        x = frame.left() + self._content_right() + 1 - self.toolbar.width()
        y = frame.top() - self.toolbar.height()
        if y < area.top():
            y = frame.top()
        self.toolbar.move(x, y)
        self.toolbar.raise_()

    def mouseDoubleClickEvent(self, event):
        if self.dragging:
            self.set_drag_mode(False)

    def _remember_position(self):
        """將而家個位轉做「螢幕＋比例」記低。"""
        frame = self.geometry()
        center = QPoint(frame.center().x(), frame.bottom())
        screen = QApplication.screenAt(center) or self._screen()
        area = screen.availableGeometry()
        self.anchor = {
            "screen": screen.name(),
            "x": (center.x() - area.x()) / area.width(),
            "bottom": (frame.bottom() - area.y()) / area.height(),
        }

    def show_sentence(self, lang, original, translation=PENDING, n=None):
        """加一句新字幕喺最底；超過兩句就踢走最舊嗰句。

        n 係句子編號：原文可以先出，譯文之後用 set_translation(n, …) 補返。
        """
        view = SentenceView(lang, original, translation, self.look)
        view.n = n
        self.views.append(view)
        self.box.addWidget(view)
        while len(self.views) > MAX_SENTENCES:
            old = self.views.pop(0)
            self.box.removeWidget(old)
            old.deleteLater()
        # 新句加喺下面，舊句自然被推上去；再調淡佢，等新句突出
        for older in self.views[:-1]:
            older.set_old(True)
        self._refresh(view)

    def set_translation(self, n, translation, terms=()):
        """將譯文補返落編號 n 嗰句。"""
        for view in self.views:
            if view.n == n:
                view.set_translation(translation, terms)
                self._refresh(view)     # 譯文長過「⋯」，高度要重新計
                return
        # 搵唔到即係嗰句已經被新句擠走咗，唔使理

    def merge(self, first_n, n, original, translation, terms=()):
        """6 秒切開嘅兩截合埋：上半截（first_n）嗰行收走，下半截（n）嗰行換做成句原文同譯文。"""
        target = next((view for view in self.views if view.n == n), None)
        if target is None:
            return      # 下半截都已經被擠走，冇地方顯示
        for view in [view for view in self.views if view.n == first_n]:
            self.views.remove(view)
            self.box.removeWidget(view)
            view.deleteLater()
        target.set_original(original)
        target.set_translation(translation, terms)
        self._refresh(target)

    def _refresh(self, view):
        # 新句未「上妝」（未套用字型同樣式）時計出嚟嘅高度會偏細，字幕會被壓扁，
        # 所以先叫佢即刻套用，再計大細
        for widget in [view, *view.findChildren(QLabel)]:
            widget.ensurePolished()
        if self.dragging:
            self.grips.raise_()     # 新加嘅句會蓋過把手層，擺返佢喺最上面
        self._place()
        if not self.paused:
            self.show()
        # 等 Qt 處理完手頭嘅嘢再計多一次，雙重保險
        QTimer.singleShot(0, self._place)

    def _place(self):
        """按記住嘅位置擺字幕條：中間對準、底邊對準，唔好出界。"""
        area = self._screen().availableGeometry()   # 已經扣咗工作列
        width = int(area.width() * self.look["闊度比例"])
        # 字幕會自動轉行，高度要按闊度計返出嚟，唔係長句會被截走
        self.box.activate()
        height = self.box.heightForWidth(width) if self.box.hasHeightForWidth() else self.sizeHint().height()
        x = area.x() + int(self.anchor["x"] * area.width()) - width // 2
        bottom = area.y() + int(self.anchor["bottom"] * area.height())
        # 夾返喺螢幕入面：拖得太埋邊，或者內容長咗，都唔會凸出去
        x = max(area.left(), min(x, area.right() - width))
        y = max(area.top(), min(bottom - height, area.bottom() - height))
        # 位置同大細一次過設定。唔好用 setFixedSize：佢鎖死最細最大值，
        # 內容一變高，Windows 仲守住舊限制，高度會卡死、字幕被壓扁
        self.setGeometry(QRect(x, y, width, height))
        self._place_toolbar()


class GripOverlay(QWidget):
    """移動模式時蓋喺字幕條最上面：四角畫方塊、兩邊畫直條，話你知邊度捉得。

    滑鼠動作全部轉交返字幕條處理；兩者左上角重疊，所以座標唔使換算。
    """

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.setMouseTracking(True)     # 未撳落去都要知滑鼠喺邊，先轉得游標
        self.hover = (None, False, False)
        self.hide()

    def set_hover(self, side, corner, top):
        if (side, corner, top) != self.hover:
            self.hover = (side, corner, top)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 粗黑邊：頂部兩隻角撞正黃色提示，冇黑邊會睇唔到
        painter.setPen(QPen(QColor("black"), 2))
        w, h = self.width(), self.height()
        side, corner, top = self.hover
        for left in (True, False):
            name = "left" if left else "right"
            # 四隻角：方塊
            for at_top in (True, False):
                hot = corner and side == name and top == at_top
                painter.setBrush(QColor("white") if hot else QColor("#f5c518"))
                x = 0 if left else w - HANDLE
                y = 0 if at_top else h - HANDLE
                painter.drawRoundedRect(QRect(x, y, HANDLE, HANDLE), 3, 3)
            # 左右兩邊中間：直條（拉闊度）
            hot = not corner and side == name
            painter.setBrush(QColor("white") if hot else QColor("#f5c518"))
            painter.drawRoundedRect(QRect(0 if left else w - 6, h // 2 - 14, 6, 28), 3, 3)

    # 收到嘅滑鼠動作原封不動交俾字幕條
    def mousePressEvent(self, event):
        self.bar.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.bar.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.bar.mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.bar.mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.set_hover(None, False, False)


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


class StyleDialog(QWidget):
    """改字幕樣式嘅細視窗：一郁即刻套落字幕條，同時存檔。"""

    def __init__(self, bar, embedded=False):
        super().__init__()
        self.bar = bar
        if not embedded:    # embedded：擺入設定視窗（第 8 期）做「字幕」頁，唔使自己做視窗
            self.setWindowTitle("譯幕：字幕樣式")
            # 字幕條係置頂嘅，呢個視窗都要置頂，唔係會被遮住
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        # 比例用 0 至 100 嘅拉桿，比打小數直觀；右邊個數字話你而家係幾多
        self.depth, depth_row = self._slider(0, 100)
        self.box_mode = QComboBox()
        self.box_mode.addItems(BOX_MODES)
        self.width_ratio, width_row = self._slider(20, 100)
        self.original_size = QSpinBox()
        self.translation_size = QSpinBox()
        for box in (self.original_size, self.translation_size):
            box.setRange(6, 72)
        self.outline = QCheckBox("每隻字加黑邊")
        self.show_original = QCheckBox("顯示原文行（Ctrl+Alt+O）")
        reset = QPushButton("還原預設")

        form = QFormLayout(self)
        form.addRow("黑底深淺", depth_row)
        form.addRow("黑底範圍", self.box_mode)
        form.addRow("闊度", width_row)
        form.addRow("原文字體大細", self.original_size)
        form.addRow("譯文字體大細", self.translation_size)
        form.addRow("字邊陰影", self.outline)
        form.addRow("原文", self.show_original)
        form.addRow(reset)

        self.load(bar.look)
        for slider in (self.depth, self.width_ratio):
            slider.valueChanged.connect(self._changed)
        for box in (self.original_size, self.translation_size):
            box.valueChanged.connect(self._changed)
        self.outline.toggled.connect(self._changed)
        self.show_original.toggled.connect(self._changed)
        self.box_mode.currentTextChanged.connect(self._changed)
        reset.clicked.connect(self._reset)

    def _slider(self, low, high):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        value = QLabel()
        value.setMinimumWidth(40)
        slider.valueChanged.connect(lambda v: value.setText(f"{v}%"))
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)
        layout.addWidget(value)
        return slider, row

    def load(self, look):
        """將樣式擺入各個控制項。"""
        # 擺嘅時候唔好觸發 _changed，唔係擺一個存一次，仲會用半新半舊嘅值
        controls = (self.depth, self.width_ratio, self.original_size, self.translation_size,
                    self.outline, self.show_original, self.box_mode)
        for control in controls:
            control.blockSignals(True)
        self.depth.setValue(round(look["黑底深淺"] * 100))
        self.width_ratio.setValue(round(look["闊度比例"] * 100))
        self.original_size.setValue(look["原文字體大細"])
        self.translation_size.setValue(look["譯文字體大細"])
        self.outline.setChecked(look["字邊陰影"])
        self.show_original.setChecked(look["顯示原文"])
        self.box_mode.setCurrentText(look["黑底範圍"])
        for control in controls:
            control.blockSignals(False)
        # blockSignals 期間拉桿旁邊個數字冇更新，補返
        for slider in (self.depth, self.width_ratio):
            slider.valueChanged.emit(slider.value())

    def _changed(self):
        self.bar.set_look({
            "黑底深淺": self.depth.value() / 100,
            "原文字體大細": self.original_size.value(),
            "譯文字體大細": self.translation_size.value(),
            "闊度比例": self.width_ratio.value() / 100,
            "字邊陰影": self.outline.isChecked(),
            "顯示原文": self.show_original.isChecked(),
            "黑底範圍": self.box_mode.currentText(),
        })

    def _reset(self):
        self.load(DEFAULT_STYLE)
        self._changed()


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


def make_tray(bar, app, extra=()):
    """工作列右下角嘅小圖示：字幕條平時穿透撳唔到，靠呢度搬位同閂。

    extra 係 [(選單文字, 功能)]，放喺選單最頂，例如第 4 關嘅「歷史」。
    """
    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip("譯幕")
    tray.dialog = None
    # 有圖示負責「閂譯幕」，所以閂咗樣式視窗都唔好成個程式收工
    app.setQuitOnLastWindowClosed(False)

    def open_style():
        # 第一次撳先開；要留住參照，唔係 Python 回收咗個視窗就即刻消失
        if tray.dialog is None:
            tray.dialog = StyleDialog(bar)
        tray.dialog.load(bar.look)      # 可能手改過 settings.json，用最新嘅值
        tray.dialog.show()
        tray.dialog.raise_()
        tray.dialog.activateWindow()

    menu = QMenu()
    for text, action in (
        *extra,
        ("字幕樣式…", open_style),
        ("搬字幕條位置", lambda: bar.set_drag_mode(True)),
        ("還原預設位置", bar.reset_position),
        ("重新載入樣式", bar.reload_style),
        ("閂譯幕", app.quit),
    ):
        item = QAction(text, menu)
        item.triggered.connect(action)
        menu.addAction(item)
    tray.setContextMenu(menu)
    tray.show()
    # 右上角工具列：移動掣撳一下入移動模式，再撳完成；齒輪出同右下角圖示一樣嘅選單。
    # 要留住參照，唔係會被 Python 回收
    move = IconButton("✥", "移動／改大細（再撳一下完成）", lambda _: bar.set_drag_mode(not bar.dragging))
    gear = IconButton("⚙", "譯幕設定", menu.exec)
    tray.toolbar = bar.toolbar = Toolbar([move, gear])
    bar.move_button = move
    move.set_active(bar.dragging)
    if bar.isVisible():
        bar.showEvent(None)
    # Windows 11 會將新圖示收埋喺工作列右下角個「^」入面，彈個通知話人知喺邊
    tray.showMessage("譯幕開咗", "右下角「^」入面嘅「譯鏡」圖示（左「あ」右「中」）：右撳可以搬位或者閂",
                     QSystemTrayIcon.MessageIcon.Information, 5000)
    # 要留住 menu 嘅參照：Python 回收咗佢，右撳就冇嘢出
    tray.menu = menu
    return tray


def main():
    # Qt 接管咗主線，預設撳 Ctrl+C 冇反應；改返預設行為等 terminal 停得到
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    bar = SubtitleBar()
    tray = make_tray(bar, app)  # noqa: F841 —— 要留住佢，唔係圖示會即刻消失

    index = 0

    def next_demo():
        nonlocal index
        bar.show_sentence(*DEMO[index % len(DEMO)])
        index += 1

    next_demo()
    # 未記過位置（第一次開），或者叫明要搬位，就入拖動模式
    if "--move" in sys.argv or "bar" not in load_settings():
        bar.set_drag_mode(True)
        print("拖動模式：拖字幕條去想要嘅位置，雙擊或者右撳完成")
    timer = QTimer()
    timer.timeout.connect(next_demo)
    timer.start(2500)
    QTimer.singleShot(DEMO_SECONDS * 1000, app.quit)
    print(f"字幕條開咗，{DEMO_SECONDS} 秒後自動閂；想早啲閂就撳 Ctrl+C")
    app.exec()


if __name__ == "__main__":
    main()
