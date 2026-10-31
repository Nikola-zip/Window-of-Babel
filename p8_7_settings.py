# 巴別塔之窗：設定視窗（Fluent 元件，配 theme.py 嘅古卷／夜空配色）
#
# 做咩：左邊導覽列分幾頁（窗、翻譯、模型、一般、熱鍵），將散喺工作列選單、窗 ⚙、settings.json 嘅設定擺埋一齊。
#   改完即刻生效兼存檔，唔使撳「儲存」。選單照留：兩邊改嘅都係同一個設定，每次打開視窗先讀返最新嘅值。
# 點用：main.py 開一個 SettingsDialog，將主程式嘅功能（轉語言、轉作品……）用 hooks 交俾佢。

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FluentIcon, FluentWindow, LineEdit, MessageBoxBase,
                            NavigationItemPosition, PrimaryPushButton, PushButton, SettingCard, SettingCardGroup,
                            SingleDirectionScrollArea, SpinBox, SubtitleLabel, SwitchButton, TitleLabel)

import theme
from i18n import AUTO, LANGUAGES, chosen_language, set_language, tr
from p4_6_launch import keep_days, load_settings, make_shortcut, save_setting
from p7_1_target import TARGETS, current, set_current
from p8_5_names import memory, work_label
from p8_6_fonts import available, chosen, chosen_name, has_bold, set_chosen, supports
from p10_1_models import CUSTOM, TIERS, apply, installed, is_installed, same_model, tier_of
from p10_1_models import current as current_models
from ui_parts import CHINESE_FONTS, make_font, make_icon

ROOT = Path(__file__).resolve().parent
PREVIEW_TEXT = {"繁體中文": "這究竟是什麼？", "English": "What on earth is this?", "日本語": "これは一体何だ？",
                "한국어": "이게 대체 뭐야?"}
# 熱鍵頁顯示嘅講法（settings.json「熱鍵」用嘅名 → 做咩）
HOTKEY_LABELS = {"歷史": "歷史面板", "清空上下文": "清空翻譯上下文", "譯鏡調整": "調整窗", "譯鏡讀字": "讀字翻譯",
                 "譯鏡自動": "自動模式", "譯鏡原文": "按住睇原文"}
# 錄新組合時認得嘅鍵：字母、數字、F1 至 F24（同 p3_3_hotkeys.parse 認得嘅一樣）
KEY_NAMES = {**{getattr(Qt.Key, f"Key_{c}"): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
             **{getattr(Qt.Key, f"Key_F{n}"): f"F{n}" for n in range(1, 25)}}
GRID_WIDTH = 300        # 右邊揀模型嘅下拉闊度：模型名好長


def hotkey_label(name):
    return tr(HOTKEY_LABELS.get(name, name))


class LensPreview(QWidget):
    """字型預覽：畫一個白色對白框，入面用揀咗嘅字型直排寫一句（同個窗一樣：冇真粗體就唔加粗）。"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(200, 220)
        self.scale = 1.0        # 譯文字大細：預覽都跟住大細

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bubble = QRectF(10, 10, self.width() - 20, self.height() - 20)
        p.setPen(QPen(QColor("black"), 3))
        p.setBrush(QColor("white"))
        p.drawEllipse(bubble)
        family = chosen("譯鏡")
        px = min(bubble.width() / 3.2, bubble.height() / 6.5) * min(self.scale, 1.0)   # 預覽框已經塞滿，淨縮得細
        font = make_font([family] + CHINESE_FONTS, 10, bold=has_bold(family))
        font.setPixelSize(int(px))
        p.setFont(font)
        p.setPen(QColor("black"))
        target = current()
        text = PREVIEW_TEXT.get(target.key, PREVIEW_TEXT["English"])
        if not target.vertical:
            # 打橫嘅語言：同個窗一樣寫橫排，字細啲先擺得落一句
            font.setPixelSize(int(px * 0.62))
            p.setFont(font)
            p.drawText(bubble.adjusted(26, 0, -26, 0),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            return
        columns = [text[:4], text[4:]]
        for c, column in enumerate(columns):      # 直排：由右邊一行起
            x = bubble.center().x() + px * 0.1 - c * px * 1.2
            top = bubble.center().y() - len(columns[0]) * px * 1.05 / 2
            for k, char in enumerate(column):
                vertical = {"，": "︐", "？": "︖"}.get(char, char)
                char = vertical if supports(family, vertical) else char     # 同個窗一樣：字型冇直排標點就用普通嘅
                p.drawText(QRectF(x, top + k * px * 1.05, px * 1.1, px * 1.05), Qt.AlignmentFlag.AlignCenter, char)


class Page(SingleDirectionScrollArea):
    """一頁設定：標題、一句說明，下面一組組卡片；內容長過視窗就捲。"""

    def __init__(self, name, title, hint):
        super().__init__(orient=Qt.Orientation.Vertical)
        self.setObjectName(name)        # Fluent 導覽列用 objectName 認頁
        self.setWidgetResizable(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(36, 24, 36, 24)
        self.column.setSpacing(14)
        self.column.addWidget(TitleLabel(title))
        note = CaptionLabel(hint)
        note.setWordWrap(True)      # 長句要換行：唔係成頁會闊過視窗，多條橫向捲軸
        self.column.addWidget(note)
        self.setWidget(self.body)

    def group(self, title):
        group = SettingCardGroup(title, self.body)
        self.column.addWidget(group)
        return group

    def finish(self):
        self.column.addStretch()


def card(group, icon, title, hint, *widgets):
    """一張設定卡：左邊圖示、標題、說明，右邊擺控制項。"""
    item = SettingCard(icon, title, hint, group)
    for widget in widgets:
        item.hBoxLayout.addWidget(widget)
        item.hBoxLayout.addSpacing(8)
    item.hBoxLayout.addSpacing(8)
    group.addSettingCard(item)
    return item


class NewWorkBox(MessageBoxBase):
    """開新作品：Fluent 版細視窗（QInputDialog 嘅舊款樣同其他頁唔夾）。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(tr("開新作品")))
        self.edit = LineEdit()
        self.edit.setPlaceholderText(tr("作品名（例如漫畫名、遊戲名）"))
        self.edit.setMinimumWidth(320)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText(tr("開"))
        self.cancelButton.setText(tr("取消"))


class SettingsDialog(FluentWindow):
    """設定視窗。hooks：主程式交落嚟嘅功能（見 main.py）；冇嘅就唔顯示嗰項。"""

    def __init__(self, lens, hooks=None):
        super().__init__()
        self.lens, self.hooks = lens, hooks or {}
        self.setWindowTitle(tr("巴別塔之窗：設定"))
        self.setWindowIcon(make_icon())
        # 個窗係置頂嘅，呢個視窗都要置頂，唔係會被遮住
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(980, 680)
        theme.style_window(self)
        # 導覽列長開、顯示文字：得五頁，唔使收埋做圖示；上一頁掣喺設定入面冇用
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.setCollapsible(False)
        self.navigationInterface.setExpandWidth(160)
        # 收埋咗上一頁、選單掣，第一項會頂到最頂，同標題列疊埋；留返標題列嘅高度
        self.navigationInterface.panel.vBoxLayout.setContentsMargins(0, 46, 0, 5)
        self.capturing = None       # 錄緊邊個熱鍵嘅新組合
        self.pages = {"窗": self._lens_page(), "翻譯": self._translate_page(), "模型": self._models_page(),
                      "一般": self._general_page()}
        for name, icon in (("窗", FluentIcon.FIT_PAGE), ("翻譯", FluentIcon.LANGUAGE), ("模型", FluentIcon.ROBOT)):
            self.addSubInterface(self.pages[name], icon, tr(name))
        self.addSubInterface(self.pages["一般"], FluentIcon.SETTING, tr("一般"), NavigationItemPosition.BOTTOM)
        if "hotkeys" in self.hooks:
            self.pages["熱鍵"] = self._hotkey_page()
            self.addSubInterface(self.pages["熱鍵"], FluentIcon.COMMAND_PROMPT, tr("熱鍵"), NavigationItemPosition.BOTTOM)
        self.stackedWidget.currentChanged.connect(lambda _: self.refresh())     # 轉頁都讀返最新（可能喺選單改過）

    # ---------- 打開 ----------
    def open(self, page="窗"):
        """打開去某一頁（「窗」「翻譯」「模型」「一般」「熱鍵」）。"""
        if page in self.pages:      # 選單撳入嚟 Qt 會塞個 checked 落嚟，唔係頁名就留喺而家嗰頁
            self.switchTo(self.pages[page])
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self):
        """將控制項設返做而家嘅值；擺嘅時候唔好觸發「改咗」，唔係擺一個存一次。"""
        self._set(self.lens_font, chosen_name("譯鏡"))
        if hasattr(self, "text_percent"):
            self._value(self.text_percent, self.lens.text_percent)
            self.preview.scale = self.lens.text_percent / 100
        self._check(self.sound_effects, self.lens.sound_effects)
        self._check(self.auto_mode, self.lens.auto)
        if "lens_visible" in self.hooks:
            self._check(self.lens_visible, self.hooks["lens_visible"]())
        self.preview.update()
        self._set(self.target, current().key)
        self._fill_works()
        if self.stackedWidget.currentWidget() is self.pages["模型"]:
            self._fill_models()     # 要問 Ollama，淨係睇緊呢頁先問，唔好拖慢開其他頁
        self._pick(self.theme_choice, theme.current_choice())
        self._pick(self.language, chosen_language())
        self._value(self.keep, keep_days())
        self._value(self.history, int(load_settings().get("歷史句數", 200)))
        if "hotkeys" in self.hooks:
            self._show_hotkeys()

    @staticmethod
    def _set(combo, text):
        combo.blockSignals(True)
        combo.setCurrentText(text)
        combo.blockSignals(False)

    @staticmethod
    def _pick(combo, data):
        combo.blockSignals(True)
        combo.setCurrentIndex(max(0, combo.findData(data)))
        combo.blockSignals(False)

    @staticmethod
    def _check(switch, on):
        switch.blockSignals(True)
        switch.setChecked(bool(on))
        switch.blockSignals(False)

    @staticmethod
    def _value(box, value):
        box.blockSignals(True)
        box.setValue(value)
        box.blockSignals(False)

    # ---------- 窗 ----------
    def _lens_page(self):
        page = Page("lens", tr("窗"), tr("轉字型、字大細唔使重新讀字；擬聲字開關下次讀字生效。"))
        group = page.group(tr("顯示"))
        if "set_lens_visible" in self.hooks:
            self.lens_visible = SwitchButton()
            self.lens_visible.checkedChanged.connect(self.hooks["set_lens_visible"])
            card(group, FluentIcon.FIT_PAGE, tr("顯示窗"), tr("收埋之後喺工作列圖示或者用熱鍵開返"), self.lens_visible)
        self.lens_font = ComboBox()
        self.lens_font.addItems(available())
        self.lens_font.setMinimumWidth(220)
        self.lens_font.currentTextChanged.connect(self._lens_font_changed)
        card(group, FluentIcon.FONT, tr("譯文字型"), tr("譯文用邊隻字型"), self.lens_font)
        if hasattr(self.lens, "set_text_percent"):
            self.text_percent = SpinBox()
            self.text_percent.setRange(60, 150)
            self.text_percent.setSingleStep(10)
            self.text_percent.setSuffix(" %")
            self.text_percent.valueChanged.connect(self._text_percent_changed)
            card(group, FluentIcon.FONT_SIZE, tr("譯文字大細"), tr("調大最多塞滿對白框；調細就成比例縮"), self.text_percent)
        group = page.group(tr("讀字"))
        self.sound_effects = SwitchButton()
        self.sound_effects.checkedChanged.connect(self.lens.set_sound_effects)
        card(group, FluentIcon.BRUSH, tr("擬聲字都譯"), tr("閂咗就保留原本嘅擬聲字"), self.sound_effects)
        self.auto_mode = SwitchButton()
        self.auto_mode.checkedChanged.connect(self.lens.set_auto)
        card(group, FluentIcon.SYNC, tr("自動模式"), tr("畫面停定就自動讀字"), self.auto_mode)
        page.column.addWidget(SubtitleLabel(tr("字型預覽")))
        self.preview = LensPreview()
        page.column.addWidget(self.preview)
        page.finish()
        return page

    def _text_percent_changed(self, percent):
        self.lens.set_text_percent(percent)
        self.preview.scale = percent / 100
        self.preview.update()

    def _lens_font_changed(self, name):
        set_chosen("譯鏡", name)
        self.preview.update()
        self.lens.font_changed(name)

    # ---------- 翻譯 ----------
    def _translate_page(self):
        page = Page("translate", tr("翻譯"), tr("譯成邊種語言，同埋每部作品嘅人名、用語。"))
        group = page.group(tr("語言"))
        self.target = ComboBox()
        self.target.addItems(list(TARGETS))
        self.target.setMinimumWidth(180)
        self.target.currentTextChanged.connect(self._target_changed)
        card(group, FluentIcon.LANGUAGE, tr("譯做"), tr("譯文用邊種語言"), self.target)
        group = page.group(tr("作品（人名記憶）"))
        self.works = ComboBox()
        self.works.setMinimumWidth(180)
        self.works.currentIndexChanged.connect(lambda _: self._work_changed(self.works.currentData()))
        new_work = PushButton(tr("開新作品…"))
        new_work.clicked.connect(self._new_work)
        card(group, FluentIcon.BOOK_SHELF, tr("作品"), tr("每部作品記住自己嘅人名譯法"), self.works, new_work)
        names = PushButton(tr("開名單"))
        names.clicked.connect(lambda: memory().open_file())
        card(group, FluentIcon.PEOPLE, tr("人名名單"), tr("用記事本改呢部作品記低嘅譯名"), names)
        lookup = PushButton(tr("網上搵譯名…"))
        lookup.setToolTip(tr("用作品名喺維基百科、Bangumi、AniList 等網站搵角色、用語嘅譯法，揀咗先寫入名單；撳先會上網"))
        lookup.clicked.connect(self._open_lookup)
        card(group, FluentIcon.SEARCH, tr("網上搵譯名"), tr("喺公開網站搵人哋點譯，你揀咗先寫入名單"), lookup)
        if "glossary" in self.hooks:
            glossary = PushButton(tr("開詞庫"))
            glossary.clicked.connect(lambda: notepad(self.hooks["glossary"]))
            card(group, FluentIcon.DOCUMENT, tr("詞庫"), tr("固定譯法；改完要重開程式"), glossary)
        page.finish()
        return page

    def _open_lookup(self):
        if getattr(self, "lookup", None) is None:
            from p9_2_lookup import lookup_dialog       # 用到先載入
            self.lookup = lookup_dialog()
        self.lookup.open()

    def _target_changed(self, key):
        target = set_current(key)
        self.preview.update()
        if "target_changed" in self.hooks:
            self.hooks["target_changed"](target)

    def _fill_works(self):
        self.works.blockSignals(True)
        self.works.clear()
        for work in memory().works():
            self.works.addItem(work_label(work), userData=work)
        self.works.setCurrentIndex(max(0, self.works.findData(memory().work)))
        self.works.blockSignals(False)

    def _work_changed(self, work):
        if not work or work == memory().work:
            return
        memory().set_work(work)
        if "work_changed" in self.hooks:
            self.hooks["work_changed"](memory().work)

    def _new_work(self):
        box = NewWorkBox(self)
        if box.exec() and box.edit.text().strip():
            memory().set_work(box.edit.text().strip())
            self._fill_works()
            if "work_changed" in self.hooks:
                self.hooks["work_changed"](memory().work)

    # ---------- 模型 ----------
    def _models_page(self):
        page = Page("models", tr("模型"), tr("揀啱你張顯示卡嘅檔；轉模型即刻生效，唔使重開，舊模型會即刻卸走。"))
        group = page.group(tr("建議組合（VRAM 已經計埋搵字、補圖模型）"))
        self.tier = ComboBox()
        for name, tier in TIERS.items():
            self.tier.addItem(tr("{name}（約 {v2} GB VRAM）", name=tr(name), v2=tier['VRAM']), userData=name)
        self.tier.addItem(tr("自訂"), userData=CUSTOM)
        self.tier.setMinimumWidth(220)
        # activated 唔係 currentIndexChanged：程式自己擺返而家嗰檔唔好當用家揀咗，唔係開頁就轉模型
        self.tier.activated.connect(self._tier_picked)
        self.tier_card = card(group, FluentIcon.SPEED_HIGH, tr("檔"), "", self.tier)
        group = page.group(tr("自己揀"))
        self.reading_model = ComboBox()
        self.reading_model.setMinimumWidth(GRID_WIDTH)
        self.reading_model.activated.connect(self._model_picked)
        card(group, FluentIcon.VIEW, tr("讀字模型"), tr("淨列識睇圖嘅模型"), self.reading_model)
        self.translation_model = ComboBox()
        self.translation_model.setMinimumWidth(GRID_WIDTH)
        self.translation_model.activated.connect(self._model_picked)
        card(group, FluentIcon.LANGUAGE, tr("翻譯模型"), tr("將讀到嘅字譯成你揀嘅語言"), self.translation_model)
        self.model_status = BodyLabel()
        self.model_status.setWordWrap(True)
        page.column.addWidget(self.model_status)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        if "open_setup" in self.hooks:
            download = PrimaryPushButton(FluentIcon.DOWNLOAD, tr("下載模型…"))
            download.setToolTip(tr("開第一次設定：睇張卡建議邊檔，撳一下就下載"))
            download.clicked.connect(self.hooks["open_setup"])
            row.addWidget(download)
        reload = PushButton(FluentIcon.SYNC, tr("重新讀取模型清單"))
        reload.clicked.connect(self._fill_models)
        row.addWidget(reload)
        row.addStretch()
        page.column.addWidget(buttons)
        page.finish()
        return page

    def _fill_models(self):
        """問 Ollama 裝咗咩：讀字淨列識睇圖嘅（唔識嘅揀咗即刻出錯）；而家用緊嘅、三檔要用嘅未下載都照列，標明。"""
        models = installed()
        reading, translation = current_models()
        if models is None:
            self.model_status.setText(tr("⚠️ Ollama 冇開，列唔到模型"))
        vision = [name for name, sees in models or [] if sees]
        others = [name for name, sees in models or [] if not sees]
        wanted_reading = [reading] + [tier["讀字"] for tier in TIERS.values()]
        wanted_translation = [translation] + [tier["翻譯"] for tier in TIERS.values()]
        # 翻譯唔一定要專門模型，識睇圖嘅模型都譯得，所以排喺後面照列
        for combo, names, wanted, chosen_now in ((self.reading_model, vision, wanted_reading, reading),
                                                 (self.translation_model, others + vision, wanted_translation,
                                                  translation)):
            combo.clear()
            listed = []
            for name in names + wanted:
                if any(same_model(name, seen) for seen in listed):
                    continue
                listed.append(name)
                combo.addItem(name if is_installed(name, models) else tr("{name}（未下載）", name=name), userData=name)
            combo.setCurrentIndex(next(i for i, name in enumerate(listed) if same_model(name, chosen_now)))
        tier = tier_of(reading, translation)
        self.tier.setCurrentIndex(self.tier.findData(tier))
        self.tier_card.setContent(tr(TIERS[tier]["說明"]) if tier in TIERS else
                                  tr("自己揀嘅組合：未經測試，讀字模型唔跟格式就會讀唔到字"))

    def _tier_picked(self, index):
        name = self.tier.itemData(index)
        if name == CUSTOM:
            self.tier_card.setContent(tr("喺下面揀讀字同翻譯模型"))
            return
        self._switch(TIERS[name]["讀字"], TIERS[name]["翻譯"])

    def _model_picked(self, _):
        self._switch(self.reading_model.currentData(), self.translation_model.currentData())

    def _switch(self, reading, translation):
        models = installed()
        missing = [name for name in (reading, translation) if not is_installed(name, models)]
        if missing:
            # 唔轉：轉咗去未下載嘅模型，下一次讀字、翻譯就會出錯
            self.model_status.setText(tr("⚠️ 未下載：{v1}，暫時唔轉（撳「下載模型…」）", v1='、'.join(missing)))
            self._fill_models()     # 揀返而家用緊嗰個，唔好令人以為轉咗
            return
        apply(reading, translation)
        if "models_changed" in self.hooks:
            self.hooks["models_changed"](reading, translation)
        self.model_status.setText(tr("✅ 轉咗：讀字 {reading}｜翻譯 {translation}", reading=reading, translation=translation))
        self._fill_models()

    # ---------- 一般 ----------
    def _general_page(self):
        page = Page("general", tr("一般"), tr("外觀、紀錄同資料夾。"))
        group = page.group(tr("外觀"))
        self.theme_choice = ComboBox()
        for choice in theme.CHOICES:
            self.theme_choice.addItem(tr(choice), userData=choice)
        self.theme_choice.setMinimumWidth(140)
        # 顯示嘅字會跟介面語言變，所以用 userData 認，唔用 currentText
        self.theme_choice.currentIndexChanged.connect(lambda _: theme.set_choice(self.theme_choice.currentData()))
        card(group, FluentIcon.PALETTE, tr("介面主題"), tr("淺色係古卷色，深色係夜空色；跟系統就跟 Windows 轉"), self.theme_choice)
        self.language = ComboBox()
        self.language.addItem(tr("跟系統"), userData=AUTO)
        for code, name in LANGUAGES.items():
            self.language.addItem(name, userData=code)
        self.language.setMinimumWidth(140)
        self.language.currentIndexChanged.connect(self._language_changed)
        self.language_card = card(group, FluentIcon.GLOBE, tr("介面語言"), tr("重開程式先全部轉晒"), self.language)
        group = page.group(tr("紀錄"))
        self.history = SpinBox()
        self.history.setRange(10, 1000)
        self.history.setSuffix(tr(" 句"))
        self.history.valueChanged.connect(self._history_changed)
        card(group, FluentIcon.HISTORY, tr("歷史面板記住"), tr("面板顯示最近幾多句"), self.history)
        self.keep = SpinBox()
        self.keep.setRange(1, 365)
        self.keep.setSuffix(tr(" 日"))
        self.keep.valueChanged.connect(lambda days: save_setting("紀錄保留日數", days))
        card(group, FluentIcon.DOCUMENT, tr("紀錄保留"), tr("超過就喺下次開機清走"), self.keep)
        group = page.group(tr("資料夾"))
        logs = PushButton(tr("開紀錄資料夾"))
        logs.clicked.connect(lambda: open_folder(ROOT / "logs"))
        shots = PushButton(tr("開截圖資料夾"))
        shots.clicked.connect(lambda: open_folder(ROOT / "screenshots"))
        card(group, FluentIcon.FOLDER, tr("資料夾"), tr("翻譯紀錄同 📷 存低嘅截圖"), logs, shots)
        shortcut = PushButton(tr("建立桌面捷徑"))
        shortcut.clicked.connect(self._make_shortcut)
        self.shortcut_card = card(group, FluentIcon.PIN, tr("桌面捷徑"), tr("撳一下就開，唔使開 terminal"), shortcut)
        page.finish()
        return page

    def _language_changed(self, _):
        set_language(self.language.currentData())
        self.language_card.setContent(tr("改咗：重開程式先生效"))

    def _make_shortcut(self):
        try:
            self.shortcut_card.setContent(tr("✅ 整好咗：{v1}", v1=make_shortcut()))
        except (OSError, subprocess.SubprocessError) as error:
            self.shortcut_card.setContent(tr("⚠️ 整唔到：{error}", error=error))

    # ---------- 熱鍵 ----------
    def _hotkey_page(self):
        page = Page("hotkeys", tr("熱鍵"), tr("撳「改」，再撳新嘅組合（要有 Ctrl／Alt／Shift／Win，加字母、數字或者 F 鍵）；Esc 取消。"))
        group = page.group(tr("全域熱鍵"))
        self.hotkey_rows = {}
        for name in self.hooks["hotkeys"].texts:
            combo = BodyLabel()
            change = PushButton(tr("改"))
            change.clicked.connect(lambda _=False, name=name: self._start_capture(name))
            item = card(group, FluentIcon.COMMAND_PROMPT, hotkey_label(name), "", combo, change)
            self.hotkey_rows[name] = (combo, change, item)
        self.hotkey_note = BodyLabel()
        self.hotkey_note.setWordWrap(True)
        page.column.addWidget(self.hotkey_note)
        reset = PushButton(FluentIcon.UPDATE, tr("全部還原預設"))
        reset.clicked.connect(self._reset_hotkeys)
        page.column.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        page.finish()
        return page

    def _show_hotkeys(self):
        keys = self.hooks["hotkeys"]
        for name, (combo, change, item) in self.hotkey_rows.items():
            capturing = name == self.capturing
            combo.setText(tr("撳新組合…") if capturing else keys.texts.get(name, ""))
            change.setText(tr("取消") if capturing else tr("改"))
            problem = keys.problems.get(name)
            item.setContent(f"⚠️ {problem}" if problem else "")

    def _start_capture(self, name):
        if self.capturing == name:          # 再撳一下「取消」
            self._stop_capture()
            return
        self.hooks["hotkeys"].suspend()     # 交還晒所有熱鍵：唔係撳舊組合會觸發舊功能，呢度收唔到
        self.capturing = name
        self.grabKeyboard()
        self._show_hotkeys()

    def _stop_capture(self, message=""):
        self.releaseKeyboard()
        self.capturing = None
        self.hooks["hotkeys"].resume()
        self._show_hotkeys()
        if message:
            self.hotkey_note.setText(message)

    def keyPressEvent(self, event):
        if self.capturing is None:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._stop_capture(tr("取消咗，冇改。"))
            return
        key = KEY_NAMES.get(event.key())
        if key is None:
            return      # 淨係撳緊 Ctrl／Alt 呢啲修飾鍵：等埋個字母先
        mods = event.modifiers()
        parts = [label for flag, label in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                                           (Qt.KeyboardModifier.AltModifier, "Alt"),
                                           (Qt.KeyboardModifier.ShiftModifier, "Shift"),
                                           (Qt.KeyboardModifier.MetaModifier, "Win")) if mods & flag]
        text = "+".join(parts + [key])
        name = self.capturing
        problem = self.hooks["hotkeys"].rebind(name, text)
        self._stop_capture(tr("「{v1}」改咗做 {text}。", v1=hotkey_label(name), text=text) if problem is None
                           else tr("用唔到 {text}：{problem}", text=text, problem=problem))

    def hideEvent(self, event):
        if self.capturing is not None:      # 錄緊就閂視窗：記得交返熱鍵
            self._stop_capture()
        super().hideEvent(event)

    def _reset_hotkeys(self):
        from p3_3_hotkeys import DEFAULT_HOTKEYS
        keys = self.hooks["hotkeys"]
        # 先交還晒再逐個綁返預設：唔係「甲」改返預設時可能撞住「乙」暫時用緊嘅舊組合
        keys.suspend()
        problems = []
        for name in keys.texts:
            keys.texts[name] = DEFAULT_HOTKEYS.get(name, keys.texts[name])
        for name in keys.texts:
            problem = keys.rebind(name, keys.texts[name])
            if problem:
                problems.append(f"{hotkey_label(name)}：{problem}")
        keys.resume()
        self._show_hotkeys()
        self.hotkey_note.setText(tr("還原咗預設。") + ("；".join(problems) if problems else ""))

    def _history_changed(self, size):
        save_setting("歷史句數", size)
        if "set_history_size" in self.hooks:
            self.hooks["set_history_size"](size)


def notepad(path):
    subprocess.Popen(["notepad.exe", str(Path(path).resolve())])


def open_folder(path):
    path.mkdir(exist_ok=True)
    os.startfile(path)      # 用檔案總管開
