# 譯幕 第7期第1關：揀譯做邊種語言
#
# 做咩：字幕條同譯鏡用同一個設定（settings.json「譯做」），可以揀繁體中文（香港）、English、日本語、한국어。
#   每種語言自己一套：翻譯指示、字型、可唔可以直排、邊種原文唔使譯、用唔用香港用字。
#   翻譯器每次砌 prompt 都問 current()，所以轉咗即刻生效，唔使重開程式。
# Hy-MT2 官方 README：有中文就用中文指示（語言名寫中文），其他用英文指示（語言名寫英文）。
#   我哋譯去英日韓一律用英文指示：原文係中文都照用，官方話兩種都得，簡單啲。
# 點用：其他檔 import 呢度；直接行係自我測試：.venv\Scripts\python -W ignore p7_1_target.py

from dataclasses import dataclass, field

from i18n import current_language, tr
from p4_6_launch import load_settings, save_setting

SETTING = "譯做"
DEFAULT = "繁體中文"


@dataclass(frozen=True)
class Target:
    key: str                # 選單同 settings.json 用嘅名
    name: str               # 寫入翻譯指示嘅語言名（中文指示用簡體「繁体中文」，英文指示用英文）
    chinese_prompt: bool    # 用中文定英文指示
    skip: frozenset         # 呢幾種原文唔使譯（同目標一樣）
    hong_kong: bool         # 用唔用香港用字、簡轉繁、語氣詞表（全部淨係啱中文）
    fonts: tuple            # 譯文字型（排先嗰個冇就用下一個）
    vertical: bool          # 譯鏡可唔可以直排（日漫原本直排嘅字）
    sound_examples: str = field(default="")     # 擬聲字提示嘅例子


TARGETS = {
    "繁體中文": Target("繁體中文", "繁体中文", True, frozenset({"zh", "yue"}), True,
                   ("Microsoft JhengHei UI", "Microsoft JhengHei"), True,
                   "ドン→咚、ゴゴゴ→轟轟轟、ドキドキ→撲通撲通、ザワザワ→嘈嘈雜雜、シーン→鴉雀無聲、"
                   "デレデレ→嬌嗲、ニコッ→嫣然一笑、キラキラ→閃閃、じーっ→盯——、わいわい→吵吵鬧鬧"),
    "English": Target("English", "English", False, frozenset({"en"}), False,
                      ("Segoe UI", "Arial"), False,
                      "ドン→BOOM, ゴゴゴ→RUMBLE, ドキドキ→THUMP THUMP, ザワザワ→MURMUR, シーン→SILENCE, "
                      "デレデレ→LOVESTRUCK, ニコッ→SMILE, キラキラ→SPARKLE, じーっ→STARE, わいわい→CHATTER"),
    "日本語": Target("日本語", "Japanese", False, frozenset({"ja"}), False,
                  ("Yu Gothic UI", "Meiryo UI"), True,
                  "쾅→ドン, 두근두근→ドキドキ, BOOM→ドーン, 휙→ヒュッ"),
    "한국어": Target("한국어", "Korean", False, frozenset({"ko"}), False,
                  ("Malgun Gothic",), False,
                  "ドン→쾅, ゴゴゴ→우르르, ドキドキ→두근두근, ザワザワ→웅성웅성, シーン→조용, "
                  "デレデレ→헤벌쭉, ニコッ→싱긋, キラキラ→반짝반짝, じーっ→빤히, わいわい→왁자지껄"),
}

_current = None


def current():
    """而家譯做邊種語言；第一次問先讀 settings.json，之後記住（轉語言用 set_current）。"""
    global _current
    if _current is None:
        # 未揀過：英文介面預設譯做 English，繁中、廣東話介面譯做繁中
        fallback = "English" if current_language() == "en" else DEFAULT
        _current = TARGETS.get(load_settings().get(SETTING), TARGETS[fallback])
    return _current


def set_current(key):
    """轉語言：即刻生效，兼寫入 settings.json 下次開機照用。"""
    global _current
    _current = TARGETS[key]
    save_setting(SETTING, key)
    return _current


# ---------- 翻譯指示（Hy-MT2 官方 README 寫法）----------
PLAIN = {True: "将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}",
         False: "Translate the following text into {target}. Note that you should only output the translated result "
                "without any additional explanation:\n\n{text}"}
CONTEXT = {True: "【背景信息】\n{background}\n\n请结合背景信息将以下文本翻译为{target}。\n\n【待翻译文本】\n{text}",
           False: "[Background Information]\n{background}\n\nPlease translate the following text into {target}, "
                  "taking the provided background information into consideration.\n\n[Source Text]\n{text}"}
HISTORY_LINE = {True: "原文：{source}\n译文：{result}", False: "Source: {source}\nTranslation: {result}"}
GLOSSARY = {True: ("参考下面的翻译：", "{source} 翻译成 {target}"),
            False: ("Reference the following translations:", "{source} translates to {target}")}
# 擬聲字提示：之前淨講「擬聲詞或效果音」，「デレ」（擬態語，形容樣子）譯咗「嬌羞地說話」、「じーっ」譯「盯著看。」；
# 加「擬態詞」、「一至四個字、唔好寫句子」同擬態語例子之後：嬌嗲、盯——、慄慄、目瞪口呆、竊竊私語
SOUND = {True: "這是漫畫裏的擬聲詞或擬態詞（不是人名，也不是對白）。請譯成簡短的{target}擬聲詞或擬態詞"
               "（一至四個字），不要寫成句子，不要解釋，例如：{examples}",
         False: "This is an onomatopoeia or mimetic word in a manga (not a name, not dialogue). Translate it into a "
                "short {target} onomatopoeia or mimetic word (one to three words), not a sentence, no explanation, "
                "for example: {examples}"}


def plain_prompt(text, target=None):
    target = target or current()
    return PLAIN[target.chinese_prompt].format(target=target.name, text=text)


def context_prompt(history, text, target=None):
    """history：[(原文, 譯文), ...]，最舊排先。"""
    target = target or current()
    line = HISTORY_LINE[target.chinese_prompt]
    background = "\n".join(line.format(source=s, result=r) for s, r in history)
    return CONTEXT[target.chinese_prompt].format(background=background, target=target.name, text=text)


def glossary_prefix(terms, target=None):
    target = target or current()
    title, line = GLOSSARY[target.chinese_prompt]
    return title + "\n" + "\n".join(line.format(source=s, target=t) for s, t in terms) + "\n\n"


def sound_prompt(text, target=None):
    target = target or current()
    hint = SOUND[target.chinese_prompt].format(target=target.name if not target.chinese_prompt else "中文",
                                               examples=target.sound_examples)
    return CONTEXT[target.chinese_prompt].format(background=hint, target=target.name, text=text)


def target_menu(on_change, parent=None):
    """「譯做」子選單（單選）：揀咗就 set_current，再叫 on_change(新語言)；工作列同 ⚙ 選單共用。"""
    from PyQt6.QtGui import QAction, QActionGroup
    from PyQt6.QtWidgets import QMenu
    menu = QMenu(tr("譯做"), parent)
    group = QActionGroup(menu)
    group.setExclusive(True)
    for key in TARGETS:
        item = QAction(key, menu)
        item.setCheckable(True)
        item.setChecked(key == current().key)
        item.triggered.connect(lambda _=False, key=key: on_change(set_current(key)))
        group.addAction(item)
        menu.addAction(item)

    def sync():
        for item in group.actions():
            item.setChecked(item.text() == current().key)
    menu.aboutToShow.connect(sync)      # 另一個選單轉咗，呢度都要剔返啱嗰個
    menu.group = group                  # 要留住參照
    return menu


def main():
    """自我測試：四種語言嘅指示、唔譯規則；再用真模型每種譯一句日文、一句英文。"""
    from p2_1_translate import ask
    ok = True
    for key, target in TARGETS.items():
        prompt = plain_prompt("こんにちは", target)
        good = target.name in prompt and ("将以下" in prompt) == target.chinese_prompt
        ok &= good
        print(f"{key}：指示用{'中文' if target.chinese_prompt else '英文'}、唔譯 {sorted(target.skip)}、"
              f"{'可以直排' if target.vertical else '淨係打橫'}　{'✅' if good else '❌'}")
    samples = ["明日は早いので、もう寝ます。", "I'll hand it back to John now.", "오늘은 정말 피곤하다."]
    for key, target in TARGETS.items():
        for text in samples:
            result, seconds = ask(plain_prompt(text, target))
            print(f"  → {key}：{text} → {result}（{seconds:.2f} 秒）")
        result, _ = ask(sound_prompt("ドキドキ", target))
        print(f"  → {key} 擬聲字：ドキドキ → {result}")
    print("指示全部啱" if ok else "有錯")


if __name__ == "__main__":
    main()
