# 巴別塔之窗：全域熱鍵（由譯幕第3期第3步改，拎走字幕條嗰幾個）
#
# 做咩：用 Windows 官方嘅 RegisterHotKey 登記熱鍵；遊戲或者其他程式喺前面都有效。
#       熱鍵寫喺 settings.json 嘅「熱鍵」，可以喺設定視窗「熱鍵」頁改，避開同其他程式撞。
# 點用：main.py 用 GlobalHotkeys.bind() 登記、while_held() 做按住型熱鍵。

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer

from i18n import tr
from ui_parts import load_settings, save_settings

# use_last_error：登記失敗時攞到 Windows 嘅錯誤代碼，知道係咪俾人霸咗
user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000       # 撳住唔放唔好連續觸發，費事暫停／繼續閃來閃去
MODIFIERS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
DEFAULT_HOTKEYS = {"歷史": "Ctrl+Alt+H",
                   # 清空上下文用 N（New，新場景）：R 好容易俾其他程式霸咗（錯誤 1409）
                   "清空上下文": "Ctrl+Alt+N",
                   # G（Glass）調整塊鏡、T（Translate）讀字、A（Auto）自動模式、V（View）按住睇原文
                   "譯鏡調整": "Ctrl+Alt+G", "譯鏡讀字": "Ctrl+Alt+T", "譯鏡自動": "Ctrl+Alt+A",
                   "譯鏡原文": "Ctrl+Alt+V"}
HOLD_CHECK = 30             # 按住型熱鍵：每幾多毫秒問一次個鍵放咗未


def parse(text):
    """將 "Ctrl+Alt+P" 轉做 Windows 要嘅（修飾鍵代碼, 按鍵代碼）。"""
    modifiers, key = 0, None
    for part in (p.strip().lower() for p in text.split("+") if p.strip()):
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif len(part) == 1 and part.isascii() and part.isalnum():
            key = ord(part.upper())     # 英文字母同數字嘅按鍵代碼就係佢大楷嘅 ASCII
        elif part[0] == "f" and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            key = 0x70 + int(part[1:]) - 1      # F1 係 0x70，順住落去
        else:
            raise ValueError(tr("睇唔明「{part}」", part=part))
    # 一定要有修飾鍵：淨係一個字母做全域熱鍵，你打字嗰陣就會亂觸發
    if key is None or not modifiers:
        raise ValueError(tr("要有最少一個 Ctrl／Alt／Shift／Win，再加一個字母、數字或者 F 鍵"))
    return modifiers, key


def load_hotkeys():
    """讀「熱鍵」設定；冇寫嘅用預設，再寫返入檔，等用戶知道可以改。"""
    settings = load_settings()
    saved = settings.get("熱鍵", {})
    hotkeys = {name: saved.get(name, default) for name, default in DEFAULT_HOTKEYS.items()}
    if saved != hotkeys:
        settings["熱鍵"] = hotkeys
        save_settings(settings)
    return hotkeys


class GlobalHotkeys(QAbstractNativeEventFilter):
    """向 Windows 登記熱鍵，再喺 Qt 收訊息嗰度截住 WM_HOTKEY。"""

    def __init__(self, app):
        super().__init__()
        self.actions = {}
        self.next_id = 1
        # 有名嘅熱鍵（bind 登記嘅）：設定視窗改綁要知邊個名用緊邊個組合、邊個編號
        self.named = {}         # 名 → 功能
        self.texts = {}         # 名 → 組合（例如 "Ctrl+Alt+P"）
        self.ids = {}           # 名 → 向 Windows 登記嘅編號（登記唔到就冇）
        self.problems = {}      # 名 → 登記唔到嘅原因
        # 熱鍵訊息係寄俾主線嘅，Qt 主線收訊息時會先交俾呢個過濾器睇
        app.installNativeEventFilter(self)
        app.aboutToQuit.connect(self.unregister_all)    # 閂之前交還，唔係其他程式用唔到

    def register(self, text, action):
        """登記一個熱鍵；成功回傳 None，失敗回傳原因。"""
        try:
            modifiers, key = parse(text)
        except ValueError as error:
            return str(error)
        hotkey_id = self.next_id
        self.next_id += 1
        # hWnd 用 None：熱鍵訊息會寄去呢條線（Qt 主線）嘅訊息隊，唔使另外開視窗
        if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, key):
            error = ctypes.get_last_error()
            if error == ERROR_HOTKEY_ALREADY_REGISTERED:
                return tr("已經俾其他程式用咗，換一個")
            return tr("Windows 錯誤代碼 {error}", error=error)
        self.actions[hotkey_id] = action
        return None

    def bind(self, name, text, action):
        """登記一個有名嘅熱鍵（設定視窗改得）；回傳同 register 一樣。"""
        self.named[name], self.texts[name] = action, text
        problem = self._bind_id(name, text)
        self.problems[name] = problem
        return problem

    def _bind_id(self, name, text):
        before = self.next_id
        problem = self.register(text, self.named[name])
        if problem is None:
            self.ids[name] = before
        return problem

    def _release(self, name):
        hotkey_id = self.ids.pop(name, None)
        if hotkey_id is not None:
            user32.UnregisterHotKey(None, hotkey_id)
            self.actions.pop(hotkey_id, None)

    def rebind(self, name, text):
        """改一個熱鍵嘅組合：即刻生效兼存檔；新組合用唔到就還原舊嗰個。成功回傳 None，失敗回傳原因。"""
        try:
            wanted = parse(text)
        except ValueError as error:
            return str(error)
        for other, other_text in self.texts.items():
            if other != name and parse_or_none(other_text) == wanted:
                return tr("同「{other}」撞咗", other=other)
        old = self.texts.get(name)
        self._release(name)
        problem = self._bind_id(name, text)
        if problem is not None:
            if old is not None:
                self._bind_id(name, old)        # 還原：唔好搞到個功能冇熱鍵
            return problem
        self.texts[name] = text
        self.problems[name] = None
        settings = load_settings()
        settings["熱鍵"] = {**settings.get("熱鍵", {}), name: text}
        save_settings(settings)
        return None

    def suspend(self):
        """暫時交還所有有名熱鍵：設定視窗錄新組合嗰陣，唔係撳落去會觸發舊功能，視窗收唔到個鍵。"""
        for name in list(self.ids):
            self._release(name)

    def resume(self):
        for name, text in self.texts.items():
            if name not in self.ids:
                self.problems[name] = self._bind_id(name, text)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self.actions:
                self.actions[msg.wParam]()
                return True, 0      # 處理咗，唔使再交俾其他人
        return False, 0

    def unregister_all(self):
        for hotkey_id in self.actions:
            user32.UnregisterHotKey(None, hotkey_id)
        self.actions.clear()


def parse_or_none(text):
    try:
        return parse(text)
    except ValueError:
        return None


def while_held(hotkeys, name, on_hold):
    """按住型熱鍵：RegisterHotKey 淨係撳落先有通知，冇「放手」通知，
    所以撳落之後定時問 GetAsyncKeyState 個字母鍵仲撳唔撳住，放咗就 on_hold(False)。
    淨係問一個鍵嘅狀態、按住期間先問，唔係低階鍵盤鉤（遊戲嘅反作弊軟件會當可疑）。
    回傳撳落時叫嘅功能（交俾 bind）；計時器掛喺佢身上，唔好俾 Python 清走。"""
    timer = QTimer()
    timer.setInterval(HOLD_CHECK)

    def check():
        key = parse_or_none(hotkeys.texts.get(name, ""))
        # 0x8000：而家撳住。用最新組合（熱鍵頁改咗都跟到）；讀唔到組合就當放咗手，唔好卡住
        if key is None or not user32.GetAsyncKeyState(key[1]) & 0x8000:
            timer.stop()
            on_hold(False)

    def pressed():
        if not timer.isActive():
            on_hold(True)
            timer.start()

    timer.timeout.connect(check)
    pressed.timer = timer
    return pressed
