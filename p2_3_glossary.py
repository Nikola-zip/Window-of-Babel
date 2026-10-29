# 譯幕 第2期第3步：人名詞庫
#
# 做咩：讀 CSV 詞庫（原文、譯名、備註），翻譯時搵出今句出現咗嘅詞，
#       用 Hy-MT2 官方「參考翻譯」寫法放喺 prompt 前面。
#       幾段測試句冇詞庫、有詞庫各譯一次，再自動檢查有冇用指定譯名。
# 點用：先確定 Ollama 開住，再喺終端機打：.venv\Scripts\python p2_3_glossary.py
# 第 4 關會 import 呢度嘅 GlossaryTranslator 同 load_glossary()。

import csv
from pathlib import Path

from p2_1_translate import ask, check_ollama, warm_up
from p2_2_context import ContextTranslator
from p7_1_target import current, glossary_prefix, plain_prompt

GLOSSARY = Path("glossaries/test.csv")

# 每段測試對白都會用到詞庫入面嘅詞
SCENES = {
    "跑團遊戲": [
        "では、聞き耳判定をどうぞ。",
        "50です。",
        "残念、失敗です。",
        "耳にまだ水が残っていたのか、あなたの聞き耳は働きませんでした。",
    ],
    "人名同地名": [
        "ルミナ、北の洞窟に行ってみよう。",
        "ルミナは笑って、剣を抜いた。",
        "こんぺこ！兎田ぺこらだぺこ！",
    ],
    "港式用字（英文）": [
        "iOS 27 improves connectivity with smarter transitions between cellular and Wi-Fi networks.",
        "Your phone now switches networks automatically.",
    ],
}


def load_glossary(path):
    """讀詞庫 CSV，回傳 [(原文, 譯名)]。"""
    # utf-8-sig：用 Excel 存嘅 CSV 開頭會有個隱形 BOM 符號，
    # 唔處理嘅話第一欄個標題會變咗「﻿原文」，搵唔到欄
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [(row["原文"].strip(), row["譯名"].strip()) for row in csv.DictReader(f)]
    # 長嘅排先：「聞き耳判定」同「聞き耳」都有嘅話，模型會先睇到完整嗰個
    return sorted([r for r in rows if r[0]], key=lambda r: len(r[0]), reverse=True)


def terms_in(text, glossary):
    """搵出今句出現咗嘅詞庫詞。"""
    # 只放今句有嘅詞：成個詞庫塞入 prompt 會長好多、慢咗，模型亦可能亂用。
    # 日文冇空格分詞，所以直接睇係咪字串嘅一部分；英文唔理大細楷
    lowered = text.lower()
    return [(source, target) for source, target in glossary if source.lower() in lowered]


class GlossaryTranslator(ContextTranslator):
    """喺第 2 關嘅上下文翻譯上面，再加詞庫。"""

    def __init__(self, glossary, size=5, names=None):
        super().__init__(size)
        self.glossary = glossary
        self.names = names      # 人名記憶（第 8 期，p8_5_names.NameMemory）；None 就唔用
        self.last_terms = []    # 上一句用咗邊啲詞，俾人檢查譯文有冇跟

    def _prompt(self, text):
        prompt = super()._prompt(text)      # 上下文嗰部分照用第 2 關
        # 詞庫入面嘅譯名係中文：譯做其他語言用唔到（第 7 期），費事中文名夾咗入英文譯文
        target = current()
        terms = terms_in(text, self.glossary) if target.hong_kong else []
        if self.names is not None:
            # 人名記憶：未見過嘅名先單獨譯一次記低（冇上下文，譯法穩定），之後句句都跟同一個譯名。
            # 詞庫寫明咗嘅名優先（用戶自己揀嘅）
            self.names.learn(text, target, lambda word: ask(plain_prompt(word, target))[0])
            fixed = {source for source, _ in terms}
            terms += [pair for pair in self.names.terms(text, target) if pair[0] not in fixed]
        self.last_terms = terms
        if not self.last_terms:
            return prompt
        # Hy-MT2 官方「參考翻譯」寫法：先列「X 翻译成 Y」，再接翻譯指示
        return glossary_prefix(self.last_terms) + prompt


def main():
    print(f"Ollama 版本：{check_ollama()}")
    warm_up()     # 熱身
    glossary = load_glossary(GLOSSARY)
    print(f"詞庫：{GLOSSARY}，{len(glossary)} 個詞")

    hits = total = 0
    for title, lines in SCENES.items():
        print(f"\n===== {title} =====")
        # 兩邊都有上下文，唯一分別係有冇詞庫，比較先公平
        plain = ContextTranslator()
        with_glossary = GlossaryTranslator(glossary)
        for text in lines:
            before, _ = plain.translate(text)
            after, seconds = with_glossary.translate(text)
            print(f"\n原文：{text}")
            print(f"  冇詞庫：{before}")
            print(f"  有詞庫（{seconds:.2f} 秒）：{after}")
            for source, target in with_glossary.last_terms:
                ok = target in after
                hits += ok
                total += 1
                print(f"    {'✅' if ok else '❌'} {source} → {target}")

    print(f"\n指定譯名命中：{hits}/{total}")


if __name__ == "__main__":
    main()
