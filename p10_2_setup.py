# 巴別塔之窗：第一次開機設定
#
# 做咩：① 檢查 Ollama（冇裝就俾官方連結：系統程式要用家自己裝，唔自動裝）② 讀張顯示卡有幾多 VRAM，
#   建議一檔 ③ 列出輕／中／高三檔，每檔寫明要下載幾多、已經有咗邊啲 ④ 用家撳「下載並使用」先下載，有進度條；
#   Hy-MT2 1.8B 下載完自動整修好範本嘅版本（Ollama 自動轉嘅範本壞咗，見 p10_1_models）。
#   揀咗嘅模型唔齊，開程式就會彈出嚟；設定「模型」頁都有掣再開。
# 點用：main.py 會用 SetupDialog。

import hashlib
import json
import threading
import urllib.request
import webbrowser
import winreg

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QButtonGroup, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (BodyLabel, CaptionLabel, IndeterminateProgressBar, PrimaryPushButton, ProgressBar,
                            PushButton, RadioButton, SimpleCardWidget, StrongBodyLabel)

from i18n import tr
from p2_1_translate import ollama_alive
from p4_6_launch import OLLAMA_APP, ensure_ollama, load_settings, save_setting
from p6_5_inpaint import FINDER_MODEL, LAMA_MODEL
from theme import ThemedWindow
from p10_1_models import (DOWNLOAD_GB, FIXED_SMALL, OLLAMA_HOST, SMALL_SOURCE, SMALL_STOP, SMALL_TEMPLATE, TIERS,
                          apply, current, installed, is_installed, post, same_model)

OLLAMA_DOWNLOAD = "https://ollama.com/download"
# Windows 登錄檔：每張顯示卡（連 AMD、Intel）嘅驅動程式都會寫低自己有幾多記憶體；唔使淨靠 nvidia-smi
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
# 張卡要有幾多 GB 先建議嗰檔：檔嘅 VRAM 加 Windows 同其他程式大約 2 GB
RECOMMEND = (("高", 16), ("中", 12), ("輕", 0))
# 搵字、補圖模型唔係 Ollama 嘅，要另外下載。2026-10-30 用戶揀成個項目用 GPL-3.0（搵字 CTD 係 GPL-3.0，
# 嚟自 manga-image-translator beta-0.2.1；補圖 LaMa 係 Apache-2.0，lama_fp32_dml.onnx 係我哋改過俾 DirectML 用嘅版本），
# 所以放喺自己 GitHub repo 嘅 Releases（標籤 models-v1，淨放模型，同程式版本分開；換模型就開 models-v2）
RELEASE_BASE = "https://github.com/Nikola-zip/Window-of-Babel/releases/download/models-v1/"
# （放喺邊、檔名、sha256、大細）：下載完核對 sha256，唔啱即係壞咗或者俾人改過，唔用
ERASER_FILES = [(FINDER_MODEL, "comictextdetector.pt.onnx",
                 "1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f", 94669756),
                (LAMA_MODEL, "lama_fp32_dml.onnx",
                 "a4a797241691c55e6e590e99478c9130f68cf15b424b126ddf27a50c18dd5acb", 208294802)]


def gpu_vram():
    """最大嗰張顯示卡：（名, GB）；讀唔到回傳（None, None），等用家自己揀。"""
    best = (None, None)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as card:
                        name = winreg.QueryValueEx(card, "DriverDesc")[0]
                        size = winreg.QueryValueEx(card, "HardwareInformation.qwMemorySize")[0] / 2 ** 30
                except OSError:
                    continue    # 唔係每個子項都係真顯示卡（例如「Properties」），冇呢兩個值就跳過
                if best[1] is None or size > best[1]:
                    best = (name, round(size, 1))
    except OSError:
        pass
    return best


def recommend(vram):
    if vram is None:
        return "中"
    return next(name for name, need in RECOMMEND if vram >= need)


def to_download(tier, models):
    """呢檔仲要下載邊啲（Ollama 名）；FIXED_SMALL 唔係下載返嚟，係由 SMALL_SOURCE 整。"""
    wanted = []
    for name in (TIERS[tier]["讀字"], TIERS[tier]["翻譯"]):
        if is_installed(name, models):
            continue
        source = SMALL_SOURCE if same_model(name, FIXED_SMALL) else name
        if not is_installed(source, models) and source not in wanted:
            wanted.append(source)
    return wanted


def eraser_missing():
    return [entry for entry in ERASER_FILES if not entry[0].exists()]


def download_file(url, path, sha256, size, progress):
    """下載一個檔：先寫去 .part，核對 sha256 啱先改名。中途斷咗、校驗唔啱，都唔會留低一個壞檔俾程式讀。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    digest, done = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "window-of-babel"})
    with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as out:
        while True:
            chunk = response.read(1 << 20)      # 每次 1 MB：邊下載邊計校驗碼，唔使成個檔讀入記憶體
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(min(done / size, 1.0), f"{done / 2 ** 20:.0f}／{size / 2 ** 20:.0f} MB")
    if digest.hexdigest() != sha256:
        part.unlink()
        raise OSError(tr("{v1} 校驗碼唔啱（檔案壞咗或者俾人改過），冇用", v1=path.name))
    part.replace(path)


def pull(name, progress):
    """下載一個模型，progress(0 至 1, 狀態字)。Ollama 一段段答（每行一個 JSON），邊收邊報進度。"""
    request = urllib.request.Request(OLLAMA_HOST + "/api/pull", data=json.dumps({"model": name}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    # 一個模型幾 GB：唔好設太短嘅 timeout，呢個係「幾耐冇新資料」嘅上限，唔係成個下載
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            if not line.strip():
                continue
            step = json.loads(line)
            if "error" in step:
                raise OSError(step["error"])
            if step.get("total"):
                progress(step.get("completed", 0) / step["total"], step.get("status", ""))
            else:
                progress(None, step.get("status", ""))


def create_fixed_small():
    """用官方範本整 FIXED_SMALL（用返 SMALL_SOURCE 個模型檔，唔使再下載）。"""
    post("/api/create", {"model": FIXED_SMALL, "from": SMALL_SOURCE, "template": SMALL_TEMPLATE,
                         "parameters": {"stop": SMALL_STOP}, "stream": False}, timeout=120)


class Signals(QObject):
    """下載喺背景線做，唔可以直接郁畫面，用 signal 交返主線。"""
    progress = pyqtSignal(object, str)      # 0 至 1（或者 None＝唔知）, 狀態字
    finished = pyqtSignal(str)              # 空字串＝成功，否則係錯誤


class SetupDialog(ThemedWindow):
    """第一次開機設定。on_done(讀字模型, 翻譯模型)：轉好模型之後叫，主程式用嚟通知譯鏡、熱身。"""

    def __init__(self, on_done=None):
        super().__init__(tr("巴別塔之窗：第一次設定"), 640, 600)
        self.on_done = on_done
        self.ollama = BodyLabel()
        self.ollama.setWordWrap(True)
        self.ollama_button = PushButton()
        self.ollama_button.clicked.connect(self._ollama_action)
        top = QHBoxLayout()
        top.addWidget(self.ollama, 1)
        top.addWidget(self.ollama_button)
        self.gpu = BodyLabel()
        self.eraser = CaptionLabel()
        self.eraser.setWordWrap(True)
        self.tiers = QButtonGroup(self)
        self.tier_buttons = {}
        self.tier_notes = {}
        tier_box = SimpleCardWidget()
        tier_column = QVBoxLayout(tier_box)
        tier_column.setContentsMargins(16, 12, 16, 12)
        tier_column.setSpacing(10)
        for name in TIERS:
            button = RadioButton()
            button.toggled.connect(self._update_button)
            self.tiers.addButton(button)
            self.tier_buttons[name] = button
            tier_column.addWidget(button)
            # 說明另外一行：Fluent 單選掣得一行高，寫埋入去第二行會俾切走
            self.tier_notes[name] = CaptionLabel(tr(TIERS[name]["說明"]))
            self.tier_notes[name].setContentsMargins(30, 0, 0, 4)
            tier_column.addWidget(self.tier_notes[name])
        self.bar = ProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.busy_bar = IndeterminateProgressBar()      # 唔知幾耐嘅步驟用跑馬燈（Fluent 進度條要分開兩個元件）
        self.busy_bar.hide()
        self.status = BodyLabel()
        self.status.setWordWrap(True)
        self.go = PrimaryPushButton(tr("下載並使用"))
        self.go.clicked.connect(self._start)
        later = PushButton(tr("遲啲先"))
        later.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(later)
        buttons.addWidget(self.go)
        self.body.addLayout(top)
        self.body.addWidget(self.gpu)
        self.body.addWidget(StrongBodyLabel(tr("揀一檔（VRAM 已經計埋搵字、補圖模型）")))
        self.body.addWidget(tier_box)
        self.body.addWidget(self.eraser)
        self.body.addStretch()
        self.body.addWidget(self.bar)
        self.body.addWidget(self.busy_bar)
        self.body.addWidget(self.status)
        self.body.addLayout(buttons)
        self.signals = Signals()
        self.signals.progress.connect(self._progress)
        self.signals.finished.connect(self._finished)
        self.busy = False
        self.models = None

    def open(self):
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self):
        """重新檢查 Ollama、顯示卡、每檔仲要下載幾多。"""
        alive = ollama_alive()
        self.models = installed() if alive else None
        if alive:
            self.ollama.setText(tr("✅ Ollama 開咗（負責行讀字、翻譯模型）"))
            self.ollama_button.setText(tr("重新檢查"))
        elif OLLAMA_APP.exists():
            self.ollama.setText(tr("⚠️ Ollama 裝咗但未開"))
            self.ollama_button.setText(tr("開 Ollama"))
        else:
            self.ollama.setText(tr("⚠️ 未裝 Ollama：巴別塔之窗要靠佢喺你部電腦行模型（免費）。裝完再撳「重新檢查」"))
            self.ollama_button.setText(tr("去官方網站下載"))
        name, vram = gpu_vram()
        self.gpu.setText(tr("顯示卡：{name}，{vram} GB VRAM", name=name, vram=vram) if name else tr("顯示卡：讀唔到幾多 VRAM，自己揀一檔"))
        best = recommend(vram)
        reading, translation = current()
        done = load_settings().get("已完成設定")
        for tier_name, tier in TIERS.items():
            need = to_download(tier_name, self.models) if alive else None
            if need is None:
                size = tr("（要先開 Ollama 先知要下載幾多）")
            elif need:
                size = tr("｜要下載約 {v1:.1f} GB", v1=sum(DOWNLOAD_GB.get(m, 0) for m in need))
            else:
                size = tr("｜✅ 已經有齊")
            tag = tr("（建議）") if tier_name == best else ""
            using = tr("（而家用緊）") if done and same_model(reading, tier["讀字"]) and same_model(translation, tier["翻譯"]) else ""
            self.tier_buttons[tier_name].setText(tr("{tier_name}{tag}{using}：約 {v4} GB VRAM{size}", tier_name=tr(tier_name), tag=tag, using=using, v4=tier['VRAM'], size=size))
        # 剔住而家用緊嘅檔；未揀過先剔建議嗰檔。試過下載完剔返建議嘅「高」，
        # 用家再撳一下掣就由「中」轉返「高」，以為下載咗冇用
        # 未完成過設定：「而家用緊」只係程式預設（高），細卡用家唔應該見到佢剔咗
        in_use = next((name for name, tier in TIERS.items()
                       if same_model(reading, tier["讀字"]) and same_model(translation, tier["翻譯"])), None)
        self.tier_buttons[(in_use if done else None) or best].setChecked(True)
        missing = eraser_missing()
        if not missing:
            self.eraser.setText("")
        elif RELEASE_BASE:
            mb = sum(entry[3] for entry in missing) / 2 ** 20
            self.eraser.setText(tr("仲要下載搵字、補圖模型（約 {mb:.0f} MB，撳下載會一齊落）：冇佢哋都照用得，但淨係用色塊蓋原文，唔會抹走原文再補返背景", mb=mb))
        else:
            self.eraser.setText(tr("⚠️ 搵字、補圖模型檔唔見咗（models\\ctd、models\\lama），作者未放上網：照用得，但淨係用色塊蓋原文"))
        self._update_button()

    def _chosen(self):
        return next(name for name, button in self.tier_buttons.items() if button.isChecked())

    def _update_button(self):
        if self.busy:
            return
        ready = self.models is not None
        need = to_download(self._chosen(), self.models) if ready else []
        self.go.setEnabled(ready)
        self.go.setText(tr("下載並使用") if need or (RELEASE_BASE and eraser_missing()) else tr("使用呢檔"))

    def _ollama_action(self):
        if ollama_alive():
            self.refresh()
        elif OLLAMA_APP.exists():
            self.status.setText(tr("⏳ 開緊 Ollama……"))
            QApplication.processEvents()
            ensure_ollama(self.status.setText)
            self.refresh()
        elif self.ollama_button.text() == tr("去官方網站下載"):
            webbrowser.open(OLLAMA_DOWNLOAD)
            # 開咗網頁，用家裝緊；粒掣轉做檢查，唔係再撳只會再開多次網頁
            self.ollama_button.setText(tr("裝好咗，重新檢查"))
        else:
            self.refresh()      # 仲未裝好的話，refresh 會將粒掣變返「去官方網站下載」

    def _start(self):
        tier = self._chosen()
        need = to_download(tier, self.models)
        self.busy = True
        self.go.setEnabled(False)
        for button in self.tier_buttons.values():
            button.setEnabled(False)
        files = eraser_missing() if RELEASE_BASE else []
        self.bar.setVisible(bool(need or files))
        threading.Thread(target=self._work, args=(tier, need, files), daemon=True).start()

    def _work(self, tier, need, files):
        """背景線：逐個下載（Ollama 模型、搵字補圖模型），1.8B 下載完整修好範本版，最後轉模型。"""
        try:
            total = len(need) + len(files)
            for i, name in enumerate(need):
                label = tr("下載 {name}（{v2}/{total}）", name=name, v2=i + 1, total=total)
                pull(name, lambda part, text, label=label: self.signals.progress.emit(part, f"{label}：{text}"))
            for i, (path, file_name, sha256, size) in enumerate(files, start=len(need) + 1):
                label = tr("下載 {file_name}（{i}/{total}）", file_name=file_name, i=i, total=total)
                download_file(RELEASE_BASE + file_name, path, sha256, size,
                              lambda part, text, label=label: self.signals.progress.emit(part, f"{label}：{text}"))
            if not is_installed(FIXED_SMALL, installed()) and FIXED_SMALL in (TIERS[tier]["讀字"], TIERS[tier]["翻譯"]):
                self.signals.progress.emit(None, tr("整緊 Hy-MT2 1.8B 修好範本嘅版本……"))
                create_fixed_small()
            self.tier_done = tier
            self.signals.finished.emit("")
        except (OSError, ValueError) as error:
            self.signals.finished.emit(str(error))

    def _progress(self, part, text):
        self.bar.setVisible(part is not None)
        self.busy_bar.setVisible(part is None)      # 唔知幾耐：跑馬燈
        if part is not None:
            self.bar.setValue(int(part * 1000))
        self.status.setText(f"⏳ {text}")

    def _finished(self, error):
        self.busy = False
        self.bar.hide()
        self.busy_bar.hide()
        for button in self.tier_buttons.values():
            button.setEnabled(True)
        if error:
            self.status.setText(tr("⚠️ 出錯：{error}。檢查吓網絡同硬碟位，再撳一次「下載並使用」會由斷咗嘅位繼續", error=error))
            self.refresh()
            return
        tier = TIERS[self.tier_done]
        apply(tier["讀字"], tier["翻譯"])
        save_setting("已完成設定", True)
        self.status.setText(tr("✅ 用緊「{v1}」檔。可以閂呢個視窗，撳 🔍 讀字", v1=self.tier_done))
        if self.on_done:
            self.on_done(tier["讀字"], tier["翻譯"])
        self.refresh()


def needs_setup():
    """開程式要唔要彈設定：未裝或者未開 Ollama、揀咗嘅模型唔齊，或者冇搵字、補圖模型檔。

    搵字補圖都要查：重裝程式但 Ollama 模型仲喺度嘅人，唔查就靜靜雞用色塊蓋字，唔知缺咗嘢。"""
    if not ollama_alive() or eraser_missing():
        return True
    models = installed()
    return not all(is_installed(name, models) for name in current())
