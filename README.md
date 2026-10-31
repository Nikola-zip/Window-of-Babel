# Window of Babel

A movable window that translates whatever sits behind it. Place it over a manga page, a game, an app or a website, and the text inside is read, translated and redrawn in the language you choose.

Everything runs on your own computer. There is no account, no API key and no cloud service.

[繁體中文說明](#繁體中文)

## Features

- **Works anywhere on screen:** manga, games, apps, websites.
- **Keeps the look of the page:** finds text, paints it out and redraws the translation in place, vertically for Chinese and Japanese where the original was vertical.
- **Translates into** Traditional Chinese, English, Japanese or Korean.
- **Auto mode:** reads again when the picture stops moving.
- **Remembers names:** each work keeps its own list of character names. Correct a translation once and it stays corrected.
- **Hold to view the original** without closing the window.
- **Choose your font:** download a free one inside the app, or add your own font file.
- **Interface in** English, Traditional Chinese or Cantonese, with light and dark themes.

## Requirements

- Windows 10 or 11 (x64)
- A GPU with 8 GB of VRAM or more (see the tiers below)
- [Ollama](https://ollama.com/download)
- Python 3.10
- About 4 to 13 GB of free disk space, depending on the tier

## Install

1. Install Ollama and Python 3.10.
2. Open PowerShell and run:

```powershell
git clone https://github.com/Nikola-zip/Window-of-Babel.git
cd Window-of-Babel
py -3.10 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -W ignore main.py
```

3. On the first run, a setup window checks Ollama, reads your VRAM and recommends a tier. Press the button and it downloads what it needs.

To add a desktop shortcut later, open Settings, go to General and choose the shortcut option.

## Model tiers

| Tier | Reading | Translation | VRAM used | Suggested card | Download | Best for |
|---|---|---|---|---|---|---|
| Light | Qwen3-VL 2B | Hy-MT2 1.8B | about 6 GB | 8 GB | 3.7 GB | Clear horizontal text. More mistakes on handwriting and small text. |
| Medium | Qwen3-VL 8B | Hy-MT2 1.8B | about 10 GB | 12 GB | 7.9 GB | Almost all text read correctly. About 90% of the High translation quality, twice as fast. |
| High | Qwen3-VL 8B | Hy-MT2 7B | about 15 GB | 16 GB or more | 12.6 GB | Most accurate. |

The figures include about 1.7 GB of VRAM and a 0.3 GB download for text finding and clean-up. You can switch tier at any time under Settings, Models.

**Tested on:** Windows 11 with an RTX 4090 (24 GB) and Ollama 0.40.6. All three tiers ran on that card; the VRAM figures for smaller cards are estimates, and AMD and Intel GPUs are untested.

## Default hotkeys

| Keys | Action |
|---|---|
| Ctrl+Alt+T | Read and translate |
| Ctrl+Alt+G | Adjust the window |
| Ctrl+Alt+A | Auto mode |
| Ctrl+Alt+V | Hold to view the original |
| Ctrl+Alt+H | History |
| Ctrl+Alt+N | Clear translation context |

You can change them under Settings, Hotkeys. Some games block global hotkeys, so the same actions are on the window's toolbar.

## Privacy

Only the area under the window is captured, and it is processed on your computer. The app uses the network only when you ask it to:

- downloading models during setup
- downloading a font
- pressing the button that looks up name translations online, which sends only the title and entry you typed

Your settings, name lists and logs stay in the app folder.

## Licence

Window of Babel is released under the [GNU General Public License v3.0](LICENSE).

Third-party models and libraries have their own terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 繁體中文

巴別塔之窗是一塊可以移動的翻譯視窗。把它放到漫畫、遊戲、應用程式或網頁上，視窗內的文字就會被讀取、翻譯，並以你選擇的語言重新寫回畫面。

所有處理都在你自己的電腦上進行，不需要帳號、API 金鑰或雲端服務。

- **需求：** Windows 10／11（x64）、8 GB VRAM 或以上的顯示卡、[Ollama](https://ollama.com/download)、Python 3.10。
- **安裝：** 依上方 [Install](#install) 的指令操作。首次開啟時，設定視窗會檢查 Ollama、讀取 VRAM、建議模型檔次，按一下即可下載。
- **譯文語言：** 繁體中文、English、日本語、한국어。
- **介面語言：** English、繁體中文、廣東話。
- **授權：** GPL-3.0；第三方模型及套件的授權見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
