"""Tier 3 preserve — live real-threshold end-to-end (on-demand).

Drives one continuous Hermes agent to a real automatic compaction, having
pinned a substantive early-middle USER turn partway through (via the
context-vis adapter, which writes the pin file the compressor reads), then
dumps A/B + pin info so an INDEPENDENT sub-agent can judge whether the pinned
turn survived verbatim while its unpinned neighbours were summarized away.

This complements tests/test_tier3_preserve_e2e.py: that test is the fast,
deterministic, mechanical proof of the pin path; this driver is the slow,
real-threshold confirmation through the full live agent + compress_context
orchestration. It is NOT a pytest test (needs a real LLM, ~10 min, and its
verdict is a sub-agent judgement) — run it on demand. See README.md.
"""
import contextlib
import json
import os
import sys
import time
from pathlib import Path

# Make the repo importable when run from anywhere (repo root is three levels up).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

HOME = Path(os.environ["HERMES_HOME"])
PROJECT = Path(os.environ["E2E_PROJECT"])
os.chdir(PROJECT)

PINNED_MARKER = "PINNED_RULE_备份保留期必须正好是 90 天一天都不能少"
UNPINNED_MARKER = "UNPINNED_RULE_报表时区固定用 UTC+8 绝不允许改动"

# Markers are stated as short user-only turns right after the intro, so they
# land EARLY (in the compression window). The bulky file-reads come later and
# become the protected recent tail — so at compaction the marker turns are the
# ones at risk, and pinning one is what decides its fate.
TURNS = [
    "我们要审计日志处理服务 logpipe。先看 README.md，一句话说它做什么。",
    f"先记住一条硬性要求：{PINNED_MARKER}。记住就好，先不用做别的。",
    f"再记住第二条硬性要求：{UNPINNED_MARKER}。同样记住就好。",
    "现在开始正式审计。读 logpipe/ingest.py，说明批处理逻辑，有没有问题。",
    "读 logpipe/parser.py，看它怎么区分日志格式，有无安全隐患。",
    "读 logpipe/store.py，说明写入逻辑。",
    "读 logpipe/report.py，说明聚合逻辑。",
    "看 data/app-2026-07.log 前 150 行，确认格式与 parser.py 的正则是否对得上。",
    "用命令行统计每个 source 出现次数与 5xx 比例。",
    "把你发现的问题按严重程度列出来。",
    "针对第一个问题说明修复思路，先别改代码。",
    "把这个修复实施到代码里，然后跑一下确认没有语法错误。",
]

PIN_AFTER_TURN = 3  # markers are in turns 2-3; pin before the file-reads trigger compaction


def _adapter(session_id):
    from hermes_state import SessionDB
    from context_vis.hermes_adapter import HermesContextAdapter
    return HermesContextAdapter(SessionDB(HOME / "state.db"), session_id, HOME), None


def _find_turn_id(session_id, marker):
    from hermes_state import SessionDB
    from context_vis.hermes_adapter import HermesContextAdapter
    db = SessionDB(HOME / "state.db")
    try:
        for t in HermesContextAdapter(db, session_id, HOME).get_full_transcript():
            if marker in t.content:
                return t.turn_id
    finally:
        db.close()
    return None


def _snapshot(agent, history):
    chars = sum(len(str(m.get("content") or "")) for m in history if isinstance(m, dict))
    comp = getattr(agent, "context_compressor", None)
    return {
        "history_msgs": len(history),
        "approx_tokens": chars // 4,
        "compression_count": getattr(comp, "compression_count", 0),
        "session_id": getattr(agent, "session_id", None),
    }


def main() -> int:
    from hermes_cli.oneshot import run_oneshot
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from context_vis.hermes_adapter import HermesContextAdapter
    from context_vis.domain import SpanRef

    real_stdout = sys.stdout
    captured = {}
    original = AIAgent.run_conversation

    def capturing(self, *args, **kwargs):
        captured["agent"] = self
        result = original(self, *args, **kwargs)
        captured["result"] = result
        return result

    AIAgent.run_conversation = capturing
    try:
        run_oneshot(TURNS[0])
    finally:
        AIAgent.run_conversation = original

    agent = captured.get("agent")
    if agent is None:
        print("FAILED: no agent captured", file=sys.stderr)
        return 1
    history = list((captured.get("result") or {}).get("messages") or [])
    pinned_turn_id = None

    devnull = open(os.devnull, "w", encoding="utf-8")
    for index, prompt in enumerate(TURNS[1:], start=2):
        try:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                result = agent.run_conversation(prompt, conversation_history=history)
            history = list(result.get("messages") or history)
        except BaseException as exc:  # noqa: BLE001
            print(f"[turn {index}] ERROR {type(exc).__name__}: {exc}", file=real_stdout, flush=True)
            break
        snap = _snapshot(agent, history)
        print(f"[turn {index:2d}] {json.dumps(snap, ensure_ascii=False)}", file=real_stdout, flush=True)

        if index == PIN_AFTER_TURN and pinned_turn_id is None:
            sid = agent.session_id
            db = SessionDB(HOME / "state.db")
            try:
                adapter = HermesContextAdapter(db, sid, HOME)
                full = adapter.get_full_transcript()
                # Pin the earliest EARLY-MIDDLE USER turn with substantive text
                # (the intended use — a user constraint), past the protected
                # head so it sits in the summarize window.
                cand = [t for t in full[4:] if t.role == "user" and len(t.content.strip()) > 20]
                pinned = cand[0]
                pinned_turn_id = pinned.turn_id
                res = adapter.request_preserve([SpanRef(pinned_turn_id, 0, len(pinned.content))])
                print(f"[pin] session={sid} pinned={pinned_turn_id} role={pinned.role} "
                      f"len={len(pinned.content)} accepted={res.accepted_turn_ids} note={res.note}",
                      file=real_stdout, flush=True)
            finally:
                db.close()
    devnull.close()

    # Dump artifacts for the independent auditor.
    sid = agent.session_id
    db = SessionDB(HOME / "state.db")
    try:
        adapter = HermesContextAdapter(db, sid, HOME)
        transcript = adapter.get_full_transcript()
        active = adapter.get_active_context()
        events = adapter.get_compression_events()
    finally:
        db.close()

    active_ids = [e.origin_turn_id for e in active.entries if e.origin_turn_id] if active else []
    pin_file = HOME / "context-vis" / "pins" / f"{sid}.json"

    def _num(tid):
        try:
            return int(tid.split(":")[1])
        except Exception:
            return None

    # Discriminating check: is the pinned turn KEPT while its immediate
    # transcript neighbours were DROPPED by the same compaction?
    ev = events[0] if events else None
    pin_num = _num(pinned_turn_id)
    neighbours = [f"hermes-msg:{pin_num - 1}", f"hermes-msg:{pin_num + 1}"] if pin_num else []
    # Byte-for-byte: the pinned turn's B content vs its content in A.
    b_content = next((t.content for t in transcript if t.turn_id == pinned_turn_id), None)
    a_content = next((e.content for e in (active.entries if active else []) if e.origin_turn_id == pinned_turn_id), None)
    out = {
        "session_id": sid,
        "compression_count": getattr(agent.context_compressor, "compression_count", 0),
        "pinned_turn_id": pinned_turn_id,
        "pin_file": json.loads(pin_file.read_text()) if pin_file.exists() else None,
        "compression_events": len(events),
        "dropped_turn_ids": sorted(ev.dropped_turn_ids, key=lambda x: _num(x)) if ev else [],
        "b_turns": len(transcript),
        "a_entries": len(active.entries) if active else 0,
        "pinned_in_kept": (pinned_turn_id in ev.kept_turn_ids) if ev else None,
        "pinned_in_dropped": (pinned_turn_id in ev.dropped_turn_ids) if ev else None,
        "pinned_in_active": pinned_turn_id in active_ids,
        "neighbours_dropped": {n: (n in ev.dropped_turn_ids) for n in neighbours} if ev else {},
        "verbatim_B_equals_A": (b_content is not None and b_content == a_content),
        "pinned_content_preview": (b_content or "")[:80],
    }
    (HOME / "preserve_e2e_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (HOME / "preserve_e2e_active.json").write_text(
        json.dumps([e.__dict__ for e in active.entries] if active else [], ensure_ascii=False, indent=1),
        encoding="utf-8")
    (HOME / "preserve_e2e_transcript.json").write_text(
        json.dumps([t.__dict__ for t in transcript], ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nRESULT " + json.dumps(out, ensure_ascii=False), file=real_stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
