import json

from agent import conversation_compression
from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    ContextCompressor,
)


def _message(turn_id, role, content):
    return {
        "role": role,
        "content": content,
        "_transcript_turn_id": turn_id,
    }


def _messages(count=20):
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            _message(
                f"t{index:03d}",
                role,
                f"MIDDLE_TURN_{index:03d} " + ("filler word " * 40),
            )
        )
    return messages


def _compressor():
    return ContextCompressor(
        model="test-model",
        protect_first_n=1,
        protect_last_n=3,
    )


def _joined(messages):
    return "\n".join(
        message["content"]
        for message in messages
        if isinstance(message.get("content"), str)
    )


def test_separate_drop_loader_preserves_legacy_v1_pin_loading(
    tmp_path,
    monkeypatch,
) -> None:
    # Given: the unchanged v1 pin record and a separate versioned drop record.
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    pins = tmp_path / "context-vis" / "pins"
    drops = tmp_path / "context-vis" / "drops"
    pins.mkdir(parents=True)
    drops.mkdir(parents=True)
    (pins / "session.json").write_text(
        json.dumps({"v": 1, "turn_ids": ["keep"]}),
        encoding="utf-8",
    )
    (drops / "session.json").write_text(
        json.dumps({"v": 1, "drop_turn_ids": ["drop"]}),
        encoding="utf-8",
    )

    # When: old and new loaders read their independent stores.
    keep_ids = conversation_compression._load_pinned_turn_ids("session")
    drop_ids = conversation_compression._load_drop_turn_ids("session")

    # Then: old pin semantics remain intact and drops do not replace them.
    assert keep_ids == {"keep"}
    assert drop_ids == {"drop"}


def test_drop_middle_turn_is_absent_from_summary_input_and_output() -> None:
    # Given: one requested drop that is genuinely in the compressible middle.
    messages = _messages()
    summarized_ids = []
    compressor = _compressor()

    def summarize(turns, **_options):
        summarized_ids.extend(
            turn["_transcript_turn_id"]
            for turn in turns
            if "_transcript_turn_id" in turn
        )
        return "SUMMARY_OF_REMAINING"

    compressor._generate_summary = summarize
    compressor._drop_turn_ids = {"t008"}

    # When: the real compressor applies dispositions.
    output = compressor.compress(messages)

    # Then: dropped raw content reaches neither summarizer nor active output.
    assert "t008" not in summarized_ids
    assert "t007" in summarized_ids
    assert "MIDDLE_TURN_008" not in _joined(output)
    assert compressor._drop_turn_ids is None


def test_keep_wins_when_the_same_middle_turn_is_also_dropped() -> None:
    # Given: the same eligible turn appears in both wholesale sets.
    messages = _messages()
    summarized_ids = []
    compressor = _compressor()

    def summarize(turns, **_options):
        summarized_ids.extend(
            turn["_transcript_turn_id"]
            for turn in turns
            if "_transcript_turn_id" in turn
        )
        return "SUMMARY_OF_REMAINING"

    compressor._generate_summary = summarize
    compressor._keep_turn_ids = {"t008"}
    compressor._drop_turn_ids = {"t008"}

    # When: the compressor resolves the conflict.
    output = compressor.compress(messages)

    # Then: the turn survives verbatim and is not summarized.
    assert "MIDDLE_TURN_008" in _joined(output)
    assert "t008" not in summarized_ids
    assert compressor._keep_turn_ids is None
    assert compressor._drop_turn_ids is None


def test_all_drop_window_calls_no_summarizer_and_keeps_protected_edges() -> None:
    # Given: every B turn is requested for drop, including protected head/tail.
    messages = _messages()
    compressor = _compressor()
    compressor._drop_turn_ids = {
        message["_transcript_turn_id"]
        for message in messages
        if "_transcript_turn_id" in message
    }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("all-drop must not call the summarizer")

    compressor._generate_summary = fail_if_called

    # When: compaction reaches only the eligible middle subset.
    output = compressor.compress(messages)

    # Then: eligible turns vanish without a synthetic summary; edges stay live.
    joined = _joined(output)
    assert "MIDDLE_TURN_008" not in joined
    assert "MIDDLE_TURN_000" in joined
    assert "MIDDLE_TURN_019" in joined
    assert not any(
        message.get(COMPRESSED_SUMMARY_METADATA_KEY)
        for message in output
    )
