from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from evals.context_vis.case_schema import Case, IntentShift

def test_c6_schema_characterization_remains_valid() -> None:
    from evals.context_vis.case_schema import case_stats, validate_case
    from evals.context_vis.cases.c6 import CASE

    assert validate_case(CASE) == []
    stats = case_stats(CASE)
    assert stats["case_id"] == "c6"
    assert stats["turns"] == len(CASE.turns)
    assert stats["segments"] == 4
    assert stats["constraints"] == 3
    assert stats["backtracks"] == 0


def _case_with_shift(shift: IntentShift) -> Case:
    from evals.context_vis.cases.c6 import CASE

    case = deepcopy(CASE)
    case.intent_shifts = [shift]
    return case


def test_intent_shift_valid_fixture_is_counted_and_accepted() -> None:
    from evals.context_vis.case_schema import IntentShift, case_stats, validate_case

    case = _case_with_shift(IntentShift(segment=1, kind="drift", cause_turn=3, note="new line"))

    assert validate_case(case) == []
    assert case_stats(case)["intent_shifts"] == 1


@pytest.mark.parametrize(
    ("segment", "kind", "cause_turn", "expected"),
    [
        (0, "drift", None, "segment"),
        (4, "drift", None, "segment"),
        (1, "sideways", None, "kind"),
        (1, "drift", -1, "cause_turn"),
        (1, "drift", 100, "cause_turn"),
        (1, "drift", 5, "cause_turn"),
    ],
)
def test_malformed_intent_shift_is_rejected(
    segment: int,
    kind: str,
    cause_turn: int | None,
    expected: str,
) -> None:
    from evals.context_vis.case_schema import IntentShift, validate_case

    errors = validate_case(_case_with_shift(IntentShift(segment, kind, cause_turn)))

    assert any(expected in error for error in errors)


def test_c7_is_registered_and_self_validating() -> None:
    from evals.context_vis.cases.c7 import CASE
    from evals.context_vis.case_schema import case_stats, validate_case
    from evals.context_vis.run_generate import SALIENT_CASE_IDS
    from evals.context_vis.seed import CASE_IDS

    assert "c7" in CASE_IDS
    assert "c7" in SALIENT_CASE_IDS
    assert validate_case(CASE) == []
    assert 25 <= len(CASE.turns) <= 30
    assert case_stats(CASE)["intent_shifts"] >= 3


def test_c7_gold_describes_a_to_b_to_c_drift_then_b_return() -> None:
    from evals.context_vis.cases.c7 import CASE

    assert [(shift.segment, shift.kind, shift.cause_turn) for shift in CASE.intent_shifts] == [
        (1, "drift", 6),
        (2, "drift", 13),
        (3, "return", 20),
    ]
    assert [shift.kind for shift in CASE.intent_shifts].count("drift") >= 2
    assert [shift.kind for shift in CASE.intent_shifts].count("return") == 1
    assert any(
        backtrack.from_segment == 3 and backtrack.to_segment == 1
        for backtrack in CASE.backtracks
    )
    names = [segment.name for segment in CASE.segments]
    assert names[0].startswith("A")
    assert names[1].startswith("B")
    assert names[2].startswith("C")
    assert names[3].startswith("B")


def test_c7_has_research_constraints_and_survival_gold() -> None:
    from evals.context_vis.cases.c7 import CASE
    from context_vis.service import CONSTRAINT_RE

    statuses = {survival.status for survival in CASE.survival}
    assert statuses == {"present", "reframed", "absent"}
    assert CASE.compaction is not None
    assert all(not CONSTRAINT_RE.search(CASE.constraints[index].text) for index in (0, 1, 2))
    assert CONSTRAINT_RE.search(CASE.constraints[3].text)
    assert any("license" in constraint.text.lower() for constraint in CASE.constraints)
    assert any("$200" in constraint.text for constraint in CASE.constraints)
    assert any("do not" in constraint.text.lower() for constraint in CASE.constraints)
    assert len(CASE.compaction.summary) < 60_000
    assert sum(len(turn.content) for turn in CASE.turns) < 60_000
