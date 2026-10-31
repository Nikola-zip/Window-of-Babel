# 巴別塔之窗：譯文字型
#
# 做咩：揀譯文用邊隻字型（settings.json「譯鏡字型」）。Windows 本身嘅字型直接用；
#   CATALOG 係一份揀好嘅免費字型清單（全部 SIL OFL 1.1），用家撳下載先由作者或者 Google Fonts 落，
#   放入 fonts\，程式自己載入（QFontDatabase.addApplicationFont），唔使裝落 Windows。
#   所以項目本身唔使分發字型，都唔使附字型授權檔。
#   用家亦可以加自己嘅字型檔：抄入 fonts\，開機自動載入，唔喺清單都會列出嚟（add_own_font）。
#   揀咗嘅字型排第一，後面照接「譯做」語言嘅字型同正黑體做後備：字型冇嗰隻字（例如粉圓冇韓文）Qt 會自動用下一隻。
# 點用：p6_3_lens.py、p8_7_settings.py 會用 chosen()；下載視窗喺 p10_3_fonts.py。

import shutil
from pathlib import Path

from p4_6_launch import load_settings, save_setting

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILES = (".ttf", ".otf", ".ttc")
DEFAULT = "微軟正黑體"
GOOGLE = "https://raw.githubusercontent.com/google/fonts/6c1dbe27dcf7d817d4b62cec033ba77fa8e2a5ec/ofl/"    # 鎖死版本
OFL = "SIL OFL 1.1"
# 可以下載嘅字型：名、字型家族名、啱邊種「譯做」語言（同 p7_1_target.TARGETS 嘅 key 一樣）、
# 檔案（檔名, 網址, sha256, 大細）。sha256 係 2026-10-31 由官方網址落一次計出嚟（霞鶩文楷用官方發佈嘅）
CATALOG = [
    {"名": "jf open 粉圓", "家族": "jf open 粉圓 2.1", "語言": ("繁體中文",), "檔案": [
        ("jf-openhuninn-2.1.ttf", "https://github.com/justfont/open-huninn-font/releases/download/v2.1/jf-openhuninn-2.1.ttf",
         "9d5bf4932d31fe94c18cd8cfddc98bc1b14ce10f4e354c682179db290a99c825", 4911464)]},
    {"名": "霞鶩文楷 TC", "家族": "LXGW WenKai TC Medium", "語言": ("繁體中文",), "檔案": [
        ("LXGWWenKaiTC-Medium.ttf", "https://github.com/lxgw/LxgwWenkaiTC/releases/download/v1.530/LXGWWenKaiTC-Medium.ttf",
         "649efd8516f42d36eacc05480d5dbd2713fb28fbd2bbee8ea76fc40875045c49", 15122300)]},
    {"名": "芫荽", "家族": "Iansui", "語言": ("繁體中文",), "檔案": [
        ("Iansui-Regular.ttf", GOOGLE + "iansui/Iansui-Regular.ttf",
         "6e6340d80d618a42b48ade9370c34fa37a8210750c6fbc8efe65f23716538a2b", 9420560)]},
    {"名": "Noto Sans JP", "家族": "Noto Sans JP", "語言": ("日本語",), "檔案": [
        ("NotoSansJP.ttf", GOOGLE + "notosansjp/NotoSansJP%5Bwght%5D.ttf",
         "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f", 9589900)]},
    {"名": "Noto Sans KR", "家族": "Noto Sans KR", "語言": ("한국어",), "檔案": [
        ("NotoSansKR.ttf", GOOGLE + "notosanskr/NotoSansKR%5Bwght%5D.ttf",
         "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252", 10414588)]},
    {"名": "Noto Sans", "家族": "Noto Sans", "語言": ("English",), "檔案": [
        ("NotoSans.ttf", GOOGLE + "notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
         "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d", 2049096)]},
    {"名": "Comic Neue", "家族": "Comic Neue", "語言": ("English",), "檔案": [
        ("ComicNeue-Regular.ttf", GOOGLE + "comicneue/ComicNeue-Regular.ttf",
         "a0ee5a37c8b27c4db0700137d928598b1e23b0089e1546a8961909176b779360", 57248),
        ("ComicNeue-Bold.ttf", GOOGLE + "comicneue/ComicNeue-Bold.ttf",
         "3e7e5fccfd7e0788f317b43312151c1bd5cf058c9697a8d83eac3939050bd61e", 55716)]},
]
# 選單顯示嘅名 → 字型家族名（載入咗先知，用 QFontDatabase.applicationFontFamilies 查過）
CHOICES = {"微軟正黑體": "Microsoft JhengHei", **{font["名"]: font["家族"] for font in CATALOG}}
SETTINGS = {"譯鏡": "譯鏡字型", "字幕": "字幕字型"}

_loaded = False
_choice = {}        # 揀咗邊隻：排字時會問幾百次，唔好次次讀 settings.json
_own = []           # 用家自己加嘅字型（唔喺 CHOICES 入面）：顯示嘅名同家族名一樣


def _register(path):
    """載入一個字型檔，回傳選單顯示嘅名；唔係字型檔就回傳 None。

    一個檔可以有幾個家族名（英文名、中文名、每種粗幼各一個），所以先對清單；
    唔喺清單就用第一個 Qt 真係認得嘅名，當係用家自己加嘅字型。"""
    from PyQt6.QtGui import QFontDatabase
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    for name, family in CHOICES.items():
        if family in families:
            return name
    known = set(QFontDatabase.families())
    name = next((family for family in families if family in known), None)
    if name and name not in _own:
        _own.append(name)
    return name


def load_fonts():
    """載入 fonts\\ 入面嘅字型（成個程式一次）；要喺開咗 QApplication 之後先叫得。"""
    global _loaded
    if _loaded:
        return
    for path in sorted(FONT_DIR.iterdir()) if FONT_DIR.exists() else []:
        if path.suffix.lower() in FONT_FILES and _register(path) is None:
            print(f"⚠️ 載入唔到字型：{path.name}")
    _loaded = True


def add_font_file(path):
    """新字型檔：即刻載入，唔使重開程式；清走 has_bold、supports 嘅記憶，費事用舊答案。回傳選單顯示嘅名。"""
    name = _register(path)
    _bold.clear()
    _raw.clear()
    return name


def add_own_font(source):
    """用家揀嘅字型檔：抄入 fonts\\，下次開機都喺度；回傳選單顯示嘅名。讀唔到就唔留低，回傳 None。"""
    source = Path(source)
    target = FONT_DIR / source.name
    fresh = not target.exists()
    if fresh:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    name = add_font_file(target)
    if name is None and fresh:
        target.unlink()
    return name


def available():
    """揀得嘅字型（電腦或者 fonts\\ 真係有嘅先列，費事揀咗冇效果）。"""
    from PyQt6.QtGui import QFontDatabase
    load_fonts()
    families = set(QFontDatabase.families())
    return [name for name, family in CHOICES.items() if family in families] + _own


def chosen(kind):
    """kind：「譯鏡」或者「字幕」。回傳揀咗嘅字型家族名（排喺最前）。"""
    load_fonts()
    if kind not in _choice:
        _choice[kind] = load_settings().get(SETTINGS[kind], DEFAULT)
    name = _choice[kind]
    return name if name in _own else CHOICES.get(name, CHOICES[DEFAULT])


def set_chosen(kind, name):
    """揀字型（選單同設定視窗共用）：即刻生效兼存檔。"""
    _choice[kind] = name
    save_setting(SETTINGS[kind], name)


def chosen_name(kind):
    """揀咗嘅字型喺選單顯示嘅名。"""
    chosen(kind)
    return _choice[kind]


_bold = {}
_raw = {}


def has_bold(family):
    """字型有冇真嘅粗體。冇就唔好叫 Qt 加粗：佢會將普通字描粗頂替（假粗體），
    筆劃變厚又唔均勻，圓體、手寫體嘅樣都冇咗（粉圓、霞鶩文楷、芫荽都淨係得普通粗幼）。"""
    if family not in _bold:
        from PyQt6.QtGui import QFontDatabase
        load_fonts()
        _bold[family] = any("bold" in style.lower() or "black" in style.lower()
                            for style in QFontDatabase.styles(family))
    return _bold[family]


def supports(family, char):
    """字型有冇呢隻字（例如直排用嘅「︕」「︖」，粉圓同芫荽冇）。"""
    if family not in _raw:
        from PyQt6.QtGui import QFont, QRawFont
        load_fonts()
        _raw[family] = QRawFont.fromFont(QFont(family, 20))
    return _raw[family].supportsCharacter(ord(char))
