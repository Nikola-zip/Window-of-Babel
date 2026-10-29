# 譯幕 第6期第3步：譯鏡翻譯同蓋字
#
# 做咩：撳 Ctrl+Alt+T（或者 🔍），讀玻璃底下嘅字（第 2 關），逐個對白框交俾翻譯
#       （HKTranslator：上下文、詞庫、香港用字、簡轉繁），喺原位用底色塊蓋住原文再寫譯文；
#       又高又窄嘅日文對白框用直排寫。玻璃底下畫面變咗（例如捲咗頁）就自動收起譯文。
# 點用：先開 Ollama，再喺終端機打：.venv\Scripts\python -W ignore p6_3_lens.py
#       Ctrl+Alt+G 調整塊鏡，Ctrl+Alt+T 讀字翻譯；main.py 會 import 呢度嘅 Lens。

import argparse
import functools
import os
import re
import signal
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from p2_1_translate import ask, warm_up
from p2_3_glossary import GLOSSARY, load_glossary
from p3_1_subtitle_bar import CHINESE_FONTS, make_font, make_icon
from p3_3_hotkeys import GlobalHotkeys, load_hotkeys
from p4_4_context import HKTranslator, hk_characters
from p4_6_launch import load_settings, save_setting
from p6_1_glass import GLASS_COLOR, Glass
from p6_2_read import clean_text, grab, read_crop, read_marked, read_text, to_png
from p6_4_auto import EMPTY, ReadingCache, TranslationCache, fingerprint
from p7_1_target import current, sound_prompt, target_menu
from p8_5_names import memory, works_menu
from p8_6_fonts import chosen, font_menu, has_bold, supports
from p6_5_inpaint import (estimate_chars, keep_lines, TEXT_PROB, TextEraser, hole_for, intersection, overlaps, owned_boxes, page_shift, pair_leftovers,
                          text_box_of, to_array, to_image)

WATCH_EVERY = 500       # 每幾多毫秒睇一次玻璃底下有冇變
# 第 7 期第 2 關：存「蓋咗字」嘅圖。塊鏡設咗唔俾截圖（WDA_EXCLUDEFROMCAPTURE），普通截圖影唔到譯文，要自己砌
SHOT_DIR = Path(__file__).resolve().parent / "譯鏡截圖"
# 自動模式：畫面停定先讀，捲緊條漫唔好讀半頁。前後兩次縮圖差唔多過 STILL，連續 STILL_TICKS 次（約 1 秒）先當停定
STILL = 2
STILL_TICKS = 2
CHANGED = 12            # 縮細嘅灰階圖平均差咗咁多（0 至 255）就當畫面變咗，例如捲咗頁
THUMB = 48              # 比較用嘅縮圖大細：細先快，又唔會因為片入面少少郁動就當變咗
INSET = 0.06            # 譯文離框邊最少留幾多（框嘅比例），唔好頂住對白框外圈
COVER_ROUND = 0.25      # 色塊圓角半徑（短邊嘅比例）：貼返圓形、橢圓對白框嘅形狀
TEXT_GROW = 0.5         # 譯文範圍：0 = 原文筆劃範圍，1 = 成個框；取中間
INK_DISTANCE = 90       # 同底色差咁多（RGB 距離）就當係原文嘅筆劃
# 搵對白框形狀時，喺模型個框外面再睇幾多（框嘅比例）：個框成日淨係包住啲字，對白框大好多；
# 漏咗出範圍邊就順住試大啲（真實漫畫測過，30% 好多時包唔晒）
BUBBLE_MARGINS = (0.3, 0.8, 1.5)
BUBBLE_GRID = 200       # 搵形狀用嘅格數（長邊）：夠細先快，對白框形狀又夠準
MIN_TEXT_SPACE = 0.35   # 對白框入面最大長方形最少要佔框嘅幾多，先信個形狀
GUTTER_CUT = 0.3        # 漏咗出範圍時，第二次開運算用字框短邊嘅幾多（格數）
OPEN_CELLS = 2          # 開運算切斷幾多格闊嘅漏口
# 對白框最多大過個框幾多倍：再大多數係漏咗入畫。個框而家多數係搵字模型嘅準確字範圍（好貼），
# 對白框成日係佢嘅 3 至 10 倍，試過 6 倍將假頁個橢圓對白框擋咗
BUBBLE_MAX = 12
# 對白框最少要有模型個框幾大：試過字入面一粒 8 × 7 像素嘅白點都當咗係對白框，塗白色蓋唔到啲字
BUBBLE_MIN = 0.4
MIN_INK = 0.03          # 對白框入面最少要有幾多係字（填返嘅窿）：冇字嘅白色位唔係呢段字嘅框
SAME_BUBBLE_IOU = 0.6   # 兩段字搵到嘅對白框重疊咁多，就當同一個框，合埋譯
UNIFORM_STD = 12        # 對白框入面顏色變化（標準差）大過咁多，就當係畫唔係對白框
# 同底色差唔多過咁多就當係對白框入面嘅背景；試過 60 會將網點灰（同白色差 59）都當背景，漏咗出框
BACKGROUND_DISTANCE = 35
EDGE_IGNORE = 0.06      # 框邊呢個比例以內嘅筆劃唔計：通常係對白框外圈
# 冇對白框嘅字（第 5 關抹字補圖）
FEATHER = 1.5           # 補好嘅圖貼返上去，邊位柔化幾多像素：硬邊會見到一圈接口
TEXT_ROOM = 0.1         # 譯文範圍喺原文四邊再擴幾多（比例）：原文範圍好貼，譯文字會太細
LOOSE_OVERLAP = 0.15    # 框外嘅段同對白字框重疊多過自己面積嘅咁多就唔譯（多數係位置估錯）
OUTLINE = 0.16          # 描邊粗幼（字大細嘅比例）：字寫喺畫上面，冇描邊喺花紋上面睇唔清
# 冇對白框嘅譯文最大幾多倍原文字咁大：試過讀字模型個框包住成格畫，譯文用大字寫滿，遮晒個人塊面
ORIGINAL_SCALE = 1.2
# 對白框入面都要有上限：試過大對白框、譯文字少，字放到成格咁大（2026-10-27 用戶截圖）；框入面唔怕遮畫，鬆少少
BUBBLE_SCALE = 1.3
# 用戶調譯文字大細（settings.json「譯鏡字大細」，百分比）：調大放寬上面兩個上限（最多塞滿個框），調細就成比例縮
TEXT_SIZE_RANGE = (60, 150)
_text_size = None


def text_size():
    """而家嘅譯文字大細（1.0 = 100%）；第一次先讀設定，之後記住，唔好每次畫都讀檔。"""
    global _text_size
    if _text_size is None:
        _text_size = int(load_settings().get("譯鏡字大細", 100))
    return _text_size / 100


def set_text_size(percent):
    global _text_size
    _text_size = int(min(max(percent, TEXT_SIZE_RANGE[0]), TEXT_SIZE_RANGE[1]))
    save_setting("譯鏡字大細", _text_size)


def scaled_layout(space, text, lang, direction=None, cap=None):
    """跟「譯鏡字大細」排字：調大＝上限放大（best_layout 本身唔會出框）；調細＝塞得落嘅大細再縮。"""
    scale = text_size()
    if scale >= 1:
        return best_layout(space, text, lang, direction, cap * scale if cap else None)
    px, placed = best_layout(space, text, lang, direction, cap)
    if not placed:
        return px, placed
    return best_layout(space, text, lang, direction, px * scale)
SPLIT_AT = set("，。、！？：；…,.!?:;")     # 譯文分落幾嚿字嗰陣，盡量喺呢啲標點後面切
# 擬聲字用 Hy-MT2 官方「背景信息」寫法提示：冇提示時當咗人名音譯（メキョ→梅喬、バッ→袋子、ニコッ→尼可），
# 加咗之後譯做「啪嘰」「砰！」「咧嘴一笑」。提示同例子跟「譯做」語言（p7_1_target.sound_prompt）
# 搵到嘅對白框要包住呢段字幾多筆劃先信佢：試過淺色背景當咗對白框，讀字模型個框又淨係包住上半截，
# 塗白色淨係塗到上半截，下半截原文露咗出嚟
TEXT_INSIDE = 0.9
# 為咗唔好最後一行得一隻字，字最多細幾多（比例）。試過 1248 次排字（橢圓同長方形框、5 至 30 隻字）：
# 唔處理有 503 次（四成）；最多細 10% 剩 167 次、20% 剩 98 次（平均細 2%，最多細 22%）、30% 剩 43 次
ORPHAN_SHRINK = 0.2
# 讀到嘅字少過筆劃估計嘅咁多就當讀漏咗。試過 0.85：漏咗一行半（30 隻得 24 隻）嗰次估計 28，0.857 啱啱冇捉到
COMPLETE = 0.9
SAME_WORDS = 0.8        # 兩段字用嘅字重疊咁多（細嗰段計）就當同一句
SOUND_KANA = 5          # 冇對白框、淨係假名、咁多隻字或以下：閂咗擬聲字就當擬聲字
COMPLETE_MIN = 8        # 估計少過咁多隻字嘅短框唔檢查（試過「どうする：」5 對 6 都重讀，嘥時間）
STROKE_GROW = 2         # 用對白框形狀時，原文筆劃再擴幾多像素塗底色（包埋字邊淡淡哋嗰圈）
INSIDE_SLACK = 2        # 檢查上面嗰樣時，對白框放寬幾多格（BUBBLE_GRID 嘅格）
# 直排要用直排專用嘅標點，唔係「，。」會擺喺錯位、「（）」會打橫
VERTICAL_FORMS = str.maketrans({
    "，": "︐", "、": "︑", "。": "︒", "！": "︕", "？": "︖", "…": "︙", "—": "︱", "ー": "丨",
    "（": "︵", "）": "︶", "「": "﹁", "」": "﹂", "『": "﹃", "』": "﹄", "～": "丨",
})


def thumbnail(image):
    """縮做細細嘅灰階圖，用嚟比較畫面有冇變。"""
    return image.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        THUMB, THUMB, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def difference(a, b):
    """兩張縮圖平均每粒差幾多（0 至 255）。"""
    total = sum(abs(a.pixelColor(x, y).value() - b.pixelColor(x, y).value())
                for y in range(THUMB) for x in range(THUMB))
    return total / (THUMB * THUMB)


def background_color(image, box):
    """對白框嘅底色：喺框入面平均撒 20 × 20 個點，每隻顏色取中位數。

    字筆劃只佔框入面一小部分，中位數會係背景（白色對白框就係白色），唔會被黑字拉暗。
    """
    x1, y1, x2, y2 = box
    w, h = image.width(), image.height()
    samples = [image.pixelColor(min(w - 1, int((x1 + (x2 - x1) * (i + 0.5) / 20) * w)),
                                min(h - 1, int((y1 + (y2 - y1) * (j + 0.5) / 20) * h)))
               for i in range(20) for j in range(20)]
    return QColor(*(int(statistics.median(getattr(c, part)() for c in samples)) for part in ("red", "green", "blue")))


def text_color(fill):
    """底色光就用黑字，暗就用白字。"""
    light = 0.299 * fill.red() + 0.587 * fill.green() + 0.114 * fill.blue()
    return QColor("black") if light > 140 else QColor("white")


def ink_box(image, box, fill):
    """原文筆劃實際佔嘅範圍（0 至 1 比例）：色塊淨係蓋呢度，唔好蓋走對白框嘅外圈。

    模型畫嘅框成日連對白框外圈都包埋；成個框蓋落去，白色方塊會剪走對白框嘅黑邊。
    """
    x1, y1, x2, y2 = box
    w, h = image.width(), image.height()
    steps = 64
    found = []
    for i in range(steps):
        for j in range(steps):
            u, v = (i + 0.5) / steps, (j + 0.5) / steps
            if min(u, v, 1 - u, 1 - v) < EDGE_IGNORE:
                continue
            c = image.pixelColor(min(w - 1, int((x1 + (x2 - x1) * u) * w)), min(h - 1, int((y1 + (y2 - y1) * v) * h)))
            distance = ((c.red() - fill.red()) ** 2 + (c.green() - fill.green()) ** 2
                        + (c.blue() - fill.blue()) ** 2) ** 0.5
            if distance > INK_DISTANCE:
                found.append((u, v))
    if not found:
        return box
    pad = 2 / steps     # 多蓋兩格，筆劃邊緣淡淡哋嗰圈都蓋埋
    us, vs = [u for u, _ in found], [v for _, v in found]
    lo_u, hi_u = max(0.0, min(us) - pad), min(1.0, max(us) + pad)
    lo_v, hi_v = max(0.0, min(vs) - pad), min(1.0, max(vs) + pad)
    return (x1 + (x2 - x1) * lo_u, y1 + (y2 - y1) * lo_v, x1 + (x2 - x1) * hi_u, y1 + (y2 - y1) * hi_v)


def largest_rectangle(mask):
    """mask（True = 可以寫字）入面最大嘅長方形：回傳（左, 上, 右, 下）格數，冇就 None。

    經典「直方圖」做法：逐行計每格上面連續有幾多格得，再用 stack 搵最大面積，成張圖行一次就得。
    """
    rows, cols = mask.shape
    heights = np.zeros(cols, dtype=int)
    best, best_rect = 0, None
    for y in range(rows):
        heights = np.where(mask[y], heights + 1, 0)
        stack = []
        for x in range(cols + 1):
            h = heights[x] if x < cols else 0
            start = x
            while stack and stack[-1][1] >= h:
                start, top = stack.pop()
                area = top * (x - start)
                if area > best:
                    best, best_rect = area, (start, y - top + 1, x, y + 1)
            stack.append((start, h))
    return best_rect


def bubble_shape(image, box, fill, cover, why=None, others=()):
    """搵對白框真正嘅形狀；漏咗出範圍邊就逐步擴大範圍再試（模型個框成日淨係包住啲字，對白框大好多）。

    回傳（形狀遮罩 QImage, 遮罩對應嘅範圍, 寫字長方形）嘅 dict，搵唔到就 None。why 係 list 就加入失敗原因。
    others：其他段字嘅框（0 至 1 比例）。佢哋喺同一嚿白色入面（黐埋嘅對白框），就將白色分開，各自攞近自己嗰份。
    """
    # 底色唔係白色都試埋白色：模型個框偏咗嘅話，取到嘅「底色」可能係隔籬幅畫嘅灰色；
    # 漫畫對白框差唔多全部係白色，搵到白色框就用佢
    fills = [fill]
    if np.linalg.norm(255 - np.array([fill.red(), fill.green(), fill.blue()])) > 40:
        fills.insert(0, QColor("white"))
    all_reasons = []
    for colour in fills:
        for margin in BUBBLE_MARGINS:
            reasons = []
            shape = _bubble_shape(image, box, colour, cover, margin, reasons, others)
            if shape is not None:
                shape["fill"] = colour
                return shape
            if not any(reason.startswith("漏") for reason in reasons):
                break       # 冇一嚿係因為「漏咗」唔要：擴大範圍都冇用
        all_reasons += [f"{colour.name()}：{reason}" for reason in reasons] if len(fills) > 1 else reasons
    if why is not None:
        why.extend(all_reasons)
    return None


def _bubble_shape(image, box, fill, cover, margin, why=None, others=()):
    """喺模型個框四邊擴 margin 嘅範圍入面搵對白框：逐嚿同底色一樣嘅白色位獨立檢查，
    揀「封閉、大細合理、入面真係有字」嘅嗰嚿（同模型個框重疊得最多嘅排先）。

    唔將框入面所有白色位撈埋：模型個框間中偏咗成百幾像素，掂到隔籬白色嘅畫，撈埋就漏晒；
    逐嚿揀，個框偏咗都搵返真正嗰個對白框，譯文寫返喺框正中。
    """
    def fail(reason):
        if why is not None:
            why.append(reason)
        return None

    x1, y1, x2, y2 = box
    # 四邊擴一樣多（按長邊計）：一行字嘅框好矮，按高度擴，上下包唔到成個對白框
    mx = my = max((x2 - x1) * image.width(), (y2 - y1) * image.height()) * margin
    mx, my = mx / image.width(), my / image.height()
    area = (max(0.0, x1 - mx), max(0.0, y1 - my), min(1.0, x2 + mx), min(1.0, y2 + my))
    W, H = image.width(), image.height()
    crop = image.copy(int(area[0] * W), int(area[1] * H),
                      max(1, int((area[2] - area[0]) * W)), max(1, int((area[3] - area[1]) * H)))
    crop = crop.scaled(BUBBLE_GRID, BUBBLE_GRID, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    pixels = to_array(crop).astype(int)
    rows, cols = pixels.shape[:2]
    target = np.array([fill.red(), fill.green(), fill.blue()])
    background = np.sqrt(((pixels - target) ** 2).sum(axis=2)) < BACKGROUND_DISTANCE

    def to_cell(u, v):
        return (int((u - area[0]) / (area[2] - area[0]) * cols), int((v - area[1]) / (area[3] - area[1]) * rows))
    bx1, by1 = to_cell(x1, y1)
    bx2, by2 = to_cell(x2, y2)
    labels, _ = ndimage.label(background)
    inside = labels[max(0, by1):max(0, by2), max(0, bx1):max(0, bx2)]
    ids, counts = np.unique(inside[inside > 0], return_counts=True)
    if len(ids) == 0:
        return fail("框入面搵唔到底色")
    box_cells = max(1, (bx2 - bx1) * (by2 - by1))
    at_edge = (area[1] <= 0, area[3] >= 1, area[0] <= 0, area[2] >= 1)     # 上、下、左、右
    reasons = []
    box_mask = np.zeros_like(background)
    box_mask[max(0, by1):max(0, by2), max(0, bx1):max(0, bx2)] = True
    other_masks = []
    for other in others:
        ox1, oy1 = to_cell(other[0], other[1])
        ox2, oy2 = to_cell(other[2], other[3])
        if ox2 <= 0 or oy2 <= 0 or ox1 >= cols or oy1 >= rows:
            continue        # 喺範圍外面，唔關事
        mask = np.zeros_like(background)
        mask[max(0, oy1):max(0, oy2), max(0, ox1):max(0, ox2)] = True
        if mask.any():
            other_masks.append(mask)
    # 漏咗出去時再切一次，今次切粗啲：對白框壓住格邊，白色連埋格與格之間（或者頁邊）嘅白邊，
    # 格邊比對白框窄好多。按字框短邊計（大約字咁粗），比對白框細、比格邊大
    strong = max(OPEN_CELLS, int(min(bx2 - bx1, by2 - by1) * GUTTER_CUT))
    slices = ndimage.find_objects(labels)
    for label in ids[np.argsort(-counts)]:
        # 先用外框大細篩走細嚿：網點背景會有幾千粒白點（試過一頁 3744 次形狀檢查、6.4 秒），
        # 外框都細過「對白框最細」嘅一定唔係，唔使做後面嘅開運算、填窿（下面填完嘅面積一定細過外框）
        rows_slice, cols_slice = slices[label - 1]
        if (rows_slice.stop - rows_slice.start) * (cols_slice.stop - cols_slice.start) < box_cells * BUBBLE_MIN:
            reasons.append("細過啲字（唔係對白框）")
            continue
        for component in cut_leaks(labels == label, box_mask, at_edge, (OPEN_CELLS, strong)):
            before = component.sum()
            component = own_share(component, box_mask, other_masks)
            shared = component.sum() < before        # 黐埋嘅框：分咗俾其他段字
            if leaks(component, at_edge):
                reasons.append(f"漏咗出範圍邊（擴咗 {margin:.0%}）")
                continue
            if component.sum() > box_cells * BUBBLE_MAX:
                reasons.append("大得離譜（多數漏咗入畫）")
                continue
            if ndimage.binary_fill_holes(component).sum() < box_cells * BUBBLE_MIN:
                reasons.append("細過啲字（唔係對白框）")
                continue
            # 對白框入面係一隻色；畫有花紋、網點，顏色有高有低。試過將灰色嘅畫當咗對白框塗灰
            if pixels[component].std(axis=0).mean() > UNIFORM_STD:
                reasons.append("唔係平滑底色（多數係畫）")
                continue
            filled = ndimage.binary_fill_holes(component)   # 字筆劃留低嘅窿填返，等色塊蓋晒原文
            if filled.sum() - component.sum() < filled.sum() * MIN_INK:
                reasons.append("入面冇字（空白位，唔係呢段字嘅框）")
                continue
            # 收細一格：格仔比真像素粗，費事色塊邊壓到對白框外圈
            bubble = ndimage.binary_erosion(filled, iterations=1)
            rect = largest_rectangle(bubble)
            # 同對白框本身面積比：橢圓入面最大長方形大約有 64%；細過 35% 即係形狀好怪
            if rect is None or (rect[2] - rect[0]) * (rect[3] - rect[1]) < bubble.sum() * MIN_TEXT_SPACE:
                reasons.append("寫字位太細")
                continue
            # 遮罩：對白框入面塗底色，其他透明；畫嘅時候拉返去範圍大細
            shape = np.zeros((rows, cols, 4), np.uint8)
            shape[bubble] = (fill.red(), fill.green(), fill.blue(), 255)
            mask = QImage(shape.tobytes(), cols, rows, cols * 4, QImage.Format.Format_RGBA8888).copy()
            ys, xs = np.nonzero(bubble)
            bounds = (area[0] + xs.min() / cols * (area[2] - area[0]), area[1] + ys.min() / rows * (area[3] - area[1]),
                      area[0] + (xs.max() + 1) / cols * (area[2] - area[0]),
                      area[1] + (ys.max() + 1) / rows * (area[3] - area[1]))
            # 黐埋嘅框分開之後，分界係斜線，跟住形狀逐行排會參差（試過「是」吊咗喺一角）：淨係用入面最大嘅長方形
            layout_grid = bubble
            if shared:
                layout_grid = np.zeros_like(bubble)
                layout_grid[rect[1]:rect[3], rect[0]:rect[2]] = True
            return {"mask": mask, "area": area, "grid": bubble, "layout_grid": layout_grid, "bounds": bounds}
    if why is not None:
        why.extend(dict.fromkeys(reasons))      # 同一個原因唔使講幾次
    return None


def leaks(component, at_edge):
    """掂到範圍邊即係漏咗出去；範圍邊啱啱係塊鏡邊就唔計（個框只係俾塊鏡切開咗）。"""
    sides = (component[0], component[-1], component[:, 0], component[:, -1])
    return any(side.any() and not edge for side, edge in zip(sides, at_edge))


def cut_leaks(component, box_mask, at_edge, cuts):
    """開運算切斷窄窄嘅漏口，留同字框重疊最多嗰嚿；回傳要試嘅候選（排先嗰個先試）。
    幼刀切完仲漏，就用粗刀再切：粗刀切完唔漏就排先試，但都留低幼刀嗰個：粗刀可能將字附近嘅白位切走，
    入面變咗冇字（試過黐埋框嘅「んだっけ？」），嗰陣要靠幼刀版本「漏咗」去擴大範圍再試。

    對白框外圈有缺口，白色會由窄位漏入後面淺色嘅畫（試過譯文寫咗喺後面灰色嘅地方）；
    對白框壓住格邊，白色又會連埋格與格之間嘅白邊。
    要喺搵連通區域之後先切：成張圖先切，字同外圈之間嘅窄白位冇埋，字唔再係「窿」，數唔到有字。"""
    def cut_with(cut):
        opened, _ = ndimage.label(ndimage.binary_opening(component, iterations=cut))
        overlap = opened[box_mask & (opened > 0)]
        if not len(overlap):
            return component
        core = opened == np.bincount(overlap).argmax()
        # 擴返開運算收細咗嘅邊，但唔好超出原本嗰嚿
        return ndimage.binary_dilation(core, iterations=cut) & component
    fine, coarse = cuts
    first = cut_with(fine)
    if not leaks(first, at_edge) or coarse <= fine:
        return [first]
    second = cut_with(coarse)
    return [first] if leaks(second, at_edge) else [second, first]


def own_share(component, box_mask, other_masks):
    """黐埋嘅對白框：同一嚿白色入面有其他段字，就每格白色分俾最近嗰段字，淨係留近自己嗰份。
    試過三個框黐埋，三段字當咗一個框，譯文一條直行跨過三個框。
    淨係計字喺呢嚿白色入面嘅（字係白色入面嘅「窿」）：隔籬另一個對白框嘅字唔算，費事將自己個框削細咗。"""
    filled = ndimage.binary_fill_holes(component)
    inside = [mask for mask in other_masks if (mask & filled).sum() >= mask.sum() * 0.5]
    if not inside:
        return component
    mine = ndimage.distance_transform_edt(~box_mask)
    theirs = ndimage.distance_transform_edt(~np.logical_or.reduce(inside))
    share = component & (mine <= theirs)
    # 分完可能散開幾嚿：留同自己啲字黐住（或者最近）嗰嚿
    labels, count = ndimage.label(share)
    if count > 1:
        near = ndimage.binary_dilation(box_mask, iterations=2)
        hits = np.bincount(labels[near & (labels > 0)], minlength=count + 1)
        share = labels == (hits.argmax() if hits.any() else 1)
    return share


def merge_shared_bubbles(blocks):
    """模型間中將同一個對白框嘅字拆做兩段；兩段搵到同一個框，就合埋做一段先翻譯。

    試過兩段各自塗底色，第二段塗嘅時候將第一段啱啱寫好嘅譯文蓋走咗。
    """
    merged = []
    for block in blocks:
        same = None
        if block.get("shape"):
            # 兩段都有自己嘅字框就唔合：字框已經按對白框分好（split_boxes），
            # 搵到同一個形狀即係黐埋嘅框，own_share() 已經分開咗
            same = next((m for m in merged if m.get("shape") and m["lang"] == block["lang"]
                         and not ("finder" in m and "finder" in block)
                         and iou(m["shape"]["bounds"], block["shape"]["bounds"]) >= SAME_BUBBLE_IOU), None)
        if same is None:
            merged.append(block)
            continue
        joiner = " " if block["lang"] in ("en", "ko", "other") else ""
        same["text"] = same["text"] + joiner + block["text"]
        same["sfx"] = same.get("sfx", False) and block.get("sfx", False)
        same["box"] = union(same["box"], block["box"])
        if block.get("text_px") is not None:
            same["text_px"] = block["text_px"] if same.get("text_px") is None else union(same["text_px"], block["text_px"])
    return merged


def union(a, b):
    """兩個框嘅外框。"""
    return tuple(f(x, y) for f, x, y in zip((min, min, max, max), a, b))


def iou(a, b):
    """兩個框嘅重疊比例（交集 ÷ 並集）。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def longest_runs(mask, axis):
    """每列（axis=0）或者每行（axis=1）最長嗰段 True：回傳 [(開始格, 結束格)]，冇就 None。"""
    lines = mask.T if axis == 0 else mask
    runs = []
    for line in lines:
        edges = np.diff(np.concatenate([[0], line.astype(int), [0]]))
        starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
        if len(starts) == 0:
            runs.append(None)
            continue
        k = int(np.argmax(ends - starts))
        runs.append((int(starts[k]), int(ends[k])))
    return runs


class BubbleSpace:
    """對白框形狀（格仔）轉做塊鏡上面嘅像素：問「呢條直／橫帶入面，對白框由邊度去到邊度」。"""

    def __init__(self, grid, area):
        self.area = area
        rows, cols = grid.shape
        self.cw, self.ch = area.width() / cols, area.height() / rows
        self.col_runs = longest_runs(grid, axis=0)
        self.row_runs = longest_runs(grid, axis=1)
        filled_cols = [c for c, run in enumerate(self.col_runs) if run]
        filled_rows = [r for r, run in enumerate(self.row_runs) if run]
        self.left = area.left() + filled_cols[0] * self.cw
        self.right = area.left() + (filled_cols[-1] + 1) * self.cw
        self.top = area.top() + filled_rows[0] * self.ch
        self.bottom = area.top() + (filled_rows[-1] + 1) * self.ch

    def _span(self, runs, start, end, origin, cell, other_origin, other_cell, pad):
        first, last = int((start - origin) // cell), int(-(-(end - origin) // cell)) - 1
        if first < 0 or last >= len(runs) or first > last:
            return None
        chosen = runs[first:last + 1]
        if any(run is None for run in chosen):
            return None
        # 成條帶都要喺框入面：取幾條格仔嘅重疊部分
        lo = other_origin + max(run[0] for run in chosen) * other_cell + pad
        hi = other_origin + min(run[1] for run in chosen) * other_cell - pad
        return (lo, hi) if hi > lo else None

    def vertical_span(self, x0, x1, pad):
        """x0 至 x1 呢條直帶入面，對白框嘅頂同底。"""
        return self._span(self.col_runs, x0, x1, self.area.left(), self.cw, self.area.top(), self.ch, pad)

    def horizontal_span(self, y0, y1, pad):
        """y0 至 y1 呢條橫帶入面，對白框嘅左同右。"""
        return self._span(self.row_runs, y0, y1, self.area.top(), self.ch, self.area.left(), self.cw, pad)


# 唔可以喺行頭嘅標點（中文排版規則）：擠唔落就連前面一個字一齊落下一行，唔好自己孤零零做行頭
NO_LINE_START = set("，。、！？：；」』）】》〉…,.!?:;)︐︑︒︕︖︶﹂﹄︙")


def tokens(text):
    """拆做一粒粒擺：中文逐個字；連住嘅英文字母、數字當一粒（唔好喺「Roadster」中間斷開）。"""
    return re.findall(r"[A-Za-z0-9]+(?:['.\-][A-Za-z0-9]+)*|\s|\S", text)


def shaped_vertical(space, text, px, cap=None):
    """跟住對白框形狀直排：由右邊一行起，每行睇框喺嗰度有幾高就擺幾多個字；擺唔晒回傳 None。
    cap：每行最多幾多隻字（平均分行用，見 balanced()）。"""
    chars = vertical_chars(text)
    col_w, row_h, pad = px * 1.15, px * 1.05, px * 0.25

    def attempt(start):
        columns, i, right = [], 0, start
        while i < len(chars):
            left = right - col_w
            if left < space.left + pad - 0.01:
                return None
            span = space.vertical_span(left, right, pad)
            fits = int((span[1] - span[0]) // row_h) if span else 0
            if cap is not None:
                fits = min(fits, cap)
            if fits > 0:
                take = chars[i:i + fits]
                # 下一粒係標點：前面嘅字留低一齊落下一行（試過吊喺行尾，會凸出對白框）
                while len(take) > 1 and i + len(take) < len(chars) and chars[i + len(take)] in NO_LINE_START:
                    take = take[:-1]
                columns.append((left, span, take))
                i += len(take)
            right = left
        # 每行由頂開始（同漫畫一樣）：試過每行各自上下置中，短嗰行跌咗落去，「糟／了！」睇落好似倒轉；
        # 成嚿字都短（例如得一行）就成嚿一齊向下移，喺框入面置中
        drop = min((span[1] - span[0]) - len(take) * row_h for _, span, take in columns) / 2 if columns else 0
        placed = [(QRectF(left, span[0] + drop + j * row_h, col_w, row_h), c)
                  for left, span, take in columns for j, c in enumerate(take)]
        return placed, right

    first = attempt(space.right - pad)
    if first is None:
        return None
    # 左邊淨低嘅位分返一半去右邊，成堆字喺框入面左右置中
    slack = first[1] - (space.left + pad)
    second = attempt(space.right - pad - slack / 2) if slack > 1 else None
    return (second or first)[0]


def shaped_horizontal(space, text, px, cap=None):
    """跟住對白框形狀打橫：由上面一行起，每行睇框喺嗰個高度有幾闊就擺幾多；擺唔晒回傳 None。
    cap：每行最多幾多粒（中日文一隻字一粒；平均分行用）。"""
    metrics = QFontMetricsF(fitted_font(px))
    parts = tokens(text)
    widths = [metrics.horizontalAdvance(part) for part in parts]
    row_h, pad = px * 1.25, px * 0.25

    def attempt(start):
        placed, i, top = [], 0, start
        while i < len(parts):
            bottom = top + row_h
            if bottom > space.bottom - pad + 0.01:
                return None
            span = space.horizontal_span(top, bottom, pad)
            if span:
                while i < len(parts) and parts[i].isspace():
                    i += 1      # 行頭唔要空格
                line, used = [], 0.0
                while i < len(parts) and used + widths[i] <= span[1] - span[0] and (cap is None or len(line) < cap):
                    line.append(i)
                    used += widths[i]
                    i += 1
                # 下一粒係標點：最後一個字留低一齊落下一行（試過吊喺行尾，會凸出對白框）
                while len(line) > 1 and i < len(parts) and parts[i] in NO_LINE_START:
                    i = line.pop()
                    used -= widths[i]
                x = (span[0] + span[1]) / 2 - used / 2      # 每行左右置中
                for k in line:
                    placed.append((QRectF(x, top, widths[k], row_h), parts[k]))
                    x += widths[k]
            top = bottom
        return placed, top

    first = attempt(space.top + pad)
    if first is None:
        return None
    slack = space.bottom - pad - first[1]
    second = attempt(space.top + pad + slack / 2) if slack > 1 else None
    return (second or first)[0]


def lines_of(placed, vertical):
    """排好嘅字分返一行行（直排睇左右位置、打橫睇上下位置），回傳每行嘅字（排版次序）。"""
    rows = {}
    for cell, part in placed:
        rows.setdefault(round(cell.left() if vertical else cell.top()), []).append(part)
    order = sorted(rows, reverse=vertical)       # 直排由右到左、打橫由上到下
    return [rows[key] for key in order]


def orphan(placed, vertical):
    """最後一行淨低一隻中日文字（例如 6／6／1），讀落好累贅。英文最後一行得一個字好正常，唔計。"""
    if not placed:
        return False
    lines = lines_of(placed, vertical)
    # 標點唔計：「了。」睇落都係淨低一隻字（標點唔做行頭，前一隻字會跟埋落去）
    words = [part for part in lines[-1] if part.isalnum()]
    return len(lines) >= 2 and len(words) == 1 and len(words[0]) == 1 and not words[0].isascii()


def balanced(layout, space, text, px, vertical):
    """排到最後一行得一隻字，就試吓每行少擺啲，令字平均分落每行（13 隻字 3 行：6／6／1 → 5／5／3）。
    塞唔落就回傳 None。"""
    placed = layout(space, text, px)
    if placed is None or not orphan(placed, vertical):
        return placed
    lines = lines_of(placed, vertical)
    total, longest = sum(len(line) for line in lines), max(len(line) for line in lines)
    for cap in range(longest - 1, max(1, -(-total // len(lines))) - 1, -1):
        again = layout(space, text, px, cap)
        if again is not None and not orphan(again, vertical):
            return again
    return placed


def best_layout(space, text, lang, direction=None, max_px=None):
    """搵塞得落對白框嘅最大字；日文兩種排法都試，直排差唔多大就用直排。回傳（字大細, 每粒字嘅位置）。

    direction 係 "vertical"／"horizontal" 就跟佢（冇對白框嘅字跟返原文方向），擺唔落直排先改打橫；
    max_px 係字最大幾多像素。"""
    def biggest(layout):
        high = min(space.right - space.left, space.bottom - space.top)
        if max_px is not None:
            high = min(high, max_px)
        low, high, found = 6.0, max(6.0, high), None
        while high - low > 0.5:
            mid = (low + high) / 2
            placed = layout(space, text, mid)
            if placed is not None:
                low, found = mid, placed
            else:
                high = mid
        if found is None:
            return low, layout(space, text, 6.0)
        # 最後一行得一隻字：先平均分行；分唔落就細少少字再試（最多細 ORPHAN_SHRINK）
        vertical = layout is shaped_vertical
        best = balanced(layout, space, text, low, vertical)
        if not orphan(best, vertical):
            return low, best
        size = low
        while size > low * (1 - ORPHAN_SHRINK):
            size *= 0.97
            again = balanced(layout, space, text, size, vertical)
            if again is not None and not orphan(again, vertical):
                return size, again
        return low, best

    if not current().vertical:
        direction = "horizontal"        # 英文、韓文唔直排
    if direction == "vertical":
        down = biggest(shaped_vertical)
        if down[1]:
            return down
    across = biggest(shaped_horizontal)
    if direction is None and lang == "ja":
        down = biggest(shaped_vertical)
        # 每行直排都淨係得一個字（又矮又闊嘅位，例如一行旁白），由右至左讀落就變咗倒轉，唔好用
        columns = len({round(cell.left()) for cell, _ in down[1]}) if down[1] else 0
        single = len(down[1] or []) > 1 and columns == len(down[1])
        if down[1] and not single and down[0] >= across[0] * 0.9:
            return down
    return across


def fitted_font(px):
    # 揀咗嘅譯文字型排第一（第 8 期），跟住「譯做」語言嘅字型（第 7 期），正黑體排最後做後備：
    # 揀咗嘅字型冇嗰隻字（例如粉圓冇韓文），Qt 會自動用後面嗰隻
    family = chosen("譯鏡")
    font = make_font([family] + list(current().fonts) + CHINESE_FONTS, 10, bold=has_bold(family))
    font.setPixelSize(max(1, int(px)))
    return font


HORIZONTAL_FLAGS = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap


def horizontal_size(rect, text):
    """打橫寫（自動轉行）塞得落個框嘅最大字（像素）。"""
    low, high = 6, max(6, rect.height())
    while high - low > 0.5:     # 二分法搵最大嘅字：比一粒粒試快好多
        mid = (low + high) / 2
        used = QFontMetricsF(fitted_font(mid)).boundingRect(rect, HORIZONTAL_FLAGS, text)
        if used.width() <= rect.width() and used.height() <= rect.height():
            low = mid
        else:
            high = mid
    return low


def vertical_chars(text):
    # 空格同換行唔佔位：直排每個格都要有字。
    # 直排專用標點要揀咗嘅字型有先換：粉圓、芫荽冇「︕」「︖」，換咗會變返正黑體，同前後啲字唔夾；
    # 普通全形「！」「？」本身企喺格正中，直排都睇得
    family = chosen("譯鏡")
    chars = []
    for char in text:
        if char.isspace():
            continue
        vertical = char.translate(VERTICAL_FORMS)
        chars.append(vertical if vertical == char or supports(family, vertical) else char)
    return chars


def vertical_size(rect, text):
    """直排寫塞得落個框嘅最大字（像素）。"""
    chars = vertical_chars(text)
    for px in range(int(min(rect.width(), rect.height())), 5, -1):    # 由大試到細，第一個塞得落就用
        per_column = max(1, int(rect.height() // (px * 1.05)))
        columns = -(-len(chars) // per_column)
        if columns * px * 1.15 <= rect.width():
            return px
    return 6


def draw_horizontal(p, rect, text, px):
    p.setFont(fitted_font(px))
    p.drawText(rect, HORIZONTAL_FLAGS, text)


def draw_vertical(p, rect, text, best):
    """直排寫：一行由上到下，行由右到左排，同日漫原本一樣。"""
    chars = vertical_chars(text)
    if not chars:
        return
    p.setFont(fitted_font(best))
    per_column = max(1, int(rect.height() // (best * 1.05)))
    columns = -(-len(chars) // per_column)
    width = columns * best * 1.15
    right = rect.center().x() + width / 2       # 成堆字喺框入面置中
    rows = min(per_column, len(chars))
    top = rect.center().y() - rows * best * 1.05 / 2
    for i, char in enumerate(chars):
        column, row = divmod(i, per_column)
        cell = QRectF(right - (column + 1) * best * 1.15, top + row * best * 1.05, best * 1.15, best * 1.05)
        p.drawText(cell, Qt.AlignmentFlag.AlignCenter, char)


def draw_parts(p, px, placed, colour, outline=False):
    """將排好嘅字（每粒一格）寫落去；outline 就加相反顏色嘅描邊。"""
    font = fitted_font(px)
    if not outline:
        p.setPen(colour)
        p.setFont(font)
        for cell, part in placed:
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, part)
        return
    # 描邊要用字嘅外形（path）畫：先畫粗邊，再喺上面填字色
    metrics = QFontMetricsF(font)
    path = QPainterPath()
    for cell, part in placed:
        x = cell.center().x() - metrics.horizontalAdvance(part) / 2
        y = cell.center().y() + (metrics.ascent() - metrics.descent()) / 2
        path.addText(QPointF(x, y), font, part)
    edge = QColor("white") if colour.lightness() < 128 else QColor("black")
    pen = QPen(edge, max(2.0, px * OUTLINE))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)     # 尖角描邊會凸出一隻隻刺
    p.strokePath(path, pen)
    p.fillPath(path, colour)


def unchanged(block):
    """譯文同原文一樣（例如英文招牌「The World Do Cafe」譯完都係佢）：唔使抹走再寫過，原文照留。"""
    def plain(text):
        return re.sub(r"[\s.,!?…・:：。、！？]", "", text).lower()
    return plain(block["translation"]) == plain(block["text"])


def paint_blocks(p, blocks, w, h):
    """喺 w × h 嘅範圍畫晒每個框：未譯好畫虛線框，譯好就用底色蓋住原文再寫譯文。

    抽出嚟係因為塊鏡設咗唔俾截圖，影相睇唔到；測試可以直接畫落一張圖度檢查。
    """
    # 次序：冇字框嘅段 → 有字框但冇對白框（抹字補圖嘅擬聲字、旁白）→ 對白框最後。
    # 唔可以淨睇有冇字框：拆字框之後擬聲字都有字框，試過「フラ…」塊補圖喺對白之後先畫，切走「雖然」半邊
    for block in sorted(blocks, key=lambda b: (bool(b.get("shape")), "finder" in b)):
        x1, y1, x2, y2 = block["box"]
        rect = QRectF(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h)
        if block["translation"] is None:
            # 未譯好：虛線框，話你知呢度有字、譯緊
            p.setPen(QPen(QColor("#ff4081"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            continue
        if unchanged(block):
            continue
        if block.get("patch") is not None:
            # 冇對白框（抹字補圖）：貼返補好嘅背景，原文就唔見咗；再喺原文位置描邊寫譯文
            a1, b1, a2, b2 = block["patch_area"]
            p.drawImage(QRectF(a1 * w, b1 * h, (a2 - a1) * w, (b2 - b1) * h), block["patch"])
            key = (w, h, block["translation"], chosen("譯鏡"), text_size())     # 轉咗字型、字大細要重新排
            if block.get("layout_key") != key:
                block["layouts"] = loose_layouts(block, w, h)
                block["layout_key"] = key
            for px, placed in block["layouts"]:
                if placed:
                    draw_parts(p, px, placed, text_color(block["fill"]), outline=True)
            continue
        if block.get("shape"):
            # 搵到對白框形狀：成個框入面塗底色（原文一定蓋晒、外圈一定唔掂），
            # 再跟住框嘅闊窄逐行擺字（橢圓中間嗰行長啲），字可以盡量大又唔出框
            shape = block["shape"]
            a1, b1, a2, b2 = shape["area"]
            area = QRectF(a1 * w, b1 * h, (a2 - a1) * w, (b2 - b1) * h)
            p.drawImage(area, shape["mask"])
            if block.get("strokes") is not None:
                s1, t1, s2, t2 = block["strokes_area"]
                p.drawImage(QRectF(s1 * w, t1 * h, (s2 - s1) * w, (t2 - t1) * h), block["strokes"])
            key = (w, h, block["translation"], chosen("譯鏡"), text_size())
            if block.get("layout_key") != key:      # 計一次就記住，唔使每次重畫都計
                cap = None
                if block.get("text_box"):
                    t1, u1, t2, u2 = block["text_box"]
                    cap = BUBBLE_SCALE * original_size(block["text"], (t2 - t1) * w * (u2 - u1) * h, 1.0)
                block["layout"] = scaled_layout(BubbleSpace(shape.get("layout_grid", shape["grid"]), area),
                                                block["translation"], block["lang"], cap=cap)
                block["layout_key"] = key
            px, placed = block["layout"]
            if placed:
                draw_parts(p, px, placed, text_color(block["fill"]))
                continue
        # 用對白框本身嘅底色淨係蓋住原文筆劃嗰範圍，唔好剪走對白框外圈；
        # 圓角大啲：對白框多數係圓或者橢圓，方角會凸咗出框外
        c1, d1, c2, d2 = block.get("cover", block["box"])
        cover = QRectF(c1 * w, d1 * h, (c2 - c1) * w, (d2 - d1) * h)
        radius = min(cover.width(), cover.height()) * COVER_ROUND
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(block["fill"])
        p.drawRoundedRect(cover, radius, radius)
        p.setPen(text_color(block["fill"]))
        # 譯文寫喺原文範圍同成個框中間：淨用原文範圍，一行英文得好矮，譯文字會好細；
        # 用成個框又會寫咗出圓形對白框外面
        box = rect.adjusted(rect.width() * INSET, rect.height() * INSET, -rect.width() * INSET, -rect.height() * INSET)
        inner = QRectF(
            cover.left() + (box.left() - cover.left()) * TEXT_GROW,
            cover.top() + (box.top() - cover.top()) * TEXT_GROW,
            cover.width() + (box.width() - cover.width()) * TEXT_GROW,
            cover.height() + (box.height() - cover.height()) * TEXT_GROW,
        )
        draw_fitted(p, inner, block["translation"], block["lang"])


def reading_order(regions, lang):
    """幾嚿字嘅閱讀次序：日文由右至左（上下疊住嘅就由上至下）；其他由上至下（並排嘅由左至右）。"""
    def before(a, b):
        if lang == "ja":
            across = min(a[2], b[2]) - max(a[0], b[0])
            if across > 0.5 * min(a[2] - a[0], b[2] - b[0]):
                return -1 if a[1] < b[1] else 1
            return -1 if a[2] > b[2] else 1
        down = min(a[3], b[3]) - max(a[1], b[1])
        if down > 0.5 * min(a[3] - a[1], b[3] - b[1]):
            return -1 if a[0] < b[0] else 1
        return -1 if a[1] < b[1] else 1
    return sorted(regions, key=functools.cmp_to_key(before))


def split_text(text, weights):
    """將譯文按比例分做幾份（每嚿字一份），盡量喺標點後面切，唔好切開英文字。"""
    parts = tokens(text)
    if len(weights) <= 1 or len(parts) <= 1:
        return [text] + [""] * (len(weights) - 1)
    total, cuts, done = sum(weights), [], 0.0
    for weight in weights[:-1]:
        done += weight
        target = round(len(parts) * done / total)
        window = max(1, len(parts) // (2 * len(weights)))
        near = [i for i in range(max(1, target - window), min(len(parts), target + window + 1))
                if parts[i - 1] in SPLIT_AT]
        cut = min(near, key=lambda i: abs(i - target)) if near else target
        cuts.append(max(cuts[-1] if cuts else 0, min(len(parts), cut)))
    edges = [0] + cuts + [len(parts)]
    return ["".join(parts[a:b]).strip() for a, b in zip(edges, edges[1:])]


def original_size(text, area, share):
    """估原文字大概幾大（像素）：呢嚿字嘅面積 ÷ 佢分到嘅字數，開方；英文字母大約半格。"""
    count = sum(0.5 if c.isascii() else 1.0 for c in text if not c.isspace()) * share
    return (area / max(1.0, count)) ** 0.5


def loose_layouts(block, w, h):
    """冇對白框嘅段：譯文按比例分落每嚿字度（讀字模型間中將兩嚿分開嘅旁白當一段），
    每嚿跟返原文方向排，字最多大過原文少少，唔好遮住幅畫。"""
    regions = reading_order(block.get("regions") or [block["text_box"]], block["lang"])
    areas = [(r[2] - r[0]) * w * (r[3] - r[1]) * h for r in regions]
    texts = split_text(block["translation"], areas)
    layouts = []
    for (t1, u1, t2, u2), area, part in zip(regions, areas, texts):
        if not part:
            continue
        gx, gy = (t2 - t1) * TEXT_ROOM, (u2 - u1) * TEXT_ROOM
        room = QRectF((t1 - gx) * w, (u1 - gy) * h, (t2 - t1 + 2 * gx) * w, (u2 - u1 + 2 * gy) * h)
        # 方向跟返原文：試過斜斜嘅一行旁白用咗直排，兩個字一行由右至左，亂晒
        tall = (u2 - u1) * h > (t2 - t1) * w
        direction = "vertical" if tall and block["lang"] == "ja" else "horizontal"
        if tall and not current().vertical:
            # 原文直排、譯文要打橫（英文、韓文）：直行好窄，英文會一個字一行；左右放闊（最多原本高度嘅 0.8）
            extra = max(0.0, (u2 - u1) * h * 0.8 - room.width()) / 2
            room = room.adjusted(-extra, 0, extra, 0)
        cap = ORIGINAL_SCALE * original_size(block["text"], area, area / sum(areas))
        # 一格嘅「形狀」＝成個長方形都用得，排字照用跟形狀嗰套（標點唔做行頭）
        layouts.append(scaled_layout(BubbleSpace(np.ones((1, 1), bool), room), part, block["lang"], direction, cap))
    return layouts


def draw_fitted(p, rect, text, lang):
    """喺 rect 入面用塞得落嘅最大字寫 text；日文兩種排法都試，直排差唔多大就用直排，保留漫畫味道。"""
    across = horizontal_size(rect, text)
    down = vertical_size(rect, text) if lang == "ja" else 0
    scale = min(1.0, text_size())       # 呢度已經係塞得落嘅最大，淨係調細有效
    if down >= across * 0.9:
        draw_vertical(p, rect, text, down * scale)
    else:
        draw_horizontal(p, rect, text, across * scale)


def find_text(image, blocks, eraser, found=None):
    """行搵字模型：跟編號框讀返嚟嘅段（有 finder）位置已經準；其餘嘅段（讀字模型自己估位置，例如框外嘅擬聲字）
    先校正讀字模型成頁嘅偏差，再配未有人要嘅字框，將同一段字嘅幾段合埋（讀字模型間中將一段字拆開，
    分開譯會疊埋或者讀唔順），每段記低真正嘅字範圍（像素）。搵到真正字範圍嘅段，個框都改用佢：
    之後搵對白框先唔會搵咗隔籬嗰個。found 係（原圖, 筆劃機會, 字框），已經搵過就唔使再搵。
    回傳（合埋咗嘅段, (原圖, 筆劃機會)）。"""
    if found is None:
        rgb = to_array(image)
        prob, boxes = eraser.find(rgb)
    else:
        rgb, prob, boxes = found
    h, w = rgb.shape[:2]
    diagonal = float(np.hypot(w, h))
    exact = [block for block in blocks if "finder" in block]
    rough = [block for block in blocks if "finder" not in block]
    free = [j for j in range(len(boxes)) if j not in {block["finder"] for block in exact}]
    spare = boxes[free]
    pixels = [(x1 * w, y1 * h, x2 * w, y2 * h) for x1, y1, x2, y2 in (block["box"] for block in rough)]
    dx, dy = page_shift(pixels, spare, diagonal) if rough else (0.0, 0.0)
    if abs(dx) >= 1 or abs(dy) >= 1:
        print(f"  讀字框成頁偏咗 ({dx:+.0f}, {dy:+.0f}) 像素，校正咗")
    pixels = [(x1 + dx, y1 + dy, x2 + dx, y2 + dy) for x1, y1, x2, y2 in pixels]
    owned = [{free[j] for j in owned_boxes(px, spare)} for px in pixels]
    for i, j in pair_leftovers(pixels, [{free.index(k) for k in mine} for mine in owned], spare, diagonal).items():
        owned[i] = {free[j]}
    entries = [(block, block["text_px"], {block["finder"]}) for block in exact]
    entries += list(zip(rough, pixels, owned))
    exact_px = [block["text_px"] for block in exact]
    merged = []
    for block, px, mine in entries:
        text_px = block["text_px"] if "finder" in block else text_box_of(px, prob, boxes, sorted(mine))
        if "finder" not in block and any(overlaps(text_px, other) for other in exact_px):
            continue        # 框外報嘅字其實喺某個編號框入面：嗰個框已經讀咗，唔好重複
        box = tuple(float(np.clip(v / size, 0, 1)) for v, size in zip(px, (w, h, w, h)))
        # 同一個搵字框，或者字範圍重疊咗一半以上：都係同一段字
        same = next((m for m in merged if m["lang"] == block["lang"]
                     and (mine & m["owned"] or overlaps(text_px, m["text_px"]))), None)
        strokes = [] if mine or text_px is None else [text_px]     # 搵字模型冇畫框：用筆劃範圍做一嚿
        if same is None:
            merged.append({**block, "box": box, "reader_box": box, "owned": set(mine), "strokes": strokes,
                           "text_px": text_px})
            continue
        joiner = " " if block["lang"] in ("en", "ko", "other") else ""
        same["text"] += joiner + block["text"]
        same["sfx"] = same.get("sfx", False) and block.get("sfx", False)
        same["box"] = same["reader_box"] = union(same["reader_box"], box)
        same["owned"] |= mine
        same["strokes"] += strokes
        if text_px is not None:
            same["text_px"] = text_px if same["text_px"] is None else union(same["text_px"], text_px)
    for block in merged:
        # 每嚿字（像素）：搵字模型嘅字框逐個一嚿；之後抹字、寫譯文都逐嚿做，唔好將兩嚿之間嘅畫都當咗係字
        regions = [tuple(float(v) for v in boxes[j]) for j in sorted(block.pop("owned"))]
        regions += [r for r in block.pop("strokes") if not any(overlaps(r, other) for other in regions)]
        block["regions_px"] = regions
        if block["text_px"] is not None:
            x1, y1, x2, y2 = block["text_px"]
            block["box"] = (x1 / w, y1 / h, x2 / w, y2 / h)
    # 框外嘅段（擬聲字）冇字框，位置靠讀字模型估；同編號框嘅字重疊多過少少，多數係估錯位，
    # 抹字寫字會遮住隔籬對白（用戶見過）→ 唔要，原文照留
    kept = []
    for block in merged:
        crowded = "finder" not in block and block["text_px"] is not None and any(
            intersection(block["text_px"], other) > LOOSE_OVERLAP * area_of(block["text_px"]) for other in exact_px)
        if crowded:
            print(f"  擬聲字／框外字「{block['text']}」同對白字框重疊，唔譯")
        else:
            kept.append(block)
    return kept, (rgb, prob)


def area_of(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def join_into_bubbles(blocks, prob):
    """冇對白框嘅段，啲字其實喺另一段嘅對白框入面（例如兩嚿相連嘅對白框）：合埋做一段，
    唔係前一段嘅譯文會跟住形狀寫入嚟，同呢段嘅譯文疊埋。"""
    kept = []
    for block in blocks:
        host = None
        if not block.get("shape") and block.get("text_px") is not None:
            host = next((k for k in kept if k.get("shape") and k["lang"] == block["lang"]
                         and text_inside({**block, "shape": k["shape"]}, prob) >= TEXT_INSIDE), None)
        if host is None:
            kept.append(block)
            continue
        joiner = " " if block["lang"] in ("en", "ko", "other") else ""
        host["text"] += joiner + block["text"]
        host["sfx"] = host.get("sfx", False) and block.get("sfx", False)
        host["text_px"] = union(host["text_px"], block["text_px"]) if host.get("text_px") is not None else block["text_px"]
    return kept


def text_inside(block, prob):
    """對白框形狀包住呢段字幾多筆劃（0 至 1）。"""
    h, w = prob.shape
    x1, y1, x2, y2 = (int(v) for v in block["text_px"])
    ys, xs = np.nonzero(prob[y1:y2, x1:x2] > TEXT_PROB)
    if len(ys) == 0:
        return 1.0
    a1, b1, a2, b2 = block["shape"]["area"]
    # 放寬兩格先檢查：形狀收細咗一格（色塊唔好壓外圈），字貼住框邊嘅框（「神殿も増え…」頂頭幾粒字）
    # 試過因此得 90%、啱啱唔過關。原文真係喺框外（例如下半截喺另一個地方）會差好遠，放寬兩格唔會救錯
    grid = ndimage.binary_dilation(block["shape"]["grid"], iterations=INSIDE_SLACK)
    rows, cols = grid.shape
    cx = ((x1 + xs + 0.5) / w - a1) / (a2 - a1) * cols
    cy = ((y1 + ys + 0.5) / h - b1) / (b2 - b1) * rows
    ok = (cx >= 0) & (cx < cols) & (cy >= 0) & (cy < rows)
    inside = np.zeros(len(xs), bool)
    inside[ok] = grid[cy[ok].astype(int), cx[ok].astype(int)]
    return float(inside.mean())


def erase_loose(found, blocks, eraser):
    """冇對白框嘅字：抹字補圖，記低補好嘅圖塊同譯文範圍。"""
    rgb, prob = found
    h, w = rgb.shape[:2]
    holes = []
    for block in blocks:
        text_box = block.get("text_px")
        if block.get("shape"):
            if text_box is not None:    # 唔使抹，但記低原文範圍：排字用嚟估原文字幾大（BUBBLE_SCALE）
                block["text_box"] = (text_box[0] / w, text_box[1] / h, text_box[2] / w, text_box[3] / h)
            continue
        if text_box is None:
            block["why"].append("搵字模型都搵唔到筆劃")
            continue
        block["text_box"] = (text_box[0] / w, text_box[1] / h, text_box[2] / w, text_box[3] / h)
        regions = block.get("regions_px") or [text_box]
        block["regions"] = [(r[0] / w, r[1] / h, r[2] / w, r[3] / h) for r in regions]
        sound = bool(block.get("sfx"))
        holes.append((block, np.logical_or.reduce([keep_lines(rgb, hole_for(r, prob, sound), r) for r in regions])))
    if not holes:
        return
    # 補圖範圍比要蓋嘅位大兩格：貼返上去嗰陣，邊位先有得淡入淡出
    wide = [ndimage.binary_dilation(hole, iterations=2) for _, hole in holes]
    filled = eraser.erase(rgb, np.logical_or.reduce(wide))
    for (block, hole), big in zip(holes, wide):
        ys, xs = np.nonzero(big)
        rows, cols = slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1)
        soft = ndimage.gaussian_filter(big[rows, cols].astype(np.float32), FEATHER) * big[rows, cols]
        alpha = np.where(hole[rows, cols], 1.0, soft)       # 原文筆劃一定蓋實，外圈先淡
        patch = np.dstack([filled[rows, cols], (alpha * 255).astype(np.uint8)])
        block["patch"] = to_image(patch)
        block["patch_area"] = (cols.start / w, rows.start / h, cols.stop / w, rows.stop / h)
        # 譯文顏色睇補返嘅背景：光就黑字白邊，暗就白字黑邊
        block["fill"] = QColor(*(int(v) for v in np.median(filled[hole], axis=0)))


def prepare_blocks(image, blocks, eraser=None, found=None):
    """每段字加埋底色、原文筆劃範圍、對白框形狀（搵唔到嘅原因），再將共用一個框嘅合埋；
    有 eraser 就先用搵字模型合埋拆開咗嘅段、檢查對白框有冇包住晒啲字，冇對白框嘅就抹字補圖。"""
    found = None
    if eraser is not None:
        try:
            blocks, found = find_text(image, blocks, eraser, found)
        except Exception as error:      # noqa: BLE001 —— 搵字出錯唔好搞到成頁冇譯文，用返舊方法
            print(f"⚠️ 搵字出錯，用返舊方法：{error}")
    for block in blocks:
        block["fill"] = background_color(image, block["box"])
        block["cover"] = ink_box(image, block["box"], block["fill"])
        block["why"] = []
        # 其他有準確位置（字框）嘅段：黐埋嘅對白框要按佢哋分開
        others = [b["box"] for b in blocks if b is not block and b.get("text_px") is not None]
        block["shape"] = bubble_shape(image, block["box"], block["fill"], block["cover"], block["why"], others)
        if block["shape"] and found is not None and block.get("text_px") is not None:
            share = text_inside(block, found[1])
            if share < TEXT_INSIDE:
                block["why"].append(f"有字喺框外面（框入面得 {share:.0%}）")
                block["shape"] = None
        if block["shape"]:
            block["fill"] = block["shape"]["fill"]      # 可能改咗用白色（模型個框偏咗、取錯底色）
    if found is not None:
        blocks = join_into_bubbles(blocks, found[1])
    blocks = merge_shared_bubbles(blocks)
    if found is not None:
        try:
            erase_loose(found, blocks, eraser)
        except Exception as error:      # noqa: BLE001 —— 補圖出錯唔好搞到成頁冇譯文，用返色塊
            print(f"⚠️ 抹字補圖出錯，用返色塊：{error}")
            for block in blocks:
                block.pop("patch", None)
    if found is not None:
        for block in blocks:
            if block.get("shape") and block.get("text_px") is not None:
                cover_strokes(block, found[1])
    for block in blocks:
        block["translation"] = None
    return blocks


def cover_strokes(block, prob):
    """對白框形狀嘅遮罩收細咗一格（唔好壓外圈），字貼住框邊嗰幾劃會露出嚟（試過「国に…」嗰行「に」）。
    額外將原文筆劃本身塗底色：淨係擴 STROKE_GROW 像素，外圈唔係字，唔會被塗走。"""
    h, w = prob.shape
    x1, y1, x2, y2 = (int(v) for v in block["text_px"])
    a1, b1 = max(0, x1 - STROKE_GROW * 2), max(0, y1 - STROKE_GROW * 2)
    a2, b2 = min(w, x2 + STROKE_GROW * 2), min(h, y2 + STROKE_GROW * 2)
    strokes = ndimage.binary_dilation(prob[b1:b2, a1:a2] > TEXT_PROB, iterations=STROKE_GROW)
    if not strokes.any():
        return
    fill = block["fill"]
    rgba = np.zeros(strokes.shape + (4,), np.uint8)
    rgba[strokes] = (fill.red(), fill.green(), fill.blue(), 255)
    block["strokes"] = to_image(rgba)
    block["strokes_area"] = (a1 / w, b1 / h, a2 / w, b2 / h)


def drop_echoes(blocks, boxes):
    """兩個字框讀到一模一樣嘅字、又貼住（相隔唔夠大嗰個框嘅長邊），就淨留大嗰個。
    試過「フラ…」後面嗰串「…」拆咗自己一個細字框，讀字模型問到佢就答隔籬嘅「フラ…」，同一句出兩次。"""
    def size(block):
        x1, y1, x2, y2 = boxes[block["finder"]]
        return (x2 - x1) * (y2 - y1)
    kept = []
    for block in sorted(blocks, key=lambda b: size(b) if "finder" in b else 0, reverse=True):
        if "finder" in block and bare(block["text"]):
            a = boxes[block["finder"]]
            twin = next((k for k in kept if "finder" in k and bare(k["text"]) == bare(block["text"])), None)
            if twin is not None:
                b = boxes[twin["finder"]]
                gap = max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])
                if gap < max(b[2] - b[0], b[3] - b[1]):
                    continue
        kept.append(block)
    return kept


def same_words(a, b):
    """兩段字係咪同一句：一段係另一段嘅一部分，或者用嘅字差唔多一樣（詞序掉轉都算）。
    試過讀字模型喺框外報「一度見られたし使うか」，框入面係「見られたし一度使うか」；
    「それに：リスクがデカすぎるし」對「リスクがデカすぎるしそれに」"""
    if a in b or b in a:
        return True
    shorter = min(len(set(a)), len(set(b)))
    return shorter > 0 and len(set(a) & set(b)) >= shorter * SAME_WORDS


def looks_like_sound(block):
    """閂咗擬聲字嗰陣要唔要掉走呢段：讀字模型話係擬聲字，或者冇對白框兼淨係得幾隻假名。
    讀字模型間中唔當擬態語係擬聲字（「フラ…」，搖搖晃晃），閂咗都照譯"""
    if block.get("sfx"):
        return True
    text = bare(block["text"])
    return (not block.get("shape") and 0 < len(text) <= SOUND_KANA
            and all("ぁ" <= c <= "ヿ" for c in text))


def bare(text):
    """淨係留字：比較兩段係咪同一句時，標點、空格、拉長音唔計。"""
    return "".join(c for c in text if c.isalnum())


def in_rects(rects, x, y):
    return any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in rects)


class LensWorker(QObject):
    """背景線：讀字，然後逐個框翻譯；每譯好一個就交返主線畫，唔使等成頁譯完。"""
    read = pyqtSignal(int, list, float)             # 第幾次、讀到嘅框、讀字用咗幾秒
    translated = pyqtSignal(int, int, str)          # 第幾次、第幾個框、譯文
    finished = pyqtSignal(int, float)               # 第幾次、總共用咗幾秒
    failed = pyqtSignal(int, str)

    def __init__(self, translator):
        super().__init__()
        self.translator = translator
        self.characters = hk_characters()
        self.busy = False
        eraser = TextEraser()
        self.eraser = eraser if eraser.available() else None    # 模型檔唔喺度就用返色塊
        # 第 4 關快取：捲返轉頭見返同一個字框唔使再問讀字模型，見過嘅原文唔使再譯
        self.readings = ReadingCache()
        self.translations = TranslationCache()
        # 框外嘅字（擬聲字）冇字框，認唔到「呢個框」；改為記「成頁」：用嗰頁所有字框嘅快取編號做記認，
        # 位置記低同第一個字框嘅相對位置（捲咗位都跟得返）。試過全部字框都認得就唔問讀字模型，擬聲字冇咗
        self.page_others = TranslationCache()

    def read_with_cache(self, image, rgb, boxes, prob=None):
        """認得嘅字框用返快取，淨係未見過嘅先畫編號交俾讀字模型（最慢嗰步，每頁 3 至 7 秒）。
        prob（筆劃圖）有就檢查有冇讀漏字（check_complete）。"""
        w, h = image.width(), image.height()
        prints = [fingerprint(rgb, box) for box in boxes]
        blocks, missing, keys = [], [], [None] * len(boxes)
        for i, (box, mark) in enumerate(zip(boxes, prints)):
            keys[i], known = self.readings.find(mark)
            if known is None:
                missing.append(i)
            elif known != EMPTY:
                x1, y1, x2, y2 = (float(v) for v in box)
                blocks.append({**known, "finder": i, "box": (x1 / w, y1 / h, x2 / w, y2 / h),
                               "text_px": (x1, y1, x2, y2)})
        # 有未見過嘅框就問；成頁冇字框（例如淨係擬聲字）都要問，佢會報框外嘅字
        if missing or len(boxes) == 0:
            answered = set()
            fresh = read_marked(image, boxes[missing], answered)
            for block in fresh:
                if "finder" in block:
                    block["finder"] = missing[block["finder"]]      # 編號係淨係未見過嗰幾個框嘅次序
            if prob is not None:
                self.check_complete(image, prob, boxes, fresh)
                for block in fresh:
                    block["checked"] = True
            fresh = drop_echoes(fresh, boxes)
            # 淨係問咗未見過嘅框，讀字模型間中將認得嗰啲框嘅字當「框外嘅字」再報一次（試過同一句出兩段）：
            # 框外嘅段喺任何一個字框入面、或者同快取讀到嘅字一樣，就唔要
            # 比較前去走標點：試過「どうする…」對「どうする：」、一句斬開幾截（「なんだよ」「ヤバそうな」）
            known_texts = [bare(block["text"]) for block in blocks + fresh if "finder" in block]
            all_boxes = [tuple(box) for box in boxes]

            def repeated(block):
                x1, y1, x2, y2 = block["box"]
                text = bare(block["text"])
                return (in_rects(all_boxes, (x1 + x2) / 2 * w, (y1 + y2) / 2 * h) or
                        any(text and same_words(text, known) for known in known_texts if known))
            fresh = [block for block in fresh if "finder" in block or not repeated(block)]
            read = {block["finder"]: block for block in fresh if "finder" in block}
            for k in answered:
                i = missing[k]
                block = read.get(i)
                keys[i] = self.readings.put(prints[i], EMPTY if block is None else
                                            {k: block[k] for k in ("text", "lang", "sfx", "checked") if k in block})
            blocks += fresh
            if boxes.size and all(key is not None for key in keys):
                ax, ay = self._anchor(boxes, keys)
                self.page_others.put(frozenset(keys), False, [
                    {**{k: block[k] for k in ("text", "lang", "sfx")},
                     "rel": (block["box"][0] * w - ax, block["box"][1] * h - ay,
                             block["box"][2] * w - ax, block["box"][3] * h - ay)}
                    for block in fresh if "finder" not in block])
        else:
            # 全部字框都認得：框外嘅字用返「成頁」記低嗰批，跟住第一個字框搬位
            others = self.page_others.get(frozenset(keys), False) or []
            ax, ay = self._anchor(boxes, keys)
            for other in others:
                r1, s1, r2, s2 = other["rel"]
                blocks.append({k: other[k] for k in ("text", "lang", "sfx")} |
                              {"box": tuple(float(np.clip(v, 0, 1)) for v in
                                            ((r1 + ax) / w, (s1 + ay) / h, (r2 + ax) / w, (s2 + ay) / h))})
        if prob is not None:
            # 快取入面嘅字都要檢查：試過讀漏咗嗰次冇捉到就記咗入快取，之後次次都係漏咗嘅版本。
            # 每個框淨係查一次（記住 checked），費事大字框估多咗、次次都重讀
            unchecked = [block for block in blocks if "finder" in block and not block.get("checked")
                         and keys[block["finder"]] is not None]
            before = {id(block): block["text"] for block in unchecked}
            self.check_complete(image, prob, boxes, unchecked)
            for block in unchecked:
                block["checked"] = True
                self.readings.update(keys[block["finder"]], {k: block[k] for k in ("text", "lang", "sfx", "checked")})
        if len(missing) < len(boxes):
            print(f"  快取：{len(boxes) - len(missing)}/{len(boxes)} 個字框唔使再讀")
        return blocks

    @staticmethod
    def check_complete(image, prob, boxes, blocks):
        """讀到嘅字明顯少過筆劃估計（少過 COMPLETE），就淨截嗰個框再讀一次，讀到多啲先用。"""
        for block in blocks:
            if "finder" not in block:
                continue
            expected = estimate_chars(prob, boxes[block["finder"]])
            got = len(block["text"].replace(" ", ""))
            if expected < COMPLETE_MIN or got >= expected * COMPLETE:
                continue
            again = clean_text(read_crop(image, boxes[block["finder"]]), block["lang"])
            print(f"  ⚠️ 好似讀漏咗字（讀到 {got} 隻，估計 {expected:.0f} 隻）：再讀一次 → {again}")
            if len(again.replace(" ", "")) > got:
                block["text"] = again

    @staticmethod
    def _anchor(boxes, keys):
        """成頁嘅記認點：快取編號最細嗰個字框嘅左上角（每次都揀返同一個框）。"""
        i = keys.index(min(keys))
        return float(boxes[i][0]), float(boxes[i][1])

    def translate_sound(self, text):
        """擬聲字：加提示譯，唔入上下文（「ドン」對之後嘅對白冇幫助，試過「！…」跟住上一句譯成「！…這是」）。"""
        names = getattr(self.translator, "names", None)
        fixed = names.sentence(text, current()) if names is not None else None
        if fixed:
            return fixed        # 用戶固定咗呢個擬聲字嘅譯法（第 9 期）
        result, _ = ask(sound_prompt(text))
        # 模型間中連例子嘅格式都抄埋（「ムカッ→ムカッ」）：淨係要箭咀後面嗰截
        result = result.split("→")[-1].strip() or result
        if not current().hong_kong:
            return result
        return self.translator.wording.apply(self.translator.characters(result))

    def start(self, job, image, sound_effects=True, skip=()):
        self.busy = True
        threading.Thread(target=self._work, args=(job, image, sound_effects, skip), daemon=True).start()

    def _work(self, job, image, sound_effects=True, skip=()):
        """skip：截圖入面唔好讀嘅範圍（像素），例如浮喺塊鏡上面嘅字幕條。"""
        start = time.perf_counter()
        try:
            found = None
            if self.eraser is not None:
                # 先用搵字模型搵晒字框，畫編號叫讀字模型逐個讀：位置準，唔使估邊段字對邊個框
                rgb = to_array(image)
                prob, boxes = self.eraser.find(rgb)
                if skip:
                    # 字幕條喺塊鏡上面：佢嘅字唔係漫畫，唔讀唔抹（試過讀咗「⏳ 載入語音模型……」做一段）
                    boxes = boxes[[not in_rects(skip, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]]
                    for x1, y1, x2, y2 in skip:
                        prob[int(y1):int(y2), int(x1):int(x2)] = 0
                found = (rgb, prob, boxes)
                blocks = self.read_with_cache(image, rgb, boxes, prob)
            else:
                blocks = read_text(to_png(image))
            if skip:
                w, h = image.width(), image.height()
                blocks = [b for b in blocks if not in_rects(skip, (b["box"][0] + b["box"][2]) / 2 * w,
                                                             (b["box"][1] + b["box"][3]) / 2 * h)]
            read_at = time.perf_counter()
            # 喺翻譯之前搵晒每段字嘅底色、原文範圍同對白框形狀：
            # 同一個框拆咗做兩段嘅，要先合埋先譯（QImage 喺背景線讀冇問題）
            blocks = prepare_blocks(image, blocks, self.eraser, found)
            if not sound_effects:
                # 閂咗擬聲字：原文照留，唔抹唔譯。要喺搵完對白框之後先篩：要知佢喺唔喺對白框入面
                blocks = [block for block in blocks if not looks_like_sound(block)]
            prepared_at = time.perf_counter()
            self.read.emit(job, blocks, prepared_at - start)
            for i, block in enumerate(blocks):
                target = current()
                if block["lang"] in target.skip:
                    # 原文同「譯做」嘅語言一樣唔使譯；中文簡體就轉繁體（同字幕條一樣）
                    same = self.characters(block["text"]) if target.hong_kong else block["text"]
                    self.translated.emit(job, i, same)
                    continue
                sound = bool(block.get("sfx"))
                # 唔同語言嘅譯文分開記；人名記憶改咗（新記咗名、用戶改咗名單、轉咗作品）都分開，費事用舊譯名
                names = getattr(self.translator, "names", None)
                key = (target.key, names.work if names else None, names.version if names else 0, block["text"])
                result = self.translations.get(key, sound)
                if result is None:
                    result = self.translate_sound(block["text"]) if sound else self.translator.translate(block["text"])[0]
                    self.translations.put(key, sound, result)
                self.translated.emit(job, i, result)
            done_at = time.perf_counter()
            # 分開計每步：知道慢喺邊先知點樣慳時間
            print(f"  用時：讀字 {read_at - start:.1f} 秒、搵字補圖 {prepared_at - read_at:.1f} 秒、"
                  f"翻譯 {done_at - prepared_at:.1f} 秒（{len(blocks)} 段）")
            self.finished.emit(job, done_at - start)
        except (OSError, ValueError, KeyError) as error:
            self.failed.emit(job, str(error))
        finally:
            self.busy = False


class Lens(Glass):
    """譯鏡：讀字、翻譯，喺原位蓋字；底下畫面變咗就收起譯文。"""

    def __init__(self, translator, on_translated=None, debug_dir=None, ignore=None):
        super().__init__()
        # ignore()：回傳唔好讀嘅視窗範圍（螢幕座標 QRect），例如主程式嘅字幕條；佢冇設唔俾截圖，會影埋入去
        self.ignore = ignore
        # 除錯：每讀完一頁，存一張「原圖｜蓋字後＋標記」對比圖（塊鏡唔俾截圖，冇呢個睇唔到效果）
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.blocks = []
        self.status = ""
        self.job = 0                    # 每讀一次加一：舊嗰次遲咗返嚟嘅結果唔要
        self.snapshot = None            # 讀字嗰刻嘅縮圖，用嚟睇畫面有冇變
        self.image = None
        self.preloading = False
        # 擬聲字都譯唔譯（settings.json「譯鏡擬聲字」）：用戶選擇過「抹走再寫譯文」，但有人想留住原本嘅設計
        self.sound_effects = bool(load_settings().get("譯鏡擬聲字", True))
        # 自動模式（settings.json「譯鏡自動」）：畫面變咗、停定咗就自己讀；打機要閂
        self.auto = bool(load_settings().get("譯鏡自動", False))
        self.auto_items = []            # 選單入面嘅剔格：用熱鍵開關都要跟住郁
        self.sound_items = []           # 「擬聲字都譯」剔格：設定視窗改咗都要跟住郁
        self.last_view = None           # 上一次睇嘅縮圖：同今次比，睇停定咗未
        self.still = 0                  # 連續幾多次冇郁
        self.on_translated = on_translated  # 主程式用嚟寫紀錄：(語言, 原文, 譯文)
        # 第 9 期：按住 👁 或者熱鍵就唔畫譯文，睇返原文；譯文照留，放手即刻畫返（唔使重新讀）
        self.showing_original = False
        self.worker = LensWorker(translator)
        self.worker.read.connect(self._got_blocks)
        self.worker.translated.connect(self._got_translation)
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.watcher = QTimer(self)
        self.watcher.timeout.connect(self._watch)

    def hold_original(self, on):
        """按住睇原文。塊鏡唔俾截圖（WDA_EXCLUDEFROMCAPTURE），收起譯文唔會令「畫面變咗」誤判。"""
        self.showing_original = bool(on)
        self.update()

    def set_sound_effects(self, on):
        self.sound_effects = bool(on)
        save_setting("譯鏡擬聲字", self.sound_effects)
        for item in self.sound_items:
            item.blockSignals(True)
            item.setChecked(self.sound_effects)
            item.blockSignals(False)

    def sound_effects_action(self, parent):
        """⚙ 選單用嘅剔格：剔咗就連擬聲字都譯，下次讀字生效。"""
        item = QAction("擬聲字都譯", parent)
        item.setCheckable(True)
        item.setChecked(self.sound_effects)
        item.toggled.connect(self.set_sound_effects)
        self.sound_items.append(item)
        return item

    @property
    def text_percent(self):
        return round(text_size() * 100)

    def set_text_percent(self, percent):
        """改譯文字大細：排字快取跟住字大細，唔使重新讀字，重畫就用新大細。"""
        set_text_size(percent)
        self.update()
        if self.gauge:
            self.gauge.update()     # 用工具列、指示或者設定視窗改，指示都要跟住

    def gauge_text(self):
        return f"{self.text_percent}%"

    def toolbar_wheel(self, step):
        """喺工具列轆滾輪：一格 10%（同設定視窗「譯文字大細」同一個設定）。"""
        before = self.text_percent
        self.set_text_percent(before + step * 10)
        after = self.text_percent
        edge = "（最大）" if after == TEXT_SIZE_RANGE[1] else "（最細）" if after == TEXT_SIZE_RANGE[0] else ""
        self._flash(f"🔠 譯文字大細 {after}%{edge}", 1.5)

    def font_changed(self, name):
        """轉咗譯文字型：唔使重新讀字，排字快取跟住字型名，重畫就會用新字型重新排。"""
        self.update()
        print(f"譯文字型：{name}")

    def work_changed(self, work):
        """轉咗作品：舊作品嘅上下文同譯文唔要。"""
        self.worker.translator.reset()
        self.clear(f"📚 作品：{work}")

    def models_changed(self, reading, translation):
        """轉咗模型：快取係舊模型讀、舊模型譯嘅，唔清走嘅話捲返轉頭會見返舊結果，以為轉咗冇用。"""
        self.worker.readings = ReadingCache()
        self.worker.translations = TranslationCache()
        self.worker.page_others = TranslationCache()
        self.worker.translator.reset()
        self.clear(f"🧠 模型：{reading.split('/')[-1]}＋{translation.split('/')[-1]}")

    def target_changed(self, target):
        """轉咗「譯做」語言：舊譯文收起、上下文清走（舊語言嘅譯文會誤導新語言）。"""
        self.worker.translator.reset()
        self.clear(f"🌐 譯做：{target.key}")

    def set_auto(self, on):
        self.auto = bool(on)
        save_setting("譯鏡自動", self.auto)
        for item in self.auto_items:
            item.blockSignals(True)
            item.setChecked(self.auto)
            item.blockSignals(False)
        self.last_view, self.still = None, 0
        self._set_status("🔁 自動模式：開（畫面停定就讀）" if self.auto else "自動模式：閂")
        QTimer.singleShot(2000, lambda: self._set_status("") if "自動模式" in self.status else None)
        if self.auto and self.isVisible():
            self.watcher.start(WATCH_EVERY)

    def toggle_auto(self):
        self.set_auto(not self.auto)

    def auto_action(self, parent):
        """⚙ 選單用嘅剔格：自動模式開關。"""
        item = QAction("自動模式", parent)
        item.setCheckable(True)
        item.setChecked(self.auto)
        item.toggled.connect(self.set_auto)
        self.auto_items.append(item)
        return item

    def showEvent(self, event):
        super().showEvent(event)
        if self.auto:
            self.last_view, self.still = None, 0
            self.watcher.start(WATCH_EVERY)
        # 第一次顯示先喺背景載入搵字同補圖模型（要幾秒、佔 VRAM）：唔用譯鏡就唔使載
        eraser = self.worker.eraser
        if eraser is not None and eraser.finder is None and not self.preloading:
            self.preloading = True
            threading.Thread(target=eraser.load, daemon=True).start()

    # ---------- 讀字同翻譯 ----------
    def read(self):
        if self.worker.busy:
            self._set_status("⏳ 仲讀緊上一頁，等等……")
            return
        if self.adjusting:
            self.set_adjusting(False)
        self.job += 1
        self.blocks = []
        self._set_status("⏳ 讀緊字……")
        QTimer.singleShot(50, self._capture)    # 等清走舊譯文先截（雖然玻璃唔會被截到）

    def _capture(self):
        self.image = grab(self)
        self.snapshot = thumbnail(self.image)
        self.worker.start(self.job, self.image, self.sound_effects, self._skip_rects())

    def _skip_rects(self):
        """ignore() 嘅視窗範圍轉做截圖像素（截圖係實際像素，150% 縮放要乘返）。"""
        if self.ignore is None:
            return []
        g, ratio = self.geometry(), self.image.devicePixelRatio()
        rects = []
        for rect in self.ignore():
            part = rect.intersected(g)
            if not part.isEmpty():
                rects.append(((part.left() - g.left()) * ratio, (part.top() - g.top()) * ratio,
                              (part.right() + 1 - g.left()) * ratio, (part.bottom() + 1 - g.top()) * ratio))
        return rects

    def _got_blocks(self, job, blocks, seconds):
        if job != self.job:
            return
        self.blocks = blocks
        self._set_status(f"⏳ 讀到 {len(blocks)} 段（{seconds:.1f} 秒），翻譯緊……" if blocks else "冇搵到字")
        self.watcher.start(WATCH_EVERY)
        print(f"\n讀到 {len(blocks)} 段，用咗 {seconds:.1f} 秒")

    def _got_translation(self, job, i, translation):
        if job != self.job or i >= len(self.blocks):
            return
        block = self.blocks[i]
        block["translation"] = translation
        print(f"  {i + 1}. [{block['lang']}] {block['text']} → {translation}")
        if self.on_translated:
            self.on_translated(block["lang"], block["text"], translation)
        self.update()

    def _done(self, job, seconds):
        if job == self.job and self.blocks and self.debug_dir:
            self._save_debug()
        if job == self.job and self.blocks:
            self._set_status(f"✅ 譯好 {len(self.blocks)} 段（共 {seconds:.1f} 秒）")
            QTimer.singleShot(2500, lambda: self._set_status("") if self.status.startswith("✅") else None)

    def _failed(self, job, error):
        if job == self.job:
            self._set_status(f"⚠️ 讀唔到：{error}")
            print(f"⚠️ 讀唔到：{error}")

    def _save_debug(self):
        """存「左原圖｜右蓋字後」：右邊加標記，粉紅虛線＝模型個框、綠＝搵到形狀、藍＝抹字補圖、橙＝用舊方法。"""
        w, h = self.width(), self.height()
        # 截圖帶住螢幕縮放比例（150%），要指明畫做 w × h；試過直接畫，原圖細咗 1.5 倍，同框對唔上
        page_rect = QRectF(0, 0, w, h)
        sheet = QImage(w * 2 + 10, h, QImage.Format.Format_RGB32)
        sheet.fill(QColor("black"))
        p = QPainter(sheet)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawImage(page_rect, self.image)
        p.translate(w + 10, 0)
        p.drawImage(page_rect, self.image)
        paint_blocks(p, self.blocks, w, h)
        p.setFont(make_font(CHINESE_FONTS, 10, bold=True))
        for i, block in enumerate(self.blocks, start=1):
            x1, y1, x2, y2 = block["box"]
            color = (QColor("#2e7d32") if block.get("shape") else
                     QColor("#1565c0") if block.get("patch") is not None else QColor("#ef6c00"))
            p.setPen(QPen(QColor("#ff4081"), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r1, s1, r2, s2 = block.get("reader_box", block["box"])
            p.drawRect(QRectF(r1 * w, s1 * h, (r2 - r1) * w, (s2 - s1) * h))
            if block.get("shape"):
                a1, b1, a2, b2 = block["shape"]["area"]
                p.setPen(QPen(color, 1.5))
                p.drawRect(QRectF(a1 * w, b1 * h, (a2 - a1) * w, (b2 - b1) * h))
            if block.get("patch") is not None:
                p.setPen(QPen(color, 1.5))
                for t1, u1, t2, u2 in block.get("regions") or [block["text_box"]]:
                    p.drawRect(QRectF(t1 * w, u1 * h, (t2 - t1) * w, (u2 - u1) * h))
            tag = QRectF(x1 * w, y1 * h, 20, 16)
            p.fillRect(tag, color)
            p.setPen(QColor("white"))
            p.drawText(tag, Qt.AlignmentFlag.AlignCenter, str(i))
        p.end()
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / f"lens_{time.strftime('%H%M%S')}.png"
        sheet.save(str(path))
        print(f"除錯圖：{path}")
        for i, block in enumerate(self.blocks, start=1):
            why = "、".join(block.get("why") or ["?"])
            reason = ("形狀" if block.get("shape") else f"抹字補圖（唔用對白框：{why}）"
                      if block.get("patch") is not None else f"舊方法：{why}")
            print(f"    {i}. {reason}　框 {[round(v, 3) for v in block['box']]}")

    def save_shot(self):
        """存「蓋咗字」嘅圖：讀字嗰刻截落嘅畫面，再畫返而家塊鏡上面嘅譯文；順手複製落剪貼簿。"""
        if self.image is None or not self.blocks:
            self._flash("📷 未有譯文，冇嘢存（先撳 🔍 讀字）")
            return
        if any(block["translation"] is None for block in self.blocks):
            self._flash("📷 仲譯緊，等譯完先存")
            return
        # 張截圖帶住螢幕縮放（150%），畫筆用返塊鏡嘅座標（同 paintEvent 一樣），存出嚟係實際像素
        shot = QImage(self.image).convertToFormat(QImage.Format.Format_RGB32)
        shot.setDevicePixelRatio(self.image.devicePixelRatio())
        p = QPainter(shot)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        paint_blocks(p, self.blocks, self.width(), self.height())
        p.end()
        SHOT_DIR.mkdir(exist_ok=True)
        path = SHOT_DIR / f"譯鏡_{time.strftime('%Y%m%d_%H%M%S')}.png"
        if not shot.save(str(path)):
            self._flash("⚠️ 存唔到截圖")
            return
        QApplication.clipboard().setImage(shot)
        print(f"📷 存咗：{path}")
        self._flash(f"📷 存咗 {path.name}（已複製）")

    @staticmethod
    def open_shots():
        SHOT_DIR.mkdir(exist_ok=True)
        os.startfile(SHOT_DIR)      # 用檔案總管開

    def _flash(self, text, seconds=2.5):
        self._set_status(text)
        QTimer.singleShot(int(seconds * 1000), lambda: self._set_status("") if self.status == text else None)

    def clear(self, reason=""):
        self.job += 1           # 仲譯緊嘅結果都唔要
        self.blocks = []
        if not self.auto:
            self.watcher.stop()     # 自動模式要繼續睇住，等畫面停定再讀
        self._set_status(reason)
        if reason:
            QTimer.singleShot(1500, lambda: self._set_status("") if self.status == reason else None)

    def _watch(self):
        """每 0.5 秒：畫面變咗（捲咗頁、揭咗頁）就收起舊譯文；自動模式再等畫面停定先讀。"""
        if not self.isVisible() or (not self.blocks and not self.auto):
            self.watcher.stop()
            return
        view = thumbnail(grab(self))
        if self.blocks and self.snapshot is not None and difference(view, self.snapshot) > CHANGED:
            # 自動模式唔出提示：捲一捲就閃一次字好煩，反正停定就會讀
            self.clear("" if self.auto else "畫面變咗，收起譯文")
        if not self.auto:
            return
        if self.worker.busy or self.adjusting:
            self.last_view, self.still = view, 0
            return
        steady = self.last_view is not None and difference(view, self.last_view) <= STILL
        self.still = self.still + 1 if steady else 0
        self.last_view = view
        # 同上次讀字嗰陣一樣嘅畫面唔使再讀（冇字嘅畫面都係）
        new_view = self.snapshot is None or difference(view, self.snapshot) > CHANGED
        if new_view and self.still >= STILL_TICKS:
            self.still = 0
            self.read()

    def _set_status(self, text):
        self.status = text
        self.update()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.blocks:
            self.clear()        # 塊鏡郁咗，舊譯文已經對唔上

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.blocks:
            self.clear()

    # ---------- 畫 ----------
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        if self.showing_original:
            return      # 連狀態字都唔畫：佢喺頂嗰條，會遮住最上面嘅原文
        paint_blocks(p, self.blocks, w, h)
        if self.status:
            box = QRectF(0, 0, w, 24)
            p.fillRect(box, QColor(0, 0, 0, 190))
            p.setPen(QColor("#ffd54a"))
            p.setFont(make_font(CHINESE_FONTS, 10, bold=True))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.status)


def main():
    parser = argparse.ArgumentParser(description="譯鏡示範")
    parser.add_argument("--debug-dir", help="每讀完一頁，存一張對比圖去呢個資料夾（除錯用）")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(200)
    app.setQuitOnLastWindowClosed(False)

    print(f"載入翻譯模型：{warm_up():.1f} 秒")
    glossary = load_glossary(GLOSSARY) if GLOSSARY.exists() else []
    lens = Lens(HKTranslator(glossary, names=memory()), debug_dir=args.debug_dir)
    lens.show()
    names = load_hotkeys()
    keys = GlobalHotkeys(app)
    for name, action in (("譯鏡調整", lens.toggle_adjusting), ("譯鏡讀字", lens.read), ("譯鏡自動", lens.toggle_auto)):
        problem = keys.register(names[name], action)
        print(f"熱鍵 {names[name]}（{name}）：{'OK' if problem is None else '登記唔到：' + problem}")

    tray = QSystemTrayIcon(make_icon(GLASS_COLOR.name()), app)
    tray.setToolTip(f"譯鏡示範｜{names['譯鏡讀字']} 讀字翻譯")
    menu = QMenu()
    for text, action in ((f"讀字翻譯（{names['譯鏡讀字']}）", lens.read), ("收起譯文", lens.clear),
                         (f"調整譯鏡（{names['譯鏡調整']}）", lens.toggle_adjusting), ("閂示範", app.quit)):
        item = QAction(text, menu)
        item.triggered.connect(action)
        menu.addAction(item)
    for text, action in (("存截圖", lens.save_shot), ("開截圖資料夾", lens.open_shots)):
        item = QAction(text, menu)
        item.triggered.connect(action)
        menu.insertAction(menu.actions()[-1], item)
    menu.insertMenu(menu.actions()[-1], target_menu(lens.target_changed, menu))     # 擺喺「閂示範」上面
    menu.insertMenu(menu.actions()[-1], works_menu(lens.work_changed, menu))
    menu.insertMenu(menu.actions()[-1], font_menu("譯鏡", lens.font_changed, menu))
    menu.insertAction(menu.actions()[-1], lens.auto_action(menu))
    menu.insertAction(menu.actions()[-1], lens.sound_effects_action(menu))
    tray.setContextMenu(menu)
    tray.show()
    lens.add_toolbar(extra=[("🔍", f"讀字翻譯（{names['譯鏡讀字']}）", lens.read),
                            ("📷", "存蓋咗字嘅截圖（順手複製）", lens.save_shot)], menu=menu)
    print(f"示範開咗：將塊鏡放喺漫畫上面，撳 {names['譯鏡讀字']} 或者 🔍")
    app.exec()


if __name__ == "__main__":
    main()
