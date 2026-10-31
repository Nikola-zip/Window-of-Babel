# Third-party notices

Window of Babel is licensed under GPL-3.0. It uses the third-party work below, which keeps its own licence.

## Model files on this project's Releases page

The `models-v1` release hosts these two files. The first-run setup downloads them and checks their SHA-256.

### comictextdetector.pt.onnx

- **Purpose:** finds text on the screen.
- **Licence:** GNU General Public License v3.0.
- **Source code and training code:** [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector)
- **File obtained from:** [zyddnys/manga-image-translator, release beta-0.2.1](https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.2.1)
- **Changes:** none.

### lama_fp32_dml.onnx

- **Purpose:** paints out the original text.
- **Licence:** Apache License 2.0. The full text is in [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt).
- **Copyright:** Copyright 2021 Samsung Research.
- **Original model:** big-lama from [advimman/lama](https://github.com/advimman/lama)
- **ONNX export:** `lama_fp32.onnx` from [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX), licensed Apache-2.0.
- **Changes:** this project modified the ONNX file so that it runs on DirectML, which supports at most four dimensions in MatMul. Reshape operations were added around those MatMul nodes. [p6_5_fix_lama.py](p6_5_fix_lama.py) is the script that made the change; it needs the `onnx` package and the original file, and users do not need to run it.
- **Training data:** big-lama was trained on the Places2 dataset. Its authors offer that dataset for academic research and education. This project is a non-commercial hobby project; if you plan commercial use, check those terms yourself.

## Models downloaded through Ollama

These are not hosted by this project. Ollama downloads them from their publishers when you choose a tier.

| Model | Licence | Publisher |
|---|---|---|
| Qwen3-VL 2B and 8B | Apache-2.0 | Qwen team |
| Hy-MT2 1.8B and 7B | Apache-2.0 | Tencent Hunyuan |

The app creates `hy-mt2-1.8b-fixed` on your computer from the official Hy-MT2 1.8B GGUF, with a corrected prompt template. See [Modelfile-hy-mt2-1.8b](Modelfile-hy-mt2-1.8b).

## Fonts

No fonts are included in this repository. When you press Download, the app gets the font from its authors or Google Fonts. All fonts in the list use the SIL Open Font License 1.1:

- jf open Huninn, by justfont
- LXGW WenKai TC, by LXGW
- Iansui, by ButTaiwan, based on Klee by Fontworks
- Noto Sans, Noto Sans JP and Noto Sans KR, by the Noto Project Authors
- Comic Neue, by Craig Rozynski and contributors

If you add your own font file, you are responsible for its licence.

## Python packages

`pip` installs these from PyPI. They are not included in this repository.

| Package | Licence |
|---|---|
| PyQt6 | GPL-3.0 |
| PyQt6-Fluent-Widgets | GPL-3.0, commercial use needs a paid licence from its author |
| onnxruntime-directml | MIT |
| NumPy | BSD-3-Clause |
| SciPy | BSD-3-Clause |
| OpenCC | Apache-2.0 |
