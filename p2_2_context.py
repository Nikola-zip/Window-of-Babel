# 譯幕 第2期第2步：翻譯時參考前幾句
#
# 做咩：兩段日文對話，每句譯兩次：一次冇上下文，一次附上前 5 句原文同譯文，
#       並排印出嚟比較。
# 點用：先確定 Ollama 開住，再喺終端機打：.venv\Scripts\python p2_2_context.py
# 第 4 關會 import 呢度嘅 ContextTranslator。

from collections import deque

from p2_1_translate import PROMPT, TARGET, ask, check_ollama, translate, warm_up
from p7_1_target import context_prompt, plain_prompt

HISTORY = 5     # 參考前幾句；規格定 5 句，再多 prompt 長咗會慢，幫助亦唔大

# Hy-MT2 官方 README 嘅「上下文翻譯」寫法，照抄唔好改：
# 呢個模型冇預設 system prompt，格式唔啱就好易多嘴解釋
CONTEXT_PROMPT = (
    "【背景信息】\n{background}\n\n"
    "请结合背景信息将以下文本翻译为{target}。\n\n"
    "【待翻译文本】\n{text}"
)

# 每段對話最尾嗰句係重點：單獨睇唔明，要靠上文
DIALOGUES = {
    # 「明日お見舞いに行く」冇講邊個去，上文先知係部長去探佢老婆
    "省略主語": [
        "先輩、昨日の飲み会どうでした？",
        "部長が来なかったから、みんな気楽に楽しんでたよ。",
        "え、来なかったんですか？",
        "うん、奥さんが入院したんだって。",
        "それは心配ですね。",
        "明日お見舞いに行くらしいよ。",
    ],
    # 「聞き耳」喺跑團遊戲係「聆聽」技能，第 1 關冇上下文就譯錯咗
    "跑團遊戲": [
        "では、聞き耳判定をどうぞ。",
        "50です。",
        "残念、失敗です。",
        "耳にまだ水が残っていたのか、あなたの聞き耳は働きませんでした。",
    ],
}


class ContextTranslator:
    """記住最近幾句，翻譯新一句時一齊交俾模型參考。"""

    def __init__(self, size=HISTORY):
        # deque 設咗 maxlen，加第 6 句會自動踢走最舊嗰句，唔使自己數
        self.history = deque(maxlen=size)

    def translate(self, text):
        """譯一句，回傳（譯文, 用咗幾多秒）。"""
        result, seconds = ask(self._prompt(text))
        # 連譯文都記低：之後幾句可以跟返前面嘅叫法，人名、稱呼前後一致
        self.history.append((text, result))
        return result, seconds

    def _prompt(self, text):
        """砌 prompt；抽出嚟係等第 3 關可以喺前面加詞庫，唔使重寫。"""
        # 第 7 期：指示跟「譯做」嗰種語言（繁中用中文指示，英日韓用官方英文指示）
        if not self.history:
            # 第一句冇嘢參考，用返普通寫法，費事空白嘅背景信息令模型亂咗
            return plain_prompt(text)
        return context_prompt(self.history, text)

    def reset(self):
        """換片或者換場景就清空，費事上一段對白誤導下一段。"""
        self.history.clear()

    def forget(self, text):
        """最近嗰句係 text 就刪走佢：6 秒切開嘅上半截要同下半截合埋重譯，上下文改記成句。"""
        if self.history and self.history[-1][0] == text:
            self.history.pop()


def main():
    print(f"Ollama 版本：{check_ollama()}")
    warm_up()     # 熱身，費事第一句計埋搬模型入 VRAM 嘅時間

    for title, lines in DIALOGUES.items():
        print(f"\n===== {title} =====")
        context = ContextTranslator()   # 每段對話由零開始，互不影響
        for text in lines:
            plain, _ = translate(text)
            with_context, seconds = context.translate(text)
            print(f"\n原文：{text}")
            print(f"  冇上下文：{plain}")
            print(f"  有上下文（{seconds:.2f} 秒）：{with_context}")


if __name__ == "__main__":
    main()
