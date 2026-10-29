# 譯幕 第8期第6關：揀譯文字型
#
# 做咩：譯鏡同字幕條各自揀譯文用邊隻字型（settings.json「譯鏡字型」「字幕字型」）。
#   免費字型（SIL OFL）放喺項目嘅 fonts\ 資料夾，程式自己載入（QFontDatabase.addApplicationFont），
#   唔使裝落 Windows：jf open 粉圓 2.1、霞鶩文楷 TC 中粗（v1.522）、芫荽 v1.020。
#   揀咗嘅字型排第一，後面照接「譯做」語言嘅字型同正黑體做後備：
#   字型冇嗰隻字（例如粉圓冇韓文）Qt 會自動用下一隻。
# 點用：p3_1_subtitle_bar.py、p6_3_lens.py 會用 chosen()；直接行係自我測試：
#   .venv\Scripts\python -W ignore p8_6_fonts.py

from pathlib import Path

from p4_6_launch import load_settings, save_setting

FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT = "微軟正黑體"
# 選單顯示嘅名 → 字型家族名（載入咗先知，用 QFontDatabase.applicationFontFamilies 查過）
CHOICES = {
    "微軟正黑體": "Microsoft JhengHei",
    "jf open 粉圓": "jf open 粉圓 2.1",
    "霞鶩文楷 TC": "LXGW WenKai TC Medium",
    "芫荽": "Iansui",
}
SETTINGS = {"譯鏡": "譯鏡字型", "字幕": "字幕字型"}

_loaded = False
_choice = {}        # 揀咗邊隻：排字時會問幾百次，唔好次次讀 settings.json


def load_fonts():
    """載入 fonts\\ 入面嘅字型（成個程式一次）；要喺開咗 QApplication 之後先叫得。"""
    global _loaded
    if _loaded:
        return
    from PyQt6.QtGui import QFontDatabase
    for path in sorted(FONT_DIR.glob("*.ttf")) if FONT_DIR.exists() else []:
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            print(f"⚠️ 載入唔到字型：{path.name}")
    _loaded = True


def available():
    """揀得嘅字型（電腦或者 fonts\\ 真係有嘅先列，費事揀咗冇效果）。"""
    from PyQt6.QtGui import QFontDatabase
    load_fonts()
    families = set(QFontDatabase.families())
    return [name for name, family in CHOICES.items() if family in families]


def chosen(kind):
    """kind：「譯鏡」或者「字幕」。回傳揀咗嘅字型家族名（排喺最前）。"""
    load_fonts()
    if kind not in _choice:
        _choice[kind] = load_settings().get(SETTINGS[kind], DEFAULT)
    return CHOICES.get(_choice[kind], CHOICES[DEFAULT])


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


def font_menu(kind, on_change, parent=None):
    """「譯文字型」子選單（單選）：揀咗就存檔，再叫 on_change(名)。"""
    from PyQt6.QtGui import QAction, QActionGroup
    from PyQt6.QtWidgets import QMenu
    menu = QMenu("譯文字型" if kind == "譯鏡" else "字幕字型", parent)
    group = QActionGroup(menu)
    group.setExclusive(True)

    def choose(name):
        set_chosen(kind, name)
        on_change(name)

    for name in available():
        item = QAction(name, menu)
        item.setCheckable(True)
        item.triggered.connect(lambda _=False, name=name: choose(name))
        group.addAction(item)
        menu.addAction(item)

    def sync():
        chosen(kind)
        current = _choice[kind]
        for item in group.actions():
            item.setChecked(item.text() == current)
    menu.aboutToShow.connect(sync)
    sync()
    menu.group = group      # 要留住參照
    return menu


def main():
    """自我測試：四隻字型都揀得、真係用到嗰隻字型（唔係靜靜雞用咗後備）。"""
    import sys
    from PyQt6.QtGui import QFont, QFontInfo
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)  # noqa: F841 —— 字型要有 QApplication
    names = available()
    print(f"揀得：{names}")
    ok = len(names) == len(CHOICES)
    for name in names:
        font = QFont()
        font.setFamilies([CHOICES[name], "Microsoft JhengHei"])
        used = QFontInfo(font).family()
        good = used == CHOICES[name]
        ok &= good
        print(f"  {name} → 實際用 {used}　{'✅' if good else '❌'}")
    print("全部啱" if ok else "有錯")


if __name__ == "__main__":
    main()
