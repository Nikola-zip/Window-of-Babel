# 巴別塔之窗 Window of Babel：主程式
#
# 做咩：浮喺螢幕上面嘅翻譯窗。擺喺任何畫面上，撳讀字（或者開自動模式），入面嘅字會喺原位譯成你揀嘅語言。
#   由譯幕（yimu）嘅主程式 p3_2_live_bar.py 改：淨留譯鏡、工作列圖示、設定視窗、熱鍵、歷史同改譯文，
#   拎走字幕條同聽聲（Whisper），所以唔使裝 faster-whisper、torch 同 NVIDIA 嗰堆套件。
# 點用：.venv\Scripts\python -W ignore main.py

import signal
import sys
import threading
from collections import deque

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from p2_1_translate import check_ollama, current_model, unload_model, warm_up
from p2_3_glossary import GLOSSARY, load_glossary
from ui_parts import HoldButton, make_icon
from p3_3_hotkeys import GlobalHotkeys, load_hotkeys, while_held
from p3_4_history import HistoryPanel, SubtitleLog
from p4_4_context import HKTranslator
from p4_6_launch import (LEVEL_COLORS, clean_old_logs, ensure_ollama, keep_days, level_of, load_settings,
                         quiet_console, save_setting, single_instance)
from p6_2_read import vision_model
from p6_3_lens import Lens
from p7_1_target import current, target_menu
from p8_5_names import memory, works_menu
from p8_7_settings import SettingsDialog
from p9_1_correct import CorrectionDialog
from p10_2_setup import SetupDialog, needs_setup

APP_NAME = "巴別塔之窗"


class Bridge(QObject):
    """背景線（開 Ollama、熱身）唔可以直接郁畫面，用 signal 交返主線。"""
    status = pyqtSignal(str)
    need_setup = pyqtSignal()       # 冇 Ollama 或者揀咗嘅模型唔齊：主線彈第一次開機設定


def start_models(bridge):
    """喺背景線開 Ollama、熱身翻譯模型：要成分鐘都得，唔好卡住畫面。讀字模型第一次讀字先載。"""
    if not ensure_ollama(bridge.status.emit) or needs_setup():
        # 唔好照熱身：模型唔喺度，熱身只會報錯；彈設定俾用家揀檔下載
        bridge.need_setup.emit()
        return
    try:
        print(f"Ollama 版本：{check_ollama()}")
        bridge.status.emit("⏳ 載入翻譯模型……")
        print(f"載入翻譯模型：{warm_up():.1f} 秒")
        bridge.status.emit("")
    except (RuntimeError, OSError) as error:
        print(f"翻譯模型載入唔到：{error}")
        bridge.status.emit("⚠️ 翻譯模型載入唔到（Ollama 有冇開？）")


def main():
    run_log = quiet_console()  # noqa: F841 —— 用捷徑開（冇 terminal）就將輸出寫入 logs\run
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)     # 閂設定、歷史視窗唔好成個程式收工，靠工作列「閂」
    lock = single_instance()   # noqa: F841 —— 要留住，閂程式先放手
    if lock is None:
        QMessageBox.information(None, APP_NAME, f"{APP_NAME}已經開咗：喺工作列右下角（可能喺「^」入面）搵佢個圖示。")
        return
    days = keep_days()
    deleted = clean_old_logs(days)
    if deleted:
        print(f"刪咗 {deleted} 個超過 {days} 日嘅舊紀錄")
    glossary = load_glossary(GLOSSARY) if GLOSSARY.exists() else []
    print(f"詞庫：{len(glossary)} 個詞")

    # Ctrl+C 都要行埋「閂之前要做嘅嘢」（清走模型），所以唔即刻殺，叫 Qt 正常收工。
    # Qt 事件迴圈入面 Python 冇機會處理訊號，用計時器每 0.2 秒叫醒佢一次
    signal.signal(signal.SIGINT, lambda *_: qt.quit())
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(200)

    log = SubtitleLog()
    correction = CorrectionDialog()     # 歷史面板每句「改」
    panel = HistoryPanel(log, on_fix=correction.open)
    lens = Lens(HKTranslator(glossary, names=memory()),
                on_translated=lambda lang, original, translation: log.add("窗", lang, original, translation))

    tray = QSystemTrayIcon(make_icon(), qt)
    tray.setToolTip(APP_NAME)
    tray_menu = QMenu()
    lens_menu = QMenu()
    lens_toggle = QAction("收埋窗", tray_menu)

    def set_lens_visible(on):
        if not on:
            lens.clear()
        lens.setVisible(on)
        lens_toggle.setText("收埋窗" if on else "顯示窗")
        save_setting("譯鏡顯示", on)    # 下次開機照返

    def lens_read():
        if not lens.isVisible():
            set_lens_visible(True)
        lens.read()

    def lens_adjust():
        if not lens.isVisible():
            set_lens_visible(True)
        lens.toggle_adjusting()

    def lens_auto():
        if not lens.auto and not lens.isVisible():
            set_lens_visible(True)      # 開自動模式即係想用個窗
        lens.toggle_auto()

    def reset_context():
        # 換咗場景（另一個遊戲、另一部漫畫）：上一段嘅上下文會誤導翻譯
        lens.worker.translator.reset()
        lens._flash("🧹 清咗翻譯上下文")

    lens_toggle.triggered.connect(lambda: set_lens_visible(not lens.isVisible()))

    # ---------- 熱鍵 ----------
    names = load_hotkeys()
    keys = GlobalHotkeys(qt)
    for name, action in (("歷史", panel.toggle), ("清空上下文", reset_context), ("譯鏡調整", lens_adjust),
                         ("譯鏡讀字", lens_read), ("譯鏡自動", lens_auto)):
        def logged(name=name, action=action):
            # 印出嚟方便查：撳咗冇反應，即刻知係熱鍵冇到，定係功能本身有問題
            print(f"撳咗 {keys.texts[name]}（{name}）")
            action()
        problem = keys.bind(name, names[name], logged)
        print(f"熱鍵 {names[name]}（{name}）：{'OK' if problem is None else '登記唔到：' + problem}")
    # 按住型熱鍵要用 keys 問最新組合（設定「熱鍵」頁改咗都跟到）
    problem = keys.bind("譯鏡原文", names["譯鏡原文"], while_held(keys, "譯鏡原文", lens.hold_original))
    print(f"熱鍵 {names['譯鏡原文']}（譯鏡原文）：{'OK' if problem is None else '登記唔到：' + problem}")

    # ---------- 譯做邊種語言、作品（人名記憶）----------
    def target_changed(target):
        lens.target_changed(target)
        print(f"譯做：{target.key}")

    def work_changed(work):
        lens.work_changed(work)
        print(f"作品：{work}")

    targets = target_menu(target_changed)
    works = works_menu(work_changed)

    # ---------- 設定視窗：選單照留，兩邊改嘅係同一個設定 ----------
    def set_history_size(size):
        log.recent = deque(log.recent, maxlen=size)     # 舊句照留（最新嗰啲），面板重畫
        for listener in log.listeners:
            listener(None)

    def models_changed(reading, translation):
        lens.models_changed(reading, translation)
        if lens.worker.eraser is None:
            # 開程式時冇搵字補圖模型（用緊色塊）：設定啱啱下載咗就即刻用，唔使重開
            from p6_5_inpaint import TextEraser
            eraser = TextEraser()
            lens.worker.eraser = eraser if eraser.available() else None
        print(f"模型：讀字 {reading}｜翻譯 {translation}")
        # 背景熱身新翻譯模型：唔熱身嘅話，轉完第一句要等搬模型入 VRAM 先譯到
        threading.Thread(target=warm_up, daemon=True).start()

    setup = SetupDialog(on_done=models_changed)     # 第一次開機設定：要留住參照

    hooks = {"target_changed": target_changed, "work_changed": work_changed, "models_changed": models_changed,
             "set_lens_visible": set_lens_visible, "lens_visible": lens.isVisible,
             "set_history_size": set_history_size, "glossary": GLOSSARY,
             "open_setup": setup.open,      # 設定「模型」頁嘅「下載模型…」
             "hotkeys": keys}       # 熱鍵頁：改綁即刻生效（GlobalHotkeys.rebind）
    settings_window = {}

    def open_settings(page="窗"):
        # 第一次撳先開；要留住參照，唔係 Python 回收咗個視窗就即刻消失
        if "dialog" not in settings_window:
            settings_window["dialog"] = SettingsDialog(lens, hooks)
        settings_window["dialog"].open(page)

    def add(menu, text, action):
        item = QAction(text, menu)
        item.triggered.connect(action)
        menu.addAction(item)
        return item

    # ---------- 工作列選單（右撳圖示）----------
    add(tray_menu, f"讀字翻譯（{names['譯鏡讀字']}）", lens_read)
    tray_menu.addAction(lens_toggle)
    tray_menu.addMenu(targets)
    tray_menu.addMenu(works)
    add(tray_menu, f"歷史（{names['歷史']}）", panel.toggle)
    tray_menu.addSeparator()
    add(tray_menu, "設定…", open_settings)
    add(tray_menu, f"閂{APP_NAME}", qt.quit)
    tray.setContextMenu(tray_menu)
    # 撳一下圖示：顯示／收埋個窗（右撳先出選單）
    tray.activated.connect(lambda reason: set_lens_visible(not lens.isVisible())
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    # ---------- 窗嘅 ⚙ 選單 ----------
    add(lens_menu, "讀字翻譯", lens_read)
    add(lens_menu, "收起譯文", lens.clear)
    add(lens_menu, "存截圖", lens.save_shot)
    lens_menu.addAction(lens.auto_action(lens_menu))
    lens_menu.addMenu(targets)      # 同工作列係同一個選單
    lens_menu.addMenu(works)
    lens_menu.addSeparator()
    add(lens_menu, "設定…", open_settings)
    add(lens_menu, "收埋窗", lambda: set_lens_visible(False))
    lens.add_toolbar(extra=[("🔍", f"讀字翻譯（{names['譯鏡讀字']}）", lens_read),
                            HoldButton("👁", f"按住睇原文（{names['譯鏡原文']}），放手變返譯文", lens.hold_original),
                            ("📷", "存蓋咗字嘅截圖（順手複製）", lens.save_shot)], menu=lens_menu)
    # 要留住參照，唔係 Python 回收咗，選單會無聲無息冇咗
    lens.menu, tray.menus = lens_menu, (tray_menu, targets, works)
    # 呢個程式就係個窗：第一次開預設顯示（譯幕預設收埋，因為字幕條先係主角）
    set_lens_visible(bool(load_settings().get("譯鏡顯示", True)))

    def on_quit():
        # 閂程式即刻清走兩個模型，唔使等 Ollama 自己過咗時間先卸，即刻還返 VRAM
        print("清走翻譯模型：" + ("OK" if unload_model() else "Ollama 冇開，唔使清"))
        print("清走讀字模型：" + ("OK" if unload_model(vision_model()) else "Ollama 冇開，唔使清"))

    qt.aboutToQuit.connect(on_quit)
    print(f"譯做：{current().key}｜作品：{memory().work}（名單 {memory().path}）")
    print(f"模型：讀字 {vision_model()}｜翻譯 {current_model()}")

    bridge = Bridge()

    def show_status(text):
        lens._flash(text, 4) if text else lens._set_status("")
        # 圖示頂個對白框就係狀態燈：等緊變灰、出錯變紅，收埋個窗都一眼知道
        tray.setIcon(make_icon(LEVEL_COLORS[level_of(text)]))

    bridge.status.connect(show_status)
    bridge.need_setup.connect(setup.open)
    tray.showMessage(APP_NAME, f"開咗：撳 {names['譯鏡讀字']} 或者 🔍 讀字翻譯；右撳工具列圖示有選單",
                     QSystemTrayIcon.MessageIcon.Information, 5000)
    # daemon：畫面一閂，背景線跟住收工
    threading.Thread(target=start_models, args=(bridge,), daemon=True).start()
    qt.exec()


if __name__ == "__main__":
    main()
