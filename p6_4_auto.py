# 譯幕 第6期第4關：自動模式要用嘅快取
#
# 做咩：捲返轉頭、揭返上一頁嗰陣，唔使再等讀字模型（每頁 3 至 7 秒，係最慢嗰步）：
#   1. 字框嘅「細圖」→ 讀到嘅字：喺字框入面搵出筆劃範圍，縮做 16 × 16 灰階（256 bytes），唔使存截圖；
#      下次見到一張好似嘅細圖（相關係數 ≥ 0.9）就當係同一個框
#   2. 原文 → 譯文：見過嘅句唔使再問翻譯模型
#   兩個都最多記 5000 個，滿咗踢走最耐冇用嗰個
# 點用：p6_3_lens.py 會 import 呢度；直接行係自我測試：.venv\Scripts\python -W ignore p6_4_auto.py

import sys
from collections import OrderedDict

import numpy as np
from scipy import ndimage

from p6_5_inpaint import resize, to_array

CACHE_SIZE = 5000       # 每個快取最多記幾多個：一頁大約 10 個框，夠睇幾百頁；5000 張細圖大約 1.3MB
THUMB_SIDE = 16         # 細圖 16 × 16
# 細圖相關係數高過咁多就當同一個框。試過：同一個框捲咗位、字框偏咗 10 粒像素都係 1.00，
# 唔同嘅字最高 0.14，所以 0.9 好安全
MATCH = 0.9
SIZE_TOLERANCE = 0.15   # 筆劃範圍闊高差唔多過 15% 先比較：大細唔同一定唔係同一個框
INK_CONTRAST = 60       # 同字框入面嘅中位數（底色）差咁多就當係筆劃
BOX_GROW = 0.08         # 字框四邊擴少少先搵筆劃：搵字模型個框偏咗都包得晒啲字
EMPTY = ""              # 讀字模型睇過、但入面冇要譯嘅字（例如淨係「！」）：都記低，下次唔使再問


def fingerprint(rgb, box):
    """字框嘅細圖：回傳（256 個數嘅單位向量, 筆劃範圍闊高），冇筆劃回 None。

    唔可以直接截字框：捲完再搵，搵字模型個框會偏幾粒像素，細圖就對唔上（試過偏 6 粒，相關係數跌到 0.56）。
    改為喺框入面搵筆劃範圍（同底色差得遠嘅像素）再截，字框點偏，筆劃都喺同一個位。"""
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = box
    gx, gy = (x2 - x1) * BOX_GROW, (y2 - y1) * BOX_GROW
    a1, b1 = int(max(0, x1 - gx)), int(max(0, y1 - gy))
    a2, b2 = int(min(w, x2 + gx)), int(min(h, y2 + gy))
    crop = rgb[b1:b2, a1:a2]
    if crop.size == 0:
        return None
    gray = crop[..., 0] * 0.299 + crop[..., 1] * 0.587 + crop[..., 2] * 0.114
    ink = np.abs(gray - np.median(gray)) > INK_CONTRAST
    # 掂到截圖邊嘅一嚿嚿唔要：多數係對白框外圈。試過擴咗範圍截埋外圈，唔同嘅字個個都似（外圈都一樣），認錯咗
    groups, _ = ndimage.label(ink)
    edge = np.unique(np.concatenate([groups[0], groups[-1], groups[:, 0], groups[:, -1]]))
    inside = ink & ~np.isin(groups, edge[edge > 0])
    ys, xs = np.nonzero(inside if inside.any() else ink)
    if len(ys) == 0:
        return None
    ink = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    vector = resize(ink, THUMB_SIDE, THUMB_SIDE).astype(np.float32).ravel()
    vector -= vector.mean()
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return None
    return vector / norm, (int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


class ReadingCache:
    """字框細圖 → 讀到嘅字（text、lang、sfx；冇字就 EMPTY）。"""

    def __init__(self, size=CACHE_SIZE):
        self.size = size
        self.entries = OrderedDict()    # 編號 → (細圖, 闊高, 讀到嘅字)；最近用過嘅排最後
        self.next_key = 0
        self.matrix = None              # 所有細圖砌成一個陣列，一次過計相關係數；有改動先重砌

    def get(self, print_):
        return self.find(print_)[1]

    def find(self, print_):
        """回傳（快取入面嗰個嘅編號, 讀到嘅字），搵唔到就（None, None）。編號用嚟認「成頁」（框外嘅字）。"""
        if print_ is None or not self.entries:
            return None, None
        vector, (width, height) = print_
        if self.matrix is None:
            self.keys = list(self.entries)
            self.matrix = np.stack([self.entries[k][0] for k in self.keys])
            self.sizes = np.array([self.entries[k][1] for k in self.keys], float)
        score = self.matrix @ vector    # 兩個單位向量嘅內積就係相關係數
        similar = (np.abs(self.sizes[:, 0] - width) <= width * SIZE_TOLERANCE) & \
                  (np.abs(self.sizes[:, 1] - height) <= height * SIZE_TOLERANCE)
        score = np.where(similar, score, -1.0)
        best = int(score.argmax())
        if score[best] < MATCH:
            return None, None
        key = self.keys[best]
        self.entries.move_to_end(key)
        return key, self.entries[key][2]

    def update(self, key, value):
        """改返已經記咗嗰個框讀到嘅字（例如再讀一次讀齊咗）。"""
        if key in self.entries:
            vector, size, _ = self.entries[key]
            self.entries[key] = (vector, size, value)

    def put(self, print_, value):
        """記低；回傳佢嘅編號（冇筆劃記唔到就 None）。"""
        if print_ is None:
            return None
        key = self.next_key
        self.entries[key] = (print_[0], print_[1], value)
        self.next_key += 1
        while len(self.entries) > self.size:
            self.entries.popitem(last=False)    # 踢走最耐冇用嗰個
        self.matrix = None
        return key


class TranslationCache:
    """（原文, 係咪擬聲字）→ 譯文。"""

    def __init__(self, size=CACHE_SIZE):
        self.size = size
        self.entries = OrderedDict()

    def get(self, text, sound=False):
        key = (text, sound)
        if key not in self.entries:
            return None
        self.entries.move_to_end(key)
        return self.entries[key]

    def put(self, text, sound, translation):
        self.entries[(text, sound)] = translation
        self.entries.move_to_end((text, sound))
        while len(self.entries) > self.size:
            self.entries.popitem(last=False)


def main():
    """自我測試：同一個對白框捲咗位、字框偏咗都認得返；唔同嘅字唔會認錯；滿咗踢走最舊嗰個。"""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)  # noqa: F841 —— 畫字要有 QApplication

    def page(offset, texts):
        image = QImage(600, 900, QImage.Format.Format_RGB32)
        image.fill(QColor("#e8e8e8"))
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Yu Gothic UI", 22)
        font.setBold(True)
        p.setFont(font)
        for i, text in enumerate(texts):
            top = 80 + i * 260 + offset
            p.setPen(QPen(QColor("black"), 3))
            p.setBrush(QColor("white"))
            p.drawEllipse(QRectF(150, top, 300, 200))
            p.drawText(QRectF(200, top + 50, 200, 100), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return to_array(image)

    texts = ["行くぞ！", "まさか", "明日は早い"]
    first, scrolled = page(0, texts), page(-37, texts)     # 捲咗 37 像素
    other = page(0, ["違う言葉", "ドン", "おはよう"])
    cache = ReadingCache()
    for i, text in enumerate(texts):
        cache.put(fingerprint(first, (190, 120 + i * 260, 410, 240 + i * 260)), {"text": text})
    ok = 0
    for i, text in enumerate(texts):
        top = 120 + i * 260 - 37
        hit = cache.get(fingerprint(scrolled, (190, top, 410, top + 120)))
        moved = cache.get(fingerprint(scrolled, (196, top - 6, 404, top + 126)))     # 字框偏咗 6 粒
        wrong = cache.get(fingerprint(other, (190, 120 + i * 260, 410, 240 + i * 260)))
        good = bool(hit and hit["text"] == text and moved and moved["text"] == text and wrong is None)
        ok += good
        print(f"「{text}」捲咗位：{hit and hit['text']}，字框偏咗：{moved and moved['text']}，"
              f"唔同嘅字：{wrong and wrong['text']}　{'✅' if good else '❌'}")
    small = TranslationCache(size=2)
    small.put("a", False, "甲")
    small.put("b", False, "乙")
    small.get("a")
    small.put("c", False, "丙")         # 「b」最耐冇用，應該俾人踢走
    lru = small.get("b") is None and small.get("a") == "甲" and small.get("c") == "丙"
    print(f"踢走最耐冇用嗰個：{'✅' if lru else '❌'}")
    print(f"{ok + lru}/{len(texts) + 1} 啱")


if __name__ == "__main__":
    main()
