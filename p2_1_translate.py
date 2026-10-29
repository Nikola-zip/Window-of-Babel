# 譯幕 第2期第1步：用自己張 4090 翻譯
#
# 做咩：將幾句固定測試句交俾本機 Ollama 行嘅 Hy-MT2-7B（Q6_K），譯做繁中書面語，
#       印埋每句用咗幾耐。
# 點用：先確定 Ollama 開住（工作列有隻羊駝），再喺終端機打：
#       .venv\Scripts\python p2_1_translate.py
# 第 2 期之後幾關會 import 呢度嘅 translate()。

import json
import time
import urllib.request

# Ollama 喺背景開住一個本機服務；叫佢翻譯即係向呢度發一個 HTTP 請求，
# 所以用 Python 自帶嘅 urllib 就得，唔使裝新套件。
# 唔好寫 localhost：Windows 會先試 IPv6（::1），Ollama 冇聽嗰度，
# 等失敗再轉 IPv4 每次嘥大約 2 秒；直接寫 127.0.0.1 就冇呢個問題
OLLAMA = "http://127.0.0.1:11434/api/chat"
OLLAMA_VERSION_URL = "http://127.0.0.1:11434/api/version"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
# 正常一句 0.1 至 0.4 秒；等到 10 秒即係出咗事（例如 Ollama 閂咗、卡住），當失敗
REQUEST_TIMEOUT = 10
# 熱身要將模型由硬碟搬入 VRAM，冷開機試過要 50 幾秒，所以等耐好多
WARMUP_TIMEOUT = 120
# 試過嘅版本。Ollama 會自己喺背景下載新版，撳咗「Restart to update」就會變，
# 新版可能改咗行為，所以一開始檢查一次，唔同就提你
# 2026-10-18 發覺自己升咗 0.40.6，打機驗收全程用佢冇問題，用戶決定改做佢
TESTED_VERSION = "0.40.6"
# 比較過 Q6_K 同 Q8_0：質素睇唔出分別，Q6_K 快三四成、少用 1.8GB VRAM，所以揀佢。
# 呢個只係「冇揀過」時嘅預設：用家可以喺設定「模型」頁轉（settings.json「翻譯模型」）
MODEL = "hf.co/unsloth/Hy-MT2-7B-GGUF:Q6_K"
_chosen = None      # 用家揀咗嘅翻譯模型；第一次用先讀設定，之後記住，唔好每句都讀檔


def current_model():
    """而家用緊邊個翻譯模型。唔可以寫做函數預設值（model=MODEL）：嗰個喺開程式嗰下就定死，轉咗都唔會變。"""
    global _chosen
    if _chosen is None:
        from p4_6_launch import load_settings     # 用到先 import：p4_6_launch 本身都 import 呢個檔
        _chosen = load_settings().get("翻譯模型") or MODEL
    return _chosen


def set_model(name):
    """轉翻譯模型（存設定由 p10_1_models 做）；下一句就用新嗰個。"""
    global _chosen
    _chosen = name

# Hy-MT2 官方 README 嘅寫法。佢冇預設 system prompt，唔跟足格式好易多嘴加解釋。
# 語言名要用 prompt 本身嘅語言寫，所以係簡體嘅「繁体中文」
PROMPT = "将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
TARGET = "繁体中文"

# 官方建議嘅生成設定；num_predict 係最多出幾多 token，字幕一句好少過 100
OPTIONS = {
    "temperature": 0.7,
    "top_p": 0.6,
    "top_k": 20,
    "repeat_penalty": 1.05,
    "num_predict": 256,
    # 記憶位（context）。Ollama 預設 32768，Q8_0 一個就食 12GB VRAM；
    # 一句字幕連 5 句上下文同詞庫都用唔使 1000，4096 綽綽有餘
    "num_ctx": 4096,
    # 固定隨機種子：temperature 0.7 會令同一句每次譯得唔同，
    # 固定咗就同一個 prompt 出同一個結果，比較改動先公平，字幕亦前後一致
    "seed": 42,
}

# 部分係之前測試片入面真係出現過嘅句，有口語、有數字、有專有名詞
TESTS = [
    "明日は早いので、もう寝ます",
    "こんな小さな子や私のでかい体が入れるかなぁ",
    "耳にまだ水が残っていたのかあなたの聞き耳は働きませんでした",
    "そこまでではないですよ。そこまでなるのはもう本当に発狂した時です。",
    "iOS 27 improves connectivity with smarter transitions between cellular and Wi-Fi networks.",
    "You can also get up to $1,200 off when you trade in an iPhone 14 or newer.",
    "No way, you've gotta be kidding me!",
    "오늘은 여기까지 하고 내일 다시 이야기합시다.",
]


def check_ollama():
    """確認 Ollama 開咗，同埋係試過嘅版本；唔係就講清楚。"""
    try:
        with urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=5) as response:
            version = json.load(response)["version"]
    except OSError:
        # 連唔到通常係 Ollama 冇開，直接講，好過彈一大堆網絡錯誤
        raise RuntimeError("連唔到 Ollama：撳開始功能表開 Ollama，等工作列有隻羊駝再試") from None
    if version != TESTED_VERSION:
        print(f"⚠️ Ollama 係 {version}，試過嘅係 {TESTED_VERSION}；"
              "可能撳咗「Restart to update」，有怪事就留意吓係咪新版改咗嘢")
    return version


def ollama_alive(timeout=1):
    """一秒內問一問 Ollama 喺唔喺度；用嚟喺出錯之後睇佢返咗嚟未，唔使逐句等 10 秒。"""
    try:
        with urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=timeout):
            return True
    except OSError:
        return False


def warm_up(model=None):
    """熱身：將模型搬入 VRAM，等耐啲都得；回傳用咗幾多秒。"""
    model = model or current_model()
    _, seconds = ask(PROMPT.format(target=TARGET, text="こんにちは"), model, timeout=WARMUP_TIMEOUT)
    return seconds


def unload_model(model=None):
    """叫 Ollama 即刻將模型清出 VRAM；閂程式、轉模型時用，唔使等 30 分鐘先自動清。"""
    model = model or current_model()
    # 官方做法：keep_alive 設 0，即係「用完即刻卸走」
    body = {"model": model, "keep_alive": 0}
    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return True
    except OSError:
        return False    # Ollama 本身閂咗就冇嘢要卸，唔使報錯


def translate(text, model=None):
    """譯一句（冇上下文），回傳（譯文, 用咗幾多秒）。"""
    return ask(PROMPT.format(target=TARGET, text=text), model)


def ask(prompt, model=None, timeout=REQUEST_TIMEOUT):
    """將砌好嘅 prompt 交俾模型，回傳（答覆, 用咗幾多秒）。

    出錯（連唔到、等超過 timeout 秒、答覆格式唔啱）會 raise，由叫嘅人決定點處理。
    """
    body = {
        "model": model or current_model(),
        "messages": [{"role": "user", "content": prompt}],
        # 用家揀咗會「先思考」嘅模型都唔好思考：翻譯一句唔使諗，諗就慢幾倍（試過對 Hy-MT2 冇影響）
        "think": False,
        "stream": False,
        "options": OPTIONS,
        # 用完留喺 VRAM 30 分鐘：每次重新搬模型入 VRAM 要幾秒，字幕等唔切
        "keep_alive": "30m",
    }
    request = urllib.request.Request(
        OLLAMA,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        reply = json.load(response)
    return reply["message"]["content"].strip(), time.perf_counter() - start


def main():
    print(f"Ollama 版本：{check_ollama()}")
    # 熱身：第一次要將模型由硬碟搬入 VRAM，好慢，唔計入
    print(f"載入模型：{warm_up():.1f} 秒")

    for text in TESTS:
        result, seconds = translate(text)
        print(f"\n原文：{text}\n譯文（{seconds:.2f} 秒）：{result}")


if __name__ == "__main__":
    main()
