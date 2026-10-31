# 譯幕 第9期第1關：改譯文就記住
#
# 做咩：歷史面板每句有「改」，撳落去開呢個細視窗，兩種改法：
#   1. 改詞：「ヤワ → 軟弱」記入而家作品嘅名單（備註「手動改」），以後有呢個詞嘅句都跟（字幕條同譯鏡都係）
#   2. 改成句：以後見到一模一樣嘅原文，直接用你寫嘅譯文，唔問模型（口頭禪、重複嘅對白）
#   兩樣都係改完即刻生效：名單檔一變，譯鏡翻譯快取都分開記，下次讀嗰頁就用新譯法。
# 點用：main.py 將 open_correction 交俾歷史面板；直接行係示範：
#   .venv\Scripts\python -W ignore p9_1_correct.py

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget)

from p7_1_target import current
from p8_5_names import memory


class CorrectionDialog(QWidget):
    """改一句譯文：上面睇原文同而家譯文，下面揀改詞定改成句。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("巴別塔之窗：改譯文")
        # 歷史面板同字幕條都係置頂嘅，呢個都要置頂，唔係會被遮住
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(560, 360)

        self.original = QLineEdit()
        self.original.setReadOnly(True)     # 唔俾改，但揀得字：揀咗就撳「用揀咗嘅字」
        self.translation = QLabel()
        self.translation.setWordWrap(True)
        self.translation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.work = QLabel()
        self.work.setStyleSheet("color: #777;")
        top = QFormLayout()
        top.addRow("原文", self.original)
        top.addRow("而家譯文", self.translation)
        top.addRow("", self.work)

        # ---- 改詞 ----
        self.term = QLineEdit()
        self.term.setPlaceholderText("原文入面嘅詞，例如 ヤワ")
        pick = QPushButton("用揀咗嘅字")
        pick.setToolTip("喺上面「原文」揀咗一截字，撳呢度就搬落嚟")
        pick.clicked.connect(lambda: self.term.setText(self.original.selectedText() or self.term.text()))
        self.term_fix = QLineEdit()
        self.term_fix.setPlaceholderText("正確譯法，例如 軟弱")
        save_term = QPushButton("記低呢個詞")
        save_term.clicked.connect(self._save_term)
        term_row = QHBoxLayout()
        term_row.addWidget(self.term, 1)
        term_row.addWidget(pick)
        term_box = QGroupBox("改詞（以後有呢個詞嘅句都跟）")
        term_form = QFormLayout(term_box)
        term_form.addRow("原文詞", term_row)
        term_form.addRow("譯法", self.term_fix)
        term_form.addRow(save_term)

        # ---- 改成句 ----
        self.sentence_fix = QLineEdit()
        save_sentence = QPushButton("記低成句")
        save_sentence.clicked.connect(self._save_sentence)
        sentence_box = QGroupBox("改成句（以後一模一樣嘅原文直接用呢個譯文）")
        sentence_form = QFormLayout(sentence_box)
        sentence_form.addRow("正確譯文", self.sentence_fix)
        sentence_form.addRow(save_sentence)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(term_box)
        layout.addWidget(sentence_box)
        layout.addWidget(self.status)
        layout.addStretch()

    def open(self, entry):
        """entry：歷史紀錄嘅一句（original、translation）。"""
        self.entry = entry
        self.original.setText(entry["original"])
        self.translation.setText(entry.get("translation") or "")
        self.work.setText(f"記入作品「{memory().work}」（譯做 {current().key}）；可以喺「作品」轉")
        self.term.clear()
        self.term_fix.clear()
        self.sentence_fix.setText(entry.get("translation") or "")
        self.status.clear()
        self.show()
        self.raise_()
        self.activateWindow()

    def _save_term(self):
        term, fix = self.term.text().strip(), self.term_fix.text().strip()
        if not term or not fix:
            self.status.setText("⚠️ 要填齊原文詞同譯法")
            return
        if term not in self.entry["original"]:
            self.status.setText(f"⚠️ 原文入面搵唔到「{term}」")
            return
        memory().set_term(term, fix, current().key)
        self.status.setText(f"✅ 記低咗：{term} → {fix}。之後嘅句會跟（窗要再讀一次嗰頁）")
        print(f"改詞：{term} → {fix}（作品 {memory().work}）")

    def _save_sentence(self):
        fix = self.sentence_fix.text().strip()
        if not fix:
            self.status.setText("⚠️ 要填正確譯文")
            return
        memory().set_sentence(self.entry["original"], fix, current().key)
        self.status.setText("✅ 記低咗：以後見到呢句原文就用呢個譯文")
        print(f"改成句：{self.entry['original']} → {fix}（作品 {memory().work}）")


def main():
    """示範：開一句假紀錄俾你改（會真係寫入而家作品嘅名單）。"""
    app = QApplication(sys.argv)
    dialog = CorrectionDialog()
    dialog.open({"original": "中身は案外ヤワじゃないか", "translation": "裡面其實意外地不那麼雅瓦吧？"})
    app.exec()


if __name__ == "__main__":
    main()
