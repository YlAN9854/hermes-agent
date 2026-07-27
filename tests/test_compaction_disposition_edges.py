import pytest

from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    SUMMARY_PREFIX,
    ContextCompressor,
    _MERGED_PRIOR_CONTEXT_HEADER,
    _MERGED_SUMMARY_DELIMITER,
    _SUMMARY_END_MARKER,
)


def _message(turn_id, role, content):
    return {
        "role": role,
        "content": content,
        "_transcript_turn_id": turn_id,
    }


def _messages():
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(20):
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


@pytest.mark.parametrize("merged", [False, True])
def test_dispositions_apply_after_standalone_or_merged_handoff_window(
    merged,
) -> None:
    # Given: a persisted handoff before a droppable raw middle turn.
    messages = _messages()
    if merged:
        messages[1]["content"] = (
            f"{_MERGED_PRIOR_CONTEXT_HEADER}\n"
            "boundary tail\n\n"
            f"{_MERGED_SUMMARY_DELIMITER}\n\n"
            f"{SUMMARY_PREFIX}\nopaque-prior-state\n\n"
            f"{_SUMMARY_END_MARKER}"
        )
        messages[1][COMPRESSED_SUMMARY_METADATA_KEY] = True
    else:
        messages.insert(
            1,
            {
                "role": "user",
                "content": f"{SUMMARY_PREFIX}\nopaque-prior-state",
                COMPRESSED_SUMMARY_METADATA_KEY: True,
            },
        )
    summarized_ids = []
    compressor = _compressor()

    def summarize(turns, **_options):
        summarized_ids.extend(
            turn["_transcript_turn_id"]
            for turn in turns
            if "_transcript_turn_id" in turn
        )
        return "UPDATED_SUMMARY"

    compressor._generate_summary = summarize
    compressor._drop_turn_ids = {"t008"}

    # When: re-compaction first resolves its final post-handoff window.
    output = compressor.compress(messages)

    # Then: the drop is still removed from final input and output.
    assert "t008" not in summarized_ids
    assert "MIDDLE_TURN_008" not in _joined(output)


def test_drop_does_not_redact_an_existing_synthetic_summary() -> None:
    # Given: an old B turn is already represented only in a persisted summary.
    messages = _messages()
    messages.insert(
        1,
        {
            "role": "user",
            "content": f"{SUMMARY_PREFIX}\nopaque-prior-state",
            COMPRESSED_SUMMARY_METADATA_KEY: True,
        },
    )
    compressor = _compressor()
    compressor._drop_turn_ids = {"old-turn-no-longer-live"}

    def summarize(_turns, **_options):
        assert compressor._previous_summary == "opaque-prior-state"
        return "UPDATED_SUMMARY"

    compressor._generate_summary = summarize

    # When: a later compaction sees the obsolete drop request.
    compressor.compress(messages)

    # Then: prior synthetic state remains iterative-summary input.
    assert compressor._previous_summary == "opaque-prior-state"


def test_drop_then_sanitize_removes_orphaned_tool_call() -> None:
    # Given: a kept assistant call whose paired tool result is dropped.
    messages = _messages()
    messages[9] = {
        **_message("t008", "assistant", "calling tool"),
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }],
    }
    messages[10] = {
        **_message("t009", "tool", "tool result"),
        "tool_call_id": "call-1",
        "tool_name": "lookup",
    }
    compressor = _compressor()
    compressor._generate_summary = lambda *_args, **_kwargs: "SUMMARY"
    compressor._keep_turn_ids = {"t008"}
    compressor._drop_turn_ids = {"t009"}

    # When: compaction applies dispositions and its existing sanitizer.
    output = compressor.compress(messages)

    # Then: the assistant survives without an API-invalid orphaned call.
    kept = next(
        message for message in output
        if message.get("_transcript_turn_id") == "t008"
    )
    assert "tool_calls" not in kept
    assert not any(
        message.get("tool_call_id") == "call-1"
        for message in output
    )


def test_protected_tail_drop_waits_until_a_later_compaction() -> None:
    # Given: a scheduled drop targets the currently protected newest turn.
    messages = _messages()
    first = _compressor()
    first._generate_summary = lambda *_args, **_kwargs: "FIRST_SUMMARY"
    first._drop_turn_ids = {"t019"}

    # When: the turn is protected now, then becomes middle after new activity.
    after_first = first.compress(messages)
    extended = [
        *after_first,
        *[
            _message(
                f"new-{index:03d}",
                "user" if index % 2 == 0 else "assistant",
                f"NEW_TURN_{index:03d} " + ("new filler " * 40),
            )
            for index in range(20)
        ],
    ]
    second = _compressor()
    second._generate_summary = lambda *_args, **_kwargs: "SECOND_SUMMARY"
    second._drop_turn_ids = {"t019"}
    after_second = second.compress(extended)

    # Then: one-shot state clears each time and persistent reload applies later.
    assert "MIDDLE_TURN_019" in _joined(after_first)
    assert first._drop_turn_ids is None
    assert "MIDDLE_TURN_019" not in _joined(after_second)
    assert second._drop_turn_ids is None


def test_pin_before_merged_handoff_survives_recompaction() -> None:
    # Given: the first boundary reinserts several pins before a merged tail summary.
    keep_ids = {"t006", "t008", "t010"}
    first = _compressor()
    first._keep_turn_ids = keep_ids
    first._generate_summary = (
        lambda *_args, **_kwargs: f"{SUMMARY_PREFIX}\nFIRST_SUMMARY"
    )
    after_first = first.compress(_messages())
    assert _MERGED_SUMMARY_DELIMITER in _joined(after_first)

    extended = [
        *after_first,
        *[
            _message(
                f"later-{index:03d}",
                "user" if index % 2 == 0 else "assistant",
                f"LATER_TURN_{index:03d} " + ("later filler " * 40),
            )
            for index in range(20)
        ],
    ]
    second = _compressor()
    second._keep_turn_ids = keep_ids
    second._generate_summary = (
        lambda *_args, **_kwargs: f"{SUMMARY_PREFIX}\nSECOND_SUMMARY"
    )

    # When: the persisted pin is reloaded for the next eligible boundary.
    after_second = second.compress(extended)

    # Then: each pin remains exactly once and in source order beside one handoff.
    output_ids = [
        message.get("_transcript_turn_id")
        for message in after_second
        if message.get("_transcript_turn_id") in keep_ids
    ]
    assert output_ids == ["t006", "t008", "t010"]
    assert sum(
        bool(message.get(COMPRESSED_SUMMARY_METADATA_KEY))
        for message in after_second
    ) == 1
    joined = _joined(after_second)
    for turn_id in sorted(keep_ids):
        assert joined.count(f"MIDDLE_TURN_{turn_id[1:]}") == 1
    assert "MIDDLE_TURN_007" not in joined
