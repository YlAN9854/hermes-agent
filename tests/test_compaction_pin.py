"""Core-side test for context-vis Tier 3 pin-aware compaction.

Exercises ContextCompressor.compress() directly with a mocked summary so no
LLM is needed: a pinned middle turn must survive verbatim while an unpinned
middle turn is summarized away.
"""
from agent.context_compressor import ContextCompressor


def _msg(turn_id, role, text):
    return {"role": role, "content": text, "_transcript_turn_id": turn_id}


def _build_messages(n_middle):
    msgs = [{"role": "system", "content": "system prompt"}]
    # Head (protected), then a long middle, then a tail. Distinct markers so we
    # can tell verbatim survival from summarization.
    for i in range(n_middle):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(_msg(f"t{i:03d}", role, f"MIDDLE_TURN_{i:03d} " + ("filler word " * 40)))
    return msgs


def _compressor():
    c = ContextCompressor(model="test-model", protect_first_n=1, protect_last_n=3)
    c._generate_summary = lambda *a, **k: "SUMMARY_OF_MIDDLE"
    return c


def test_pinned_middle_turn_survives_verbatim_while_others_summarized():
    msgs = _build_messages(20)
    pinned_id = "t009"
    pinned_text = dict(msgs[10])["content"]  # msgs[0] is system, so t009 is msgs[10]
    assert msgs[10]["_transcript_turn_id"] == pinned_id

    compressor = _compressor()
    compressor._keep_turn_ids = {pinned_id}
    out = compressor.compress(msgs)

    joined = "\n".join(m.get("content", "") for m in out if isinstance(m.get("content"), str))
    # The pinned turn's exact text survives; the summary marker is present; a
    # different middle turn (t007) was summarized away, not kept verbatim.
    assert "MIDDLE_TURN_009" in joined
    assert "SUMMARY_OF_MIDDLE" in joined
    assert "MIDDLE_TURN_007" not in joined
    # The pin flag is consumed one-shot.
    assert compressor._keep_turn_ids is None


def test_load_pinned_turn_ids_reads_the_adapter_pin_file(tmp_path, monkeypatch):
    import json
    import hermes_constants
    from agent.conversation_compression import _load_pinned_turn_ids

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    pins = tmp_path / "context-vis" / "pins"
    pins.mkdir(parents=True)
    (pins / "sess.json").write_text(json.dumps({"v": 1, "turn_ids": ["hermes-msg:3", "hermes-msg:7"]}))

    assert _load_pinned_turn_ids("sess") == {"hermes-msg:3", "hermes-msg:7"}
    # Missing file, unknown session, and bad version all degrade to no pins.
    assert _load_pinned_turn_ids("other") == set()
    assert _load_pinned_turn_ids(None) == set()
    (pins / "v2.json").write_text(json.dumps({"v": 99, "turn_ids": ["x"]}))
    assert _load_pinned_turn_ids("v2") == set()


def test_no_pins_leaves_behaviour_unchanged():
    msgs = _build_messages(20)
    compressor = _compressor()
    out = compressor.compress(msgs)  # no _keep_turn_ids set

    joined = "\n".join(m.get("content", "") for m in out if isinstance(m.get("content"), str))
    assert "SUMMARY_OF_MIDDLE" in joined
    # No middle turn survives verbatim when nothing is pinned.
    assert "MIDDLE_TURN_009" not in joined
