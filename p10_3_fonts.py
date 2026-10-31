# 巴別塔之窗：更多字型
#
# 做咩：列出 p8_6_fonts.CATALOG 嘅免費字型，啱而家「譯做」語言嘅排先；用家撳「下載」先落，
#   核對 sha256，放入 fonts\，即刻用得，唔使重開程式。冇網、下載失敗都唔影響其他功能。
#   清單冇想要嘅，可以加自己嘅字型檔；授權由用家自己負責，項目冇分發到。
# 點用：p8_7_settings.py 開 FontsDialog(on_use)；on_use(字型名) 喺用家揀咗字型之後叫。

import os
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, ProgressBar, PushButton, SimpleCardWidget, SingleDirectionScrollArea,
                            StrongBodyLabel)

from i18n import tr
from p7_1_target import current
from p8_6_fonts import CATALOG, FONT_DIR, FONT_FILES, OFL, add_font_file, add_own_font, available, chosen_name
from p10_2_setup import download_file
from theme import ThemedWindow

# 每種語言嘅例句：每張卡用嗰隻字型寫，一睇就知個樣
SAMPLES = {"繁體中文": "這究竟是什麼？", "日本語": "これは一体何だ？", "한국어": "이게 대체 뭐야?", "English": "What on earth is this?"}


class Signals(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(str, str)     # 字型名, 錯誤（空字串＝成功）


class FontsDialog(ThemedWindow):
    def __init__(self, on_use):
        super().__init__(tr("巴別塔之窗：更多字型"), 660, 700)
        self.on_use = on_use
        self.rows = {}
        self.busy = False
        note = CaptionLabel(tr("全部係免費字型（{license}），由作者或者 Google Fonts 下載，放喺程式資料夾。", license=OFL))
        note.setWordWrap(True)
        self.body.addWidget(note)
        own_note = CaptionLabel(tr("清單冇想要嘅？可以加自己嘅字型檔，會抄入 fonts 資料夾；唔要就喺嗰度刪走，重開程式就冇。"))
        own_note.setWordWrap(True)
        self.body.addWidget(own_note)
        buttons = QHBoxLayout()
        own = PushButton(tr("加入自己嘅字型…"))
        own.clicked.connect(self._add_own)
        folder = PushButton(tr("開字型資料夾"))
        folder.clicked.connect(self._open_folder)
        buttons.addWidget(own)
        buttons.addWidget(folder)
        buttons.addStretch()
        self.body.addLayout(buttons)
        scroll =SingleDirectionScrollArea(orient=Qt.Orientation.Vertical)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 8, 0)
        self.list.setSpacing(8)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, 1)
        self.bar = ProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.status = BodyLabel()
        self.status.setWordWrap(True)
        self.body.addWidget(self.bar)
        self.body.addWidget(self.status)
        self.signals = Signals()
        self.signals.progress.connect(self._progress)
        self.signals.finished.connect(self._finished)

    def _row(self, font):
        box = SimpleCardWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(16, 10, 16, 10)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(StrongBodyLabel(tr(font["名"])))
        size = sum(item[3] for item in font["檔案"]) / 2 ** 20
        text.addWidget(CaptionLabel(f"{'、'.join(font['語言'])}｜{size:.1f} MB"))
        sample = BodyLabel(SAMPLES[font["語言"][0]])
        text.addWidget(sample)
        row.addLayout(text, 1)
        button = PushButton()
        button.setMinimumWidth(96)
        button.clicked.connect(lambda _=False, font=font: self._press(font))
        row.addWidget(button)
        self.rows[font["名"]] = (font, sample, button)
        return box

    def open(self):
        """每次打開按「譯做」語言重新排：啱而家語言嘅排先。"""
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        target = current().key
        for font in sorted(CATALOG, key=lambda f: target not in f["語言"]):
            self.list.addWidget(self._row(font))
        self.list.addStretch()
        self._update()
        if not self.busy:
            self.status.setText(tr("而家譯做 {target}：啱用嘅字型排先。", target=target))
        self.show()
        self.raise_()
        self.activateWindow()

    def _update(self):
        using = chosen_name("譯鏡")
        have = available()      # 問 Qt 認唔認得，唔係睇檔名：Windows 本身裝咗嗰隻都算有
        for name, (font, sample, button) in self.rows.items():
            if name in have:
                sample.setFont(QFont(font["家族"], 14))     # 有先用到嗰隻字型寫例句
            button.setText(tr("使用緊") if name == using else tr("使用") if name in have else tr("下載"))
            button.setEnabled(name != using and not self.busy)

    def _press(self, font):
        if font["名"] in available():
            self._use(font["名"], tr("✅ 用緊 {name}", name=tr(font["名"])))
            return
        self.busy = True
        self._update()
        self.bar.setValue(0)
        self.bar.show()
        threading.Thread(target=self._work, args=(font,), daemon=True).start()

    def _use(self, name, message):
        self.on_use(name)
        self.status.setText(message)
        self._update()

    def _add_own(self):
        patterns = " ".join(f"*{suffix}" for suffix in FONT_FILES)
        path, _ = QFileDialog.getOpenFileName(self, tr("揀字型檔"), "", f"{tr('字型檔')} ({patterns})")
        if path:
            self._add_file(path)

    def _add_file(self, path):
        try:
            name = add_own_font(path)
        except OSError as error:
            self.status.setText(tr("⚠️ 抄唔到字型檔：{error}", error=error))
            return
        if name is None:
            self.status.setText(tr("⚠️ 讀唔到呢個檔：可能唔係字型，或者壞咗"))
            return
        self._use(name, tr("✅ 加咗 {name}，而家用緊佢", name=tr(name)))

    def _open_folder(self):
        FONT_DIR.mkdir(parents=True, exist_ok=True)     # 未下載過字型就未有呢個資料夾
        os.startfile(FONT_DIR)      # 用檔案總管開

    def _work(self, font):
        """背景線下載：download_file 寫 .part、核對 sha256，唔啱就唔留低壞檔。"""
        try:
            for name, url, sha256, size in font["檔案"]:
                if not (FONT_DIR / name).exists():
                    download_file(url, FONT_DIR / name, sha256, size, self.signals.progress.emit)
            self.signals.finished.emit(font["名"], "")
        except (OSError, ValueError) as error:
            self.signals.finished.emit(font["名"], str(error))

    def _progress(self, part, text):
        self.bar.setValue(int(part * 1000))
        self.status.setText(f"⏳ {text}")

    def _finished(self, name, error):
        self.busy = False
        self.bar.hide()
        if error:
            self.status.setText(tr("⚠️ 下載唔到 {name}：{error}", name=tr(name), error=error))
            self._update()
            return
        for file_name, *_ in self.rows[name][0]["檔案"]:
            add_font_file(FONT_DIR / file_name)
        # 專登落嘅字型，用家想用嘅機會最大：直接換，唔使再撳多一下
        self._use(name, tr("✅ 下載咗 {name}，而家用緊佢", name=tr(name)))
