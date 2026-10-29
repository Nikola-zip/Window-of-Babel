# 巴別塔之窗：設定視窗（由譯幕第8期第7關嘅設定視窗改，拎走字幕、聽聲嗰啲）
#
# 做咩：一個視窗分幾頁（譯鏡、翻譯、一般、熱鍵），將散喺工作列選單、譯鏡 ⚙、settings.json 嘅設定擺埋一齊。
#   改完即刻生效兼存檔，唔使撳「儲存」。選單照留：兩邊改嘅都係同一個設定，每次打開視窗先讀返最新嘅值。
# 點用：main.py 開一個 SettingsDialog，將主程式嘅功能（轉語言、轉作品……）用 hooks 交俾佢。
#   直接行係示範（假譯鏡，睇介面用）：.venv\Scripts\python -W ignore p8_7_settings.py

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
                             QLabel, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from p3_1_subtitle_bar import CHINESE_FONTS, make_font
from p4_6_launch import keep_days, load_settings, save_setting
from p7_1_target import TARGETS, current, set_current
from p8_5_names import memory
from p8_6_fonts import available, chosen, chosen_name, has_bold, set_chosen, supports
from p10_1_models import CUSTOM, TIERS, apply, installed, is_installed, same_model, tier_of
from p10_1_models import current as current_models

ROOT = Path(__file__).resolve().parent
PREVIEW_TEXT = "這究竟是什麼？"
# 熱鍵頁顯示嘅講法（settings.json「熱鍵」用嘅名 → 做咩）
HOTKEY_LABELS = {"歷史": "歷史面板", "清空上下文": "清空翻譯上下文", "譯鏡調整": "調整譯鏡", "譯鏡讀字": "譯鏡讀字翻譯",
                 "譯鏡自動": "譯鏡自動模式", "譯鏡原文": "譯鏡按住睇原文"}
# 錄新組合時認得嘅鍵：字母、數字、F1 至 F24（同 p3_3_hotkeys.parse 認得嘅一樣）
KEY_NAMES = {**{getattr(Qt.Key, f"Key_{c}"): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
             **{getattr(Qt.Key, f"Key_F{n}"): f"F{n}" for n in range(1, 25)}}


class LensPreview(QWidget):
    """譯鏡字型預覽：畫一個白色對白框，入面用揀咗嘅字型直排寫一句（同譯鏡一樣：冇真粗體就唔加粗）。"""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(180, 220)
        self.scale = 1.0        # 譯文字大細（設定「譯文字大細」）：預覽都跟住大細

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor("#bdbdbd"))
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
        columns = [PREVIEW_TEXT[:4], PREVIEW_TEXT[4:]]
        for c, column in enumerate(columns):      # 直排：由右邊一行起
            x = bubble.center().x() + px * 0.1 - c * px * 1.2
            top = bubble.center().y() - len(columns[0]) * px * 1.05 / 2
            for k, char in enumerate(column):
                vertical = {"，": "︐", "？": "︖"}.get(char, char)
                char = vertical if supports(family, vertical) else char     # 同譯鏡一樣：字型冇直排標點就用普通嘅
                p.drawText(QRectF(x, top + k * px * 1.05, px * 1.1, px * 1.05), Qt.AlignmentFlag.AlignCenter, char)


class SettingsDialog(QWidget):
    """設定視窗。hooks：主程式交落嚟嘅功能（見 main.py）；冇嘅就唔顯示嗰項。"""

    def __init__(self, lens, hooks=None):
        super().__init__()
        self.lens, self.hooks = lens, hooks or {}
        self.setWindowTitle("巴別塔之窗：設定")
        # 塊鏡係置頂嘅，呢個視窗都要置頂，唔係會被遮住
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._lens_page(), "譯鏡")
        self.tabs.addTab(self._translate_page(), "翻譯")
        self.tabs.addTab(self._models_page(), "模型")
        self.tabs.addTab(self._general_page(), "一般")
        self.capturing = None       # 錄緊邊個熱鍵嘅新組合
        if "hotkeys" in self.hooks:
            self.tabs.addTab(self._hotkey_page(), "熱鍵")
        self.tabs.currentChanged.connect(lambda _: self.refresh())     # 轉頁都讀返最新（可能喺選單改過）
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        note = QLabel("改完即刻生效，會自動存檔。")
        note.setStyleSheet("color: #777;")
        layout.addWidget(note)

    # ---------- 打開 ----------
    def open(self, page="譯鏡"):
        """打開去某一頁（「譯鏡」「翻譯」「模型」「一般」「熱鍵」）。"""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == page:
                self.tabs.setCurrentIndex(i)
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self):
        """將控制項設返做而家嘅值；擺嘅時候唔好觸發「改咗」，唔係擺一個存一次。"""
        self._set(self.lens_font, chosen_name("譯鏡"))
        if hasattr(self, "text_percent"):
            self.text_percent.blockSignals(True)
            self.text_percent.setValue(self.lens.text_percent)
            self.text_percent.blockSignals(False)
            self.preview.scale = self.lens.text_percent / 100
        self._check(self.sound_effects, self.lens.sound_effects)
        self._check(self.auto_mode, self.lens.auto)
        if "lens_visible" in self.hooks:
            self._check(self.lens_visible, self.hooks["lens_visible"]())
        self.preview.update()
        self._set(self.target, current().key)
        self._fill_works()
        if self.tabs.tabText(self.tabs.currentIndex()) == "模型":
            self._fill_models()     # 要問 Ollama，淨係睇緊呢頁先問，唔好拖慢開其他頁
        self.keep.blockSignals(True)
        self.keep.setValue(keep_days())
        self.keep.blockSignals(False)
        self.history.blockSignals(True)
        self.history.setValue(int(load_settings().get("歷史句數", 200)))
        self.history.blockSignals(False)
        if "hotkeys" in self.hooks:
            self._show_hotkeys()

    @staticmethod
    def _set(combo, text):
        combo.blockSignals(True)
        combo.setCurrentText(text)
        combo.blockSignals(False)

    @staticmethod
    def _check(box, on):
        box.blockSignals(True)
        box.setChecked(bool(on))
        box.blockSignals(False)

    # ---------- 譯鏡 ----------
    def _lens_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        form = QFormLayout()
        if "set_lens_visible" in self.hooks:
            self.lens_visible = QCheckBox("顯示譯鏡")
            self.lens_visible.toggled.connect(self.hooks["set_lens_visible"])
            form.addRow("塊鏡", self.lens_visible)
        self.lens_font = QComboBox()
        self.lens_font.addItems(available())
        self.lens_font.currentTextChanged.connect(self._lens_font_changed)
        form.addRow("譯文字型", self.lens_font)
        if hasattr(self.lens, "set_text_percent"):
            self.text_percent = QSpinBox()
            self.text_percent.setRange(60, 150)
            self.text_percent.setSingleStep(10)
            self.text_percent.setSuffix(" %")
            self.text_percent.setToolTip("調大最多大到塞滿對白框；調細就成比例縮。唔使重新讀字")
            self.text_percent.valueChanged.connect(self._text_percent_changed)
            form.addRow("譯文字大細", self.text_percent)
        self.sound_effects = QCheckBox("擬聲字都譯")
        self.sound_effects.toggled.connect(self.lens.set_sound_effects)
        form.addRow("擬聲字", self.sound_effects)
        self.auto_mode = QCheckBox("自動模式（畫面停定就讀）")
        self.auto_mode.toggled.connect(self.lens.set_auto)
        form.addRow("自動", self.auto_mode)
        tip = QLabel("轉字型、字大細唔使重新讀字；擬聲字開關下次讀字生效。")
        tip.setStyleSheet("color: #777;")
        tip.setWordWrap(True)
        form.addRow(tip)
        layout.addLayout(form, 1)
        self.preview = LensPreview()
        layout.addWidget(self.preview)
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
        page = QWidget()
        form = QFormLayout(page)
        self.target = QComboBox()
        self.target.addItems(list(TARGETS))
        self.target.currentTextChanged.connect(self._target_changed)
        form.addRow("譯做", self.target)

        self.works = QComboBox()
        self.works.currentTextChanged.connect(self._work_changed)
        new_work = QPushButton("開新作品…")
        new_work.clicked.connect(self._new_work)
        names = QPushButton("開名單")
        names.clicked.connect(lambda: memory().open_file())
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.works, 1)
        line.addWidget(new_work)
        line.addWidget(names)
        form.addRow("作品（人名記憶）", row)
        lookup = QPushButton("網上搵譯名…")
        lookup.setToolTip("用作品名喺維基百科、Bangumi、AniList 等網站搵角色、用語嘅譯法，揀咗先寫入名單；撳先會上網")
        lookup.clicked.connect(self._open_lookup)
        form.addRow("", lookup)

        if "glossary" in self.hooks:
            glossary = QPushButton("開詞庫（改完要重開程式）")
            glossary.clicked.connect(lambda: notepad(self.hooks["glossary"]))
            form.addRow("詞庫", glossary)
        return page

    def _open_lookup(self):
        if getattr(self, "lookup", None) is None:
            from p9_2_lookup import lookup_dialog       # 用到先載入
            self.lookup = lookup_dialog()
        self.lookup.open()

    def _target_changed(self, key):
        target = set_current(key)
        if "target_changed" in self.hooks:
            self.hooks["target_changed"](target)

    def _fill_works(self):
        self.works.blockSignals(True)
        self.works.clear()
        self.works.addItems(memory().works())
        self.works.setCurrentText(memory().work)
        self.works.blockSignals(False)

    def _work_changed(self, work):
        if not work or work == memory().work:
            return
        memory().set_work(work)
        if "work_changed" in self.hooks:
            self.hooks["work_changed"](memory().work)

    def _new_work(self):
        work, ok = QInputDialog.getText(self, "開新作品", "作品名（例如漫畫名、遊戲名）：")
        if ok and work.strip():
            memory().set_work(work.strip())
            self._fill_works()
            if "work_changed" in self.hooks:
                self.hooks["work_changed"](memory().work)

    # ---------- 模型 ----------
    def _models_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.tier = QComboBox()
        for name, tier in TIERS.items():
            self.tier.addItem(f"{name}（約 {tier['VRAM']} GB VRAM）", name)
        self.tier.addItem("自訂（自己揀下面兩個）", CUSTOM)
        # activated 唔係 currentIndexChanged：程式自己擺返而家嗰檔唔好當用家揀咗，唔係開頁就轉模型
        self.tier.activated.connect(self._tier_picked)
        form.addRow("檔", self.tier)
        self.tier_note = QLabel()
        self.tier_note.setWordWrap(True)
        self.tier_note.setStyleSheet("color: #777;")
        form.addRow("", self.tier_note)
        self.reading_model = QComboBox()
        self.reading_model.activated.connect(self._model_picked)
        form.addRow("讀字模型（👁 識睇圖）", self.reading_model)
        self.translation_model = QComboBox()
        self.translation_model.activated.connect(self._model_picked)
        form.addRow("翻譯模型", self.translation_model)
        self.model_status = QLabel()
        self.model_status.setWordWrap(True)
        form.addRow(self.model_status)
        reload = QPushButton("重新讀取模型清單")
        reload.clicked.connect(self._fill_models)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(reload)
        if "open_setup" in self.hooks:
            download = QPushButton("下載模型…")
            download.setToolTip("開第一次設定：睇張卡建議邊檔，撳一下就下載")
            download.clicked.connect(self.hooks["open_setup"])
            row.addWidget(download)
        form.addRow("", buttons)
        tip = QLabel("轉模型即刻生效，唔使重開；冇再用嘅舊模型會即刻卸走，還返 VRAM。"
                     "VRAM 已經計埋搵字、補圖模型（約 1.7 GB）。")
        tip.setStyleSheet("color: #777;")
        tip.setWordWrap(True)
        form.addRow(tip)
        return page

    def _fill_models(self):
        """問 Ollama 裝咗咩：讀字淨列識睇圖嘅（唔識嘅揀咗即刻出錯）；而家用緊嘅、三檔要用嘅未下載都照列，標明。"""
        models = installed()
        reading, translation = current_models()
        if models is None:
            self.model_status.setText("⚠️ Ollama 冇開，列唔到模型")
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
                combo.addItem(name if is_installed(name, models) else f"{name}（未下載）", name)
            combo.setCurrentIndex(next(i for i, name in enumerate(listed) if same_model(name, chosen_now)))
        tier = tier_of(reading, translation)
        self.tier.setCurrentIndex(self.tier.findData(tier))
        self.tier_note.setText(TIERS[tier]["說明"] if tier in TIERS else "自己揀嘅組合：未經測試，讀字模型唔跟格式就會讀唔到字")

    def _tier_picked(self, index):
        name = self.tier.itemData(index)
        if name == CUSTOM:
            self.tier_note.setText("喺下面揀讀字同翻譯模型")
            return
        self._switch(TIERS[name]["讀字"], TIERS[name]["翻譯"])

    def _model_picked(self, _):
        self._switch(self.reading_model.currentData(), self.translation_model.currentData())

    def _switch(self, reading, translation):
        models = installed()
        missing = [name for name in (reading, translation) if not is_installed(name, models)]
        if missing:
            # 唔轉：轉咗去未下載嘅模型，下一次讀字、翻譯就會出錯
            self.model_status.setText(f"⚠️ 未下載：{'、'.join(missing)}，暫時唔轉（撳「下載模型…」）")
            self._fill_models()     # 揀返而家用緊嗰個，唔好令人以為轉咗
            return
        apply(reading, translation)
        if "models_changed" in self.hooks:
            self.hooks["models_changed"](reading, translation)
        self.model_status.setText(f"✅ 轉咗：讀字 {reading}｜翻譯 {translation}")
        self._fill_models()

    # ---------- 一般 ----------
    def _general_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.history = QSpinBox()
        self.history.setRange(10, 1000)
        self.history.setSuffix(" 句")
        self.history.valueChanged.connect(self._history_changed)
        form.addRow("歷史面板記住", self.history)
        self.keep = QSpinBox()
        self.keep.setRange(1, 365)
        self.keep.setSuffix(" 日")
        self.keep.valueChanged.connect(lambda days: save_setting("紀錄保留日數", days))
        form.addRow("紀錄保留（下次開機清）", self.keep)
        logs = QPushButton("開紀錄資料夾")
        logs.clicked.connect(lambda: open_folder(ROOT / "logs"))
        shots = QPushButton("開譯鏡截圖資料夾")
        shots.clicked.connect(lambda: open_folder(ROOT / "譯鏡截圖"))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(logs)
        line.addWidget(shots)
        form.addRow("資料夾", row)
        return page

    # ---------- 熱鍵 ----------
    def _hotkey_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        self.hotkey_rows = {}
        keys = self.hooks["hotkeys"]
        for row, name in enumerate(keys.texts):
            combo, status = QLabel(), QLabel()
            change = QPushButton("改")
            change.clicked.connect(lambda _=False, name=name: self._start_capture(name))
            grid.addWidget(QLabel(HOTKEY_LABELS.get(name, name)), row, 0)
            grid.addWidget(combo, row, 1)
            grid.addWidget(change, row, 2)
            grid.addWidget(status, row, 3)
            self.hotkey_rows[name] = (combo, change, status)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        self.hotkey_note = QLabel("撳「改」，再撳新嘅組合（要有 Ctrl／Alt／Shift／Win，加字母、數字或者 F 鍵）；Esc 取消。")
        self.hotkey_note.setWordWrap(True)
        self.hotkey_note.setStyleSheet("color: #777;")
        layout.addWidget(self.hotkey_note)
        reset = QPushButton("全部還原預設")
        reset.clicked.connect(self._reset_hotkeys)
        layout.addWidget(reset)
        layout.addStretch()
        return page

    def _show_hotkeys(self):
        keys = self.hooks["hotkeys"]
        for name, (combo, change, status) in self.hotkey_rows.items():
            capturing = name == self.capturing
            combo.setText("撳新組合…" if capturing else keys.texts.get(name, ""))
            change.setText("取消" if capturing else "改")
            problem = keys.problems.get(name)
            status.setText(f"⚠️ {problem}" if problem else "")
            status.setStyleSheet("color: #d9534f;")

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
            self._stop_capture("取消咗，冇改。")
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
        self._stop_capture(f"「{HOTKEY_LABELS.get(name, name)}」改咗做 {text}。" if problem is None
                           else f"用唔到 {text}：{problem}")

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
                problems.append(f"{HOTKEY_LABELS.get(name, name)}：{problem}")
        keys.resume()
        self._show_hotkeys()
        self.hotkey_note.setText("還原咗預設。" + ("；".join(problems) if problems else ""))

    def _history_changed(self, size):
        save_setting("歷史句數", size)
        if "set_history_size" in self.hooks:
            self.hooks["set_history_size"](size)


def notepad(path):
    subprocess.Popen(["notepad.exe", str(Path(path).resolve())])


def open_folder(path):
    path.mkdir(exist_ok=True)
    os.startfile(path)      # 用檔案總管開


def main():
    """示範：用一個假譯鏡睇介面；改嘅設定會真係存入 settings.json。"""
    class FakeLens:
        sound_effects, auto, text_percent = True, False, 100

        def set_text_percent(self, percent):
            self.text_percent = percent
            print("譯文字大細：", percent)

        def set_sound_effects(self, on):
            self.sound_effects = on
            print("擬聲字都譯：", on)

        def set_auto(self, on):
            self.auto = on
            print("自動模式：", on)

        def font_changed(self, name):
            print("譯文字型：", name)

    app = QApplication(sys.argv)
    dialog = SettingsDialog(FakeLens(), {"target_changed": lambda t: print("譯做：", t.key),
                                         "work_changed": lambda w: print("作品：", w)})
    dialog.open()
    app.exec()


if __name__ == "__main__":
    main()
