# 譯幕 第6期第5關（工具）：改補圖模型，等佢喺 DirectML（GPU）行得到
#
# 點解要改：LaMa 個 ONNX 冇用標準 FFT，用 sin／cos 矩陣乘法代替；入面有 144 個
#   「2 維矩陣 × 5 維數組」嘅 MatMul，DirectML 嘅 MatMul 最多處理 4 維，一行就出「參數錯誤」。
# 點改：每個咁嘅 MatMul，乘之前將 5 維嗰個前面幾維壓埋做一維（變 4 維），乘完再變返原本形狀。
#   淨係改咗數組點擺，數值完全一樣。
# 點用：.venv\Scripts\python p6_5_fix_lama.py（只要行一次；原本個檔唔郁，另存新檔）

from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper, shape_inference

SOURCE = Path("models/lama/lama_fp32.onnx")
TARGET = Path("models/lama/lama_fp32_dml.onnx")
MAX_RANK = 4        # DirectML MatMul 最多幾多維


def ranks(model):
    """每個中間結果有幾多維：先將輸入嘅「批次」定做 1，形狀推算先計得晒。"""
    fixed = onnx.ModelProto()
    fixed.CopyFrom(model)
    for value in fixed.graph.input:
        for dim in value.type.tensor_type.shape.dim:
            if dim.dim_param:
                dim.ClearField("dim_param")
                dim.dim_value = 1
    inferred = shape_inference.infer_shapes(fixed, data_prop=True)
    found = {init.name: len(init.dims) for init in inferred.graph.initializer}
    for value in [*inferred.graph.value_info, *inferred.graph.input, *inferred.graph.output]:
        if value.type.tensor_type.HasField("shape"):
            found[value.name] = len(value.type.tensor_type.shape.dim)
    return found


def fix(model):
    rank = ranks(model)
    graph = model.graph
    # 幾個固定數：用 initializer 擺，所有改咗嘅 MatMul 共用
    consts = {"fix_one_minus_one": [1, -1], "fix_minus2": [-2], "fix_zero": [0],
              "fix_big": [2 ** 62]}
    for name, value in consts.items():
        graph.initializer.append(numpy_helper.from_array(np.array(value, np.int64), name))

    new_nodes, changed = [], 0
    for node in graph.node:
        if node.op_type != "MatMul":
            new_nodes.append(node)
            continue
        a, b = node.input
        ra, rb = rank.get(a), rank.get(b)
        if ra is None or rb is None or max(ra, rb) <= MAX_RANK:
            new_nodes.append(node)
            continue
        if min(ra, rb) > 2:
            raise ValueError(f"{node.name}：兩邊都係多維（{ra}、{rb}），未識改")
        big_first = ra > rb         # 多維嗰個喺左邊定右邊
        big, small = (a, b) if big_first else (b, a)
        p = f"{node.name}_fix"
        # 多維嗰個嘅形狀：[前面幾維..., 尾兩維]；壓做 [1, 前面幾維乘埋, 尾兩維]
        new_nodes += [
            helper.make_node("Shape", [big], [f"{p}_shape"]),
            helper.make_node("Slice", [f"{p}_shape", "fix_minus2", "fix_big"], [f"{p}_tail"]),
            helper.make_node("Slice", [f"{p}_shape", "fix_zero", "fix_minus2"], [f"{p}_lead"]),
            helper.make_node("Concat", ["fix_one_minus_one", f"{p}_tail"], [f"{p}_flat_shape"], axis=0),
            helper.make_node("Reshape", [big, f"{p}_flat_shape"], [f"{p}_flat"]),
            helper.make_node("MatMul", [f"{p}_flat", small] if big_first else [small, f"{p}_flat"], [f"{p}_out"]),
            # 乘完嘅尾兩維由結果度攞返（行數、列數可能變咗），前面幾維用返原本嘅
            helper.make_node("Shape", [f"{p}_out"], [f"{p}_out_shape"]),
            helper.make_node("Slice", [f"{p}_out_shape", "fix_minus2", "fix_big"], [f"{p}_out_tail"]),
            helper.make_node("Concat", [f"{p}_lead", f"{p}_out_tail"], [f"{p}_back_shape"], axis=0),
            helper.make_node("Reshape", [f"{p}_out", f"{p}_back_shape"], list(node.output), name=node.name),
        ]
        changed += 1
    del graph.node[:]
    graph.node.extend(new_nodes)
    return changed


def check(path_a, path_b):
    """用 CPU 行原本同改咗嘅模型，比較輸出：應該差唔多一模一樣。"""
    import onnxruntime as ort
    rng = np.random.default_rng(0)
    image = rng.random((1, 3, 512, 512), np.float32)
    mask = (rng.random((1, 1, 512, 512)) > 0.9).astype(np.float32)
    outs = [ort.InferenceSession(str(p), providers=["CPUExecutionProvider"]).run(None, {"image": image, "mask": mask})[0]
            for p in (path_a, path_b)]
    return float(np.abs(outs[0] - outs[1]).max())


def main():
    model = onnx.load(SOURCE)
    changed = fix(model)
    onnx.checker.check_model(model)
    onnx.save(model, TARGET)
    print(f"改咗 {changed} 個 MatMul，存咗 {TARGET}")
    print(f"同原本模型輸出最多差 {check(SOURCE, TARGET):.6f}（0 至 255）")


if __name__ == "__main__":
    main()
