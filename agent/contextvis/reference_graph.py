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

import os
from typing import Any, Dict, List

from agent.contextvis.chunking import (
    _FILE_TOOLS,
    _path_from_args,
    _tool_call_index,
)
from agent.contextvis.regime import _salient_tokens, _segment_turns

try:
    from agent.tool_result_classification import FILE_MUTATING_TOOL_NAMES as _WRITE_TOOLS
except Exception:  # pragma: no cover - 防御:分类模块缺失时退回已知写工具
    _WRITE_TOOLS = frozenset({"write_file", "patch"})

_READ_TOOLS = frozenset(_FILE_TOOLS)  # {"read_file"}


def _lex_enabled() -> bool:
    """层② 文字共现总开关(env HERMES_CONTEXTVIS_LEX,默认开)。"""
    return os.environ.get("HERMES_CONTEXTVIS_LEX", "1") not in ("0", "false", "False", "")


def _lex_hubfrac() -> float:
    """hub 抑制:token 出现轮数 > n_turns*frac → 视作环境词、不连边(默认 0.6,env 可调)。"""
    try:
        return float(os.environ.get("HERMES_CONTEXTVIS_LEX_HUBFRAC", "0.6"))
    except (TypeError, ValueError):
        return 0.6


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


def _lexical_edges(
    messages: List[Dict[str, Any]],
    mi2c: Dict[int, str],
) -> List[Dict[str, Any]]:
    """层② 文字共现边(复用 regime 的 salient 抽取,= 被扔掉的 token_turns 宝藏)。

    防毛球三件套:**链不成团**(token 出现的轮按序相邻连,不连成全团)、**特异度权重**
    (边权 = Σ 1/df,罕见 token 强)、**hub 抑制**(df > n_turns*frac 的环境词不连边)。
    方向按时间(早→晚,启发式)。端点取每轮首个 user 消息的 messageIndex → mi2c 解析回
    chunk(用 messageIndex 而非 turn 号,规避 regime 0-indexed vs chunking 1-indexed)。
    """
    turn_of, n_turns, boiler, raw = _segment_turns(messages)
    if n_turns <= 1:
        return []

    turn_salient: List[set] = [set() for _ in range(n_turns)]
    turn_first_mi: Dict[int, int] = {}
    for i, msg in enumerate(messages):
        if boiler[i] or msg.get("role") == "system":
            continue  # 系统底座不算对话轮,跳过免造 turn0 假 hub
        t = turn_of[i]
        turn_salient[t] |= _salient_tokens(raw[i])
        if msg.get("role") == "user" and t not in turn_first_mi:
            turn_first_mi[t] = i

    token_turns: Dict[str, set] = {}
    for t, s in enumerate(turn_salient):
        for tok in s:
            token_turns.setdefault(tok, set()).add(t)

    hub_cap = max(3, round(n_turns * _lex_hubfrac()))
    pair_weight: Dict[tuple, float] = {}
    pair_tokens: Dict[tuple, set] = {}
    for tok, ts in token_turns.items():
        df = len(ts)
        if df < 2 or df > hub_cap:
            continue  # df<2 不复现;df>hub_cap 环境词
        w = 1.0 / df
        order = sorted(ts)
        for a, b in zip(order, order[1:]):  # 链:相邻出现轮,不连成团(防毛球)
            key = (a, b)
            pair_weight[key] = pair_weight.get(key, 0.0) + w
            pair_tokens.setdefault(key, set()).add(tok)

    edges: List[Dict[str, Any]] = []
    for (a, b), w in pair_weight.items():
        ra, rb = turn_first_mi.get(a), turn_first_mi.get(b)
        if ra is None or rb is None:
            continue
        toks = sorted(pair_tokens[(a, b)], key=lambda x: len(token_turns[x]))  # 最罕见在前
        via = toks[0] + (f" +{len(toks) - 1}" if len(toks) > 1 else "")
        edges.append({
            "src": mi2c.get(ra),
            "dst": mi2c.get(rb),
            "src_mi": ra,
            "dst_mi": rb,
            "kind": "lexical",
            "rel": "cooccur",
            "via": via,
            "weight": round(w, 3),
        })
    return edges


def _keyword_index(
    messages: List[Dict[str, Any]],
    mi2c: Dict[int, str],
) -> List[Dict[str, Any]]:
    """关键词索引 = 复现 salient token → 它出现的 chunkIds(**token-中心**路径追踪入口)。

    与层②文字共现**同源**(都吃 ``_segment_turns`` 的 raw + ``_salient_tokens``),但聚到
    **chunk** 而非 turn:供右栏列出、点击某关键词后画布高亮其全部出现块 + 贯穿连线
    (区别于 chunk-中心的"点块看边")。只留 ≥2 个 chunk 的**复现** token(单次出现无线索可追),
    按出现块数降序取前 N。系统词/boilerplate 跳过,免造环境噪声。
    """
    _turn_of, _n_turns, boiler, raw = _segment_turns(messages)
    kc: Dict[str, set] = {}
    for i, msg in enumerate(messages):
        if boiler[i] or msg.get("role") == "system":
            continue
        cid = mi2c.get(i)
        if not cid:
            continue
        for tok in _salient_tokens(raw[i]):
            kc.setdefault(tok, set()).add(cid)
    out = [
        {"key": tok, "chunks": sorted(cids), "n": len(cids)}
        for tok, cids in kc.items()
        if len(cids) >= 2
    ]
    out.sort(key=lambda k: (-k["n"], k["key"]))
    return out[:40]


def reference_graph(
    messages: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """层① 工具溯源引用图。

    返回::

        {
          "edges": [ {src, dst, src_mi, dst_mi, kind:"tool", rel, via:<path>, weight} ],
          "artifacts": [ {key:<path>, kind:"file", messageIndices:[...], chunks:[...], n} ],
          "files": [ {key:<path>, chunks:[...chunkId], n, tokens} ],
          "keywords": [ {key:<token>, chunks:[...chunkId], n} ],
          "layers": ["tool"],
        }

    - **边**:每次读/写连其**前最近一次同路径 write**;``rel`` = ``"read"``(写后读=数据流)
      或 ``"revision"``(写后写=修订)。``src``/``dst`` 为 chunkId(messageIndex 解析不到 → ``None``)。
    - **artifact**:被 ≥2 条消息触及的路径(= 形成线索/边的复现产物)。
    - **files**:工具触及过的**全部**文件路径(≥1)→ chunkIds,按总 token 降序;喂右栏「产物优先」索引/路径追踪。
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

    # 产物索引(喂右栏「产物优先」+ 路径追踪):工具触及过的**全部**文件路径(≥1 次,区别于
    # artifacts 的 ≥2「成线索」)→ 它的 chunkIds(tool_result/file 块)。按总 token 降序——
    # file 是上下文膨胀主因,把最占地的产物顶上去,点它在画布追踪/高亮。
    chunk_tok = {c.get("id"): c.get("tokens", 0) for c in (chunks or []) if c.get("id")}
    files: List[Dict[str, Any]] = []
    for p, mis in path_msgs.items():
        cids = sorted({mi2c[m] for m in sorted(set(mis)) if m in mi2c})
        if not cids:
            continue
        files.append({
            "key": p,
            "chunks": cids,
            "n": len(cids),
            "tokens": sum(chunk_tok.get(cid, 0) for cid in cids),
        })
    files.sort(key=lambda f: (-f["tokens"], -f["n"], f["key"]))

    layers = ["tool"]
    if _lex_enabled():
        edges.extend(_lexical_edges(messages, mi2c))
        layers.append("lexical")

    return {
        "edges": edges,
        "artifacts": artifacts,
        "files": files,
        "keywords": _keyword_index(messages, mi2c),
        "layers": layers,
    }
