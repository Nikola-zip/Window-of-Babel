# 譯幕 第6期第2步：譯鏡讀字
#
# 做咩：撳 Ctrl+Alt+T，截玻璃底下嘅畫面（玻璃自己唔會截到），交俾識睇圖嘅模型
#       （Ollama 嘅 Qwen3-VL 8B），攞返每段字嘅原文、位置同語言；
#       喺玻璃上面每段字嘅位置畫框同編號，terminal 印出每段字。截圖唔會存落硬碟。
# 點用：先開 Ollama，再喺終端機打：.venv\Scripts\python -W ignore p6_2_read.py
#       Ctrl+Alt+G 調整塊鏡，Ctrl+Alt+T 讀字；第 3 關會 import 呢度嘅 read_text() 同 ReadingGlass。

import base64
import json
import re
import urllib.error
import urllib.request

from PyQt6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

from p2_1_translate import OLLAMA

VISION_MODEL = "qwen3-vl:8b-instruct"   # instruct：唔會先長篇思考，答得快；冇揀過時嘅預設
_chosen = None      # 用家揀咗嘅讀字模型（settings.json「讀字模型」）；第一次用先讀設定，之後記住
READ_TIMEOUT = 180      # 第一次要將 6GB 模型搬入 VRAM，等耐啲
MAX_SIDE = 1600         # 截圖長邊最多幾多像素：圖越大模型要睇嘅格越多、越慢，對白字一般唔使咁清
SAME_BUBBLE = 0.8       # 兩段嘅框重疊咗細嗰個咁多（或以上），就當係同一個對白框
# 答案最多幾多格（token）：一段字大約 30 至 50 格，2048 夠四十幾段。試過模型卡住不停重複，
# 寫到 680 行、爆咗 num_ctx，JSON 俾人切斷，成頁讀唔到
MAX_ANSWER = 2048
# 叫模型用固定格式答：Ollama 會逼佢跟呢個 JSON 結構，唔會答一大段解釋
SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "bbox_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                    "lang": {"type": "string", "enum": ["ja", "en", "ko", "zh", "other"]},
                    "sfx": {"type": "boolean"},
                },
                "required": ["text", "bbox_2d", "lang", "sfx"],
            },
        }
    },
    "required": ["blocks"],
}
# 用英文寫：模型對英文指示跟得最穩；座標用 Qwen3-VL 慣用嘅 0 至 1000 比例
PROMPT = (
    "You are a text detector for manga, comics, webtoons and game screens. "
    "Find every separate piece of text in the image: speech bubbles, narration boxes, titles, "
    "sound effects, buttons and menu items. For each one return:\n"
    "- text: the original text exactly as written, NOT translated. Vertical Japanese is read top-to-bottom, "
    "columns right-to-left; join the columns of one bubble into one string.\n"
    "- bbox_2d: [x1, y1, x2, y2] tightly around that text, in relative coordinates from 0 to 1000 "
    "(0,0 is the top-left corner of the image, 1000,1000 the bottom-right).\n"
    "- lang: ja, en, ko, zh or other.\n"
    "- sfx: true if it is a sound effect or onomatopoeia drawn as part of the art (e.g. ドン, ゴゴゴ, BOOM), "
    "false for speech, narration, titles and menu text.\n"
    "One item per bubble or box, not per line. If there is no text, return an empty list."
)


def grab(widget):
    """截 widget 底下嘅畫面（QImage）。widget 自己設咗唔俾截，所以截到嘅係下面嘅嘢。"""
    screen = widget.screen()
    origin = screen.geometry().topLeft()
    g = widget.geometry()
    # 150% 縮放嘅螢幕會截到實際像素（例如 400 寬嘅玻璃截到 600），字清楚啲
    return screen.grabWindow(0, g.x() - origin.x(), g.y() - origin.y(), g.width(), g.height()).toImage()


def to_png(image):
    """縮細到長邊 MAX_SIDE 再轉 PNG bytes 交俾模型；記憶體入面做，唔存硬碟。"""
    if max(image.width(), image.height()) > MAX_SIDE:
        image = image.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def vision_model():
    """而家用緊邊個讀字模型（設定「模型」頁可以轉）。"""
    global _chosen
    if _chosen is None:
        from p4_6_launch import load_settings     # 用到先 import，同 p2_1_translate 一樣
        _chosen = load_settings().get("讀字模型") or VISION_MODEL
    return _chosen


def set_vision_model(name):
    """轉讀字模型（存設定由 p10_1_models 做）；下一次讀字就用新嗰個。"""
    global _chosen
    _chosen = name


def ask_vision(prompt, schema, png, **options):
    """將圖同指示交俾識睇圖模型，回傳佢答嘅 JSON 字串；options 係額外設定（例如 repeat_penalty）。"""
    body = {
        "model": vision_model(),
        # 用家揀咗會「先思考」嘅模型（例如 Qwen3.5）都唔好思考：試過 9B 預設會思考，讀一頁慢幾倍
        "think": False,
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(png).decode()]}],
        "stream": False,
        "format": schema,
        # temperature 0：讀字要準，唔要創意；num_ctx：一張圖大約用一兩千格，再加答案
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": MAX_ANSWER, **options},
        # 用完留 10 分鐘就卸：6GB 唔好長期霸住 VRAM，睇漫畫又唔會逐頁重新搬
        "keep_alive": "10m",
    }
    request = urllib.request.Request(OLLAMA, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=READ_TIMEOUT) as response:
            return json.load(response)["message"]["content"]
    except urllib.error.HTTPError as error:
        reason = error.read().decode("utf-8", "replace")
        if "repeat limit" in reason:
            # 模型卡住不停寫同一個字，Ollama 自己中途叫停、報 500（「token repeat limit reached」）。
            # 當佢答咗唔完整嘅嘢：交返空答案，read_marked() 見到唔係 JSON 就會換個寫法再讀
            return ""
        # 其他錯：將 Ollama 講嘅原因講出嚟，唔好淨係得「Internal Server Error」。
        # 用 OSError（HTTPError 本身都係）：譯鏡同示範版捉錯嘅地方照捉到
        raise OSError(f"讀字模型出錯（HTTP {error.code}）：{reason[:200]}") from error


def clean_text(text, lang):
    """直排每一行之間模型會加換行；唔駁返，翻譯模型會照抄換行，譯文一截截，直排仲會多咗空格。"""
    joiner = " " if lang in ("en", "ko", "other") else ""
    return joiner.join(line.strip() for line in text.splitlines() if line.strip())


def worth_translating(text):
    """冇字、或者淨係數字同標點（頁碼、單獨一個「！」）嘅唔使譯，原文照留就得。"""
    return any(c.isalpha() for c in text)


def read_text(png):
    """將圖交俾識睇圖模型，回傳 [{text, box: (x1, y1, x2, y2) 0 至 1 比例, lang, sfx}]。"""
    answer = ask_vision(PROMPT, SCHEMA, png)
    blocks, seen = [], set()
    for block in parse_blocks(answer):
        key = (block["text"], tuple(block["bbox_2d"]))
        if key in seen:
            continue        # 模型卡住重複寫同一段：留一次就夠
        seen.add(key)
        x1, y1, x2, y2 = (min(max(v, 0), 1000) / 1000 for v in block["bbox_2d"])
        text = clean_text(block["text"], block["lang"])
        if x2 > x1 and y2 > y1 and worth_translating(text):    # 框反轉咗嘅唔要
            # 擬聲字：讀字模型睇得到啲字係唔係畫成效果字，比淨睇文字準（「アレ？」係對白、「メキョ」係效果音）
            blocks.append({"text": text, "box": (x1, y1, x2, y2), "lang": block["lang"],
                           "sfx": bool(block.get("sfx", False))})
    return merge_same_bubble(blocks)


# ---------- 先搵字框再讀（第 6 期第 5 關）----------
# 讀字模型畫嘅框成日偏咗、大細唔啱，又會將幾個對白框當成一段，配唔返搵字模型嘅準確字框，
# 譯文入錯框、日文留低（真漫畫試過）。所以反轉次序：先用搵字模型搵晒字框，喺圖上面畫紅框同編號，
# 叫讀字模型逐個編號讀；佢唔使寫座標，答案仲短啲。框外嘅字（擬聲字）先叫佢報位置
MARK_COLOR = QColor("#e00000")
MARKED_SCHEMA = {
    "type": "object",
    "properties": {
        "boxes": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "text": {"type": "string"},
            "lang": {"type": "string", "enum": ["ja", "en", "ko", "zh", "other"]},
            "sfx": {"type": "boolean"},
        }, "required": ["id", "text", "lang", "sfx"]}},
        "others": SCHEMA["properties"]["blocks"],
    },
    "required": ["boxes", "others"],
}
MARKED_PROMPT = (
    "This is a manga/comic/game image. Some text has been marked with numbered red boxes; the number is in a red tag "
    "at the top-left corner of each box. For EACH numbered box, write the original text inside that box exactly as "
    "written, NOT translated (vertical Japanese: top-to-bottom, columns right-to-left; join the columns into one string). "
    "If a box has no readable text, use an empty string.\n"
    "Then list every other piece of text that is NOT inside any red box (for example sound effects drawn as art), with "
    "bbox_2d [x1, y1, x2, y2] in relative coordinates 0 to 1000.\n"
    "lang: ja, en, ko, zh or other. sfx: true if it is a sound effect or onomatopoeia drawn as part of the art."
)


# 第 8 期第 4 關：讀字慢喺「寫答案」（每秒大約 120 格，睇圖得 0.03 秒）。上面嘅 JSON 每個框都要寫
# "id"、"text"、"lang"、"sfx"、縮排同換行，格式字多過真正嘅字（12 個框 551 格）。改做每個框寫一句
# 「編號|語言|擬聲|字」：同一頁 219 格，4.6 秒變 1.9 秒，讀到嘅字一模一樣；英韓日混合假頁 2.7 秒變 0.8 秒
LINES_SCHEMA = {
    "type": "object",
    "properties": {"boxes": {"type": "array", "items": {"type": "string"}},
                   "others": {"type": "array", "items": {"type": "string"}}},
    "required": ["boxes", "others"],
}
LINES_PROMPT = (
    MARKED_PROMPT.split("\nlang:")[0].replace(" with bbox_2d [x1, y1, x2, y2] in relative coordinates 0 to 1000.", ".")
    + "\nAnswer as JSON with two arrays of strings. Each item of \"boxes\" is \"id|lang|sfx|text\", "
    "e.g. \"3|ja|0|こんにちは\". Each item of \"others\" is \"x1,y1,x2,y2|lang|sfx|text\" with coordinates 0 to 1000. "
    "lang: ja, en, ko, zh or other. sfx: 1 if it is a sound effect, onomatopoeia or mimetic word drawn as part of "
    "the art (usually large stylized letters outside speech bubbles), else 0."
)
LINE_ANSWER_PER_BOX = 40    # 一句大約 15 至 25 格

# 卡死咗（答案唔完整）就用呢個寫法再讀一次：每段寫成一行，加重複懲罰。8 頁真漫畫試過：
# 原本寫法同呢個都冇卡死，但加咗一句「唔好讀注音」就有一頁不停數「（1）（2）（3）……」寫到上限，成頁讀唔到；
# 模型幾時卡死好睇指示點寫，所以兩種寫法互相後備
RETRY_PROMPT = MARKED_PROMPT.replace("join the columns into one string). ",
                                     "join the columns into one string, written on a single line without line breaks). ")
RETRY_OPTIONS = {"repeat_penalty": 1.15}
# 答案上限跟框嘅數目計：一個框（連 JSON 格式）大約 40 至 60 格；卡死嗰陣唔使等到寫滿 2048 格先知（試過要 17 秒）
ANSWER_PER_BOX = 80
ANSWER_EXTRA = 300      # 框外嘅字（擬聲字）


def mark_boxes(image, boxes):
    """喺截圖上面畫紅框同編號（編號貼喺框左上角外面，唔好遮住啲字）。boxes 係像素。"""
    marked = image.convertToFormat(QImage.Format.Format_RGB32)
    marked.setDevicePixelRatio(1)       # 截圖帶住 150% 縮放；唔設，畫嘅位會偏
    p = QPainter(marked)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = max(14, round(marked.height() / 70))     # 縮到 1600 長邊交俾模型之後都要睇得清
    font = QFont("Arial")
    font.setPixelSize(size)
    font.setBold(True)
    p.setFont(font)
    for number, (x1, y1, x2, y2) in enumerate(boxes, start=1):
        p.setPen(QPen(MARK_COLOR, max(2, size // 7)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))
        tag = QRectF(x1 - 2, y1 - size * 1.3, size * (1.4 if number < 10 else 2.0), size * 1.25)
        p.fillRect(tag, MARK_COLOR)
        p.setPen(QColor("white"))
        p.drawText(tag, Qt.AlignmentFlag.AlignCenter, str(number))
    p.end()
    return marked


def read_marked(image, boxes, answered=None):
    """先畫編號框再讀：回傳段落 list。框入面嘅段有 finder（第幾個字框）同 text_px（準確位置，像素）；
    框外嘅段同 read_text() 一樣，淨係有讀字模型估嘅 box（0 至 1 比例）。
    answered 係 set 就加入模型真係答咗嘅框（連答咗「冇字」嘅），快取用：冇答到嘅唔好當係冇字。"""
    png = to_png(mark_boxes(image, boxes))
    answer = ask_vision(LINES_PROMPT, LINES_SCHEMA, png,
                        num_predict=min(MAX_ANSWER, ANSWER_EXTRA + LINE_ANSWER_PER_BOX * len(boxes)))
    parsed = parse_lines(answer)
    if parsed is not None:
        boxed, others = parsed
    else:
        # 卡住或者寫壞咗：用返舊嘅 JSON 寫法（每段寫成一行＋重複懲罰）再讀一次，兩種寫法唔會喺同一個位卡
        print("  ⚠️ 讀字模型卡住咗，換個寫法再讀一次")
        limit = min(MAX_ANSWER, ANSWER_EXTRA + ANSWER_PER_BOX * len(boxes))
        answer = ask_vision(RETRY_PROMPT, MARKED_SCHEMA, png, num_predict=limit, **RETRY_OPTIONS)
    try:
        if parsed is None:
            data = json.loads(answer)
            boxed, others = data.get("boxes", []), data.get("others", [])
    except json.JSONDecodeError:
        # 答到一半俾人切斷：救返完整嘅段，有 id 嘅係框入面、有 bbox_2d 嘅係框外
        pieces = [json.loads(piece) for piece in re.findall(r"\{[^{}]*\}", answer) if _is_json(piece)]
        boxed = [b for b in pieces if "id" in b and "text" in b]
        others = [b for b in pieces if "bbox_2d" in b and "text" in b]
        print(f"  ⚠️ 讀字模型答案唔完整，救返 {len(boxed) + len(others)} 段")
    w, h = image.width(), image.height()
    blocks, texts = [], set()
    for item in boxed:
        number = item.get("id")
        if not isinstance(number, int) or not 1 <= number <= len(boxes):
            continue
        if answered is not None:
            answered.add(number - 1)
        lang = item.get("lang", "other")
        text = clean_text(item.get("text", ""), lang)
        if not worth_translating(text) or number - 1 in {b["finder"] for b in blocks}:
            continue
        x1, y1, x2, y2 = (float(v) for v in boxes[number - 1])
        blocks.append({"text": text, "lang": lang, "sfx": bool(item.get("sfx", False)), "finder": number - 1,
                       "box": (x1 / w, y1 / h, x2 / w, y2 / h), "text_px": (x1, y1, x2, y2)})
        texts.add(text.replace(" ", ""))
    for item in others:
        bbox = item.get("bbox_2d", [])
        lang = item.get("lang", "other")
        text = clean_text(item.get("text", ""), lang)
        if len(bbox) != 4 or not worth_translating(text) or text.replace(" ", "") in texts:
            continue        # 框入面已經讀咗嘅字，模型間中會喺框外再報一次
        if text[0] in "（(" and text[-1] in "）)":
            continue        # 成段係括號注釋（例如「（声）」），唔係要譯嘅字
        x1, y1, x2, y2 = (min(max(v, 0), 1000) / 1000 for v in bbox)
        if x2 > x1 and y2 > y1:
            blocks.append({"text": text, "lang": lang, "sfx": bool(item.get("sfx", False)), "box": (x1, y1, x2, y2)})
            texts.add(text.replace(" ", ""))
    return blocks


# 單獨截一個框再讀（讀漏咗字先用）：成頁有編號嗰陣模型間中跳行，試過「…時間だったが肉体が悲鳴を…」
# 漏咗「だったが肉体」；淨截嗰個框出嚟讀，兩次都讀齊，0.3 至 1 秒
CROP_PROMPT = (
    "Write the original text in this image exactly as written, NOT translated. Vertical Japanese: read "
    "top-to-bottom, columns right-to-left, join the columns into one line. Ignore small furigana (ruby) beside "
    "kanji. Output only the text."
)
CROP_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
CROP_PAD = 12               # 截框嗰陣四邊多留幾多像素：字貼住框邊都唔會截爛


def read_crop(image, box):
    """淨截 box（像素）嗰嚿交俾讀字模型讀；讀唔到回空字串。"""
    x1, y1, x2, y2 = (int(v) for v in box)
    crop = image.copy(x1 - CROP_PAD, y1 - CROP_PAD, x2 - x1 + 2 * CROP_PAD, y2 - y1 + 2 * CROP_PAD)
    try:
        return str(json.loads(ask_vision(CROP_PROMPT, CROP_SCHEMA, to_png(crop))).get("text", ""))
    except (json.JSONDecodeError, AttributeError):
        return ""


def parse_lines(answer):
    """「編號|語言|擬聲|字」寫法 → （框入面嘅段, 框外嘅段），格式同舊 JSON 寫法一樣（id/text/lang/sfx、bbox_2d）。
    答案唔係完整 JSON（卡住、俾上限切斷）就回 None，等 read_marked 換寫法再讀。"""
    try:
        data = json.loads(answer)
        lines, extra = data.get("boxes", []), data.get("others", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    boxed, others = [], []
    for line in lines:
        parts = str(line).split("|", 3)     # 字本身可能有「|」：淨係切頭三個
        if len(parts) == 4 and parts[0].strip().isdigit():
            boxed.append({"id": int(parts[0]), "lang": parts[1].strip() or "other",
                          "sfx": parts[2].strip() == "1", "text": parts[3]})
    for line in extra:
        parts = str(line).split("|", 3)
        try:
            bbox = [float(v) for v in parts[0].split(",")]
        except ValueError:
            continue
        if len(parts) == 4 and len(bbox) == 4:
            others.append({"bbox_2d": bbox, "lang": parts[1].strip() or "other",
                           "sfx": parts[2].strip() == "1", "text": parts[3]})
    if (lines or extra) and not (boxed or others):
        return None     # 寫咗嘢但一句都唔啱格式：當寫壞咗
    return boxed, others


def _is_json(piece):
    try:
        json.loads(piece)
        return True
    except json.JSONDecodeError:
        return False


def parse_blocks(answer):
    """讀模型嘅 JSON 答案；答到一半俾人切斷（太長）就救返已經寫完嘅段。"""
    try:
        return json.loads(answer).get("blocks", [])
    except json.JSONDecodeError:
        pass
    # 每段係 {"text": …, "bbox_2d": […], "lang": …}，入面冇再包 {}：逐個完整嘅 {…} 試讀
    blocks = []
    for piece in re.findall(r"\{[^{}]*\}", answer):
        try:
            block = json.loads(piece)
        except json.JSONDecodeError:
            continue
        if isinstance(block.get("text"), str) and len(block.get("bbox_2d", [])) == 4 and "lang" in block:
            blocks.append(block)
    if not blocks:
        raise ValueError("讀字模型答咗一段唔完整嘅答案")
    print(f"  ⚠️ 讀字模型答案唔完整，救返 {len(blocks)} 段")
    return blocks


def overlap(a, b):
    """兩個框重疊咗細嗰個嘅幾多（0 至 1）：差唔多一樣、或者一個包住另一個都會好高。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller


def merge_same_bubble(blocks, threshold=SAME_BUBBLE):
    """模型間中會將一個對白框嘅每行直排拆開做幾段（框一模一樣）；重疊得多嘅當同一個框，字按次序駁返。

    試過一頁日漫讀到 25 段，其中六段嘅框完全一樣；同一個位再讀就正確合埋做 8 段。
    第 3 關要逐個對白框翻譯，拆開咗會譯成碎片。
    """
    merged = []
    for block in blocks:
        same = next((m for m in merged if m["lang"] == block["lang"] and overlap(m["box"], block["box"]) >= threshold),
                    None)
        if same is None:
            merged.append(dict(block))
            continue
        a, b = same["text"], block["text"]
        same["sfx"] = same.get("sfx", False) and block.get("sfx", False)    # 全部都係擬聲字先算
        # 英文、韓文要空格分開；日文、中文直接駁
        same["text"] = f"{a} {b}" if block["lang"] in ("en", "ko", "other") else a + b
        same["box"] = (min(same["box"][0], block["box"][0]), min(same["box"][1], block["box"][1]),
                       max(same["box"][2], block["box"][2]), max(same["box"][3], block["box"][3]))
    return merged


