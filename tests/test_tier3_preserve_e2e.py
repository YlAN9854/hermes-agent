"""Tier 3 preserve — pure-backend end-to-end.

Exercises the whole preserve chain through its real public surfaces, with only
the summary LLM stubbed for determinism (the summary's content is irrelevant
to preservation):

  seed a real session in a temp HERMES_HOME
    -> adapter.request_preserve(spans)                 [writes the real pin file]
    -> conversation_compression._load_pinned_turn_ids  [the loader the agent uses]
    -> ContextCompressor.compress(messages)            [honours the pin set]
    -> SessionDB.archive_and_compact(compressed)       [persists the new A]
    -> adapter.get_active_context()                    [observable truth]

Assertions are mechanical (a pinned constraint turn is present verbatim in A;
an unpinned middle turn is gone), so no agent judgement is needed. A separate
live-agent driver (evals/context_vis/preserve_e2e) covers the real-threshold
path and is judged by a sub-agent.
"""
import json

import pytest

from agent.context_compressor import ContextCompressor
from agent.conversation_compression import _load_pinned_turn_ids
from context_vis.domain import SpanRef
from context_vis.hermes_adapter import HermesContextAdapter
from hermes_state import SessionDB

PINNED = "硬性约束：绝对不能修改 schema.sql，账单团队的夜间对账任务依赖那些列"
UNPINNED = "另一条约束：报表时区固定用 UTC+8"


def _seed(db):
    """A head, a long middle holding the two constraints, and a recent tail."""
    db.create_session("s", "cli")
    db.append_message("s", "user", "开始审计 logpipe 服务。")           # 1 head
    db.append_message("s", "assistant", "好的，我先看结构。")           # 2 head
    db.append_message("s", "user", PINNED)                              # 3 middle (pinned)
    db.append_message("s", "assistant", "记下了 schema 约束。")         # 4 middle
    db.append_message("s", "user", UNPINNED)                            # 5 middle (unpinned)
    for i in range(6, 16):                                             # 6-15 middle filler
        role = "user" if i % 2 == 0 else "assistant"
        db.append_message("s", role, f"审计进展第 {i} 步：" + "分析日志格式与统计口径。" * 6)
    db.append_message("s", "user", "最后总结一下。")                    # 16 tail
    db.append_message("s", "assistant", "总结完成。")                   # 17 tail


def test_tier3_preserve_pin_survives_backend_compaction(tmp_path, monkeypatch):
    import hermes_constants
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    db = SessionDB(tmp_path / "state.db")
    _seed(db)
    adapter = HermesContextAdapter(db, "s", tmp_path)
    transcript = adapter.get_full_transcript()
    pinned = next(t for t in transcript if PINNED in t.content)
    unpinned = next(t for t in transcript if UNPINNED in t.content)

    # 1. Pin the constraint through the real public API — writes the pin file.
    result = adapter.request_preserve([SpanRef(pinned.turn_id, 0, len(pinned.content))])
    assert result.accepted_turn_ids == [pinned.turn_id]
    assert json.loads((tmp_path / "context-vis" / "pins" / "s.json").read_text())["turn_ids"] == [pinned.turn_id]

    # 2. The in-memory history the agent would compress (system + the B turns,
    #    each carrying its transcript id exactly as the live loader stamps them).
    messages = [{"role": "system", "content": "system prompt"}] + [
        {"role": t.role, "content": t.content, "_transcript_turn_id": t.turn_id} for t in transcript
    ]

    # 3. The real pin-honouring compaction — the two lines compress_context runs.
    compressor = ContextCompressor(model="test-model", protect_first_n=1, protect_last_n=3)
    compressor._generate_summary = lambda *a, **k: "SUMMARY_OF_MIDDLE"
    compressor._keep_turn_ids = _load_pinned_turn_ids("s")
    assert compressor._keep_turn_ids == {pinned.turn_id}
    compressed = compressor.compress(messages)

    # The pinned constraint is at risk (a genuine middle turn) yet survives
    # verbatim; the unpinned sibling is summarized away.
    joined = "\n".join(m["content"] for m in compressed if isinstance(m.get("content"), str))
    assert PINNED in joined
    assert UNPINNED not in joined
    assert "SUMMARY_OF_MIDDLE" in joined

    # 4. Persist the new A and read it back through the observable surface.
    db.archive_and_compact("s", compressed)
    active = HermesContextAdapter(db, "s", tmp_path).get_active_context()
    pinned_entries = [e for e in active.entries if e.origin_turn_id == pinned.turn_id]
    assert len(pinned_entries) == 1
    assert pinned_entries[0].content == pinned.content  # byte-for-byte in A
    assert not any(UNPINNED in e.content for e in active.entries if not e.synthetic)

    # 5. B is immutable — the dropped constraint is still fully retrievable.
    b_after = HermesContextAdapter(db, "s", tmp_path).get_full_transcript()
    assert any(UNPINNED in t.content for t in b_after)
    assert any(t.turn_id == pinned.turn_id and t.content == pinned.content for t in b_after)
    db.close()


def test_tier3_no_pin_drops_the_same_constraint(tmp_path, monkeypatch):
    """Control: without a pin, the same middle constraint is summarized away —
    so the survival above is caused by the pin, not by its position."""
    import hermes_constants
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    db = SessionDB(tmp_path / "state.db")
    _seed(db)
    transcript = HermesContextAdapter(db, "s", tmp_path).get_full_transcript()
    messages = [{"role": "system", "content": "system prompt"}] + [
        {"role": t.role, "content": t.content, "_transcript_turn_id": t.turn_id} for t in transcript
    ]

    compressor = ContextCompressor(model="test-model", protect_first_n=1, protect_last_n=3)
    compressor._generate_summary = lambda *a, **k: "SUMMARY_OF_MIDDLE"
    # No pin file written, no _keep_turn_ids set.
    compressed = compressor.compress(messages)

    joined = "\n".join(m["content"] for m in compressed if isinstance(m.get("content"), str))
    assert PINNED not in joined  # dropped when not pinned
    assert "SUMMARY_OF_MIDDLE" in joined
    db.close()
