"""ContextVis 服务端分块流水线 —— 三段：segment → chunk(策略) → 产出。

只读、best-effort：为 dashboard 的 ContextVis 视图产出"当前 prompt 由哪些
chunk 构成"的真值快照。token 用 Hermes 既有的 chars//4 估算
(``estimate_messages_tokens_rough``)，最后**整体缩放**校准到真实总占用
(``agent.context_compressor.last_prompt_tokens``)——逐块绝对值是重建，比例
与总量是真实。

架构（见根目录 CLAUDE.md + 计划档3）：

  ① Segmenter   —— 把真实上下文（system parts / tool schemas / history）
                   切成原子 ``Segment``（最小不可分单元 + 指回真实会话的 ref）。
  ② ChunkStrategy 注册表 —— 每个**渲染带(band)**一个策略；结构化(v1) ↔
                   语义(未来) 可插拔，接口不变即可替换。
  ③ build_snapshot_chunks —— 跑流水线，产出 {chunks, strategy_versions, generated_at}。

渲染带(5 个，对应概念图的 5 个区域)：
    system · tool_schema · history · file · tool_result
其中 history 带聚合 user/assistant/tool_call 三种 segment（细分只在 segment
层保留，给 provenance / 未来语义聚类用）。

为未来交互预留：每个 chunk 带 ``source_refs``（provenance，指回真实 message），
``fate`` 字段留空——它们是"只读视图"升级"可编辑视图"的地基。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 每个 chunk 原文的截断上限（字符）。超出标注省略 + 真实 token 数。原文随快照
# 推送供右侧栏检视器显示；localhost 下可接受，HERMES_CONTEXTVIS_RAW=0 可关。
_RAW_CAP = 32_000


def _raw_enabled() -> bool:
    val = os.environ.get("HERMES_CONTEXTVIS_RAW", "1")
    return str(val).strip().lower() not in {"0", "false", "no", "off"}


def _cap_raw(text: str, tokens: int) -> str:
    if len(text) <= _RAW_CAP:
        return text
    return text[:_RAW_CAP] + f"\n\n…（已截断，本块约 {tokens:,} tok）"


def _join_raw(segs: "List[Segment]") -> str:
    return "\n\n".join(s.raw for s in segs if s.raw)

# ── segment 类型（细粒度，内部用） ────────────────────────────────────
SEG_SYSTEM = "system"
SEG_TOOL_SCHEMA = "tool_schema"
SEG_USER = "user"
SEG_ASSISTANT = "assistant"
SEG_TOOL_CALL = "tool_call"
SEG_TOOL_RESULT = "tool_result"
SEG_FILE = "file"

# ── 渲染带（chunk 的 type，5 个） ─────────────────────────────────────
BAND_ORDER = ["system", "tool_schema", "history", "file", "tool_result"]

# segment 类型 → 渲染带
_SEG_TO_BAND = {
    SEG_SYSTEM: "system",
    SEG_TOOL_SCHEMA: "tool_schema",
    SEG_USER: "history",
    SEG_ASSISTANT: "history",
    SEG_TOOL_CALL: "history",
    SEG_FILE: "file",
    SEG_TOOL_RESULT: "tool_result",
}

# 哪些 Hermes 工具名算"读文件类"→ file 带（按路径标签）。其余 tool 结果 →
# tool_result 带（按 _summarize_tool_result 摘要标签）。
_FILE_TOOLS = {"read_file"}

# 策略版本号：未来换语义策略时 bump，便于前端/诊断区分。
_STRATEGY_VERSIONS = {
    "system": "structural-1",
    "tool_schema": "by-toolset-1",
    "history": "by-turn-1",
    "file": "identity-1",
    "tool_result": "identity-1",
}


@dataclass
class Segment:
    """最小不可分单元 + 指回真实会话的 ref（provenance）。"""

    id: str
    type: str
    turn: int
    tokens: int
    label: str
    ref: Dict[str, Any]
    group: Optional[str] = None  # tool_schema 的 toolset 名等
    raw: str = ""  # 原文，供右侧栏检视器显示
    folded: bool = False  # 压缩折叠产物（摘要消息），非对话轮


@dataclass
class Chunk:
    """展示单元（= 一个渲染带内的一块）。JSON 字段名对齐 web 契约（camelCase）。"""

    id: str
    type: str  # 渲染带
    tokens: int
    turn: int
    label: str
    sourceRefs: List[Dict[str, Any]]
    group: Optional[str] = None
    members: int = 1
    turnSpan: Optional[List[int]] = None
    fate: Optional[str] = None  # 预留：未来交互式压缩用，v1 恒空
    raw: Optional[str] = None  # 成员原文拼接（截断），供检视器
    folded: bool = False  # 压缩折叠产物（摘要）：turn 带画成「已折叠」块


# ── token 估算（复用 Hermes 既有 chars//4 口径） ──────────────────────

def _est_str(s: str) -> int:
    return (len(s) + 3) // 4 if s else 0


def _est_msg(msg: Dict[str, Any]) -> int:
    """单条 message 的 token 估算，复用既有 estimate_messages_tokens_rough。"""
    try:
        from agent.model_metadata import estimate_messages_tokens_rough

        return estimate_messages_tokens_rough([msg])
    except Exception:
        return _est_str(str(msg.get("content") or ""))


# ── ① Segmenter ──────────────────────────────────────────────────────

def _segment_system(agent: Any) -> List[Segment]:
    """system prompt → 3 段（stable / context / volatile），来自既有分节拼装。"""
    out: List[Segment] = []
    try:
        from agent.system_prompt import build_system_prompt_parts

        parts = build_system_prompt_parts(agent) or {}
    except Exception:
        # 退路：用缓存的整串当单段，不让 system 缺失整张快照。
        cached = getattr(agent, "_cached_system_prompt", "") or ""
        if cached:
            return [Segment("sys:all", SEG_SYSTEM, 0, _est_str(cached),
                            "system prompt", {"part": "system:all"}, raw=cached)]
        return out
    for key in ("stable", "context", "volatile"):
        text = parts.get(key) or ""
        if not text.strip():
            continue
        out.append(
            Segment(
                id=f"sys:{key}",
                type=SEG_SYSTEM,
                turn=0,
                tokens=_est_str(text),
                label=key,
                ref={"part": f"system:{key}"},
                raw=text,
            )
        )
    return out


def _segment_tool_schemas(agent: Any) -> List[Segment]:
    """发给模型的 tool schema 数组 → 每工具 1 段，group=toolset。"""
    out: List[Segment] = []
    tools = getattr(agent, "tools", None) or []
    try:
        from model_tools import get_toolset_for_tool
    except Exception:
        get_toolset_for_tool = None  # type: ignore
    for i, tool in enumerate(tools):
        try:
            fn = tool.get("function", tool) if isinstance(tool, dict) else {}
            name = fn.get("name") or f"tool_{i}"
            raw = json.dumps(tool, ensure_ascii=False, indent=2)
            tokens = _est_str(json.dumps(tool, ensure_ascii=False))
        except Exception:
            continue
        toolset = None
        if get_toolset_for_tool:
            try:
                toolset = get_toolset_for_tool(name)
            except Exception:
                toolset = None
        out.append(
            Segment(
                id=f"schema:{name}",
                type=SEG_TOOL_SCHEMA,
                turn=0,
                tokens=tokens,
                label=name,
                ref={"part": f"tool:{name}"},
                group=toolset or "tools",
                raw=raw,
            )
        )
    return out


def _tool_call_index(history: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """tool_call_id → {name, args_json}，用于把 tool 结果配回它的调用参数。"""
    index: Dict[str, Dict[str, str]] = {}
    for msg in history:
        for call in (msg.get("tool_calls") or []):
            try:
                cid = call.get("id")
                fn = call.get("function") or {}
                if cid:
                    index[cid] = {
                        "name": fn.get("name") or "",
                        "args": fn.get("arguments") or "",
                    }
            except Exception:
                continue
    return index


def _summarize(tool_name: str, args_json: str, content: str) -> str:
    try:
        from agent.context_compressor import _summarize_tool_result

        return _summarize_tool_result(tool_name, args_json, content)
    except Exception:
        return f"[{tool_name or 'tool'}] ({len(content or '')} chars)"


def _path_from_args(args_json: str) -> str:
    try:
        args = json.loads(args_json) if args_json else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    return args.get("path") or args.get("file_path") or "?"


def _segment_history(history: List[Dict[str, Any]]) -> List[Segment]:
    """会话历史 → 每消息 1 段；role=tool 按来源工具分流 file / tool_result。"""
    out: List[Segment] = []
    call_index = _tool_call_index(history)
    marker = _summary_end_marker()
    turn = 0
    for i, msg in enumerate(history):
        role = msg.get("role")
        if role == "system":
            continue  # system prompt 由 _segment_system 负责，避免重复
        # 压缩摘要(user 角色、content 以 END marker 结尾)是**折叠产物**，不是对话轮：
        # 不计入轮号(免得顶掉后续真实轮的编号)，单独成「已折叠」块。merge-prefix
        # 情形 marker 在正文中段、不在末尾，故不会误伤真实消息。
        is_summary = (
            role in ("user", "assistant")
            and _content_text(msg).rstrip().endswith(marker)
        )
        if role == "user" and not is_summary:
            turn += 1
        tokens = _est_msg(msg)
        ref = {"messageIndex": i}
        raw = _msg_raw(msg)
        if is_summary:
            out.append(Segment(f"msg:{i}", SEG_ASSISTANT, turn, tokens,
                               "已折叠摘要", ref, raw=raw, folded=True))
        elif role == "user":
            text = _content_text(msg)
            out.append(Segment(f"msg:{i}", SEG_USER, turn, tokens,
                               _snippet(text) or "user", ref, raw=raw))
        elif role == "assistant":
            text = _content_text(msg)
            label = _snippet(text) or ("tool call" if msg.get("tool_calls") else "assistant")
            out.append(Segment(f"msg:{i}", SEG_ASSISTANT, turn, tokens, label, ref, raw=raw))
        elif role == "tool":
            cid = msg.get("tool_call_id") or ""
            paired = call_index.get(cid, {})
            tool_name = msg.get("tool_name") or paired.get("name") or "tool"
            args_json = paired.get("args") or ""
            content = _content_text(msg)
            if tool_name in _FILE_TOOLS:
                out.append(Segment(f"msg:{i}", SEG_FILE, turn, tokens,
                                   _path_from_args(args_json), ref, raw=raw))
            else:
                out.append(Segment(f"msg:{i}", SEG_TOOL_RESULT, turn, tokens,
                                   _summarize(tool_name, args_json, content), ref, raw=raw))
        # 其它 role 忽略
    return out


def _msg_raw(msg: Dict[str, Any]) -> str:
    """一条消息的可读原文：正文 + 工具调用详情（name(arguments)）。"""
    parts: List[str] = []
    txt = _content_text(msg)
    if txt:
        parts.append(txt)
    for call in (msg.get("tool_calls") or []):
        try:
            fn = call.get("function") or {}
            name = fn.get("name") or "tool"
            args = fn.get("arguments") or ""
            parts.append(f"→ {name}({args})")
        except Exception:
            continue
    return "\n".join(parts)


def _content_text(msg: Dict[str, Any]) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, dict) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return " ".join(parts)
    return ""


def _snippet(text: str, n: int = 48) -> str:
    text = " ".join((text or "").split())
    return (text[: n - 1] + "…") if len(text) > n else text


def _summary_end_marker() -> str:
    """压缩摘要(user 角色)末尾的 END marker —— 用来把折叠产物从对话轮里认出来。

    懒导入避免与 context_compressor 形成模块级导入环;失败回退硬编码常量。
    """
    try:
        from agent.context_compressor import _SUMMARY_END_MARKER

        return _SUMMARY_END_MARKER
    except Exception:  # pragma: no cover - 导入形态变更时的兜底
        return (
            "\n\n--- END OF CONTEXT SUMMARY — "
            "respond to the message below, not the summary above ---"
        )


# ── token 缩放：整体校准到真实总占用 ──────────────────────────────────

def _scale(segments: List[Segment], target: int) -> None:
    if target <= 0 or not segments:
        return
    total = sum(s.tokens for s in segments)
    if total <= 0:
        return
    factor = target / total
    for s in segments:
        s.tokens = max(0, round(s.tokens * factor))


# ── ② ChunkStrategy 注册表（按渲染带，可插拔） ────────────────────────

def _strat_identity(band: str, segs: List[Segment]) -> List[Chunk]:
    return [
        Chunk(
            id=f"{band}:{s.id}",
            type=band,
            tokens=s.tokens,
            turn=s.turn,
            label=s.label,
            sourceRefs=[s.ref],
            group=s.group,
            members=1,
            turnSpan=[s.turn, s.turn],
            raw=_cap_raw(s.raw, s.tokens),
        )
        for s in segs
    ]


def _strat_group_by_turn(band: str, segs: List[Segment]) -> List[Chunk]:
    """history 带：同一轮的 user/assistant/tool_call 合并成一块；
    压缩折叠产物(folded)**单独成块**，不并入任何对话轮。"""
    chunks: List[Chunk] = []
    # 折叠摘要：每条单独成「已折叠」块（id 用 msg 序号，区别于 turnN）。
    for s in segs:
        if not s.folded:
            continue
        chunks.append(
            Chunk(
                id=f"{band}:{s.id}",
                type=band,
                tokens=s.tokens,
                turn=s.turn,
                label=s.label,
                sourceRefs=[s.ref],
                members=1,
                turnSpan=[s.turn, s.turn],
                folded=True,
                raw=_cap_raw(s.raw, s.tokens),
            )
        )
    by_turn: Dict[int, List[Segment]] = {}
    for s in segs:
        if s.folded:
            continue
        by_turn.setdefault(s.turn, []).append(s)
    for turn in sorted(by_turn):
        group = by_turn[turn]
        # 标签优先取该轮 user 段的首句（主线视角）。
        label = next((g.label for g in group if g.type == SEG_USER), None) or group[0].label
        chunks.append(
            Chunk(
                id=f"{band}:turn{turn}",
                type=band,
                tokens=sum(g.tokens for g in group),
                turn=turn,
                label=f"第{turn}轮 · {label}" if turn else label,
                sourceRefs=[g.ref for g in group],
                members=len(group),
                turnSpan=[turn, turn],
                raw=_cap_raw(_join_raw(group), sum(g.tokens for g in group)),
            )
        )
    return chunks


def _strat_group_by_toolset(band: str, segs: List[Segment]) -> List[Chunk]:
    """tool_schema 带：按 toolset 合并相似工具（结构化版"合并小块"）。"""
    by_set: Dict[str, List[Segment]] = {}
    for s in segs:
        by_set.setdefault(s.group or "tools", []).append(s)
    chunks: List[Chunk] = []
    for toolset in sorted(by_set):
        group = by_set[toolset]
        chunks.append(
            Chunk(
                id=f"{band}:{toolset}",
                type=band,
                tokens=sum(g.tokens for g in group),
                turn=0,
                label=f"{toolset} ({len(group)})" if len(group) > 1 else group[0].label,
                sourceRefs=[g.ref for g in group],
                group=toolset,
                members=len(group),
                raw=_cap_raw(_join_raw(group), sum(g.tokens for g in group)),
            )
        )
    return chunks


# band → 策略。换语义策略时只替换这里的值，上下游不变。
_STRATEGIES: Dict[str, Callable[[str, List[Segment]], List[Chunk]]] = {
    "system": _strat_identity,
    "tool_schema": _strat_group_by_toolset,
    "history": _strat_group_by_turn,
    "file": _strat_identity,
    "tool_result": _strat_identity,
}


# ── ③ 流水线入口 ─────────────────────────────────────────────────────

def build_snapshot_chunks(
    agent: Any,
    session: Optional[Dict[str, Any]] = None,
    scale_to: Optional[int] = None,
) -> Dict[str, Any]:
    """跑 segment → chunk 流水线，返回可 JSON 序列化的 context.snapshot 载荷。

    best-effort：任一来源失败只丢该来源，不抛出（viz 不该影响对话）。

    ``scale_to``：缩放目标 token 覆盖。默认用 ``comp.last_prompt_tokens``(真实占用);
    压缩闸门"压缩后立即补发"场景下真实计数还没回来(=-1/0),传入估算值缩放。
    """
    session = session or {}
    history = list(session.get("history") or [])

    segments: List[Segment] = []
    segments += _segment_system(agent)
    segments += _segment_tool_schemas(agent)
    segments += _segment_history(history)

    # 整体缩放到真实总占用（或调用方给的覆盖值）。
    comp = getattr(agent, "context_compressor", None)
    target = (
        int(scale_to)
        if scale_to is not None
        else (int(getattr(comp, "last_prompt_tokens", 0) or 0) if comp else 0)
    )
    _scale(segments, target)

    # 压缩阈值（绝对 token，与 budget 同尺度，不参与上面的缩放）——
    # 前端「实际占用」模式据此画 compact 线。
    compact_at = int(getattr(comp, "threshold_tokens", 0) or 0) if comp else 0

    # 按带分组 → 应用各带策略。
    by_band: Dict[str, List[Segment]] = {}
    for s in segments:
        band = _SEG_TO_BAND.get(s.type, "history")
        by_band.setdefault(band, []).append(s)

    chunks: List[Chunk] = []
    for band in BAND_ORDER:
        segs = by_band.get(band)
        if not segs:
            continue
        strat = _STRATEGIES.get(band, _strat_identity)
        band_chunks = strat(band, segs)
        band_chunks.sort(key=lambda c: c.tokens, reverse=True)
        chunks.extend(band_chunks)

    return {
        "chunks": [_chunk_dict(c) for c in chunks],
        "strategy_versions": dict(_STRATEGY_VERSIONS),
        "generated_at": time.time(),
        "scaled_to": target,
        "compact_at": compact_at,
    }


def message_indices_for_chunks(
    agent: Any,
    session: Optional[Dict[str, Any]],
    chunk_ids: Any,
) -> set:
    """把一组 chunk id 解析成真实 history 的 message 下标集合（apply/fold 共用）。

    与 provenance 同源:重新跑一遍分块拿确定性 id → sourceRefs，只收带
    ``messageIndex`` 的引用。system / tool_schema 的 sourceRefs 只有 ``part``、
    无消息背书，**自动被忽略**——drop/fold 永不触碰这两类。
    """
    wanted = {str(x) for x in (chunk_ids or [])}
    if not wanted:
        return set()
    payload = build_snapshot_chunks(agent, session)
    indices: set = set()
    for c in payload.get("chunks", []):
        if c.get("id") not in wanted:
            continue
        for ref in c.get("sourceRefs") or []:
            mi = ref.get("messageIndex") if isinstance(ref, dict) else None
            if isinstance(mi, int):
                indices.add(mi)
    return indices


# 旧名保留:方向 A 阶段 3(drop)沿用。fold 复用同一解析,故泛化为上面的名字。
drop_indices_for_chunks = message_indices_for_chunks


def _chunk_dict(c: Chunk) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": c.id,
        "type": c.type,
        "tokens": c.tokens,
        "turn": c.turn,
        "label": c.label,
        "sourceRefs": c.sourceRefs,
        "members": c.members,
    }
    if c.group is not None:
        d["group"] = c.group
    if c.turnSpan is not None:
        d["turnSpan"] = c.turnSpan
    if c.fate is not None:
        d["fate"] = c.fate
    if c.folded:
        d["folded"] = True
    if _raw_enabled() and c.raw:
        d["raw"] = c.raw
    return d
