# 譯幕 第8期第5關：人名記憶
#
# 做咩：同一部作品嘅人名前後譯得一樣。試過「タダシ」有上下文譯「忠」、冇上下文譯「塔達希」，同一頁兩個譯法。
#   1. 每句翻譯之前搵「名」：片假名詞（タダシ、クロノス、ヴィラン）、漢字名加稱呼（山田さん、田中様）
#   2. 未記過嘅，單獨譯一次個名（冇上下文，試過穩定），記入嗰部作品嘅 CSV
#   3. 之後句句有呢個名，都用 Hy-MT2「參考翻譯」寫法叫模型跟住（同詞庫一樣）
#   每部作品一個檔：glossaries\names\作品名.csv（欄：原文,譯做,譯名,備註），用記事本改，存檔即刻生效。
#   譯做唔同語言各自記（譯做 English 嘅「タダシ」係 Tadashi）。
# 點用：p2_3_glossary.py 嘅 GlossaryTranslator 會用呢度；選單「作品」揀邊部。
#   直接行係自我測試：.venv\Scripts\python -W ignore p8_5_names.py

import csv
import re
import subprocess
import threading
from pathlib import Path

from i18n import tr
from p4_6_launch import load_settings, save_setting

NAMES_DIR = Path("glossaries/names")
SETTING = "作品"
DEFAULT_WORK = "未分類"
FIELDS = ["原文", "譯做", "譯名", "備註"]
# 第 9 期：用戶喺歷史面板改嘅詞（備註寫 MANUAL）同成句固定譯文（另一個檔「作品.成句.csv」）
MANUAL = "手動改"
SENTENCE_SUFFIX = ".成句"
SENTENCE_FIELDS = ["原文", "譯做", "譯文", "備註"]
# 片假名詞：兩個字以上（「ー」「・」唔計做字）
KATAKANA = re.compile(r"[ァ-ヺ][ァ-ヺー・]+")
# 漢字名加稱呼：兩至四個漢字（一個字嘅多數唔係名：「神様」「皆様」「客様」）
HONORIFIC = re.compile(r"([一-龯々]{2,4})(?:さん|様|さま|くん|君|ちゃん|殿|先生|先輩|氏)")
# 單獨譯個名，譯出嚟長過原文咁多倍就當模型講多咗嘢（寫咗成句、解釋），唔記
MAX_STRETCH = 3


def safe_name(work):
    """作品名做檔名：Windows 檔名唔可以有 \\ / : * ? " < > |"""
    return re.sub(r'[\\/:*?"<>|]', "_", work).strip() or DEFAULT_WORK


# 試過名單記咗好多唔係名嘅片假名（用戶真漫畫一個月）：擬聲字「バチッ」「ドサッ」「サッ」（譯咗「薩」）、
# 語氣「ハア」「ハァ」、笑聲「アハハハ」「ケラ」、口語形容詞「ヤバ」「ヤワ」（譯咗「雅瓦」）「デカ」。下面幾條篩走佢哋
SMALL_END = "ッァィゥェォャュョ"      # 呢啲細字結尾嘅多數係擬聲字、語氣（「ギョッ」「ハァ」）
LAUGHS = ("ハハ", "ヘヘ", "フフ", "ホホ", "ケラ", "ゲラ")
# 後面跟住呢啲就係當形容詞、副詞用（「ヤバそう」「ヤワじゃない」「デカすぎ」），唔係名
NOT_NAME_AFTER = ("そう", "すぎ", "じゃ", "っぽ", "っ", "な")


def plausible_name(word, after=""):
    """呢個片假名詞似唔似名（或者值得記嘅專有名詞）。after：原句入面緊接佢後面嘅字。"""
    letters = word.replace("ー", "").replace("・", "")
    if len(letters) < 2 or letters[-1] in SMALL_END or any(laugh in letters for laugh in LAUGHS):
        return False
    # 重複嘅（「ハハハ」「ドキドキ」）係笑聲、擬聲字，唔係名
    if len(set(letters)) == 1 or (len(letters) % 2 == 0 and letters[:len(letters) // 2] * 2 == letters):
        return False
    if after.startswith(NOT_NAME_AFTER):
        return False
    return interjections().lookup(word) is None     # 語氣詞表有嘅（「ハア」）唔係名


_interjections = None


def interjections():
    global _interjections
    if _interjections is None:
        from p4_4_context import Interjections
        _interjections = Interjections()
    return _interjections


def candidates(text):
    """今句入面可能係名嘅詞（未分邊個記咗）。"""
    found = []
    for match in KATAKANA.finditer(text):
        word = match.group().strip("・")
        if plausible_name(word, text[match.end():]):
            found.append(word)
    found += HONORIFIC.findall(text)
    return list(dict.fromkeys(found))     # 唔要重複，保持次序


def appears(source, text, strict=True):
    """名有冇喺句入面出現。片假名名要成個詞先算：試過「タイ」（泰國）連「タイプ」「タイミング」都配埋，
    叫模型譯做泰國；所以前後唔可以再黐住片假名。
    strict=False（用戶手動改嘅詞）：唔理後面跟住乜嘢：用戶改「ヤワ → 軟弱」就係想「ヤワじゃない」都跟"""
    if not KATAKANA.fullmatch(source):
        return source in text       # 漢字名（「山田」）冇得咁分，照用包含
    if not strict:
        return re.search(f"(?<![ァ-ヺー・]){re.escape(source)}(?![ァ-ヺー・])", text) is not None
    # 後面跟住「じゃ」「そう」呢啲（當形容詞用）唔算：名單入面已經有嘅「ヤワ」唔會套落「ヤワじゃないか」
    pattern = f"(?<![ァ-ヺー・]){re.escape(source)}(?![ァ-ヺー・])"
    return any(not text[m.end():].startswith(NOT_NAME_AFTER) for m in re.finditer(pattern, text))


class NameMemory:
    """一部作品嘅名單；字幕條同譯鏡兩條翻譯線共用一個（有鎖）。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.work = load_settings().get(SETTING, DEFAULT_WORK)
        self.rows = []
        self.sentences = {}     # （譯做, 原文）→ 固定譯文
        self.mtime = None
        self.version = 0        # 名單一變就加一：譯鏡嘅翻譯快取要分開記，費事用咗舊譯名
        self._load()

    @property
    def path(self):
        return NAMES_DIR / f"{safe_name(self.work)}.csv"

    @property
    def sentence_path(self):
        return NAMES_DIR / f"{safe_name(self.work)}{SENTENCE_SUFFIX}.csv"

    def _mtimes(self):
        return tuple(p.stat().st_mtime if p.exists() else None for p in (self.path, self.sentence_path))

    def _load(self):
        self.rows, self.sentences = [], {}
        if self.path.exists():
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                self.rows = [row for row in csv.DictReader(f) if (row.get("原文") or "").strip()]
        if self.sentence_path.exists():
            with open(self.sentence_path, encoding="utf-8-sig", newline="") as f:
                self.sentences = {(row.get("譯做", ""), row["原文"].strip()): row.get("譯文", "").strip()
                                  for row in csv.DictReader(f) if (row.get("原文") or "").strip()}
        self.mtime = self._mtimes()
        self.version += 1

    def _refresh(self):
        """用戶用記事本改咗就重新讀：唔使重開程式。"""
        if self._mtimes() != self.mtime:
            self._load()

    def _known(self, target_key):
        return {row["原文"].strip(): row["譯名"].strip() for row in self.rows if row.get("譯做") == target_key}

    def terms(self, text, target):
        """今句有嘅名：[(原文, 譯名)]，長嘅排先（「タダシ様」同「タダシ」都有就先睇完整嗰個）。"""
        with self.lock:
            self._refresh()
            known = self._known(target.key)
            manual = {row["原文"].strip() for row in self.rows
                      if row.get("譯做") == target.key and row.get("備註") == MANUAL}
        found = [(source, name) for source, name in known.items()
                 if name and appears(source, text, strict=source not in manual)]
        return sorted(found, key=lambda pair: len(pair[0]), reverse=True)

    def sentence(self, text, target):
        """呢句原文有冇用戶固定咗嘅譯文（成句一模一樣先算，前後空格唔計）；冇就 None。"""
        with self.lock:
            self._refresh()
            return self.sentences.get((target.key, text.strip())) or None

    def set_term(self, source, name, target_key):
        """用戶改詞：同一個原文舊嗰行（自動記低或者以前改過）換做新譯法，備註「手動改」。"""
        with self.lock:
            self._refresh()
            rows = [row for row in self.rows if not (row["原文"].strip() == source and row.get("譯做") == target_key)]
            rows.append({"原文": source, "譯做": target_key, "譯名": name, "備註": MANUAL})
            self._write(self.path, FIELDS, rows)

    def set_sentence(self, original, translation, target_key):
        """用戶改成句：以後見到一模一樣嘅原文直接用呢個譯文。"""
        with self.lock:
            self._refresh()
            self.sentences[(target_key, original.strip())] = translation.strip()
            rows = [{"原文": text, "譯做": key, "譯文": value, "備註": MANUAL}
                    for (key, text), value in self.sentences.items()]
            self._write(self.sentence_path, SENTENCE_FIELDS, rows)

    def _write(self, path, fields, rows):
        NAMES_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        self._load()

    def learn(self, text, target, translate_name):
        """今句有未記過嘅名，就逐個用 translate_name(名) 譯一次再記低。回傳新記咗嘅 [(原文, 譯名)]。"""
        with self.lock:
            self._refresh()
            known = self._known(target.key)
            new = [word for word in candidates(text) if word not in known]
        learned = []
        for word in new:
            name = translate_name(word).strip().strip("。．.！!？?、，,「」『』\"' ")
            if not name or len(name) > len(word) * MAX_STRETCH + 2 or KATAKANA.search(name) and target.hong_kong:
                continue    # 講多咗嘢、或者譯做中文仲係片假名（冇譯到）：下次再試
            learned.append((word, name))
        if learned:
            with self.lock:
                self._append(learned, target.key)
        return learned

    def _append(self, pairs, target_key):
        NAMES_DIR.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with open(self.path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            for source, name in pairs:
                writer.writerow({"原文": source, "譯做": target_key, "譯名": name, "備註": "自動記低"})
        self._load()

    # ---------- 作品 ----------
    def works(self):
        """有名單檔嘅作品，加埋而家嗰部（未有檔都列）。"""
        names = {path.stem for path in NAMES_DIR.glob("*.csv")
                 if not path.stem.endswith(SENTENCE_SUFFIX)} if NAMES_DIR.exists() else set()
        return sorted(names | {safe_name(self.work)})

    def set_work(self, work):
        with self.lock:
            self.work = safe_name(work)
            save_setting(SETTING, self.work)
            self._load()

    def open_file(self):
        """用記事本開名單（未有就先開個空檔連標題）；改完存檔，下一句就用新譯名。"""
        with self.lock:
            if not self.path.exists():
                NAMES_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
                    csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        subprocess.Popen(["notepad.exe", str(self.path.resolve())])


_memory = None


def memory():
    """成個程式共用一份名單（字幕條同譯鏡都係同一部作品）。"""
    global _memory
    if _memory is None:
        _memory = NameMemory()
    return _memory


def works_menu(on_change, parent=None):
    """「作品」子選單：揀邊部（單選）、開新作品、開名單。on_change(作品名) 喺轉咗之後叫。"""
    from PyQt6.QtGui import QAction, QActionGroup
    from PyQt6.QtWidgets import QInputDialog, QMenu
    menu = QMenu(tr("作品"), parent)
    group = QActionGroup(menu)
    group.setExclusive(True)

    def choose(work):
        memory().set_work(work)
        on_change(memory().work)

    def new_work():
        work, ok = QInputDialog.getText(None, tr("開新作品"), tr("作品名（例如漫畫名、遊戲名）："))
        if ok and work.strip():
            choose(work.strip())

    def rebuild():
        # 每次打開先砌：用記事本／新作品加咗檔都即刻見到
        menu.clear()
        for item in group.actions():
            group.removeAction(item)
        for work in memory().works():
            item = QAction(work, menu)
            item.setCheckable(True)
            item.setChecked(work == memory().work)
            item.triggered.connect(lambda _=False, work=work: choose(work))
            group.addAction(item)
            menu.addAction(item)
        menu.addSeparator()
        menu.addAction(tr("開新作品…")).triggered.connect(new_work)
        menu.addAction(tr("開名單（記事本）")).triggered.connect(lambda: memory().open_file())
    menu.aboutToShow.connect(rebuild)
    rebuild()
    menu.group = group      # 要留住參照
    return menu


def main():
    """自我測試：搵名嘅規則；再用真模型記一頁對白嘅名（寫入 glossaries\\names\\自我測試.csv，測完刪）。"""
    tests = {
        "タダシよ頑張っとるようじゃな": ["タダシ"],
        "た…タダシ様これはいったい？": ["タダシ"],
        "ああ クロノス様！いらっしゃいませ！": ["クロノス"],
        "山田さん、田中様もどうぞ": ["山田", "田中"],
        "ハハハ、ドキドキするね": [],
        "神様、お客様、皆様": [],
        "ヴィランを倒した": ["ヴィラン"],
    }
    ok = 0
    for text, want in tests.items():
        got = candidates(text)
        ok += got == want
        print(f"{text} → {got}　{'✅' if got == want else '❌ 應該係 ' + str(want)}")
    print(f"搵名：{ok}/{len(tests)} 啱")

    from p2_1_translate import ask
    from p7_1_target import current, plain_prompt
    names = NameMemory()
    names.work = "自我測試"
    if names.path.exists():
        names.path.unlink()
    names._load()
    for text in ["タダシよ頑張っとるようじゃな", "た…タダシ様これはいったい？", "タダシの子らじゃなあ！"]:
        learned = names.learn(text, current(), lambda word: ask(plain_prompt(word))[0])
        print(f"{text}：新記 {learned}，用 {names.terms(text, current())}")
    names.path.unlink()


if __name__ == "__main__":
    main()
