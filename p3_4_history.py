# 巴別塔之窗：歷史面板同紀錄檔（由譯幕第3期第4步改）
#
# 做咩：每句字幕寫入 logs\當日日期.jsonl（每句一行：時間、來源、語言、原文、譯文、延遲）；
#       Ctrl+Alt+H 打開歷史面板，顯示最近 200 句（settings.json 嘅「歷史句數」可以改），
#       捲得、揀字複製得、可以一次過複製全部，亦可以用記事本開成個紀錄檔。
#       歷史面板同紀錄檔讀同一份資料，重開都睇得返今日之前嘅句。
# 點用：main.py 會 import 呢度嘅 SubtitleLog 同 HistoryPanel（譯幕版嘅假字幕示範拎走咗）。

import json
import subprocess
from collections import deque
from datetime import date, datetime
from html import escape
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QHBoxLayout
from qfluentwidgets import FluentIcon, PushButton, TextBrowser, qconfig

from i18n import tr
from theme import ThemedWindow, accent_color, muted_color
from ui_parts import CHINESE_FONTS, load_settings, make_font, save_settings

LOG_DIR = Path("logs")
# 規格寫 50 句，但睇片每分鐘大約 12 句，50 句得返 4 分鐘左右；
# 預設 200 句（大約 15 至 20 分鐘），用戶可以喺 settings.json 嘅「歷史句數」改
DEFAULT_HISTORY = 200


def history_size():
    """讀「歷史句數」；寫錯或者太誇張就夾返 10 至 1000。"""
    settings = load_settings()
    try:
        size = min(max(int(settings.get("歷史句數", DEFAULT_HISTORY)), 10), 1000)
    except (TypeError, ValueError):
        size = DEFAULT_HISTORY
    if settings.get("歷史句數") != size:
        settings["歷史句數"] = size
        save_settings(settings)
    return size


class SubtitleLog:
    """每日一個 JSONL 紀錄檔；歷史面板同紀錄檔用同一份資料。"""

    def __init__(self, folder=LOG_DIR, keep=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        # deque 設咗 maxlen：記住最近幾句，舊嘅自動踢走（全部仲喺紀錄檔度）
        self.recent = deque(maxlen=keep or history_size())
        self.listeners = []     # 有新句就通知佢哋，例如歷史面板
        self._load_today()

    def _path(self):
        # 一日一個檔：好搵、好刪，規格講私隱要定期清，刪舊日子個檔就得
        return self.folder / f"{date.today().isoformat()}.jsonl"

    def _load_today(self):
        """重開都讀返今日之前嘅句，歷史面板唔會空白。"""
        path = self._path()
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                self.recent.append(json.loads(line))
            except ValueError:
                continue    # 例如上次寫到一半斷電，壞咗嗰行跳過，唔好令成個程式死

    def add(self, source, lang, original, translation, delay=None):
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "source": source,           # 例如「聽聲·chrome.exe」；將來讀字會係「讀字·遊戲名」
            "lang": lang,
            "original": original,
            "translation": translation,  # 中文唔譯就係空白
            "delay": None if delay is None else round(delay, 2),  # 講完到譯文；驗收計中位數要用
        }
        # JSONL：一句一行，加嘢只係喺尾加一行，唔使重寫成個檔；ensure_ascii=False 等中日文睇得明
        with self._path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.recent.append(entry)
        for listener in self.listeners:
            listener(entry)


class HistoryPanel(ThemedWindow):
    """歷史面板：最近 50 句，捲得、揀字複製得。"""

    def __init__(self, log, on_fix=None):
        super().__init__(tr("巴別塔之窗：歷史"), 640, 720)
        self.log = log
        self.on_fix = on_fix    # 有就每句加「改」連結（第 9 期：改譯文就記住），撳落去叫 on_fix(嗰句)

        # TextBrowser 本身係唯讀，但可以揀字、Ctrl+C 複製
        self.view = TextBrowser()
        self.view.setFont(make_font(CHINESE_FONTS, 12))
        # 「改」連結唔好當網址開，自己處理
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        copy_all = PushButton(FluentIcon.COPY, tr("複製全部"))
        copy_all.clicked.connect(self.copy_all)
        open_file = PushButton(FluentIcon.DOCUMENT, tr("開紀錄檔"))
        open_file.setToolTip(tr("用記事本打開今日成個紀錄檔；面板睇唔晒嘅舊句都喺度"))
        open_file.clicked.connect(self.open_log)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(open_file)
        buttons.addWidget(copy_all)
        self.body.addWidget(self.view)
        self.body.addLayout(buttons)

        log.listeners.append(lambda entry: self.render())
        qconfig.themeChanged.connect(lambda _: self.render())    # 啲字嘅顏色寫喺 HTML，轉深淺色要重畫
        self.render()

    def render(self):
        """成個面板重新畫：最多 50 句，好快，又唔使理點樣刪走最頂嗰句。"""
        bar = self.view.verticalScrollBar()
        # 本身喺最底先跟住捲落去；你捲咗上去睇舊句，就唔好扯你返落嚟
        at_bottom = bar.value() >= bar.maximum() - 4
        position = bar.value()
        blocks = []
        self.shown = list(self.log.recent)     # 「改」連結用位置認返邊句
        for i, entry in enumerate(self.shown):
            when = entry["time"][11:]   # 淨係要「時:分:秒」
            meta = f"{when}　{entry['lang'].upper()}　{entry['source']}"
            translation = entry["translation"] or tr("（中文，唔譯）")
            fix = (f'　<a href="fix:{i}" style="color:{accent_color()};">改</a>'
                   if self.on_fix and entry["translation"] else "")
            blocks.append(
                f'<p><span style="color:{muted_color()};">{escape(meta)}</span>{fix}<br>'
                f'<span style="color:{muted_color()};">{escape(entry["original"])}</span><br>'
                f"<b>{escape(translation)}</b></p>"
            )
        self.view.setHtml("".join(blocks))
        bar.setValue(bar.maximum() if at_bottom else position)

    def _link(self, url):
        text = url.toString()
        if text.startswith("fix:") and self.on_fix:
            index = int(text[4:])
            if 0 <= index < len(self.shown):
                self.on_fix(self.shown[index])

    def copy_all(self):
        """一次過複製晒：一句一行「時間 [語言] 原文 → 譯文」，貼去筆記都好睇。"""
        lines = [
            f"{e['time'][11:]} [{e['lang']}] {e['original']} → {e['translation'] or tr('（中文，唔譯）')}"
            for e in self.log.recent
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def open_log(self):
        """用記事本開今日個紀錄檔。"""
        path = self.log._path()
        path.touch()    # 今日未有句都開到，費事記事本問你係咪開新檔
        # 指明用記事本：.jsonl 喺 Windows 未必有預設程式，直接開會彈出「揀程式」
        subprocess.Popen(["notepad.exe", str(path.resolve())])

    def toggle(self):
        """熱鍵用：開住就收埋，收埋就打開兼擺最前。"""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
