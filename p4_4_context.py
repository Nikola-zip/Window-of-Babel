# 譯幕 第4期第4步：上下文、用字、語氣詞
#
# 做咩：① HKTranslator：譯完將台灣／大陸用字換做香港用字（glossaries\hk_wording.csv）；
#          淨係語氣詞嘅句（はい、えー、Oh……）用固定譯法（glossaries\interjections.csv），唔問模型
# 點用：直接行就係自我測試（要開住 Ollama）：
#       .venv\Scripts\python -W ignore p4_4_context.py
#       main.py（譯鏡）會用 HKTranslator。譯幕版嘅換片偵測 MediaWatcher 淨係字幕用，呢度拎走咗

import csv
import re
from pathlib import Path

import opencc

from p2_1_translate import ask
from p2_3_glossary import GlossaryTranslator
from p7_1_target import current, glossary_prefix, plain_prompt

WORDING = Path("glossaries/hk_wording.csv")
INTERJECTIONS = Path("glossaries/interjections.csv")
CONTEXT_GAP = 30        # 規格：冇人講嘢超過咁多秒就清空上下文
WHOLE_SENTENCE = 0.1    # 純簡體字佔一句咁多（或以上）就當成句係簡體，成句轉


def is_traditional(char):
    """Big5（繁體中文電腦一向用嘅字集）有呢個字，即係繁體都用緊，唔好郁。"""
    try:
        char.encode("cp950")
        return True
    except UnicodeEncodeError:
        return False


def hk_characters():
    """回傳一個「簡體字 → 繁體字」嘅 function（第 5 期第 1 關）；用字（網絡、你）交俾換字表。

    唔可以成句交 OpenCC 轉：佢當成句都係簡體，「傢伙」會變「傢夥」、「了解」變「瞭解」、
    「說」變香港異體「説」（翻查 928 句舊譯文，105 句會被改，大部分係改錯本身啱嘅字）。
    所以只收「純簡體字」嗰幾個位嘅改動：Big5 冇嘅字（这、设、续）先轉；
    「伙」「了」「里」「后」呢類繁體都有用嘅字一律唔郁。
    用 s2tw 唔用 s2hk：字形同模型其他字一致（為、說），s2t 又會出香港人少用嘅「爲」。
    每條線各自叫一次攞自己嗰個：唔肯定 OpenCC 同時俾兩條線用安唔安全。
    """
    cc = opencc.OpenCC("s2tw.json")

    def convert(text):
        han = [c for c in text if "一" <= c <= "鿿"]
        simplified = sum(not is_traditional(c) for c in han)
        if not simplified:
            return text     # 冇簡體字：最常見，唔使轉
        # 成句都係簡體（Whisper 出普通話）：成句交 OpenCC，「后来」「什么」「网站」呢類
        # Big5 都有嘅字先轉得到。翻查舊紀錄：簡體原文純簡體字佔 13% 以上，
        # 繁體譯文夾咗幾個簡體字嘅最多 7%，所以 10% 做分界
        if simplified / len(han) >= WHOLE_SENTENCE:
            return cc.convert(text)
        # 繁體句夾咗幾個簡體字（模型間中出錯）：成句轉先有詞語前後文，再逐個字揀收唔收
        whole = cc.convert(text)
        if len(whole) == len(text):
            return "".join(new if not is_traditional(old) else old for old, new in zip(text, whole))
        # 長度唔同（好少見）：逐個簡體字自己轉
        return "".join(c if is_traditional(c) else cc.convert(c) for c in text)

    return convert


def load_pairs(path, source_column, target_column):
    """讀兩欄 CSV，回傳 {原本: 換做}；檔案唔存在就當空表。"""
    if not path.exists():
        print(f"⚠️ 搵唔到 {path}，唔換")
        return {}
    # utf-8-sig：用 Excel 存過嘅 CSV 開頭有隱形 BOM，唔處理第一欄會讀錯名
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row[source_column].strip(): row[target_column].strip()
                for row in csv.DictReader(f) if row[source_column].strip()}


class Wording:
    """台灣／大陸用字 → 香港用字。"""

    def __init__(self, path=WORDING):
        self.table = load_pairs(path, "台灣用字", "香港用字")
        # 一次過換晒，唔好逐個 replace：逐個換嘅話，換出嚟嘅字可能又俾下一個詞再換一次。
        # 長詞排先：「行動網路」要喺「網路」之前比對，唔係會變「行動網絡」
        words = sorted(self.table, key=len, reverse=True)
        self.pattern = re.compile("|".join(map(re.escape, words))) if words else None

    def apply(self, text):
        if not self.pattern:
            return text
        return self.pattern.sub(lambda m: self.table[m.group(0)], text)


def interjection_key(text):
    """去標點空格大細楷，拉長咗嘅「えええええ」變「えー」先查表。
    「～」係拉長音，當「ー」唔好刪：試過「ええ～～～！！」（驚訝）刪剩「ええ」（應承），譯咗做「嗯」"""
    key = re.sub(r"[～〜~]+", "ー", text)
    key = re.sub(r"[\W_]+", "", key).lower()
    key = re.sub(r"([ぁ-ゖァ-ヺ])\1{2,}", r"\1ー", key)    # 同一個假名連續三個或以上 = 拉長音
    return re.sub(r"ー+", "ー", key)


class Interjections:
    """淨係語氣詞嘅句用固定譯法：模型逐個音譯會出怪字，又易撈埋上一句。"""

    def __init__(self, path=INTERJECTIONS):
        self.table = {interjection_key(k): v for k, v in load_pairs(path, "原文", "譯法").items()}

    def lookup(self, text):
        key = interjection_key(text)
        if key in self.table:
            return self.with_ending(text, self.table[key])
        # 英文拉長咗（「Ohhhh」「Hmmmm」）：同一個字母連續三個或以上，試吓縮做一個或者兩個
        for repeat in (r"\1", r"\1\1"):
            shorter = re.sub(r"([a-z])\1{2,}", repeat, key)
            if shorter in self.table:
                return self.with_ending(text, self.table[shorter])
        return None

    @staticmethod
    def with_ending(text, fixed):
        """原文句尾嘅「！」「？」照搬落譯文（「はい！」→「好！」）：查表時刪咗，但語氣靠佢。"""
        ending = re.search(r"[！!？?]+$", text.strip())
        if not ending or re.search(r"[！!？?。…]$", fixed):
            return fixed
        return fixed + ending.group().replace("!", "！").replace("?", "？")


# 日文假名（平假名、片假名；唔計「ー」「・」，中文譯文都會用）
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")


class HKTranslator(GlossaryTranslator):
    """詞庫＋上下文翻譯，再加香港用字同語氣詞固定譯法。"""

    def __init__(self, glossary, size=5, names=None):
        super().__init__(glossary, size, names)
        self.wording = Wording()
        self.interjections = Interjections()
        self.characters = hk_characters()

    def translate(self, text):
        names = getattr(self, "names", None)
        fixed = names.sentence(text, current()) if names is not None else None
        if fixed:
            # 用戶喺歷史面板固定咗呢句（第 9 期）：照用，唔問模型；入埋上下文，之後幾句跟得住
            self.last_terms = []
            self.history.append((text, fixed))
            return fixed, 0.0
        if not current().hong_kong:
            # 譯做英日韓（第 7 期）：語氣詞固定譯法、簡轉繁、香港用字全部係中文用嘅，唔做
            return super().translate(text)
        fixed = self.interjections.lookup(text)
        if fixed is not None:
            # 唔入上下文：「はい」「えー」對之後嘅句冇幫助，反而逼走真正有用嗰幾句
            self.last_terms = []
            return fixed, 0.0
        had_context = bool(self.history)
        result, seconds = super().translate(text)
        if had_context and KANA.search(result):
            # 有上下文嗰陣，模型間中照抄日文人名（「タダシ」→「タダシ」「タ…タダシ様」），譯鏡見到譯文同原文一樣
            # 就留返原文，個框好似冇譯過。唔用上下文再譯一次，試過穩定譯做「塔達希」；假名少咗先用
            prefix = glossary_prefix(self.last_terms) if self.last_terms else ""
            retry, more = ask(prefix + plain_prompt(text))
            seconds += more
            if len(KANA.findall(retry)) < len(KANA.findall(result)):
                result = retry
                self.history[-1] = (text, result)
        # 先將模型間中出嘅簡體字（「设计」「续航」）轉繁體，再換用字：
        # 換字表啲詞係繁體，「视频」要先變「視頻」先換得到做「影片」
        converted = self.wording.apply(self.characters(result))
        # 上下文都記香港版：模型見到之前用「你」「網絡」，之後會傾向跟住用
        self.history[-1] = (text, converted)
        return converted, seconds


def self_test():
    from p2_1_translate import check_ollama, warm_up
    from p2_3_glossary import load_glossary
    from p2_3_glossary import GLOSSARY

    wording = Wording()
    print(f"用字表：{len(wording.table)} 個詞")
    # 直接試換字：特別睇住「行動」「智慧」唔可以亂換
    samples = {
        "您的行動網路已連線，請到智慧型手機的設定查看品質。": "你的流動網絡已連線，請到智能手機的設定查看質素。",
        "泰德的行動充滿智慧。": "泰德的行動充滿智慧。",
        "我坐計程車去便利商店買冰淇淋。": "我坐的士去便利店買雪糕。",
    }
    ok = True
    for text, want in samples.items():
        got = wording.apply(text)
        ok &= got == want
        print(f"{'✅' if got == want else '❌'} {text} → {got}")

    interjections = Interjections()
    for text, want in [("はいはいはい", "好好好"), ("えええええ!", "呃"), ("Ohhhh!", "哦"), ("Ha ha ha ha!", "哈哈哈哈"),
                       ("Hmmmm...", "嗯"), ("はい、どうぞ", None), ("やった!", None)]:
        got = interjections.lookup(text)
        ok &= got == want
        print(f"{'✅' if got == want else '❌'} 「{text}」→ {got or '交俾模型譯'}")

    # 第 5 期第 1 關：簡體轉香港繁體，同埋轉完再換用字（「视频」→「視頻」→「影片」）
    characters = hk_characters()
    for text, want in [("在這款車型中，既有常規版本的设计", "在這款車型中，既有常規版本的設計"),
                       ("电动车续航测试", "電動車續航測試"),
                       ("我們將往森林裡面前進，著急地穿著衣服", "我們將往森林裡面前進，著急地穿著衣服"),
                       # 本身繁體：以前成句交 OpenCC 會變「傢夥」「瞭解」「説」
                       ("多個不明身份的傢伙，讓她了解這是說要我留下", "多個不明身份的傢伙，讓她了解這是說要我留下"),
                       # 成句簡體（Whisper 出普通話）：「后来」「什么」「网站」Big5 都有，要成句轉先得
                       ("后来他们为什么没有去网站看", "後來他們為什麼沒有去網站看")]:
        got = characters(text)
        ok &= got == want
        print(f"{'✅' if got == want else '❌'} {text} → {got}")
    got = wording.apply(characters("这个视频的质量很好"))
    ok &= got == "這個影片的質素很好"
    print(f"{'✅' if got == '這個影片的質素很好' else '❌'} 这个视频的质量很好 → {got}")

    # 真模型：呢幾句以前會出台灣用字，譯完唔應該再有
    print(f"\nOllama 版本：{check_ollama()}，熱身 {warm_up():.1f} 秒")
    translator = HKTranslator(load_glossary(GLOSSARY))
    tests = [
        "Please check your network settings on your smartphone.",
        "The video quality depends on your software and hardware.",
        "I took a taxi to the convenience store and bought ice cream.",
        "Print the document and send me a text message.",
        "お客様、こちらの席へどうぞ。",
        "ご注文はお決まりですか？",
        "はいはいはい",
        "えー",
    ]
    for text in tests:
        result, seconds = translator.translate(text)
        left = [w for w in wording.table if w in result]
        ok &= not left
        print(f"{'✅' if not left else '❌ 仲有 ' + '、'.join(left)} {text} → {result}（{seconds:.2f} 秒）")
    print("全部啱" if ok else "有錯！")



if __name__ == "__main__":
    self_test()
