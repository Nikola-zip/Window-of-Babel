# 巴別塔之窗：揀模型（讀字模型＋翻譯模型）
#
# 做咩：三檔建議（2026-10-29 實測）同「自己揀」：
#   輕 Qwen3-VL 2B＋Hy-MT2 1.8B（約 6 GB VRAM）、中 Qwen3-VL 8B＋Hy-MT2 1.8B（約 10 GB）、高 Qwen3-VL 8B＋Hy-MT2 7B（約 15 GB）。
#   VRAM 用 Ollama 報嘅 size_vram 量，已經加埋搵字補圖約 1.7 GB。
#   中檔將 VRAM 留俾讀字：讀錯字，翻譯點好都冇用；1.8B 翻譯約九成同 7B 一樣好、快一倍。
# 點用：設定視窗「模型」頁；直接行就列出 Ollama 裝咗嘅模型同而家用緊邊檔：
#   .venv\Scripts\python -W ignore p10_1_models.py

import json
import urllib.request

import p2_1_translate
import p6_2_read
from p4_6_launch import save_setting

OLLAMA_HOST = "http://127.0.0.1:11434"
# Hy-MT2 1.8B 要用修好範本嘅版本：Ollama 由騰訊 GGUF 自動轉出嚟嘅範本冇放句子入去，次次答「onse」。
# 用 Modelfile-hy-mt2-1.8b 喺本機整（ollama create），唔使再下載；第一次開機設定會自動做
FIXED_SMALL = "hy-mt2-1.8b-fixed"
SMALL_SOURCE = "hf.co/tencent/Hy-MT2-1.8B-GGUF:Q6_K"    # 騰訊官方 GGUF，FIXED_SMALL 由佢整
# 騰訊官方 chat_template.jinja 嘅寫法，轉做 Ollama 範本（用 /api/create 整，同 Modelfile-hy-mt2-1.8b 一樣）
SMALL_TEMPLATE = ("<｜hy_begin▁of▁sentence｜>{{ if .System }}{{ .System }}<｜hy_place▁holder▁no▁3｜>{{ end }}"
                  "<｜hy_User｜>{{ .Prompt }}<｜hy_Assistant｜>{{ .Response }}")
SMALL_STOP = ["<｜hy_place▁holder▁no▁2｜>", "<｜hy_place▁holder▁no▁8｜>"]
# 下載大細（GB，Ollama 頁面寫嘅）：第一次開機設定話用家知要下載幾多
DOWNLOAD_GB = {"qwen3-vl:2b-instruct": 1.9, "qwen3-vl:8b-instruct": 6.1, SMALL_SOURCE: 1.5,
               "hf.co/unsloth/Hy-MT2-7B-GGUF:Q6_K": 6.2}
TIERS = {
    "輕": {"讀字": "qwen3-vl:2b-instruct", "翻譯": FIXED_SMALL, "VRAM": 6,
          "說明": "清楚嘅橫字（遊戲選單、網頁）OK；漫畫手寫字、細字會錯多啲"},
    "中": {"讀字": "qwen3-vl:8b-instruct", "翻譯": FIXED_SMALL, "VRAM": 10,
          "說明": "讀字差唔多全啱；翻譯約九成同高檔一樣好，快一倍"},
    "高": {"讀字": "qwen3-vl:8b-instruct", "翻譯": "hf.co/unsloth/Hy-MT2-7B-GGUF:Q6_K", "VRAM": 15,
          "說明": "最準（作者日用嗰套）"},
}
CUSTOM = "自訂"


def post(path, body, timeout=10):
    request = urllib.request.Request(OLLAMA_HOST + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


_vision = {}    # 模型名 → 識唔識睇圖：問過一次就記住，個模型唔會變


def installed():
    """Ollama 裝咗嘅模型：[(名, 識唔識睇圖)]。Ollama 冇開就回傳 None（同「一個都冇」分開）。"""
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=3) as response:
            names = [m["name"] for m in json.load(response).get("models", [])]
    except OSError:
        return None
    result = []
    for name in names:
        if name not in _vision:
            try:
                # capabilities 有 "vision" 先識睇圖；唔識嘅揀做讀字模型會即刻出錯
                _vision[name] = "vision" in post("/api/show", {"model": name}).get("capabilities", [])
            except OSError:
                _vision[name] = False
        result.append((name, _vision[name]))
    return result


def same_model(a, b):
    """Ollama 名冇寫 tag 就係「:latest」：hy-mt2-1.8b-fixed 同 hy-mt2-1.8b-fixed:latest 係同一個。"""
    def full(name):
        return name if ":" in name.split("/")[-1] else name + ":latest"
    return full(a) == full(b)


def is_installed(name, models):
    return models is not None and any(same_model(name, n) for n, _ in models)


def current():
    """而家用緊嘅（讀字模型, 翻譯模型）。"""
    return p6_2_read.vision_model(), p2_1_translate.current_model()


def tier_of(reading, translation):
    """呢對模型係邊檔；唔係三檔任何一檔就係「自訂」。"""
    for name, tier in TIERS.items():
        if same_model(reading, tier["讀字"]) and same_model(translation, tier["翻譯"]):
            return name
    return CUSTOM


def apply(reading, translation):
    """轉模型：存設定、下一次讀字／翻譯即刻用新嗰個；舊嗰個冇用就即刻卸走，還返 VRAM。"""
    old_reading, old_translation = current()
    p6_2_read.set_vision_model(reading)
    p2_1_translate.set_model(translation)
    save_setting("讀字模型", reading)
    save_setting("翻譯模型", translation)
    for old in {old_reading, old_translation}:
        if not same_model(old, reading) and not same_model(old, translation):
            p2_1_translate.unload_model(old)     # Ollama 冇開都唔緊要，佢自己會回 False


def main():
    models = installed()
    if models is None:
        print("Ollama 冇開")
        return
    reading, translation = current()
    print(f"而家：讀字 {reading}｜翻譯 {translation}（{tier_of(reading, translation)}檔）")
    for name, vision in models:
        print(f"  {'👁 ' if vision else '   '}{name}")
    for name, tier in TIERS.items():
        missing = [m for m in (tier["讀字"], tier["翻譯"]) if not is_installed(m, models)]
        print(f"{name}檔（約 {tier['VRAM']} GB）：{'齊' if not missing else '未下載 ' + '、'.join(missing)}")


if __name__ == "__main__":
    main()
