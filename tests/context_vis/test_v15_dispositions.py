import json
from pathlib import Path

from context_vis.api import (
    PreserveRequest,
    get_context_session,
    preserve_context_turns,
)
from context_vis.codec import model_from_dict
from context_vis.domain import ContextVisModel, PreserveResult, SpanRef, Turn
from context_vis.hermes_adapter import HermesContextAdapter
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from hermes_constants import get_hermes_home
from hermes_state import SessionDB


def _seed(
    home: Path,
) -> tuple[SessionDB, HermesContextAdapter, ContextVisRepository, int]:
    db = SessionDB(home / "state.db")
    db.create_session("dispositions", "cli")
    db.append_message("dispositions", "user", "keep")
    db.append_message("dispositions", "assistant", "drop")
    db.append_message("dispositions", "user", "tail")
    repository = ContextVisRepository(home)
    revision = repository.save(
        "dispositions",
        ContextVisModel().to_dict(),
        "hermes-msg:3",
    )
    return (
        db,
        HermesContextAdapter(db, "dispositions", home),
        repository,
        revision,
    )


def test_adapter_preserves_v1_pin_bytes_and_writes_separate_drop_store(
    tmp_path: Path,
) -> None:
    # Given: one live raw turn to keep and another to schedule for drop.
    db, adapter, repository, _revision = _seed(tmp_path)
    expected_pin_bytes = json.dumps(
        {"v": 1, "turn_ids": ["hermes-msg:1"]},
        ensure_ascii=False,
    )

    # When: the real Hermes adapter writes both wholesale sets.
    result = adapter.request_preserve(
        [SpanRef("hermes-msg:1", 0, 4)],
        drop_spans_in_B=[SpanRef("hermes-msg:2", 0, 4)],
    )

    # Then: old pin readers retain identical bytes and drops are independent.
    assert (
        tmp_path / "context-vis" / "pins" / "dispositions.json"
    ).read_text(encoding="utf-8") == expected_pin_bytes
    assert json.loads(
        (
            tmp_path / "context-vis" / "drops" / "dispositions.json"
        ).read_text(encoding="utf-8")
    ) == {"v": 1, "drop_turn_ids": ["hermes-msg:2"]}
    assert result.accepted_turn_ids == ["hermes-msg:1"]
    assert result.accepted_drop_turn_ids == ["hermes-msg:2"]
    repository.close()
    db.close()


def test_adapter_keep_wins_and_rejects_non_live_drop(
    tmp_path: Path,
) -> None:
    # Given: a keep/drop conflict plus a B turn no longer present in active A.
    db, adapter, repository, _revision = _seed(tmp_path)
    with db._lock:
        db._conn.execute(
            "UPDATE messages SET active=0 WHERE session_id=? AND id=?",
            ("dispositions", 2),
        )
        db._conn.commit()
    adapter = HermesContextAdapter(db, "dispositions", tmp_path)

    # When: conflicts and already-absent turns are submitted together.
    result = adapter.request_preserve(
        [SpanRef("hermes-msg:1", 0, 4)],
        drop_spans_in_B=[
            SpanRef("hermes-msg:1", 0, 4),
            SpanRef("hermes-msg:2", 0, 4),
        ],
    )

    # Then: keep wins and neither unsafe drop reaches the separate store.
    assert result.accepted_turn_ids == ["hermes-msg:1"]
    assert result.accepted_drop_turn_ids == []
    assert result.rejected_drop_turn_ids == [
        "hermes-msg:1",
        "hermes-msg:2",
    ]
    assert result.note and "live raw" in result.note
    drop_record = json.loads(
        (
            tmp_path / "context-vis" / "drops" / "dispositions.json"
        ).read_text(encoding="utf-8")
    )
    assert drop_record["drop_turn_ids"] == []
    repository.close()
    db.close()


def test_old_model_rows_default_to_no_dropped_turns() -> None:
    # Given: a serialized row from before drop dispositions existed.
    legacy = ContextVisModel().to_dict()
    del legacy["dropped"]

    # When: the current codec rehydrates the legacy row.
    model = model_from_dict(legacy)

    # Then: compatibility defaults to no scheduled drops.
    assert model.dropped == []


def test_service_roundtrips_keep_and_drop_wholesale_sets(
    tmp_path: Path,
) -> None:
    # Given: a real adapter, repository, and current revision.
    db, adapter, repository, revision = _seed(tmp_path)
    service = ContextVisService(adapter, repository)

    # When: the service saves both desired disposition sets.
    payload = service.request_preserve(
        ["hermes-msg:1"],
        revision,
        ["hermes-msg:2"],
    )

    # Then: result and persisted model agree on accepted keep/drop turns.
    assert payload["result"]["accepted_turn_ids"] == ["hermes-msg:1"]
    assert payload["result"]["accepted_drop_turn_ids"] == ["hermes-msg:2"]
    assert payload["model"]["preserved"] == ["hermes-msg:1"]
    assert payload["model"]["dropped"] == ["hermes-msg:2"]
    reloaded, _, _ = service.load()
    assert reloaded.preserved == ["hermes-msg:1"]
    assert reloaded.dropped == ["hermes-msg:2"]
    repository.close()
    db.close()


def test_real_api_exposes_capability_and_roundtrips_drops(
    _isolate_hermes_home: None,
) -> None:
    # Given: a real session with two live raw B turns.
    home = get_hermes_home()
    db = SessionDB(home / "state.db")
    db.create_session("disposition-api", "cli")
    db.append_message("disposition-api", "user", "keep")
    db.append_message("disposition-api", "assistant", "drop")
    db.close()
    current = get_context_session("disposition-api")

    # When: the API receives the complete keep/drop sets.
    payload = preserve_context_turns(
        "disposition-api",
        PreserveRequest(
            revision=current["model"]["revision"],
            turn_ids=["hermes-msg:1"],
            drop_turn_ids=["hermes-msg:2"],
        ),
    )

    # Then: capability and response expose truthful disposition support.
    assert current["capabilities"]["dispositions"] is True
    assert payload["model"]["preserved"] == ["hermes-msg:1"]
    assert payload["model"]["dropped"] == ["hermes-msg:2"]


class PinOnlyAdapter:
    tier = 3
    session_id = "pin-only"
    legacy_warning = None

    def get_full_transcript(self) -> list[Turn]:
        return [Turn("t1", "user", "keep", None, 1)]

    def request_preserve(
        self,
        spans_in_B: list[SpanRef],
    ) -> PreserveResult:
        return PreserveResult(
            True,
            [span.turn_id for span in spans_in_B],
            [],
        )


def test_pin_only_adapter_rejects_drop_without_faking_support(
    tmp_path: Path,
) -> None:
    # Given: a Tier 3 adapter that supports only the legacy pin method.
    repository = ContextVisRepository(tmp_path)
    revision = repository.save(
        PinOnlyAdapter.session_id,
        ContextVisModel().to_dict(),
        "t1",
    )
    service = ContextVisService(PinOnlyAdapter(), repository)

    # When: a caller sends both keep and drop desires.
    payload = service.request_preserve(["t1"], revision, ["t1"])

    # Then: keep works while drop is explicitly rejected and never persisted.
    assert payload["result"]["accepted_turn_ids"] == ["t1"]
    assert payload["result"]["accepted_drop_turn_ids"] == []
    assert payload["result"]["rejected_drop_turn_ids"] == ["t1"]
    assert payload["model"]["preserved"] == ["t1"]
    assert payload["model"]["dropped"] == []
    repository.close()
