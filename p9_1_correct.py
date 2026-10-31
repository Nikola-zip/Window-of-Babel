# 巴別塔之窗：改譯文就記住（Fluent 元件）
#
# 做咩：歷史面板每句有「改」，撳落去開呢個細視窗，兩種改法：
#   1. 改詞：「ヤワ → 軟弱」記入而家作品嘅名單（備註「手動改」），以後有呢個詞嘅句都跟
#   2. 改成句：以後見到一模一樣嘅原文，直接用你寫嘅譯文，唔問模型（口頭禪、重複嘅對白）
#   兩樣都係改完即刻生效：名單檔一變，翻譯快取都分開記，下次讀嗰頁就用新譯法。
# 點用：main.py 將 correction.open 交俾歷史面板。

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (BodyLabel, CaptionLabel, LineEdit, PrimaryPushButton, PushButton, SimpleCardWidget,
                            StrongBodyLabel)

from i18n import tr
from p7_1_target import current
from p8_5_names import memory
from theme import ThemedWindow


def section(title):
    """一張卡加標題：改詞、改成句各一張。回傳（卡, 入面嘅直排）。"""
    box = SimpleCardWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(16, 12, 16, 14)
    column.setSpacing(8)
    column.addWidget(StrongBodyLabel(title))
    return box, column


class CorrectionDialog(ThemedWindow):
    """改一句譯文：上面睇原文同而家譯文，下面揀改詞定改成句。"""

    def __init__(self):
        super().__init__(tr("巴別塔之窗：改譯文"), 600, 520)
        self.original = LineEdit()
        self.original.setReadOnly(True)     # 唔俾改，但揀得字：揀咗就撳「用揀咗嘅字」
        self.translation = BodyLabel()
        self.translation.setWordWrap(True)
        self.translation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.work = CaptionLabel()
        top = QFormLayout()
        top.addRow(BodyLabel(tr("原文")), self.original)
        top.addRow(BodyLabel(tr("而家譯文")), self.translation)
        top.addRow("", self.work)
        self.body.addLayout(top)

        # ---------- 改詞 ----------
        term_box, column = section(tr("改詞（以後有呢個詞嘅句都跟）"))
        self.term = LineEdit()
        self.term.setPlaceholderText(tr("原文入面嘅詞，例如 ヤワ"))
        pick = PushButton(tr("用揀咗嘅字"))
        pick.setToolTip(tr("喺上面「原文」揀咗一截字，撳呢度就搬落嚟"))
        pick.clicked.connect(lambda: self.term.setText(self.original.selectedText() or self.term.text()))
        row = QHBoxLayout()
        row.addWidget(self.term, 1)
        row.addWidget(pick)
        column.addLayout(row)
        self.term_fix = LineEdit()
        self.term_fix.setPlaceholderText(tr("正確譯法，例如 軟弱"))
        column.addWidget(self.term_fix)
        save_term = PrimaryPushButton(tr("記低呢個詞"))
        save_term.clicked.connect(self._save_term)
        column.addWidget(save_term, alignment=Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(term_box)

        # ---------- 改成句 ----------
        sentence_box, column = section(tr("改成句（以後一模一樣嘅原文直接用呢個譯文）"))
        self.sentence_fix = LineEdit()
        self.sentence_fix.setPlaceholderText(tr("正確譯文"))
        column.addWidget(self.sentence_fix)
        save_sentence = PrimaryPushButton(tr("記低成句"))
        save_sentence.clicked.connect(self._save_sentence)
        column.addWidget(save_sentence, alignment=Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(sentence_box)

        self.status = BodyLabel()
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.body.addStretch()

    def open(self, entry):
        """entry：歷史紀錄嘅一句（original、translation）。"""
        self.entry = entry
        self.original.setText(entry["original"])
        self.translation.setText(entry.get("translation") or "")
        self.work.setText(tr("記入作品「{v1}」（譯做 {v2}）；可以喺「作品」轉", v1=memory().work, v2=current().key))
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
            self.status.setText(tr("⚠️ 要填齊原文詞同譯法"))
            return
        if term not in self.entry["original"]:
            self.status.setText(tr("⚠️ 原文入面搵唔到「{term}」", term=term))
            return
        memory().set_term(term, fix, current().key)
        self.status.setText(tr("✅ 記低咗：{term} → {fix}。之後嘅句會跟（窗要再讀一次嗰頁）", term=term, fix=fix))
        print(f"改詞：{term} → {fix}（作品 {memory().work}）")

    def _save_sentence(self):
        fix = self.sentence_fix.text().strip()
        if not fix:
            self.status.setText(tr("⚠️ 要填正確譯文"))
            return
        memory().set_sentence(self.entry["original"], fix, current().key)
        self.status.setText(tr("✅ 記低咗：以後見到呢句原文就用呢個譯文"))
        print(f"改成句：{self.entry['original']} → {fix}（作品 {memory().work}）")
