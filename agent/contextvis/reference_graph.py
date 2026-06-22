"""ContextVis 引用图(v2 地基)—— 分层可信度阶梯的**第①层:工具溯源边**。

设计见 ``context-vis/v2/operations.md`` §6「怎么建:一把可信度阶梯」。
本模块只建**层① 工具溯源**:每次触及路径 X(``read_file`` 读 / ``write_file``·``patch`` 写)
都连到 X 的**前一次写**——**写后读 = 数据流依赖**(后者用了前者写的内容)、**写后写 = 修订链**
(后者改了前者写的文件)。两者都是**系统真干过**的有向、高精度依赖,不是文字猜测。
层②(文字/语义共现)、层③(LLM 按需)留作后续增量。

与 ``chunk_topic_map`` / ``residual_drop_map`` 同构:纯函数、零 LLM、吃 ``messages`` + ``chunks``,
经 **messageIndex** 把事件解析回 chunkId(规避 regime/chunking 的 turn 编号不一致)。

工具名集合**复用单一真相源**:写集 = ``tool_result_classification.FILE_MUTATING_TOOL_NAMES``,
读集 = ``chunking._FILE_TOOLS`` —— 别在这里另立一份会漂移的清单。
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent.contextvis.chunking import (
    _FILE_TOOLS,
    _path_from_args,
    _tool_call_index,
)

try:
    from agent.tool_result_classification import FILE_MUTATING_TOOL_NAMES as _WRITE_TOOLS
except Exception:  # pragma: no cover - 防御:分类模块缺失时退回已知写工具
    _WRITE_TOOLS = frozenset({"write_file", "patch"})

_READ_TOOLS = frozenset(_FILE_TOOLS)  # {"read_file"}


def _mi_to_chunk(chunks: List[Dict[str, Any]]) -> Dict[int, str]:
    """messageIndex → chunkId(取首个覆盖该消息的 chunk)。与 chunk_topic_map 同一映射口径。"""
    out: Dict[int, str] = {}
    for c in chunks or []:
        cid = c.get("id")
        if cid is None:
            continue
        for ref in c.get("sourceRefs") or []:
            if isinstance(ref, dict) and isinstance(ref.get("messageIndex"), int):
                out.setdefault(ref["messageIndex"], cid)
    return out


def reference_graph(
    messages: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """层① 工具溯源引用图。

    返回::

        {
          "edges": [ {src, dst, src_mi, dst_mi, kind:"tool", rel, via:<path>, weight} ],
          "artifacts": [ {key:<path>, kind:"file", messageIndices:[...], chunks:[...], n} ],
          "layers": ["tool"],
        }

    - **边**:每次读/写连其**前最近一次同路径 write**;``rel`` = ``"read"``(写后读=数据流)
      或 ``"revision"``(写后写=修订)。``src``/``dst`` 为 chunkId(messageIndex 解析不到 → ``None``)。
    - **artifact**:被 ≥2 条消息触及的路径(= 形成线索/边的复现产物),喂符号表泳道。
    - 读一个本对话没写过的外部文件 → 无边(无前写);读↔读不成边(留给层②文字共现)。
    """
    messages = messages or []
    call_index = _tool_call_index(messages)
    mi2c = _mi_to_chunk(chunks)

    last_write: Dict[str, int] = {}          # path -> 最近一次写的 messageIndex
    path_msgs: Dict[str, List[int]] = {}     # path -> 触及它的所有 messageIndex(artifact 用)
    edges: List[Dict[str, Any]] = []

    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        cid = msg.get("tool_call_id") or ""
        paired = call_index.get(cid, {})
        name = msg.get("tool_name") or paired.get("name") or ""
        is_write = name in _WRITE_TOOLS
        is_read = name in _READ_TOOLS
        if not (is_write or is_read):
            continue
        path = _path_from_args(paired.get("args") or "")
        if not path or path == "?":
            continue
        # 每次触及(读/写)→ 连该路径**前一次写**:写后读=数据流;写后写=修订链。
        w = last_write.get(path)
        if w is not None and w != i:
            edges.append({
                "src": mi2c.get(w),
                "dst": mi2c.get(i),
                "src_mi": w,
                "dst_mi": i,
                "kind": "tool",
                "rel": "revision" if is_write else "read",
                "via": path,
                "weight": 1.0,
            })
        if is_write:
            last_write[path] = i
        path_msgs.setdefault(path, []).append(i)

    artifacts: List[Dict[str, Any]] = []
    for p, mis in path_msgs.items():
        uniq = sorted(set(mis))
        if len(uniq) < 2:
            continue
        artifacts.append({
            "key": p,
            "kind": "file",
            "messageIndices": uniq,
            "chunks": sorted({mi2c[m] for m in uniq if m in mi2c}),
            "n": len(uniq),
        })

    return {"edges": edges, "artifacts": artifacts, "layers": ["tool"]}
