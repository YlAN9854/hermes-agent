from copy import deepcopy

import pytest

from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    SUMMARY_PREFIX,
    ContextCompressor,
    _MERGED_SUMMARY_DELIMITER,
)


def _message(turn_id: str, role: str, content: str) -> dict[str, object]:
    return {
        "role": role,
        "content": content,
        "_transcript_turn_id": turn_id,
    }


def _messages() -> list[dict[str, object]]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system prompt"}
    ]
    for index in range(20):
        messages.append(
            _message(
                f"t{index:03d}",
                "user" if index % 2 == 0 else "assistant",
                f"MIDDLE_TURN_{index:03d} " + ("filler word " * 40),
            )
        )
    return messages


def _compressor() -> ContextCompressor:
    return ContextCompressor(
        model="test-model",
        protect_first_n=1,
        protect_last_n=3,
    )


def _summary_carriers(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        message
        for message in messages
        if message.get(COMPRESSED_SUMMARY_METADATA_KEY)
    ]


@pytest.mark.parametrize(
    "raw_suffix",
    [
        "",
        f"\n\n{_MERGED_SUMMARY_DELIMITER}\n\nTHIS_LITERAL_IS_STILL_RAW",
    ],
    ids=["ordinary", "literal-delimiter"],
)
def test_reloaded_pin_on_merged_carrier_keeps_raw_once_with_one_summary(
    raw_suffix: str,
) -> None:
    # Given: one compaction merges its summary into a raw transcript carrier.
    source = _messages()
    source_by_id = {
        message["_transcript_turn_id"]: message
        for message in source
        if "_transcript_turn_id" in message
    }
    source_by_id["t017"]["content"] = (
        str(source_by_id["t017"]["content"]) + raw_suffix
    )
    first = _compressor()
    first._generate_summary = (
        lambda *_args, **_kwargs: f"{SUMMARY_PREFIX}\nFIRST_SUMMARY"
    )
    after_first = first.compress(source)
    first_carriers = _summary_carriers(after_first)
    assert len(first_carriers) == 1
    carrier_id = first_carriers[0]["_transcript_turn_id"]
    later_kept_id = "t019"
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

    # When: a control and a carrier-pin reload cross the next boundary.
    control = _compressor()
    control._generate_summary = (
        lambda *_args, **_kwargs: f"{SUMMARY_PREFIX}\nCONTROL_SUMMARY"
    )
    control_output = control.compress(deepcopy(extended))
    pinned = _compressor()
    pinned._keep_turn_ids = {str(carrier_id), later_kept_id}
    pinned._generate_summary = (
        lambda *_args, **_kwargs: f"{SUMMARY_PREFIX}\nPINNED_SUMMARY"
    )
    pinned_output = pinned.compress(deepcopy(extended))

    # Then: both paths have one summary and the pinned raw turns occur once in order.
    assert len(_summary_carriers(control_output)) == 1
    assert len(_summary_carriers(pinned_output)) == 1
    pinned_raw = [
        message
        for message in pinned_output
        if message.get("_transcript_turn_id") in {carrier_id, later_kept_id}
        and not message.get(COMPRESSED_SUMMARY_METADATA_KEY)
    ]
    assert [
        message["_transcript_turn_id"] for message in pinned_raw
    ] == [carrier_id, later_kept_id]
    assert COMPRESSED_SUMMARY_METADATA_KEY not in pinned_raw[0]
    assert pinned_raw[0]["content"] == source_by_id[carrier_id]["content"]
    assert pinned_raw[1]["content"] == source_by_id[later_kept_id]["content"]
    assert sum(
        message.get("_transcript_turn_id") == carrier_id
        for message in pinned_output
    ) == 1
