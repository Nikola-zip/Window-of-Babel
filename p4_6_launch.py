# 巴別塔之窗：一撳就開（由譯幕第4期第6步改）
#
# 做咩：main.py 開機要用嘅零件：未開 Ollama 就幫你開、刪舊紀錄、唔俾開兩個、
#       冇 terminal 嘅時候將輸出寫入 logs\run。
# 點用：直接行就喺桌面整一個「巴別塔之窗」捷徑（撳佢就開，唔使 terminal）：
#       .venv\Scripts\python p4_6_launch.py

import ctypes
import json
import os
import subprocess
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

from p2_1_translate import ollama_alive

PROJECT = Path(__file__).resolve().parent
SETTINGS = PROJECT / "settings.json"
LOG_DIRS = [PROJECT / "logs", PROJECT / "logs" / "debug", PROJECT / "logs" / "run"]
DEFAULT_KEEP_DAYS = 30
OLLAMA_APP = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama app.exe"
OLLAMA_WAIT = 60        # 開 Ollama 之後最多等幾多秒佢應機
# 換圖示就換檔名：Windows 會按檔名記住舊圖示，同名覆蓋嘅話桌面捷徑照出舊嗰個
ICON = PROJECT / "window_of_babel.ico"
ICON_SIZES = (16, 24, 32, 48, 256)
SHORTCUT_NAME = "巴別塔之窗.lnk"

# 狀態字開頭嘅符號就係嚴重程度：出錯 > 等緊 > 正常（工作列圖示用嚟揀顏色）
ERROR, WAITING, NORMAL = 2, 1, 0
LEVEL_COLORS = {NORMAL: "#4fc3f7", WAITING: "#9e9e9e", ERROR: "#e53935"}     # 藍、灰、紅：圖示頂個對白框嘅光


def level_of(text):
    """由狀態字估嚴重程度：「⚠️」出錯；「⏳」「🔌」等緊；其他（✅ 🔊 🧹、空字）正常。"""
    if text.startswith("⚠"):
        return ERROR
    if text.startswith(("⏳", "🔌")):
        return WAITING
    return NORMAL


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key, value):
    """淨係改一個設定：每次都重新讀，費事蓋走字幕條啱啱存咗嘅位置、樣式。"""
    settings = load_settings()
    settings[key] = value
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def keep_days():
    """讀「紀錄保留日數」；冇寫或者寫錯就用預設 30，再寫返入檔，等用戶知可以改。"""
    value = load_settings().get("紀錄保留日數")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        save_setting("紀錄保留日數", DEFAULT_KEEP_DAYS)
        return DEFAULT_KEEP_DAYS
    return value


def clean_old_logs(days, today=None):
    """刪走超過 days 日嘅紀錄（睇檔名個日期，唔睇修改時間）；回傳刪咗幾多個。"""
    cutoff = (today or date.today()) - timedelta(days=days)
    deleted = 0
    for folder in LOG_DIRS:
        for path in folder.glob("????-??-??.*"):
            try:
                day = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue    # 唔係日期名嘅檔唔郁
            if day < cutoff and path.suffix in (".jsonl", ".log"):
                path.unlink()
                deleted += 1
    return deleted


def single_instance():
    """開咗一個就唔俾開第二個：兩個會爭熱鍵、爭 GPU。回傳要留住嘅鎖，已經開咗就回傳 None。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    # Windows 嘅「具名互斥鎖」：同一個名第二次開會話已經存在；程式閂咗 Windows 會自動收返。
    # 名同譯幕（yimu_subtitles）唔同：兩個係唔同程式，開住譯幕都開得巴別塔之窗
    handle = kernel32.CreateMutexW(None, False, "Local\\window_of_babel")
    if ctypes.get_last_error() == 183:     # ERROR_ALREADY_EXISTS
        return None
    return handle


def quiet_console():
    """用 pythonw（冇黑色視窗）開嘅時候，print 冇地方去：改為寫入 logs\\run\\日期.log，出事有得睇。"""
    if sys.stdout is not None:
        return None
    folder = PROJECT / "logs" / "run"
    folder.mkdir(parents=True, exist_ok=True)
    # buffering=1：逐行寫入，程式死咗都唔會甩咗最後幾行
    log = open(folder / f"{date.today():%Y-%m-%d}.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    warnings.filterwarnings("ignore")   # 等於 terminal 版嘅 -W ignore
    print(f"\n===== {datetime.now():%H:%M:%S} 開機（冇 terminal）=====")
    return log


def ensure_ollama(on_status=print):
    """Ollama 冇開就幫你開（同撳開始功能表一樣），等佢應機；回傳開唔開到。"""
    if ollama_alive():
        return True
    if not OLLAMA_APP.exists():
        on_status(f"⚠️ 搵唔到 Ollama（{OLLAMA_APP}）")
        return False
    on_status("⏳ 開緊 Ollama……")
    # DETACHED_PROCESS：Ollama 自己獨立行，閂譯幕唔會連佢一齊閂
    subprocess.Popen([str(OLLAMA_APP)], creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
    deadline = time.monotonic() + OLLAMA_WAIT
    while time.monotonic() < deadline:
        if ollama_alive():
            return True
        time.sleep(1)
    on_status("⚠️ Ollama 開唔到，開返佢之後會自動繼續")
    return False


def make_icon_file():
    """用同工作列一樣嘅圖示（對白框疊成塔）整個 .ico 俾捷徑用，入面有幾個大細。

    每個大細都用 make_icon() 直接畫，再用 .ico 格式（檔頭＋目錄＋每個大細一張 PNG）砌埋：
    淨係一張 256 嘅大圖，桌面縮細嗰陣會矇。
    """
    import struct

    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QGuiApplication
    from ui_parts import make_icon
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 —— 畫字要有 Qt 程式
    images = []
    for size in ICON_SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        make_icon(size=size).pixmap(size, size).save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))
    header = struct.pack("<HHH", 0, 1, len(images))     # 保留、類型 1（圖示）、有幾張
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        # 闊、高（256 要寫 0）、色數、保留、平面、色深、資料大細、資料喺邊
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    ICON.write_bytes(header + entries + blobs)
    return ICON


# 用 Windows 自帶嘅 PowerShell 整捷徑，唔使為咗一個捷徑多裝 comtypes。
# 用 Windows 問桌面喺邊：有啲人個桌面俾 OneDrive 搬咗去第二度。
# WorkingDirectory 一定要設：程式用相對路徑搵 settings.json、logs、glossaries、models。
# 路徑經環境變數傳入：有中文、空格都唔使理引號；結果用 UTF-8 印返出嚟，桌面路徑有中文都讀得返
SHORTCUT_SCRIPT = """
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop $env:WOB_NAME
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$link.TargetPath = $env:WOB_TARGET
$link.Arguments = '"' + $env:WOB_MAIN + '"'
$link.WorkingDirectory = $env:WOB_FOLDER
$link.IconLocation = $env:WOB_ICON
$link.Description = $env:WOB_NOTE
$link.Save()
Write-Output $path
"""


def make_shortcut():
    """喺桌面整「巴別塔之窗」捷徑：用 .venv 嘅 pythonw（唔會彈黑色視窗）開 main.py；回傳捷徑路徑。"""
    env = {**os.environ, "WOB_NAME": SHORTCUT_NAME, "WOB_MAIN": str(PROJECT / "main.py"),
           "WOB_TARGET": str(PROJECT / ".venv" / "Scripts" / "pythonw.exe"), "WOB_FOLDER": str(PROJECT),
           "WOB_ICON": str(make_icon_file()), "WOB_NOTE": "巴別塔之窗：螢幕翻譯窗"}
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_SCRIPT], env=env,
                          capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW)     # 唔要閃個黑色視窗
    if done.returncode != 0:
        raise OSError(done.stderr.strip()[:200] or "PowerShell 整唔到捷徑")
    return Path(done.stdout.strip())


if __name__ == "__main__":
    print(f"整好咗：{make_shortcut()}")
