# 譯幕 第6期第5關：抹字補圖
#
# 做咩：冇對白框嘅字（旁白、擬聲字、寫喺畫上面嘅字），用兩個開源模型處理：
#   1. 搵字（comic-text-detector，漫畫專用）：逐粒像素標出邊度係字嘅筆劃，連擬聲字都搵到；
#      讀字模型（Qwen3-VL）個框成日偏咗，用呢個「黐」返正確位置
#   2. 補圖（LaMa）：將字筆劃抹走，睇住周圍幅畫補返背景，唔再用色塊遮住幅畫
#   兩個都經 DirectML 用 GPU 行（onnxruntime-directml）：CPU 試過搵字一頁 14 秒、補圖每嚿 1.1 秒，
#   GPU 係 0.02 秒同 0.09 秒。補圖模型要先用 p6_5_fix_lama.py 改過先行得到 GPU。
# 點用：p6_3_lens.py 會 import 呢度嘅 TextEraser；直接行係自我測試：
#   .venv\Scripts\python -W ignore p6_5_inpaint.py [存對比圖嘅資料夾]

import gc
import sys
import threading
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy import ndimage

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

FINDER_MODEL = Path("models/ctd/comictextdetector.pt.onnx")
LAMA_MODEL = Path("models/lama/lama_fp32_dml.onnx")
# 閒咗幾多秒釋放搵字補圖模型（約 1.7 GB VRAM）：同 Ollama 讀字模型 keep_alive 10 分鐘一致；
# 再用要等大約 6 秒載返。每隔幾多秒睇一次閒咗未
IDLE_UNLOAD = 600
IDLE_CHECK = 30
FIND_SIZE = 1024        # 搵字模型固定食 1024 × 1024
LAMA_SIZE = 512         # 補圖模型固定食 512 × 512
TEXT_PROB = 0.3         # 搵字模型話「係字」嘅機會高過咁多就當係筆劃（官方預設）
BOX_CONF = 0.4          # 字框信心（官方預設）
BOX_OVERLAP = 0.35      # 兩個字框重疊咁多就當同一個，留信心高嗰個（官方預設）
# 讀字模型個框偏咗都要搵得返：喺佢四邊再擴咁多（框嘅比例）去搵字
SNAP_GROW = 0.5
SNAP_MIN_GROW = 24      # 細框最少擴幾多像素
SNAP_OWN = 0.5          # 搵字模型個框有一半以上喺擴大咗嘅範圍入面，先當係呢段字
SHIFT_MATCH = 0.15      # 計成頁偏差時，讀字框同搵字框相距少過塊鏡對角線咁多先當配得上
PAIR_MATCH = 0.12       # 第二輪配對：相距少過塊鏡對角線咁多
PAIR_SIZE = 4           # 第二輪配對：兩個框面積最多差幾多倍
# 抹字範圍：筆劃擴大少少，字邊淡淡哋嗰圈、旁白嘅白色描邊都要抹埋。
# 按字框短邊（大約一行字咁高）計，試過固定 4 像素，旁白嘅白邊留低咗一圈
HOLE_GROW = 0.12
HOLE_GROW_RANGE = (3, 12)
# 擬聲字：筆劃圖本身已經包埋粗描邊，再按字框大細擴（大字擴 12 像素）會連字與字之間嘅網點都抹埋，
# 補圖模型補唔返網點，變咗一嚿嚿光滑白色、灰色（睇落似殘影）
SOUND_GROW = 4
LINE_LONGER = 1.1       # 抹字範圍入面嘅黑線長過字框咁多倍就當係格邊、框邊，唔抹
LINE_MIN = 40           # 最短幾多像素先算係線（細字框嘅字都唔會俾當線）
LINE_DARK = 100         # 幾黑先算係線（灰階 0 至 255）
CONTEXT = 0.6           # 交俾補圖模型嘅一嚿圖，喺要抹嘅範圍外面再包幾多（比例）：要有周圍嘅畫先補得似
MIN_CONTEXT = 32        # 最少包幾多像素
JOIN_GAP = 8            # 相隔唔夠咁多像素嘅字一齊補，費事逐粒字截一嚿
# 拆字框（第 8 期）：搵字模型會將幾個黐埋嘅對白框嘅字框做一個（試過「神殿の力を…」同「言ってなかった…」
# 兩個框一個字框，譯文一條長直行跨過三個框），又會漏咗細字（「あぁ」「んだっけ？」）。
# 所以喺筆劃圖入面自己搵一行行字，再分組：同一個對白框嘅行，行距窄、頭尾對齊
# 兩行之間空位闊過一行字粗幼嘅咁多倍，就當唔同對白框。實測：同一個框嘅行距最闊 1.07（「た…タダシ様／
# これはいったい？」），黐埋嘅兩個框 1.6（「言ってなかった…／んだっけ？」），取中間
LINE_GAP = 1.3
LINE_OVERLAP = 0.3      # 兩行頭尾重疊少過短嗰行嘅咁多，就當唔同對白框（例如上一個框講完，下一行喺下面先開始）
# 一行粗過中位數咁多倍就自己一組：擬聲字（「じーっ」闊 85 像素）貼住對白（29 像素）都唔好撈埋。
# 淨係睇「粗過」：注音（ふりがな）幼過正文，要同正文一齊
THICK_ALONE = 2.0
SPARSE_JOIN = 1.5       # 疏嘅點淨係可以同闊過行粗咁多倍嘅行（擬聲字）合組
SPARSE = 0.25           # 一行筆劃密度低過咁多（一串點）就唔同其他行合組
BIG_STROKE = 1.5        # 闊行入面一粒筆劃大過行粗幼咁多倍就當係擬聲字嗰種大字
PIECE_GAP = 1.0         # 同一行入面空咗多過一個字咁長，就切開做兩段
MIN_PIECE = 12          # 少過咁多粒筆劃像素嘅一段唔要（雜點）
RUBY_THIN = 0.6         # 幼過行粗幼咁多倍嘅行當係注音，估字數唔計
DUPLICATE = 0.8         # 拆完兩個字框重疊多過細嗰個嘅咁多就當同一個
BOX_PAD = 3             # 拆出嚟嘅字框四邊加幾多像素：畫編號紅框唔好壓住筆劃
# 冇字框包住嘅筆劃（搵字模型漏咗）：一嚿要夠咁多粒像素、筆劃機會平均夠高先補字框，費事網點、花紋當咗字
LEFTOVER_MIN = 150
LEFTOVER_PROB = 0.6


def to_array(image):
    """QImage → numpy 陣列（高 × 闊 × RGB），方便一次過計成張圖。

    一定要 copy：轉格式會整一張臨時 QImage，陣列淨係指住佢嘅記憶體；function 完咗 Qt 就收走，
    之後再讀成個程式會爆（試過真截圖係 RGB32，譯鏡一讀字就冇聲冇氣閂咗）。
    """
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    data = image.constBits()
    data.setsize(image.sizeInBytes())
    rows = np.frombuffer(data, np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width() * 3].reshape(image.height(), image.width(), 3).copy()


def to_image(array):
    """numpy 陣列（RGB 或者灰階）→ QImage；copy() 等佢唔再靠住 numpy 嗰嚿記憶體。"""
    array = np.ascontiguousarray(array, np.uint8)
    h, w = array.shape[:2]
    if array.ndim == 2:
        return QImage(array.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()
    channels = array.shape[2]
    fmt = QImage.Format.Format_RGBA8888 if channels == 4 else QImage.Format.Format_RGB888
    return QImage(array.tobytes(), w, h, w * channels, fmt).copy()


def resize(array, w, h, smooth=True):
    """用 Qt 縮放：快過自己用 numpy 計；遮罩要用 smooth=False（唔好整出半透明邊）。"""
    mode = Qt.TransformationMode.SmoothTransformation if smooth else Qt.TransformationMode.FastTransformation
    scaled = to_image(array).scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
    if array.ndim == 2:
        scaled = scaled.convertToFormat(QImage.Format.Format_Grayscale8)
        data = scaled.constBits()
        data.setsize(scaled.sizeInBytes())
        return np.frombuffer(data, np.uint8).reshape(h, scaled.bytesPerLine())[:, :w].copy()
    return to_array(scaled)


def open_session(path):
    """有 DirectML 就用 GPU，冇就用 CPU（慢好多，但照用得）。"""
    options = ort.SessionOptions()
    # DirectML 官方要求：唔好預先規劃記憶體、一個個運算順住做
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
    return ort.InferenceSession(str(path), options, providers=providers)


def keep_best(boxes, scores):
    """重疊嘅字框淨係留信心最高嗰個（non-maximum suppression）。"""
    kept = []
    for i in np.argsort(-scores):
        if all(overlap_ratio(boxes[i], boxes[j]) <= BOX_OVERLAP for j in kept):
            kept.append(i)
    return boxes[kept]


def overlap_ratio(a, b):
    """交集 ÷ 並集。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def intersection(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


class TextEraser:
    """搵字＋補圖。兩個模型第一次用先載入（要幾秒，又佔大約 1.7GB VRAM）；閒咗 IDLE_UNLOAD 秒就釋放，
    下次用先載返（同 Ollama 讀字模型 keep_alive 10 分鐘一致）。以前一載就留到閂程式，淨用其他程式都霸住 VRAM"""

    def __init__(self):
        self.finder = None
        self.lama = None
        self.lock = threading.Lock()    # 背景載入、讀字、閒置釋放三條線可能同時想郁
        self.last_used = 0.0
        self.watching = False

    def available(self):
        return FINDER_MODEL.exists() and LAMA_MODEL.exists()

    def load(self):
        self._sessions()

    def _sessions(self):
        """攞住兩個模型（未載就載）：回傳嘅係呢一刻嘅參照，閒置線就算啱啱釋放，手上呢份都會用完先清。"""
        with self.lock:
            if self.finder is None:
                start = time.perf_counter()
                self.finder = open_session(FINDER_MODEL)
                self.lama = open_session(LAMA_MODEL)
                # 熱身：GPU 第一次行要準備（補圖第一次 1.3 秒，之後 0.09 秒），唔好喺用戶等緊嗰陣先做
                self.finder.run(None, {"images": np.zeros((1, 3, FIND_SIZE, FIND_SIZE), np.float32)})
                self.lama.run(None, {"image": np.zeros((1, 3, LAMA_SIZE, LAMA_SIZE), np.float32),
                                     "mask": np.zeros((1, 1, LAMA_SIZE, LAMA_SIZE), np.float32)})
                print(f"載入搵字同補圖模型：{time.perf_counter() - start:.1f} 秒（{self.finder.get_providers()[0]}）")
            self.last_used = time.monotonic()
            if not self.watching:
                self.watching = True
                threading.Thread(target=self._watch_idle, daemon=True).start()
            return self.finder, self.lama

    def _watch_idle(self):
        """背景線：每 IDLE_CHECK 秒睇一次，閒咗超過 IDLE_UNLOAD 秒就放手，VRAM 即刻還返。"""
        while True:
            time.sleep(IDLE_CHECK)
            with self.lock:
                if self.finder is not None and time.monotonic() - self.last_used > IDLE_UNLOAD:
                    self.finder = self.lama = None
                    gc.collect()        # 即刻清：唔等 Python 自己得閒先放 GPU 記憶體
                    print(f"搵字同補圖模型閒咗 {IDLE_UNLOAD // 60} 分鐘，釋放咗（下次讀字再載）")

    def find(self, rgb):
        """回傳（每粒像素係字嘅機會 0 至 1, 字框 [[x1, y1, x2, y2], ...] 像素）。"""
        finder, _ = self._sessions()
        h, w = rgb.shape[:2]
        scale = FIND_SIZE / max(w, h)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        # 同官方一樣：保持比例縮放，擺喺左上角，右邊同下面補黑色
        canvas = np.zeros((FIND_SIZE, FIND_SIZE, 3), np.uint8)
        canvas[:nh, :nw] = resize(rgb, nw, nh)
        blocks, seg, _lines = finder.run(None, {"images": canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255})
        prob = resize((seg[0, 0, :nh, :nw] * 255).astype(np.uint8), w, h).astype(np.float32) / 255
        rows = blocks[0]
        scores = rows[:, 4] * rows[:, 5:].max(axis=1)       # 有字嘅信心 × 類別信心
        rows, scores = rows[scores > BOX_CONF], scores[scores > BOX_CONF]
        boxes = np.stack([rows[:, 0] - rows[:, 2] / 2, rows[:, 1] - rows[:, 3] / 2,
                          rows[:, 0] + rows[:, 2] / 2, rows[:, 1] + rows[:, 3] / 2], axis=1) / scale
        boxes = keep_best(boxes, scores) if len(boxes) else boxes.reshape(0, 4)
        boxes = split_boxes(prob, np.clip(boxes, 0, [w, h, w, h]))
        return prob, boxes

    def erase(self, rgb, hole):
        """將 hole（True = 要抹）嘅位補返背景；逐嚿截出嚟交補圖模型，唔使成張圖縮細。"""
        _, lama = self._sessions()
        result = rgb.copy()
        h, w = hole.shape
        groups, count = ndimage.label(ndimage.binary_dilation(hole, iterations=JOIN_GAP))
        for found in ndimage.find_objects(groups):
            y1, y2, x1, x2 = found[0].start, found[0].stop, found[1].start, found[1].stop
            pad = max(MIN_CONTEXT, int(max(x2 - x1, y2 - y1) * CONTEXT))
            # 盡量截正方形：補圖模型食正方形，太扁縮落去會變形
            side = max(x2 - x1, y2 - y1) + 2 * pad
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cx1, cy1 = max(0, cx - side // 2), max(0, cy - side // 2)
            cx2, cy2 = min(w, cx1 + side), min(h, cy1 + side)
            cx1, cy1 = max(0, cx2 - side), max(0, cy2 - side)
            crop, mask = result[cy1:cy2, cx1:cx2], hole[cy1:cy2, cx1:cx2]
            if not mask.any():
                continue
            ch, cw = mask.shape
            image = resize(crop, LAMA_SIZE, LAMA_SIZE).transpose(2, 0, 1)[None].astype(np.float32) / 255
            small = resize(mask.astype(np.uint8) * 255, LAMA_SIZE, LAMA_SIZE, smooth=False) > 127
            out = lama.run(None, {"image": image, "mask": small[None, None].astype(np.float32)})[0][0]
            filled = resize(np.clip(out.transpose(1, 2, 0), 0, 255).astype(np.uint8), cw, ch)
            crop[mask] = filled[mask]       # 淨係換抹咗嘅位，其他像素保持原圖
        return result


def runs_of(flags):
    """一串 True／False 入面一段段連住嘅 True：[(開始, 結束)]（唔包結束）。"""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], flags.astype(np.int8), [0]])))
    return list(zip(edges[::2], edges[1::2]))


def weighted_median(values, weights):
    order = np.argsort(values)
    values, weights = np.asarray(values, float)[order], np.asarray(weights, float)[order]
    half = weights.sum() / 2
    return float(values[np.searchsorted(np.cumsum(weights), half)])


def text_lines(mask, vertical):
    """mask 入面一行行字：回傳（[(橫向開始, 結束, 直向開始, 結束)], 一行字嘅粗幼）。
    直排嘅「行」係一條條直柱（左右之間有空位）；每條再按上下嘅大空位切開（兩個框嘅字啱啱喺同一條直線上）。
    打橫就將成張 mask 轉 90 度用同一套。"""
    m = mask if vertical else mask.T
    columns = [(a, b) for a, b in runs_of(m.any(axis=0)) if m[:, a:b].sum() >= MIN_PIECE]
    if not columns:
        return [], 0
    # 行粗幼按筆劃多少加權：字框併咗隔籬啲「…」、細線入嚟，幾粒細嘢唔好拉低中位數
    # （試過「身体に力が入らない…」中位數由 136 跌到 12，直排當咗打橫切成三截）
    thick = weighted_median([b - a for a, b in columns], [m[:, a:b].sum() for a, b in columns])
    # 特別闊嘅一行再細分：擬聲字嘅筆劃伸過嚟同隔籬對白嗰行左右疊埋，投影冇空位，兩樣當咗一條粗行
    # （試過「フラ…」連埋對白框最右嗰行「君に術をかけた」，成句對白讀咗落錯嘅字框）。
    # 入面逐粒獨立筆劃睇大細：正常字咁大嘅、特別大嘅（擬聲字）各自再搵一次行
    split = []
    for a, b in columns:
        if b - a > THICK_ALONE * thick:
            split += split_wide(m, a, b, thick)
        else:
            split.append((a, b, m))
    pieces = []
    for a, b, layer in split:
        parts = []
        for start, end in runs_of(layer[:, a:b].any(axis=1)):
            # 字同字之間嘅細空位（例如「…」）唔切；空位按呢行自己同正常行粗，邊個大用邊個：
            # 擬聲字嘅大字之間隔得遠（「フ」「ラ」相隔 61 像素，正常行粗 53），唔好切碎
            if parts and start - parts[-1][1] <= PIECE_GAP * max(thick, b - a):
                parts[-1] = (parts[-1][0], end)
            else:
                parts.append((start, end))
        pieces += [(a, b, start, end) for start, end in parts if layer[start:end, a:b].sum() >= MIN_PIECE]
    return pieces, thick


def split_wide(m, a, b, thick):
    """一條特別闊嘅行：筆劃按大細分開兩層（正常字、特別大），每層各自再按左右空位分行。
    回傳 [(開始, 結束, 嗰層 mask)]；分唔開就照舊一條。"""
    labels, count = ndimage.label(m[:, a:b], structure=np.ones((3, 3)))
    if count < 2:
        return [(a, b, m)]
    big = np.zeros(count + 1, bool)
    for i, found in enumerate(ndimage.find_objects(labels), 1):
        big[i] = max(found[0].stop - found[0].start, found[1].stop - found[1].start) > BIG_STROKE * thick
    if big[1:].all() or not big[1:].any():
        return [(a, b, m)]
    result = []
    for wanted in (False, True):
        layer = np.zeros_like(m)
        layer[:, a:b] = (labels > 0) & (big[labels] == wanted)
        result += [(a + c1, a + c2, layer) for c1, c2 in runs_of(layer[:, a:b].any(axis=0))
                   if layer[:, a + c1:a + c2].sum() >= MIN_PIECE]
    return result


def group_lines(pieces, thick, alone=()):
    """將一行行字分組：行距窄兼頭尾對齊嘅係同一組（同一個對白框）。回傳 [[piece, ...], ...]。
    alone：好疏嘅行（第幾條），淨係可以同粗大嘅行合組。"""
    group = list(range(len(pieces)))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i
    for i, (a1, b1, s1, e1) in enumerate(pieces):
        for j in range(i + 1, len(pieces)):
            a2, b2, s2, e2 = pieces[j]
            gap = max(a2 - b1, a1 - b2)                 # 左右（直排）之間嘅空位；負數即係疊埋
            shared = min(e1, e2) - max(s1, s2)          # 上下（直排）重疊咗幾長
            thicker = max(b1 - a1, b2 - a2) > THICK_ALONE * thick and                 max(b1 - a1, b2 - a2) > THICK_ALONE * min(b1 - a1, b2 - a2)
            # 疏嘅點（alone）淨係可以跟粗大嘅字（擬聲字）一組：「フラ…」嗰串點屬於「フラ」，唔屬於隔籬對白；
            # 試過自己做一個字框，讀字模型亂咁讀成「Ooo...」
            if i in alone or j in alone:
                wide = max(b1 - a1, b2 - a2)
                if wide <= SPARSE_JOIN * thick:
                    continue
                # 點喺大字正下面（同一條直線、上下貼近），係接住落去嘅「…」
                below = max(s2 - e1, s1 - e2)
                if gap < 0 and below <= PIECE_GAP * wide:
                    group[root(i)] = root(j)
                    continue
            if not thicker and gap <= LINE_GAP * thick and shared >= LINE_OVERLAP * min(e1 - s1, e2 - s2):
                group[root(i)] = root(j)
    groups = {}
    for i, piece in enumerate(pieces):
        groups.setdefault(root(i), []).append(piece)
    return list(groups.values())


def split_box(mask, left, top):
    """一個字框入面嘅字分組，每組一個字框（像素）；分唔開（得一組）回傳 None。
    直排定打橫：揀「行」拉得最長嗰種（直排字用直柱切，每條都瘦長；用打橫切會變成一大嚿）。"""
    best = None
    for vertical in (True, False):
        pieces, thick = text_lines(mask, vertical)
        if not pieces:
            continue
        # 「行」有幾瘦長，按每段筆劃多少加權平均：細點細線唔好同真正嘅字有同等票數
        ink = [mask[s:e, a:b].sum() if vertical else mask[a:b, s:e].sum() for a, b, s, e in pieces]
        stretch = np.average([(e - s) / max(1, b - a) for a, b, s, e in pieces], weights=ink)
        if best is None or stretch > best[0]:
            best = (stretch, vertical, pieces, thick)
    if best is None:
        return None
    _, vertical, pieces, thick = best
    # 好疏嘅一行（「…」一串點）唔同人合組：試過擬聲字「フラ…」嗰串點貼住對白最右行，撈埋之後對白字框包埋擬聲字。
    # 正常字密度 0.42 至 0.61，嗰串點 0.15
    layer = mask if vertical else mask.T
    alone = {i for i, (a, b, s, e) in enumerate(pieces) if layer[s:e, a:b].mean() < SPARSE}
    groups = group_lines(pieces, thick, alone)
    if len(groups) < 2:
        return None
    h, w = mask.shape
    boxes = []
    for pieces in groups:
        a1, a2 = min(p[0] for p in pieces), max(p[1] for p in pieces)
        s1, s2 = min(p[2] for p in pieces), max(p[3] for p in pieces)
        x1, y1, x2, y2 = (a1, s1, a2, s2) if vertical else (s1, a1, s2, a2)
        boxes.append([left + max(0, x1 - BOX_PAD), top + max(0, y1 - BOX_PAD),
                      left + min(w, x2 + BOX_PAD), top + min(h, y2 + BOX_PAD)])
    return boxes


def estimate_chars(prob, box):
    """估計字框入面大約有幾多隻字：每行長度 ÷ 行粗幼（漢字、假名大約正方形）。
    英文字母窄過一格，只會估少唔會估多；注音（幼過正文嘅行）唔計。"""
    x1, y1, x2, y2 = (int(v) for v in box)
    mask = prob[y1:y2, x1:x2] > TEXT_PROB
    best = None
    for vertical in (True, False):
        pieces, thick = text_lines(mask, vertical)
        if not pieces:
            continue
        ink = [mask[s:e, a:b].sum() if vertical else mask[a:b, s:e].sum() for a, b, s, e in pieces]
        stretch = np.average([(e - s) / max(1, b - a) for a, b, s, e in pieces], weights=ink)
        if best is None or stretch > best[0]:
            best = (stretch, pieces, thick)
    if best is None:
        return 0.0
    _, pieces, thick = best
    return float(sum((e - s) / thick for a, b, s, e in pieces if b - a >= RUBY_THIN * thick))


def split_boxes(prob, boxes):
    """拆開包住幾個對白框嘅字框，再幫搵字模型漏咗嘅字補字框（像素）。"""
    mask = prob > TEXT_PROB
    h, w = mask.shape
    boxes = [[int(v) for v in box] for box in boxes]

    def leftovers():
        """冇字框包住嘅筆劃，相近嘅撈埋一嚿（一個字嘅幾劃、一行嘅幾個字）：[(範圍 slice, 筆劃)]"""
        covered = np.zeros_like(mask)
        for x1, y1, x2, y2 in boxes:
            covered[max(0, y1 - BOX_PAD):y2 + BOX_PAD, max(0, x1 - BOX_PAD):x2 + BOX_PAD] = True
        rest = mask & ~covered
        labels, _ = ndimage.label(ndimage.binary_dilation(rest, iterations=JOIN_GAP))
        return [(found, rest[found] & (labels[found] == i)) for i, found in enumerate(ndimage.find_objects(labels), 1)]
    # 黐住字框嘅漏字併入去先分組：試過「あぁ」喺字框隔籬，自己變咗一個框，同「神殿の力を…」分開咗讀
    for found, region in leftovers():
        ys, xs = np.nonzero(region)
        top, left = found[0].start, found[1].start
        x1, y1, x2, y2 = left + xs.min(), top + ys.min(), left + xs.max() + 1, top + ys.max() + 1
        for box in boxes:
            if x1 <= box[2] + JOIN_GAP and x2 >= box[0] - JOIN_GAP and y1 <= box[3] + JOIN_GAP and y2 >= box[1] - JOIN_GAP:
                box[:] = [min(box[0], x1), min(box[1], y1), max(box[2], x2), max(box[3], y2)]
                break
    result = []
    for x1, y1, x2, y2 in boxes:
        parts = split_box(mask[y1:y2, x1:x2], x1, y1)
        result += parts if parts else [[x1, y1, x2, y2]]
    # 離字框遠嘅漏字：自己做字框，照樣分組
    for found, region in leftovers():
        if region.sum() < LEFTOVER_MIN or prob[found][region].mean() < LEFTOVER_PROB:
            continue
        top, left = found[0].start, found[1].start
        parts = split_box(region, left, top)
        if parts is None:
            ys, xs = np.nonzero(region)
            parts = [[left + max(0, xs.min() - BOX_PAD), top + max(0, ys.min() - BOX_PAD),
                      left + min(region.shape[1], xs.max() + 1 + BOX_PAD), top + min(region.shape[0], ys.max() + 1 + BOX_PAD)]]
        result += parts
    # 兩個搵字框各自拆出同一行（一個大框包住幾行、另一個淨係包住其中一行），會得到差唔多一樣嘅字框，
    # 同一段字讀兩次、譯兩次：重疊多過細嗰個嘅 DUPLICATE 就淨留大嗰個
    result = sorted(result, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    kept = []
    for box in result:
        area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
        if all(intersection(box, other) < area * DUPLICATE for other in kept):
            kept.append(box)
    return np.array(kept, float).reshape(-1, 4).clip(0, [w, h, w, h])


def page_shift(reader_boxes, boxes, diagonal):
    """讀字模型成頁嘅框一齊偏咗幾多（像素）：真漫畫試過成頁偏 (+11, +35) 至 (+45, +42)，
    逐段黐位追唔到咁遠。每個讀字框配最近嘅搵字框，取中位數（個別配錯唔會拉歪），做三次逐步收窄。
    配得上嘅少過兩對就當冇偏。"""
    if len(reader_boxes) == 0 or len(boxes) == 0:
        return 0.0, 0.0
    q = np.asarray(reader_boxes, float)
    centres = np.stack([(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2], axis=1)
    shift = np.zeros(2)
    for _ in range(3):
        mine = np.stack([(q[:, 0] + q[:, 2]) / 2, (q[:, 1] + q[:, 3]) / 2], axis=1) + shift
        gaps = centres[None] - mine[:, None]                # 每個讀字框 → 每個搵字框
        distance = np.hypot(gaps[..., 0], gaps[..., 1])
        nearest = distance.argmin(axis=1)
        rows = np.arange(len(q))
        close = distance[rows, nearest] < SHIFT_MATCH * diagonal
        if close.sum() < 2:
            return 0.0, 0.0
        shift = shift + np.median(gaps[rows, nearest][close], axis=0)
    return float(shift[0]), float(shift[1])


def pair_leftovers(reader_boxes, owned, boxes, diagonal):
    """第二輪：校正咗都配唔到字框嘅段，喺附近未有人要嘅字框揀中心最近、大細差唔多嘅。

    試過讀字框偏咗 120 像素，掂唔到真正嗰個字框，譯文寫咗入隔籬嘅對白框。
    最近嘅一對先配，每個字框淨係配一段。回傳 {段編號: 字框編號}。"""
    used = set().union(*owned) if owned else set()
    pairs = []
    for i, box in enumerate(reader_boxes):
        if owned[i]:
            continue
        area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
        for j, b in enumerate(boxes):
            if j in used or not 1 / PAIR_SIZE <= (b[2] - b[0]) * (b[3] - b[1]) / area <= PAIR_SIZE:
                continue
            gap = np.hypot((b[0] + b[2] - box[0] - box[2]) / 2, (b[1] + b[3] - box[1] - box[3]) / 2)
            if gap < PAIR_MATCH * diagonal:
                pairs.append((gap, i, j))
    chosen = {}
    for _, i, j in sorted(pairs):
        if i not in chosen and j not in used:
            chosen[i] = j
            used.add(j)
    return chosen


def overlaps(a, b, share=0.5):
    """兩個框重疊咗細嗰個嘅一半以上。"""
    if a is None or b is None:
        return False
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return small > 0 and intersection(a, b) >= share * small


def grown_box(box):
    """讀字模型個框四邊擴大：佢個框偏咗都包得到真正嘅字。"""
    x1, y1, x2, y2 = box
    gx = max(SNAP_MIN_GROW, (x2 - x1) * SNAP_GROW)
    gy = max(SNAP_MIN_GROW, (y2 - y1) * SNAP_GROW)
    return (x1 - gx, y1 - gy, x2 + gx, y2 + gy)


def owned_boxes(box, boxes):
    """讀字模型個框（像素）屬於搵字模型邊幾個字框：一半以上喺擴大咗嘅範圍入面，又掂到原本個框。

    兩段字掂到同一個字框，多數係讀字模型將一段字拆開咗（例如直排每行一段），要合埋先譯。
    """
    grown = grown_box(box)
    return [i for i, b in enumerate(boxes)
            if intersection(b, grown) >= SNAP_OWN * (b[2] - b[0]) * (b[3] - b[1])
            and intersection(b, box) > 0]       # 一定要掂到原本個框：唔好黐咗去隔籬段字


def stroke_box(box, prob):
    """搵字模型冇畫框嘅字（例如擬聲字）：用同原本個框有重疊嘅筆劃（連埋一嚿嚿計），搵唔到回 None。"""
    x1, y1, x2, y2 = box
    grown = grown_box(box)
    h, w = prob.shape
    gx1, gy1 = int(max(0, grown[0])), int(max(0, grown[1]))
    gx2, gy2 = int(min(w, grown[2])), int(min(h, grown[3]))
    strokes = prob[gy1:gy2, gx1:gx2] > TEXT_PROB
    if not strokes.any():
        return None
    groups, _ = ndimage.label(ndimage.binary_dilation(strokes, iterations=JOIN_GAP))
    inside = groups[max(0, int(y1) - gy1):max(0, int(y2) - gy1), max(0, int(x1) - gx1):max(0, int(x2) - gx1)]
    ids = np.unique(inside[inside > 0])
    if len(ids) == 0:
        return None
    ys, xs = np.nonzero(np.isin(groups, ids) & strokes)
    return (gx1 + xs.min(), gy1 + ys.min(), gx1 + xs.max() + 1, gy1 + ys.max() + 1)


def text_box_of(box, prob, boxes, owned):
    """真正嘅字範圍（像素）：有搵字模型字框就用佢哋合埋，冇就睇筆劃；搵唔到回 None。"""
    if owned:
        chosen = boxes[list(owned)]
        return (chosen[:, 0].min(), chosen[:, 1].min(), chosen[:, 2].max(), chosen[:, 3].max())
    return stroke_box(box, prob)


def snap(box, prob, boxes, taken):
    """讀字模型個框（像素）→ 真正嘅字範圍（像素），搵唔到回 None；taken 係已經俾其他段字揀咗嘅字框。"""
    mine = [i for i in owned_boxes(box, boxes) if i not in taken]
    taken.update(mine)
    return text_box_of(box, prob, boxes, mine)


def hole_for(text_box, prob, sound=False):
    """呢段字要抹嘅像素：範圍入面嘅筆劃，再擴大少少包埋描邊。sound：擬聲字，擴少啲（見 SOUND_GROW）。"""
    h, w = prob.shape
    x1, y1, x2, y2 = text_box
    if sound:
        grow = SOUND_GROW
    else:
        grow = int(np.clip(round(min(x2 - x1, y2 - y1) * HOLE_GROW), *HOLE_GROW_RANGE))
    margin = grow + 2
    a1, b1 = int(max(0, x1 - margin)), int(max(0, y1 - margin))
    a2, b2 = int(min(w, x2 + margin)), int(min(h, y2 + margin))
    hole = np.zeros((h, w), bool)
    hole[b1:b2, a1:a2] = ndimage.binary_dilation(prob[b1:b2, a1:a2] > TEXT_PROB, iterations=grow)
    return hole


def keep_lines(rgb, hole, box):
    """抹字範圍入面嘅格邊、框邊（又長又直嘅黑線）唔抹：試過「わいわい」連格邊條線都抹走咗。
    一條打橫或者打直嘅黑線長過字框嘅 LINE_LONGER 倍就當係格邊：字嘅筆劃喺字框入面，唔會長過字框。"""
    h, w = hole.shape
    x1, y1, x2, y2 = (int(v) for v in box)
    reach_x, reach_y = int((x2 - x1) * LINE_LONGER), int((y2 - y1) * LINE_LONGER)
    ys, xs = np.nonzero(hole)
    if len(ys) == 0:
        return hole
    # 喺抹字範圍四邊再擴一條線咁長嘅範圍入面數：格邊伸出字框外面先數得夠長
    a1, a2 = max(0, xs.min() - reach_x), min(w, xs.max() + 1 + reach_x)
    b1, b2 = max(0, ys.min() - reach_y), min(h, ys.max() + 1 + reach_y)
    crop = rgb[b1:b2, a1:a2].astype(np.float32)
    dark = crop[..., 0] * 0.299 + crop[..., 1] * 0.587 + crop[..., 2] * 0.114 < LINE_DARK
    line = np.zeros_like(dark)
    for mask, reach, out in ((dark, reach_x, line), (dark.T, reach_y, line.T)):
        for row in range(mask.shape[0]):
            for start, end in runs_of(mask[row]):
                if end - start > max(reach, LINE_MIN):
                    out[row, start:end] = True
    if not line.any():
        return hole
    line = ndimage.binary_dilation(line, iterations=1)     # 包埋線邊淡淡哋嗰圈
    kept = hole.copy()
    kept[b1:b2, a1:a2] &= ~line
    return kept


def main():
    """自我測試：假漫畫頁（旁白、網點上嘅直排字、擬聲字、對白框），扮讀字模型個框偏咗。"""
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)  # noqa: F841 —— 畫字要有 QApplication
    w, h = 900, 1300
    page = QImage(w, h, QImage.Format.Format_RGB888)
    p = QPainter(page)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, w, h)
    gradient.setColorAt(0, QColor("#d8d8d8"))
    gradient.setColorAt(1, QColor("#7a7a7a"))
    p.fillRect(0, 0, w, h, gradient)
    rng = np.random.default_rng(1)
    p.setPen(QPen(QColor("#303030"), 3))
    for _ in range(60):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        p.drawLine(QPointF(x, y), QPointF(x + rng.uniform(-200, 200), y + rng.uniform(-200, 200)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#555"))
    for yy in range(700, 1000, 9):
        for xx in range(0, 450, 9):
            p.drawEllipse(QPointF(xx, yy), 2, 2)

    def outlined(text, x, y, size, vertical=False, angle=0, fill="black", edge="white", edge_px=6):
        font = QFont("Yu Gothic UI", size)
        font.setBold(True)
        path = QPainterPath()
        for i, char in enumerate(text if vertical else [text]):
            path.addText(QPointF(0, i * size * 1.4), font, char)
        p.save()
        p.translate(x, y)
        p.rotate(angle)
        p.setPen(QPen(QColor(edge), edge_px))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawPath(path)
        p.restore()

    outlined("その日、街は静かだった", 60, 120, 28)
    outlined("まさか", 120, 760, 34, vertical=True)
    outlined("ドン", 520, 900, 90, angle=-12, fill="white", edge="black", edge_px=8)
    p.end()

    rgb = to_array(page.convertToFormat(QImage.Format.Format_RGB32))     # 同真截圖一樣格式
    eraser = TextEraser()
    eraser.load()
    # 扮讀字模型：個框偏咗（真實試過偏成百像素）
    fake = {"旁白": (90, 60, 460, 150), "直排": (90, 690, 190, 930), "擬聲字": (470, 760, 760, 950)}
    start = time.perf_counter()
    prob, boxes = eraser.find(rgb)
    found = time.perf_counter() - start
    hole = np.zeros(prob.shape, bool)
    taken = set()
    for name, box in fake.items():
        text_box = snap(box, prob, boxes, taken)
        print(f"{name}：讀字框 {box} → {None if text_box is None else tuple(int(v) for v in text_box)}")
        if text_box is not None:
            hole |= hole_for(text_box, prob)
    start = time.perf_counter()
    result = eraser.erase(rgb, hole)
    print(f"搵字 {found:.2f} 秒、補圖 {time.perf_counter() - start:.2f} 秒，抹咗 {hole.mean():.1%} 嘅像素")
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
        out.mkdir(parents=True, exist_ok=True)
        sheet = np.concatenate([rgb, np.repeat((hole * 255).astype(np.uint8)[:, :, None], 3, 2), result], axis=1)
        to_image(sheet).save(str(out / "inpaint_test.png"))
        print(f"對比圖：{out / 'inpaint_test.png'}")


if __name__ == "__main__":
    main()
