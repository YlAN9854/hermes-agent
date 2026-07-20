import json

import pytest

from agent import compaction_probe
from agent.compaction_probe import ENV_FLAG, record_compaction


@pytest.fixture
def probe_home(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    monkeypatch.setattr(compaction_probe, "_probe_dir", lambda: tmp_path / "context-vis" / "compaction")
    return tmp_path / "context-vis" / "compaction"


def _turn(turn_id, content="hi", role="user", **extra):
    return {"role": role, "content": content, "_transcript_turn_id": turn_id, **extra}


def _records(directory, session="s1"):
    path = directory / f"{session}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record_one(messages_after, session="s1", messages_before=None):
    record_compaction(
        session_id=session,
        boundary_parent_session_id=session,
        in_place=True,
        messages_before=messages_before if messages_before is not None else [_turn("t1"), _turn("t2"), _turn("t3")],
        messages_after=messages_after,
        compression_count=1,
    )


def test_probe_writes_nothing_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    monkeypatch.setattr(compaction_probe, "_probe_dir", lambda: tmp_path / "out")
    _record_one([_turn("t3")])
    assert not (tmp_path / "out").exists()


def test_probe_records_kept_and_dropped_turn_ids(probe_home):
    summary_msg = {"role": "user", "content": "Compacted summary body.", "_compressed_summary": True}
    _record_one([summary_msg, _turn("t3")])

    record = _records(probe_home)[0]
    assert record["v"] == 1
    assert record["before_turn_ids"] == ["t1", "t2", "t3"]
    assert record["after_turn_ids"] == ["t3"]  # t1/t2 dropped; the summary carries no B id
    assert record["summary_text"] == "Compacted summary body."
    assert record["unlinked_after"] == 1
    assert record["summary_truncated"] is False


def test_probe_extracts_summary_merged_into_a_tail_message(probe_home):
    merged = _turn(
        "t3",
        "Original tail text.\n\n[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted.\n"
        "The user set a hard rule.\n"
        "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---",
        _compressed_summary=True,
    )
    _record_one([merged])

    summary = _records(probe_home)[0]["summary_text"]
    assert summary.startswith("[CONTEXT COMPACTION")
    assert "The user set a hard rule." in summary
    assert "Original tail text." not in summary  # sliced out of the host message
    assert "END OF CONTEXT SUMMARY" not in summary


def test_probe_truncates_an_oversized_summary(probe_home, monkeypatch):
    monkeypatch.setattr(compaction_probe, "SUMMARY_CHAR_CAP", 50)
    _record_one([{"role": "user", "content": "x" * 500, "_compressed_summary": True}])

    record = _records(probe_home)[0]
    assert record["summary_truncated"] is True
    assert len(record["summary_text"]) == 50


def test_probe_handles_list_content_and_missing_summary(probe_home):
    _record_one([{"role": "user", "content": [{"text": "part one"}, {"text": "part two"}], "_compressed_summary": True},
                 _turn("t3")])
    assert _records(probe_home)[0]["summary_text"] == "part one\npart two"

    _record_one([_turn("t3")])
    assert _records(probe_home)[1]["summary_text"] is None


def test_probe_never_raises_on_hostile_messages(probe_home):
    class Hostile(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    _record_one([Hostile()], messages_before=[Hostile()])
    # Swallowed: no crash, and nothing half-written.
    assert not (probe_home / "s1.jsonl").exists()


def test_probe_rotates_an_oversized_file(probe_home, monkeypatch):
    monkeypatch.setattr(compaction_probe, "MAX_FILE_BYTES", 10)
    _record_one([_turn("t3")])
    _record_one([_turn("t3")])

    assert (probe_home / "s1.jsonl.1").exists()
    assert len(_records(probe_home)) == 1  # current file restarted after rotation
