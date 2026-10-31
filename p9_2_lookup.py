# 譯幕 第9期第2關：網上搵譯名
#
# 做咩：喺幾個免費公開網站（唔使帳戶）搵作品嘅人名、用語譯法，排成對比表俾你揀，剔咗先寫入名單。
#   譯幕本身一直唔上網；呢度係你撳「搵」先會上，送出去嘅只有你打嘅作品名同條目名。
#   來源（可信程度由高到低）：
#   1. 貼上：你喺瀏覽器複製成頁（萌娘百科擋咗程式查詢，淨係人睇得），貼入嚟照格式抽
#   2. 維基百科：「中文名／中文名（日文名／日文名（讀音），聲：…）」用規則抽；全名用「・」分開嘅再拆開逐截對
#   3. Bangumi：角色嘅「简体中文名」（轉繁體、香港用字）；淨係譯做繁中先用
#   4. AniList：角色英文名；譯做 English 直接用，其他語言交俾 Hy-MT2 由英文名譯（「模型估（由英文名）」）
#   5. 模型估：條目有呢個詞但抽唔到，就將前後幾段交俾 Hy-MT2 做「背景信息」再譯
#   MangaDex 唔係譯名來源，係攞作品喺各語言嘅名（冷門作品用香港譯名先搵到維基條目）。
#   維基跟「譯做」：繁中 → 中文維基（香港用字）、English → 英文、한국어 → 韓文、日本語 → 日文。
# 點用：設定視窗「翻譯」頁「網上搵譯名…」；直接行係示範（真係會上網）：
#   .venv\Scripts\python -W ignore p9_2_lookup.py シャングリラ・フロンティア

import json
import re
import sys
import urllib.parse
import urllib.request

from i18n import tr
from p2_1_translate import ask
from p7_1_target import CONTEXT, current

USER_AGENT = "window-of-babel/0.1 (hobby project)"     # 維基要求寫清楚係乜程式
TIMEOUT = 20
WIKIS = {"繁體中文": ("zh", "zh-hk"), "English": ("en", None), "한국어": ("ko", None), "日本語": ("ja", None)}
NEW_MAX = 20            # 新發現嘅詞最多幾多個字先列：再長嘅多數係作品標題、句子
BANGUMI_MAX = 40        # Bangumi 每個角色要多問一次，最多問幾多個
BANGUMI_WORKERS = 4     # 同時問幾多個角色
SNIPPET = 120           # 交俾模型嘅段落：詞前後各幾多字
SNIPPETS = 3            # 最多幾段
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺ一-龯々]")
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
READING = re.compile(r"[ぁ-ゖー]+\s[ぁ-ゖー\s]+")      # 「さいが れい」：漢字名嘅讀音（姓同名之間有空格），唔係名
# 中文：名（日文）：「中文名／中文名（日文名／日文名（讀音），聲：…」；英文：「Name (日本語, romaji)」
PAIR_CJK = re.compile(r"([^\s（）()，,。；：:「」『』\[\]]{1,30})[（(]([^（）()，,；;\n]{1,40}?)(?=[（(，,）);；]|聲|声)")
# 英文：「Sunraku (サンラク, Sanraku)」「Rakuro Hizutome (陽務 楽郎, Hizutome Rakurō)」：名有空格、括號前有空格
PAIR_LATIN = re.compile(r"([A-Z][A-Za-z0-9'’.\-]*(?: [A-Z][A-Za-z0-9'’.\-]*){0,4}) ?\(([^(),，]{1,40}?)[,，)]")
# 韓文：「히즈토메 라쿠로(陽務 楽郎)」：名有空格
PAIR_HANGUL = re.compile(r"([가-힣A-Za-z0-9]+(?: [가-힣A-Za-z0-9]+){0,3}) ?[（(]([^()（），,]{1,40}?)[,，)）]")
# 唔係名嘅「對」：聲優嗰段「日本；香港」之類
NOT_NAMES = {"日本", "香港", "台灣", "臺灣", "中國", "日語", "日文", "英語", "聲",
             "台湾", "中国", "日语", "英语", "声"}       # 萌娘百科、Bangumi 係簡體
BANGUMI_VOLUME = re.compile(r"[（(]\d+[)）]\s*$")    # 「シャングリラ・フロンティア (24)」：單行本，冇角色


def wiki_host(target=None):
    language, variant = WIKIS.get((target or current()).key, ("zh", "zh-hk"))
    return f"https://{language}.wikipedia.org/w/api.php", variant


def call(api, **params):
    params["format"] = "json"
    url = api + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def search(query, target=None):
    """搵條目：回傳 [(標題, 頁碼)]，最多 5 個。"""
    api, _ = wiki_host(target)
    data = call(api, action="query", list="search", srsearch=query, srlimit=5)
    return [(hit["title"], hit["pageid"]) for hit in data.get("query", {}).get("search", [])]


def article(pageid, target=None):
    """條目全文（純文字；中文維基用香港用字版本）。"""
    api, variant = wiki_host(target)
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "pageids": pageid}
    if variant:
        params["variant"] = variant
    pages = call(api, **params).get("query", {}).get("pages", {})
    return next(iter(pages.values()), {}).get("extract", "")


# ---------- 其他網站（都係免費公開 API，唔使帳戶）----------
def get_json(url, data=None):
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def mangadex_titles(query):
    """MangaDex：用任何一個名（日文、英文、羅馬拼音）搵漫畫，回傳 [{語言: [名, ...]}]（最多 3 部）。
    冷門作品維基多數冇，但 MangaDex 有齊各語言嘅作品名（試過《ドラゴンの胃でおやすみ》有香港譯名）"""
    data = get_json("https://api.mangadex.org/manga?" + urllib.parse.urlencode({"title": query, "limit": 3}))
    works = []
    for item in data.get("data", []):
        attributes = item.get("attributes", {})
        names = {}
        for entry in [attributes.get("title", {})] + attributes.get("altTitles", []):
            for language, title in entry.items():
                names.setdefault(language, []).append(title)
        works.append(names)
    return works


def anilist_characters(query):
    """AniList：作品嘅角色（日文名 → 英文名），回傳（作品日文名, {日文名: 英文名}）；搵唔到回（None, {}）。"""
    graphql = ("query($s:String){Media(search:$s,type:MANGA){title{native} characters(perPage:50)"
               "{nodes{name{native full}}}}}")
    try:
        media = get_json("https://graphql.anilist.co", {"query": graphql, "variables": {"s": query}})["data"]["Media"]
    except (OSError, KeyError, TypeError, ValueError):
        return None, {}     # AniList 搵唔到會回錯誤（404），當冇
    if not media:
        return None, {}
    characters = {}
    for node in media["characters"]["nodes"]:
        native, full = node["name"].get("native"), node["name"].get("full")
        if native and full:
            add_pair(characters, native, full, latin=True)
    return media["title"].get("native"), characters


def bangumi_subject(query):
    """Bangumi 揀邊個條目：動畫（type 2）先，再搵書（type 1）；跳過單行本（「(24)」）同冇角色嘅。
    試過淨搵書，第一個係單行本第 24 期，角色 0 個。回傳（條目, 角色清單）；搵唔到（None, []）"""
    for kind in (2, 1):
        try:
            search = get_json("https://api.bgm.tv/search/subject/" + urllib.parse.quote(query)
                              + f"?type={kind}&responseGroup=small")
        except (OSError, ValueError):
            continue        # 搵唔到有時回 404，當冇
        for subject in (search.get("list") or [])[:3]:
            if BANGUMI_VOLUME.search(subject.get("name", "")):
                continue
            characters = get_json(f"https://api.bgm.tv/v0/subjects/{subject['id']}/characters")
            if characters:
                return subject, characters
    return None, []


def bangumi_characters(query, limit=BANGUMI_MAX, progress=None):
    """Bangumi（番組計劃）：角色中文名（有人填先有，多數係簡體），回傳（作品名, {日文名: 中文名}）。"""
    subject, listing = bangumi_subject(query)
    if not subject:
        return None, {}
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def detail(character):
        try:
            return get_json(f"https://api.bgm.tv/v0/characters/{character['id']}")
        except (OSError, ValueError):
            return {}       # 一個角色讀唔到唔緊要，其他照用

    characters = {}
    listing = listing[:limit]
    # 每個角色一秒左右，40 個逐個問要成分鐘；同時問幾個（唔好太多，人哋係免費服務）
    with ThreadPoolExecutor(BANGUMI_WORKERS) as pool:
        futures = [pool.submit(detail, character) for character in listing]
        for i, _ in enumerate(as_completed(futures)):
            if progress:
                progress(i, len(listing))
    for future in futures:          # 照 Bangumi 次序（主角先）記，唔好跟邊個先返
        info = future.result()
        chinese = next((item["value"] for item in info.get("infobox", []) if item.get("key") == "简体中文名"), None)
        if isinstance(chinese, str) and chinese:
            add_pair(characters, info.get("name", ""), chinese)
    return subject.get("name_cn") or subject.get("name"), characters


def pairs_in(text, target=None):
    """照格式抽（日文 → 譯名）。同一個日文名第一次出現嗰個為準（條目通常先寫最常用嗰個）。
    抽法跟「譯做」嘅維基：中文冇空格；英文、韓文嘅名有空格。"""
    found = {}
    key = (target or current()).key
    pattern = {"English": PAIR_LATIN, "한국어": PAIR_HANGUL}.get(key, PAIR_CJK)
    for match in pattern.finditer(text):
        names = re.split(r"[／/]", match.group(1))
        japanese = re.split(r"[／/]", match.group(2))
        if len(names) != len(japanese):
            names, japanese = names[:1], japanese[:1]
        for name, word in zip(names, japanese):
            add_pair(found, word, name, latin=key == "English")
    return found


def add_pair(found, word, name, latin=False):
    """記低一對（日文 → 譯名），再將全名拆開逐截對：「アーサー・ペンシルゴン」→「亞瑟·潘希魯貢」。
    latin：譯名係英文：英文將漢字名嘅姓名掉轉（陽務 楽郎 → Rakuro Hizutome），片假名名照順序"""
    # Bangumi 將遊戲名同真名寫埋一行：「サンラク／陽務楽郎 → 桑乐／阳务乐郎」，數目一樣先逐個對
    words, names = re.split(r"[／/]", word), re.split(r"[／/]", name)
    if len(words) > 1 and len(words) == len(names):
        for one_word, one_name in zip(words, names):
            add_pair(found, one_word, one_name, latin)
        return

    def add(japanese, translated):
        japanese, translated = clean(japanese), clean(translated)
        if (not japanese or not translated or japanese == translated or not JAPANESE.search(japanese)
                or KANA.search(translated) or japanese in NOT_NAMES or translated in NOT_NAMES
                or not any(c.isalpha() for c in translated) or READING.fullmatch(japanese)
                or re.search(r"[〈〉《》、]", translated)):
            return      # 譯名入面仲有假名＝冇譯到；聲優、地方名唔係；「1→2」（等級表）冇字唔係名；讀音唔係名；
            #             中間有書名號、頓號＝抽咗半句（「GIRLS〉、《末日十字軍」）
        found.setdefault(japanese, translated)

    add(word, name)
    word_parts = [p for p in re.split(r"[・\s]", word) if p]
    name_parts = [p for p in re.split(r"[·・\s]", name) if p]
    if len(word_parts) > 1 and len(word_parts) == len(name_parts):
        if latin and not KANA.search(word):
            name_parts = name_parts[::-1]
        for part, name_part in zip(word_parts, name_parts):
            add(part, name_part)


def clean(text):
    """去走前後綴：「日語：シャングリラ」「《香格里拉」。"""
    text = re.sub(r"^(日語|日语|日文|原名|英語|英语|英文)[:：]", "", text.strip())
    return text.strip(" ・·《》「」『』〈〉【】\"'")


def new_names(pairs, known):
    """條目有、名單未有嘅詞：淨列有假名嘅（角色名、外來語）；淨漢字嘅多數係中文句子（「打倒哥布林」）。"""
    return {japanese: name for japanese, name in pairs.items()
            if KANA.search(japanese) and japanese not in known and len(japanese) <= NEW_MAX}


def snippets(term, text):
    return [text[max(0, m.start() - SNIPPET):m.end() + SNIPPET].replace("\n", " ")
            for m in list(re.finditer(re.escape(term), text))[:SNIPPETS]]


def model_guess(term, text, target=None):
    """條目有呢個詞但抽唔到：前後幾段做「背景信息」交俾 Hy-MT2 譯（佢會跟住段落嘅譯法）；冇就 None。"""
    parts = snippets(term, text)
    if not parts:
        return None
    target = target or current()
    prompt = CONTEXT[target.chinese_prompt].format(background="\n".join(parts), target=target.name, text=term)
    result, _ = ask(prompt)
    result = result.strip().strip("。．.！!？?、，,「」『』\"' ")
    return result if result and result != term and len(result) <= len(term) * 4 + 4 else None


def from_english(english, target=None):
    """冇人譯過但有英文名（AniList）：交俾 Hy-MT2 由英文名譯，譯法穩陣過由片假名估。"""
    from p7_1_target import plain_prompt
    target = target or current()
    result, _ = ask(plain_prompt(english, target))
    result = result.strip().strip("。．.！!？?、，,「」『』\"' ")
    if target.key == "繁體中文" and not re.search(r"[一-鿿]", result):
        return None     # 模型間中照抄英文（Eristella）：咁就唔算有譯
    return result or None


def suggestions(terms, text, target=None, progress=None):
    """每個詞：{原文: (維基譯名或者 None, 模型估或者 None)}；條目冇提過嘅詞唔列。
    terms：要搵嘅詞（名單入面嘅原文）。progress(第幾個, 總數) 俾視窗顯示進度。"""
    pairs = pairs_in(text, target)
    result = {}
    for i, term in enumerate(terms):
        if progress:
            progress(i, len(terms))
        wiki = pairs.get(term)
        if wiki is None and term not in text:
            continue
        guess = None if wiki else model_guess(term, text, target)
        if wiki or guess:
            result[term] = (wiki, guess)
    return result


def same_title(title, names):
    """維基條目名似唔似作品名：去走標點空格，頭 8 個字喺對方入面就算（副題、・同·唔同都唔緊要）。"""
    def bare(text):
        return re.sub(r"[\W_]+", "", text).lower()
    title = bare(title)
    return bool(title) and any(bare(name) and (bare(name)[:8] in title or (len(title) >= 4 and title in bare(name))) for name in names)


# ---------- 合晒各網站做對比 ----------
MODEL = "模型估"
MODEL_ENGLISH = "模型估（由英文名）"
_convert = None


def to_target(text, target=None):
    """簡體（萌娘百科、Bangumi）→ 繁體；譯做其他語言、本身係繁體都唔郁。
    人名逐隻字轉，淨轉 Big5 冇嘅字：成個名交 OpenCC 會將姓氏「范」轉做「範」（亚瑟·范西尔冈 → 亞瑟·範西爾岡）；
    香港用字表（網路 → 網絡）係譯文用，人名唔使"""
    global _convert
    if not text or (target or current()).key != "繁體中文":
        return text
    if _convert is None:
        import opencc                       # 用到先載入
        _convert = opencc.OpenCC("s2tw.json")
    from p4_4_context import is_traditional
    return "".join(c if is_traditional(c) else _convert.convert(c) for c in text)


def compare(sources, known, texts=(), english=None, target=None, progress=None, cache=None):
    """合晒各來源，回傳 {原文: [(出處, 譯名), ...]}，可信嘅排先。
    sources：{出處: {日文: 譯名}}，按可信程度排（貼上 → 維基 → Bangumi）；english：AniList {日文: 英文名}；
    texts：條目、貼上嘅全文（模型估用）。名單有嘅詞：冇網站寫明先叫模型估；名單未有嘅：網站有寫先列。
    cache：{(出處, 原文): 譯名}：讀多個條目再對比，唔使再問模型"""
    target = target or current()
    cache = {} if cache is None else cache
    english = english or {}
    if target.key == "English" and english:
        sources, english = {**sources, "AniList": english}, {}      # 英文名就係譯名，唔使模型
    terms = dict.fromkeys(known)
    for found in list(sources.values()) + [english]:
        terms.update(dict.fromkeys(new_names(found, known)))

    def ask_model(label, term, work):
        if (label, term) not in cache:
            cache[(label, term)] = work()
        return cache[(label, term)]

    result = {}
    for i, term in enumerate(terms):
        if progress:
            progress(i, len(terms))
        choices = [(label, found[term]) for label, found in sources.items() if term in found]
        if not choices and term in english:
            choices = [(MODEL_ENGLISH, ask_model(MODEL_ENGLISH, term, lambda: from_english(english[term], target)))]
        if not choices and term in known:
            text = next((t for t in texts if term in t), None)
            if text:
                choices = [(MODEL, ask_model(MODEL, term, lambda: model_guess(term, text, target)))]
        choices = [(label, to_target(name, target)) for label, name in choices if name]
        # 規則有時連前面嘅字都抽埋（「玩家名桑乐（日语：サンラク）」→「玩家名桑樂」）：
        # 另一個網站嘅譯名啱啱係佢個尾，就剪返做短嗰個
        names = {name for _, name in choices}
        choices = [(label, next((short for short in names if len(short) < len(name) and name.endswith(short)), name))
                   for label, name in choices]
        if choices:
            result[term] = choices
    return result


# ---------- 揀譯名嘅視窗 ----------
def lookup_dialog():
    """要用 Qt 先 import：上面嘅函數唔使開視窗都用得（測試、示範）。"""
    from PyQt6.QtCore import Qt, QUrl
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QApplication, QHBoxLayout, QTableWidgetItem, QVBoxLayout
    from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, ComboBox, EditableComboBox, FluentIcon, LineEdit,
                                PlainTextEdit, PrimaryPushButton, PushButton, SimpleCardWidget, StrongBodyLabel,
                                TableWidget)

    from p8_5_names import DEFAULT_WORK, memory
    from theme import ThemedWindow

    def unique(items):
        return list(dict.fromkeys(i for i in items if i))

    class LookupDialog(ThemedWindow):
        COLUMNS = [tr("用"), tr("原文"), tr("而家譯名"), tr("新譯名（可以自己改）"), tr("各網站譯法")]
        SITES = ["MangaDex", "維基", "AniList", "Bangumi", "貼上"]

        def __init__(self):
            super().__init__(tr("巴別塔之窗：網上搵譯名"), 900, 800)
            self.query = LineEdit()
            self.query.setPlaceholderText(tr("作品名（日文原名、英文名、中文譯名都得，例如 シャングリラ・フロンティア）"))
            find = PrimaryPushButton(FluentIcon.SEARCH, tr("搵"))
            find.clicked.connect(self._search)
            self.query.returnPressed.connect(self._search)
            self.report = CaptionLabel()
            self.report.setWordWrap(True)
            self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.hits = ComboBox()
            read = PushButton(tr("讀呢個條目"))
            read.clicked.connect(self._read)

            # ---- 貼上文字：萌娘百科擋咗程式，但你喺瀏覽器睇得，複製成頁貼入嚟就得 ----
            self.paste = PlainTextEdit()
            self.paste.setPlaceholderText(tr("喺瀏覽器打開角色介紹頁（例如萌娘百科），Ctrl+A 全選、Ctrl+C 複製，貼喺度，再撳「讀貼上嘅文字」。成頁貼都得，簡體會自動轉繁體。"))
            self.paste.setMaximumHeight(90)
            moegirl = PushButton(FluentIcon.GLOBE, tr("喺瀏覽器開萌娘百科"))
            moegirl.clicked.connect(lambda: self._browse(
                "https://zh.moegirl.org.cn/index.php?variant=zh-hk&search=", name=self.original))
            google = PushButton(FluentIcon.GLOBE, tr("Google 搵"))
            google.clicked.connect(lambda: self._browse("https://www.google.com/search?q=", tr(" 角色")))
            read_paste = PushButton(tr("讀貼上嘅文字"))
            read_paste.clicked.connect(self._read_paste)
            paste_buttons = QHBoxLayout()
            paste_buttons.addWidget(moegirl)
            paste_buttons.addWidget(google)
            paste_buttons.addStretch()
            paste_buttons.addWidget(read_paste)
            paste_box = SimpleCardWidget()
            paste_layout = QVBoxLayout(paste_box)
            paste_layout.setContentsMargins(14, 10, 14, 12)
            paste_layout.addWidget(StrongBodyLabel(tr("貼上網頁文字（最可信：網頁寫明嘅譯名排第一）")))
            paste_layout.addWidget(self.paste)
            paste_layout.addLayout(paste_buttons)

            self.status = BodyLabel(tr("撳「搵」先會上網（只係送作品名）。"))
            self.status.setWordWrap(True)
            self.table = TableWidget()
            self.table.setBorderVisible(True)
            self.table.setBorderRadius(8)
            self.table.setColumnCount(len(self.COLUMNS))
            self.table.setHorizontalHeaderLabels(self.COLUMNS)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.show_new = CheckBox(tr("加埋名單未有嘅角色、用語"))
            self.show_new.toggled.connect(self._fill)
            save = PrimaryPushButton(tr("將剔咗嘅寫入名單"))
            save.clicked.connect(self._save)
            top = QHBoxLayout()
            top.addWidget(self.query, 1)
            top.addWidget(find)
            middle = QHBoxLayout()
            middle.addWidget(BodyLabel(tr("維基條目")))
            middle.addWidget(self.hits, 1)
            middle.addWidget(read)
            bottom = QHBoxLayout()
            bottom.addWidget(self.show_new)
            bottom.addStretch()
            bottom.addWidget(save)
            self.body.addLayout(top)
            self.body.addWidget(self.report)
            self.body.addLayout(middle)
            self.body.addWidget(paste_box)
            self.body.addWidget(self.status)
            self.body.addWidget(self.table, 1)
            self.body.addLayout(bottom)
            self.sources = {"貼上": {}, "維基": {}, "Bangumi": {}}     # 次序＝可信程度
            self.texts = {"貼上": "", "維基": ""}
            self.english, self.cache, self.sites, self.found, self.known = {}, {}, {}, {}, {}
            self.title = ""         # 作品喺「譯做」嗰種語言嘅名（MangaDex），Google 用
            # 萌娘百科用日文原名搵：用戶試過用中文譯名搵唔到，日文名就搵到
            self.original = ""

        def open(self):
            work = memory().work
            if not self.query.text() and work != DEFAULT_WORK:
                self.query.setText(work)
            self.show()
            self.raise_()
            self.activateWindow()

        def _busy(self, text):
            self.status.setText(text)
            QApplication.processEvents()        # 上網、問模型要幾秒，等狀態字先出

        def _site(self, name, text):
            self.sites[name] = text
            self.report.setText("\n".join(f"• {tr(site)}：{self.sites[site]}" for site in self.SITES if site in self.sites))
            QApplication.processEvents()

        def _search(self):
            query = self.query.text().strip()
            if not query:
                return
            target = current()
            if target.key == "日本語":
                self.status.setText(tr("譯做日本語唔使搵譯名。"))
                return
            # 新作品：清走上一次嘅網站結果同模型估（貼上嘅照留，可能係你先貼後搵）
            self.sources.update({"維基": {}, "Bangumi": {}})
            self.texts["維基"] = ""
            self.english, self.cache, self.sites = {}, {}, {}
            if self.sources["貼上"]:
                self._site("貼上", tr("{v1} 對（之前貼嘅）", v1=len(self.sources['貼上'])))

            # MangaDex：作品喺各語言嘅名，冷門作品用香港譯名先搵到維基
            self._busy(tr("⏳ MangaDex：搵作品喺各語言嘅名……"))
            try:
                works = mangadex_titles(query)
            except (OSError, ValueError) as error:
                works = []
                self._site("MangaDex", tr("上唔到（{error}）", error=error))
            titles = works[0] if works else {}
            language = WIKIS.get(target.key, ("zh", None))[0]
            local = unique([t for key in {"zh": ["zh-hk", "zh", "zh-tw"]}.get(language, [language])
                            for t in titles.get(key, [])])[:2]
            japanese = titles.get("ja", [])[:1]
            others = japanese + titles.get("ja-ro", [])[:1] + titles.get("en", [])[:1]
            self.title = (local or [query])[0]
            # 你打嘅有假名就係日文名；冇就用 MangaDex 嘅日文名，去走「～副題～」（太長搵唔到）
            self.original = query if KANA.search(query) else re.split(r"[～〜]", (japanese or [query])[0])[0].strip()
            if works:
                self._site("MangaDex", "、".join(local) if local else tr("有呢部作品，但冇呢種語言嘅名"))
            elif "MangaDex" not in self.sites:
                self._site("MangaDex", tr("搵唔到"))

            # 維基：用你打嘅名、MangaDex 嘅譯名同日文名都搵
            self._busy(tr("⏳ 維基百科：搵條目……"))
            names = unique(local + [query] + japanese)
            hits = []
            for name in names[:3]:
                try:
                    hits += [hit for hit in search(name, target) if hit not in hits]
                except OSError as error:
                    self._site("維基", tr("上唔到（{error}）", error=error))
                    break
            # 條目名同作品名對得上嘅排先；全部對唔上就唔自動讀
            # （試過冷門作品搵到一個無關嘅人名條目排第一）
            hits.sort(key=lambda hit: not same_title(hit[0], names))
            self.hits.clear()
            for title, pageid in hits[:8]:
                self.hits.addItem(title, userData=pageid)
            if not hits and "維基" not in self.sites:
                self._site("維基", tr("搵唔到條目"))
            elif hits and not same_title(hits[0][0], names):
                self._site("維基", tr("{v1} 個條目，但冇一個個名似呢部作品，要自己揀再撳「讀呢個條目」", v1=len(hits)))

            # AniList：角色英文名
            self._busy(tr("⏳ AniList：搵角色英文名……"))
            for name in unique([query] + others):
                native, self.english = anilist_characters(name)
                if self.english:
                    self._site("AniList", tr("「{native}」{v2} 個角色英文名", native=native, v2=len(self.english)))
                    break
            else:
                self._site("AniList", tr("搵唔到（淨搵漫畫）"))

            # Bangumi：角色中文名，淨係譯做繁中先有用
            if target.key == "繁體中文":
                for name in unique([query] + japanese + local):
                    try:
                        title, found = bangumi_characters(
                            name, progress=lambda i, n: self._busy(tr("⏳ Bangumi：讀角色 {v1}/{n}……", v1=i + 1, n=n)))
                    except (OSError, ValueError) as error:
                        self._site("Bangumi", tr("上唔到（{error}）", error=error))
                        break
                    if found:
                        self.sources["Bangumi"] = found
                        self._site("Bangumi", tr("「{title}」{v2} 個角色中文名", title=title, v2=len(found)))
                        break
                else:
                    self._site("Bangumi", tr("搵唔到有中文名嘅角色"))

            if hits and same_title(hits[0][0], names):
                self._read()        # 唔啱就喺下拉揀過再撳「讀呢個條目」
            else:
                self._compare()

        def _read(self):
            pageid = self.hits.currentData()
            if pageid is None:
                return
            self._busy(tr("⏳ 讀緊維基條目……"))
            try:
                text = article(pageid)
            except OSError as error:
                self._site("維基", tr("上唔到（{error}）", error=error))
                return
            self.texts["維基"] = text
            self.sources["維基"] = pairs_in(text, current())
            self._site("維基", tr("「{v1}」抽到 {v2} 對（共 {v3} 個條目，可以喺下面揀過）", v1=self.hits.currentText(), v2=len(self.sources['維基']), v3=self.hits.count()))
            self._compare()

        def _read_paste(self):
            text = self.paste.toPlainText().strip()
            if not text:
                self.status.setText(tr("⚠️ 未貼文字：喺瀏覽器 Ctrl+A、Ctrl+C，再喺上面個格 Ctrl+V。"))
                return
            self.texts["貼上"] = text
            self.sources["貼上"] = pairs_in(text, current())
            self._site("貼上", tr("{v1} 字，抽到 {v2} 對", v1=len(text), v2=len(self.sources['貼上'])))
            self._compare()

        def _browse(self, url, suffix="", name=None):
            name = name or self.title or self.query.text().strip()
            if name:
                QDesktopServices.openUrl(QUrl(url + urllib.parse.quote(name + suffix)))

        def _compare(self):
            target = current()
            self.known = memory()._known(target.key)
            sources = {label: found for label, found in self.sources.items() if found}
            self.found = compare(sources, self.known, [t for t in self.texts.values() if t], self.english, target,
                                 progress=lambda i, n: self._busy(tr("⏳ 對比緊 {v1}/{n}……", v1=i + 1, n=n)), cache=self.cache)
            in_list = sum(term in self.known for term in self.found)
            self.show_new.setText(tr("加埋名單未有嘅角色、用語（{v1} 個）", v1=len(self.found) - in_list))
            self._fill()
            self.status.setText(tr("名單入面 {in_list} 個詞搵到譯法。網站寫明嘅先預先剔咗；「模型估」唔係網站寫明，要睇清楚。剔咗嘅先會寫入（當「手動改」）。", in_list=in_list))

        def _fill(self):
            rows = []
            for term, choices in self.found.items():
                now = self.known.get(term, "")
                if term not in self.known and not self.show_new.isChecked():
                    continue
                names = unique([name for _, name in choices] + [now])
                detail = "｜".join(f"{tr(label)} {name}" for label, name in choices)
                trusted = choices[0][0] not in (MODEL, MODEL_ENGLISH)
                rows.append((term, now, names, detail, term in self.known and trusted and names[0] != now))
            self.table.setRowCount(0)           # 先清晒舊行：唔係舊嘅下拉選單會殘留疊喺上面
            self.table.setRowCount(len(rows))
            for r, (term, now, choices, detail, checked) in enumerate(rows):
                use = CheckBox()
                use.setChecked(checked)
                self.table.setCellWidget(r, 0, use)
                for c, text in ((1, term), (2, now), (4, detail)):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(text)
                    self.table.setItem(r, c, item)
                pick = EditableComboBox()
                pick.addItems(choices)
                pick.setCurrentIndex(0)
                self.table.setCellWidget(r, 3, pick)
            self.table.resizeColumnsToContents()

        def _save(self):
            target = current()
            saved = []
            for r in range(self.table.rowCount()):
                if not self.table.cellWidget(r, 0).isChecked():
                    continue
                term = self.table.item(r, 1).text()
                name = self.table.cellWidget(r, 3).currentText().strip()
                if name:
                    memory().set_term(term, name, target.key)
                    saved.append(f"{term} → {name}")
            self.status.setText(tr("✅ 寫入咗 {v1} 個：", v1=len(saved)) + "、".join(saved[:10]) + ("……" if len(saved) > 10 else ""))
            print("網上譯名寫入名單：", saved)

    return LookupDialog()


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "シャングリラ・フロンティア"
    hits = search(query)
    print("搵到：", hits)
    if not hits:
        return
    text = article(hits[0][1])
    pairs = pairs_in(text)
    print(f"條目 {len(text)} 字，抽到 {len(pairs)} 對：")
    for japanese, name in list(pairs.items())[:30]:
        print(f"  {japanese} → {name}")
    for term, (wiki, guess) in suggestions(["サンラク", "シャングリラ", "クソゲーハンター", "オイカッツォ", "ペンシルゴン"],
                                           text).items():
        print(f"{term}：維基 {wiki}｜模型估 {guess}")


if __name__ == "__main__":
    main()
