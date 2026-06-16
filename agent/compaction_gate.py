"""ContextVis 压缩闸门（方向 A 的对偶）—— 把 auto-compress 从静默改成用户确认。

Hermes 默认到阈值就**静默**压缩;闸门在触发处拦一道,把"系统打算怎么压"用 treemap 的
fate 叠加画给用户看 + 占用前后投影,确认(继续)或推迟后才压。证据链与设计见
context-vis/compaction-gate.md。

复用 Hermes 审批(human-in-the-loop)基建 [tools/approval.py] 的阻塞-等待-超时-心跳
原语,**不造新控制流**。只在交互(dashboard 附着、已注册 notify)会话生效;无人值守
(CLI/cron、无 notify)直接返回 None → 调用方照常自动压。门控 env HERMES_CONTEXTVIS_GATE
(默认关,opt-in)。第一阶段纯预览 + 确认,不编辑。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _gate_enabled() -> bool:
    return os.environ.get("HERMES_CONTEXTVIS_GATE", "0").strip().lower() in _TRUTHY


def _regime_gating_enabled() -> bool:
    """两级门控开关(默认开)。设 0 → 回退老的"逢 has_middle 必弹"一级门控。"""
    return os.environ.get("HERMES_CONTEXTVIS_REGIME", "1").strip().lower() in _TRUTHY


def _should_gate_for_regime(
    agent: Any, messages: List[Dict[str, Any]], plan: Dict[str, Any]
) -> tuple[bool, str, str]:
    """两级门控判定:这次压缩到底要不要打断用户?

    A 级(regime):有没有值得护的主线?没有 → 森林,静默自动压。
    B 级(collision):这次压缩的折叠区 [head_end, tail_start) 是否触及主线消息?
                     不触及(只压死重)→ 即使在任务态也静默压。
    A ∧ B 才打断。返回 (是否打断, 原因串, 主线 focus)。任何异常 → 保守放行打断(退回一级行为)。

    `focus` = 检测出的当前主线焦点(R 后续①:喂给焦点压缩的 focus_topic);仅 task 态有意义,
    其余为空串。误判代价不对称:漏弹只是退化成今天的静默自动压(无回归),故拿不准时倾向不扰。
    """
    if not _regime_gating_enabled():
        return True, "regime-gating-off", ""
    try:
        from agent.contextvis.regime import get_regime_detector

        a = get_regime_detector(agent).assess(messages, agent)
    except Exception as e:  # noqa: BLE001 — 检测失败绝不能挡住压缩流程
        logger.debug("regime detect failed: %s", e)
        return True, "regime-detect-error", ""
    if a.regime != "task":
        return False, f"forest ({a.reason})", ""
    head_end, tail_start = plan.get("head_end", 0), plan.get("tail_start", 0)
    collision = any(head_end <= i < tail_start for i in a.on_thread_indices)
    focus = (getattr(a, "focus", "") or "").strip()
    if not collision:
        return False, f"task-no-collision ({a.reason})", focus
    return True, f"task-collision ({a.reason})", focus


def _resolve_session_key() -> str:
    try:
        from gateway.session_context import get_session_env

        return get_session_env("HERMES_SESSION_KEY", "") or ""
    except Exception:
        return os.getenv("HERMES_SESSION_KEY", "") or ""


def _resolve_notify_cb():
    """解析当前会话的 gateway notify 回调(交互会话才有);非交互返回 None。

    与工具审批同一套:无 notify = 无 dashboard 附着 = 无人值守 → 调用方静默跳过。
    """
    try:
        from tools.approval import (
            _gateway_notify_cbs,
            _is_gateway_approval_context,
            _lock,
        )
    except Exception:
        return None
    if not _is_gateway_approval_context():
        return None
    session_key = _resolve_session_key()
    if not session_key:
        return None
    with _lock:
        return _gateway_notify_cbs.get(session_key)


def emit_post_compaction_snapshot(agent: Any, messages: List[Dict[str, Any]]) -> None:
    """压缩刚跑完(turn 中途)立即补发一份新鲜 context.snapshot。

    auto-compress 发生在 turn 中途,而常规 session.info / context.snapshot 要等整轮
    结束才发——导致点「继续压缩」后 treemap 卡在压缩前。这里走 notify 桥(发闸门请求
    那条路)主动推一份压缩后的快照,让 treemap 立刻回落。真实 prompt token 此刻还没回来
    (compress 把 last_prompt_tokens 置 -1),用估算值缩放。非交互会话 → notify 为空 → 静默跳过。
    """
    notify_cb = _resolve_notify_cb()
    if notify_cb is None:
        return
    try:
        from agent.contextvis import build_snapshot_chunks
        from agent.model_metadata import estimate_request_tokens_rough

        comp = getattr(agent, "context_compressor", None)
        sys_prompt = getattr(agent, "_cached_system_prompt", "") or ""
        tools = getattr(agent, "tools", None) or None
        est = estimate_request_tokens_rough(
            messages, system_prompt=sys_prompt, tools=tools
        )
        ctx = int(getattr(comp, "context_length", 0) or 0) if comp else 0
        payload = build_snapshot_chunks(agent, {"history": messages}, scale_to=est)
        payload["_event"] = "context.snapshot"
        # 携带占用,让 treemap header / 占用条也即时回落(adapter 见 used/percent 即应用)。
        payload["used"] = est
        payload["percent"] = round(est / ctx * 100) if ctx > 0 else 0
        payload["budget"] = ctx
        # 真实累计压缩次数,让「压缩 ×N」mid-turn 即时累加(一轮多次压缩也不漏)。
        payload["compressions"] = int(getattr(comp, "compression_count", 0) or 0)
        notify_cb(payload)
    except Exception as e:  # noqa: BLE001 — 补发失败绝不能影响对话
        logger.debug("post-compaction snapshot emit skipped: %s", e)


def _system_fate_for_chunks(
    chunks: List[Dict[str, Any]], head_end: int, tail_start: int
) -> Dict[str, str]:
    """每个 chunk 按其 sourceRefs.messageIndex 落点派系统命运。

    落在折叠区 [head_end, tail_start) → ``fold``;否则 ``keep``。无 messageIndex 的
    system/tool_schema 不标(系统压缩本就不动它们,treemap 上保持原样)。
    """
    fate: Dict[str, str] = {}
    for c in chunks:
        idxs = [
            r["messageIndex"]
            for r in (c.get("sourceRefs") or [])
            if isinstance(r, dict) and isinstance(r.get("messageIndex"), int)
        ]
        if not idxs:
            continue
        fate[c["id"]] = "fold" if any(head_end <= i < tail_start for i in idxs) else "keep"
    return fate


def request_compaction_decision(
    agent: Any, messages: List[Dict[str, Any]]
) -> Optional[Dict[str, str]]:
    """auto-compress 触发时拦一道:把系统计划发给前端,阻塞 agent 线程等用户决定。

    返回:
      ``{"choice": "continue", "focus": <主线焦点>}`` —— 照常压缩(用户确认 / 超时 / 出错);
          `focus` 喂焦点压缩的 `focus_topic`(R 后续①),空串表示位置式回退。
      ``{"choice": "defer", "focus": ...}``           —— 本轮不压(用户推迟)
      ``None``                                         —— 未开闸 / 非交互 / 无中段可折叠 → 调用方走原自动压缩
    """
    if not _gate_enabled():
        return None
    comp = getattr(agent, "context_compressor", None)
    if comp is None:
        return None
    try:
        plan = comp.plan_compaction(messages)
    except Exception as e:  # noqa: BLE001 — 闸门绝不能挡住压缩
        logger.debug("compaction gate: plan failed: %s", e)
        return None
    if not plan.get("has_middle"):
        return None  # 没有可折叠的中段 → 闸门无意义,照常走

    # 交互上下文 + 已注册 notify 才挂闸;否则无人值守 → None → 调用方自动压。
    try:
        from tools.approval import (
            _await_gateway_decision,
            _gateway_notify_cbs,
            _is_gateway_approval_context,
            _lock,
        )
    except Exception:
        return None
    if not _is_gateway_approval_context():
        return None
    session_key = _resolve_session_key()
    if not session_key:
        return None
    with _lock:
        notify_cb = _gateway_notify_cbs.get(session_key)
    if notify_cb is None:
        return None

    # 两级门控(R 第一刀):森林 → 闸门闭嘴;任务但这次只压死重 → 也别扰。静默自动压。
    should_gate, gate_reason, focus = _should_gate_for_regime(agent, messages, plan)
    if not should_gate:
        logger.debug("compaction gate suppressed by regime — %s", gate_reason)
        return None

    # 系统计划 + 占用投影(用 scaled chunk tokens,与 treemap / 真实占用同尺度)。
    try:
        from agent.contextvis import build_snapshot_chunks

        chunks = build_snapshot_chunks(agent, {"history": messages}).get("chunks", [])
    except Exception as e:  # noqa: BLE001
        logger.debug("compaction gate: chunks failed: %s", e)
        chunks = []
    head_end, tail_start = plan["head_end"], plan["tail_start"]
    system_fate = _system_fate_for_chunks(chunks, head_end, tail_start)

    fold_tokens = sum(
        c["tokens"] for c in chunks if system_fate.get(c["id"]) == "fold"
    )
    ratio = float(plan.get("summary_target_ratio", 0.2))
    freed = int(fold_tokens * (1 - ratio))
    before = int(
        getattr(comp, "last_prompt_tokens", 0) or sum(c["tokens"] for c in chunks)
    )
    ctx = int(plan.get("context_length", 0) or getattr(comp, "context_length", 0) or 0)
    est_after = max(0, before - freed)
    pct = lambda t: (round(t / ctx * 100) if ctx > 0 else 0)  # noqa: E731
    fold_turns = sum(
        1
        for c in chunks
        if system_fate.get(c["id"]) == "fold" and c.get("type") == "history"
    )

    approval_data = {
        "_event": "context.compaction_request",
        "kind": "compaction",
        "system_fate": system_fate,
        "current_tokens": before,
        "current_percent": pct(before),
        "threshold": int(getattr(comp, "threshold_tokens", 0) or 0),
        "budget": ctx,
        "est_after_tokens": est_after,
        "est_after_percent": pct(est_after),
        "fold_turns": fold_turns,
        # 两级门控放行原因(任务态 + 本次压缩触及主线),供闸门条标"检测到主线任务"。
        "regime": "task",
        "collision_reason": gate_reason,
        # R 后续①:检测出的主线焦点。前端只读显示"将按此焦点压";确认(continue)后喂 focus_topic。
        "focus": focus,
        # 闸门 turn 中途触发,带上这一刻的新鲜 chunks + 占用,让前端 treemap 立刻
        # 刷成"即将被压的真实状态"——否则 treemap/占用还停在轮初的旧值,与 banner
        # 和 system_fate(按新消息算的 chunk id)对不上。
        "chunks": chunks,
    }

    try:
        decision = _await_gateway_decision(
            session_key, notify_cb, approval_data, surface="gateway"
        )
    except Exception as e:  # noqa: BLE001 — 出错别挡着,照常压
        logger.warning("compaction gate await failed: %s", e)
        return {"choice": "continue", "focus": focus}
    choice = "defer" if decision.get("choice") == "defer" else "continue"
    return {"choice": choice, "focus": focus}
