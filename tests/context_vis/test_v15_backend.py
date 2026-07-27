import json
import sqlite3
from pathlib import Path

from context_vis.api import get_context_session
from context_vis.hermes_adapter import HermesContextAdapter
from hermes_constants import get_hermes_home
from hermes_state import SessionDB


def test_baseline_active_context_separates_summary_from_live_b_turn(
    tmp_path: Path,
) -> None:
    # Given: a compacted session with one synthetic summary and one live B turn.
    db = SessionDB(tmp_path / "state.db")
    db.create_session("baseline", "cli")
    db.append_message("baseline", "user", "constraint")
    db.append_message("baseline", "assistant", "acknowledged")
    db.append_message("baseline", "user", "continue")
    loaded = db.get_messages_as_conversation("baseline")
    db.archive_and_compact(
        "baseline",
        [
            {
                "role": "assistant",
                "content": "[CONTEXT SUMMARY]: constraint retained",
                "_compressed_summary": True,
            },
            loaded[2],
        ],
    )

    # When: ContextVis reads mutable A and immutable B through the real adapter.
    adapter = HermesContextAdapter(db, "baseline", tmp_path)
    active = adapter.get_active_context()
    transcript = adapter.get_full_transcript()

    # Then: A distinguishes the synthetic summary from its live B-linked tail.
    assert active is not None
    assert [(entry.synthetic, entry.origin_turn_id) for entry in active.entries] == [
        (True, None),
        (False, "hermes-msg:3"),
    ]
    assert [turn.turn_id for turn in transcript] == [
        "hermes-msg:1",
        "hermes-msg:2",
        "hermes-msg:3",
    ]
    db.close()


def test_tier_one_response_has_no_compression_payload(
    _isolate_hermes_home: None,
) -> None:
    # Given: a valid session without any active model context.
    db = SessionDB(get_hermes_home() / "state.db")
    db.create_session("tier-one", "cli")
    db.close()

    # When: the real ContextVis session endpoint serializes it.
    payload = get_context_session("tier-one")

    # Then: Tier 1 degrades by omitting compression truth, never fabricating it.
    assert payload["capabilities"]["tier"] == 1
    assert payload["compression"] is None


def test_observed_standalone_summary_serializes_compression_truth(
    _isolate_hermes_home: None,
) -> None:
    # Given: an observed compaction with a standalone summary and a live tail.
    home = get_hermes_home()
    db = SessionDB(home / "state.db")
    db.create_session("standalone", "cli")
    db.append_message("standalone", "user", "constraint")
    db.append_message("standalone", "assistant", "acknowledged")
    db.append_message("standalone", "user", "continue")
    loaded = db.get_messages_as_conversation("standalone")
    summary = "[CONTEXT SUMMARY]: constraint retained"
    db.archive_and_compact(
        "standalone",
        [
            {
                "role": "assistant",
                "content": summary,
                "_compressed_summary": True,
            },
            loaded[2],
        ],
    )
    probe_dir = home / "context-vis" / "compaction"
    probe_dir.mkdir(parents=True)
    (probe_dir / "standalone.jsonl").write_text(
        json.dumps(
            {
                "v": 1,
                "event_id": "observed-standalone",
                "ts": 100.0,
                "before_turn_ids": [
                    "hermes-msg:1",
                    "hermes-msg:2",
                    "hermes-msg:3",
                ],
                "after_turn_ids": ["hermes-msg:3"],
                "summary_text": summary,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    db.close()

    # When: the real endpoint serializes active context and its event.
    compression = get_context_session("standalone")["compression"]

    # Then: every pointer names immutable B and synthetic A text has no SpanRef.
    assert compression["fidelity"] == "observed"
    assert compression["live_turn_ids"] == ["hermes-msg:3"]
    assert compression["synthetic_entries"] == [
        {"role": "assistant", "content": summary}
    ]
    assert compression["unlinked_live_count"] == 0
    assert compression["events"][0]["event_id"] == "observed-standalone"
    assert compression["events"][0]["kept_turn_ids"] == ["hermes-msg:3"]
    assert compression["events"][0]["dropped_turn_ids"] == [
        "hermes-msg:1",
        "hermes-msg:2",
    ]
    assert set(compression["synthetic_entries"][0]) == {"role", "content"}


def test_observed_merged_summary_keeps_boundary_tail_live(
    _isolate_hermes_home: None,
) -> None:
    # Given: a current merged-summary row that still contains a live B tail.
    home = get_hermes_home()
    db = SessionDB(home / "state.db")
    db.create_session("merged", "cli")
    db.append_message("merged", "user", "one")
    db.append_message("merged", "assistant", "two")
    db.append_message("merged", "user", "A😀B")
    loaded = db.get_messages_as_conversation("merged")
    summary = "[CONTEXT SUMMARY]: earlier turns compacted"
    merged_content = (
        "[PRIOR CONTEXT — for reference only; not a new message]\n"
        "A😀B\n\n"
        "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]\n\n"
        f"{summary}\n\n"
        "--- END OF CONTEXT SUMMARY — respond to the message below, "
        "not the summary above ---"
    )
    db.archive_and_compact(
        "merged",
        [
            {
                **loaded[2],
                "content": merged_content,
                "_compressed_summary": True,
            }
        ],
    )
    probe_dir = home / "context-vis" / "compaction"
    probe_dir.mkdir(parents=True)
    (probe_dir / "merged.jsonl").write_text(
        json.dumps(
            {
                "v": 1,
                "event_id": "observed-merged",
                "ts": 200.0,
                "before_turn_ids": [
                    "hermes-msg:1",
                    "hermes-msg:2",
                    "hermes-msg:3",
                ],
                "after_turn_ids": ["hermes-msg:3"],
                "summary_text": summary,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    db.close()

    # When: active-context truth is serialized.
    compression = get_context_session("merged")["compression"]

    # Then: the tail remains B-linked and only the summary portion is synthetic.
    assert compression["live_turn_ids"] == ["hermes-msg:3"]
    assert compression["synthetic_entries"] == [
        {"role": "user", "content": summary}
    ]
    assert compression["unlinked_live_count"] == 0


def test_reconstructed_unlinked_context_reports_uncertainty(
    _isolate_hermes_home: None,
) -> None:
    # Given: an old active row whose immutable-B provenance was never recorded.
    home = get_hermes_home()
    db = SessionDB(home / "state.db")
    db.create_session("legacy", "cli")
    db.append_message("legacy", "user", "legacy active text")
    db.close()
    with sqlite3.connect(home / "state.db") as connection:
        connection.execute(
            "UPDATE messages SET transcript_turn_id=NULL WHERE session_id=?",
            ("legacy",),
        )

    # When: the real endpoint reconstructs the active context.
    compression = get_context_session("legacy")["compression"]

    # Then: missing linkage is explicit and is never promoted to a live B id.
    assert compression["fidelity"] == "reconstructed"
    assert compression["live_turn_ids"] == []
    assert compression["synthetic_entries"] == []
    assert compression["unlinked_live_count"] == 1
