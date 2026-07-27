from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_vis.api import router
from context_vis.codec import model_from_dict
from context_vis.domain import (
    ContextVisModel,
    SemanticUnit,
    SpanRef,
    SummarySentence,
    Turn,
    validate_model,
)
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from hermes_constants import get_hermes_home
from hermes_state import SessionDB


class IntentAdapter:
    tier = 2
    session_id = "intent-service"
    legacy_warning = None

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = turns

    def get_full_transcript(self) -> list[Turn]:
        return self.turns


def _turns(prefix: str = "t") -> list[Turn]:
    return [
        Turn(f"{prefix}1", "user", "A😀B", None, 1),
        Turn(f"{prefix}2", "assistant", "middle", None, 2),
        Turn(f"{prefix}3", "user", "omega", None, 3),
    ]


def _model(turns: list[Turn]) -> ContextVisModel:
    units = [
        SemanticUnit(
            f"u{index}",
            f"unit {index}",
            [SummarySentence(turn.content, [SpanRef(turn.turn_id, 0, len(turn.content))])],
            [turn.turn_id],
            created_at_turn=turn.turn_id,
        )
        for index, turn in enumerate(turns, start=1)
    ]
    return ContextVisModel(units=units, tier=2)


def _seed_service(
    tmp_path: Path,
) -> tuple[ContextVisService, ContextVisRepository, int]:
    turns = _turns()
    repository = ContextVisRepository(tmp_path)
    revision = repository.save(
        IntentAdapter.session_id,
        _model(turns).to_dict(),
        turns[-1].turn_id,
    )
    return ContextVisService(IntentAdapter(turns), repository), repository, revision


def _seed_api_session(home: Path) -> int:
    db = SessionDB(home / "state.db")
    db.create_session("intent-api", "cli")
    for turn in _turns("hermes-msg:"):
        db.append_message("intent-api", turn.role, turn.content)
    db.close()
    repository = ContextVisRepository(home)
    revision = repository.save(
        "intent-api",
        _model(_turns("hermes-msg:")).to_dict(),
        "hermes-msg:3",
    )
    repository.close()
    return revision


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_old_model_rows_default_to_no_intent_segments() -> None:
    # Given: a stored row written before intent segments existed.
    raw = ContextVisModel().to_dict()
    del raw["intent_segments"]

    # When: the current codec rehydrates it.
    model = model_from_dict(raw)

    # Then: the compatibility default is an empty list.
    assert model.intent_segments == []


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        ([{"segment_id": "", "label": "alpha", "from_unit_id": "u1", "to_unit_id": "u1"}], "segment_id"),
        ([{"segment_id": "s1", "label": " ", "from_unit_id": "u1", "to_unit_id": "u1"}], "label"),
        ([{"segment_id": "s1", "label": "alpha", "from_unit_id": "missing", "to_unit_id": "u1"}], "unknown unit"),
        ([{"segment_id": "s1", "label": "alpha", "from_unit_id": "u3", "to_unit_id": "u1"}], "closed range"),
        ([
            {"segment_id": "same", "label": "alpha", "from_unit_id": "u1", "to_unit_id": "u1"},
            {"segment_id": "same", "label": "omega", "from_unit_id": "u3", "to_unit_id": "u3"},
        ], "duplicate"),
        ([
            {"segment_id": "s1", "label": "alpha", "from_unit_id": "u1", "to_unit_id": "u2"},
            {"segment_id": "s2", "label": "omega", "from_unit_id": "u2", "to_unit_id": "u3"},
        ], "overlap"),
        ([
            {"segment_id": "s2", "label": "omega", "from_unit_id": "u3", "to_unit_id": "u3"},
            {"segment_id": "s1", "label": "alpha", "from_unit_id": "u1", "to_unit_id": "u1"},
        ], "ordered"),
        ([{
            "segment_id": "s1",
            "label": "alpha",
            "from_unit_id": "u1",
            "to_unit_id": "u1",
            "trigger_span": {"turn_id": "missing", "char_start": 0, "char_end": 1},
        }], "transcript B"),
        ([{
            "segment_id": "s1",
            "label": "alpha",
            "from_unit_id": "u1",
            "to_unit_id": "u1",
            "trigger_span": {"turn_id": "t1", "char_start": 0, "char_end": 4},
        }], "transcript B"),
    ],
)
def test_intent_validator_rejects_malformed_segments(
    segments: list[dict[str, str | dict[str, str | int]]],
    message: str,
) -> None:
    # Given: valid units plus one malformed manual intent payload.
    turns = _turns()
    model = model_from_dict({**_model(turns).to_dict(), "intent_segments": segments})

    # When/Then: validation rejects it with an actionable reason.
    with pytest.raises(ValueError, match=message):
        validate_model(model, turns)


def test_sparse_closed_intent_ranges_are_valid() -> None:
    # Given: two closed ranges with an intentionally unlabelled unit-sized gap.
    turns = _turns()
    segments = [
        {"segment_id": "s1", "label": "alpha", "from_unit_id": "u1", "to_unit_id": "u1"},
        {"segment_id": "s2", "label": "omega", "from_unit_id": "u3", "to_unit_id": "u3"},
    ]
    model = model_from_dict({**_model(turns).to_dict(), "intent_segments": segments})

    # When: the domain validator checks the annotation layer.
    validate_model(model, turns)

    # Then: gaps remain valid and aggregate partition rules are untouched.
    assert [segment.segment_id for segment in model.intent_segments] == ["s1", "s2"]


def test_save_edits_roundtrips_unicode_trigger_and_forces_user_origin(
    tmp_path: Path,
) -> None:
    # Given: a valid three-unit model and a trigger spanning the whole A😀B turn.
    service, repository, revision = _seed_service(tmp_path)
    payload = {
        "intent_segments": [{
            "segment_id": "s1",
            "label": "alpha",
            "from_unit_id": "u1",
            "to_unit_id": "u2",
            "trigger_span": {"turn_id": "t1", "char_start": 0, "char_end": 3},
            "note": "manual",
            "origin": "llm_draft",
        }]
    }

    # When: the wholesale edit is saved and reloaded.
    saved = service.save_edits(payload, revision)
    reloaded, _, _ = service.load()

    # Then: code-point offsets roundtrip and edits always become user-owned.
    assert saved["intent_segments"][0]["trigger_span"]["char_end"] == 3
    assert saved["intent_segments"][0]["origin"] == "user_edited"
    assert reloaded.intent_segments[0].origin == "user_edited"
    repository.close()


def test_stale_intent_revision_leaves_persisted_model_unchanged(
    tmp_path: Path,
) -> None:
    # Given: one successful edit followed by a different edit at its old revision.
    service, repository, revision = _seed_service(tmp_path)
    first = [{
        "segment_id": "s1",
        "label": "saved",
        "from_unit_id": "u1",
        "to_unit_id": "u1",
    }]
    service.save_edits({"intent_segments": first}, revision)

    # When: a stale writer attempts to replace it.
    with pytest.raises(RuntimeError, match="revision_conflict"):
        service.save_edits(
            {"intent_segments": [{**first[0], "label": "stale"}]},
            revision,
        )

    # Then: repository CAS preserved the successful model exactly.
    reloaded, _, _ = service.load()
    assert [segment.label for segment in reloaded.intent_segments] == ["saved"]
    repository.close()


def test_intent_api_roundtrip_uses_real_router(
    _isolate_hermes_home: None,
) -> None:
    # Given: a stored model addressed through the production router path.
    revision = _seed_api_session(get_hermes_home())
    body = {
        "revision": revision,
        "intent_segments": [{
            "segment_id": "api-segment",
            "label": "api edit",
            "from_unit_id": "u1",
            "to_unit_id": "u2",
            "trigger_span": {
                "turn_id": "hermes-msg:1",
                "char_start": 0,
                "char_end": 3,
            },
        }],
    }

    # When: an ASGI client edits the model through the real route.
    with TestClient(_app()) as client:
        response = client.put(
            "/api/context-vis/sessions/intent-api/model",
            json=body,
        )

    # Then: the response contains the validated, persisted edit.
    assert response.status_code == 200
    segment = response.json()["model"]["intent_segments"][0]
    assert segment["segment_id"] == "api-segment"
    assert segment["origin"] == "user_edited"


@pytest.mark.parametrize(
    ("segments", "detail"),
    [
        ([
            {"segment_id": "same", "label": "one", "from_unit_id": "u1", "to_unit_id": "u1"},
            {"segment_id": "same", "label": "two", "from_unit_id": "u3", "to_unit_id": "u3"},
        ], "duplicate"),
        ([
            {"segment_id": "s1", "label": "one", "from_unit_id": "u1", "to_unit_id": "u2"},
            {"segment_id": "s2", "label": "two", "from_unit_id": "u2", "to_unit_id": "u3"},
        ], "overlap"),
        ([{
            "segment_id": "s1",
            "label": "unicode",
            "from_unit_id": "u1",
            "to_unit_id": "u1",
            "trigger_span": {
                "turn_id": "hermes-msg:1",
                "char_start": 0,
                "char_end": 4,
            },
        }], "transcript B"),
        ([{
            "segment_id": "s1",
            "label": "missing end",
            "from_unit_id": "u1",
        }], "to_unit_id"),
    ],
)
def test_intent_api_returns_actionable_4xx_for_malformed_input(
    _isolate_hermes_home: None,
    segments: list[dict[str, str | dict[str, str | int]]],
    detail: str,
) -> None:
    # Given: a stored model and a malformed manual intent edit.
    revision = _seed_api_session(get_hermes_home())

    # When: an ASGI client submits the invalid payload.
    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.put(
            "/api/context-vis/sessions/intent-api/model",
            json={"revision": revision, "intent_segments": segments},
        )

    # Then: the boundary returns an actionable client error, never a 500.
    assert 400 <= response.status_code < 500
    assert detail in response.text
