# 巴別塔之窗：介面語言
#
# 做咩：tr("原句") 由字表攞而家介面語言嘅譯文；code 入面寫嘅廣東話就係 key，所以「廣東話」唔使字表。
#   字表放 ui\<語言>.json（{"原句": "譯文"}）；查唔到就顯示原句，唔會出錯，日後加新句唔怕漏。
#   第一次開跟 Windows 語言：繁體中文（香港、台灣、澳門）用書面語，其他一律英文；喺設定揀咗就記住（settings.json「介面語言」）。
#   加新語言：加一個 ui\<語言>.json，再喺 LANGUAGES 加一行，唔使改其他 code。
# 點用：from i18n import tr；有變數嘅句 tr("讀到 {n} 段", n=3)。

import ctypes
import json
import locale
from pathlib import Path

from ui_parts import load_settings, save_settings

UI_DIR = Path(__file__).resolve().parent / "ui"
AUTO = "auto"
LANGUAGES = {"en": "English", "zh-Hant": "繁體中文", "yue": "廣東話"}     # 代號 → 喺選單顯示嘅名（用佢自己嘅語言）
TRADITIONAL = ("zh_HK", "zh_TW", "zh_MO")
_table = None


def windows_language():
    """Windows 顯示語言：繁中地區用繁中，其他一律英文（簡中等日後有字表再加）。"""
    try:
        name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except (AttributeError, OSError):
        return "en"
    return "zh-Hant" if name.startswith(TRADITIONAL) else "en"


def chosen_language():
    """用家揀咗嘅（"auto" 或者語言代號）；寫錯就當跟系統。"""
    choice = load_settings().get("介面語言", AUTO)
    return choice if choice == AUTO or choice in LANGUAGES else AUTO


def set_language(choice):
    """存低用家揀嘅語言：介面字喺開視窗時已經擺好，要重開程式先全部轉晒。"""
    settings = load_settings()
    settings["介面語言"] = choice
    save_settings(settings)


def current_language():
    choice = chosen_language()
    return windows_language() if choice == AUTO else choice


def _load():
    global _table
    language = current_language()
    path = UI_DIR / f"{language}.json"
    try:
        _table = json.loads(path.read_text(encoding="utf-8")) if language != "yue" else {}
    except (OSError, ValueError):
        _table = {}     # 字表唔見咗或者壞咗：顯示原句，唔好開唔到程式
    return _table


def tr(text, **values):
    """將原句換成介面語言；values 係句入面 {名} 嘅值（譯文可以調換次序）。"""
    table = _table if _table is not None else _load()
    result = table.get(text, text)
    return result.format(**values) if values else result
