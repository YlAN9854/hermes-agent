"""Schema and validation for synthetic long-horizon conversation cases.

A case is a scripted multi-turn conversation with gold annotations:
- segments: the intended topic/task boundaries (gold standard for unit splitting)
- constraints: scattered high-impact constraints (gold standard for salient info)
- backtracks: intended "abandon then return" relations between segments

Gold annotations are used only by the programmatic evaluator; blind judges
never see them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLES = {"user", "assistant", "tool"}


@dataclass
class T:
    role: str
    content: str
    tool_name: str | None = None


@dataclass
class Segment:
    name: str
    start: int  # inclusive turn index
    end: int    # inclusive turn index


@dataclass
class GoldConstraint:
    turn: int
    text: str  # must be an exact substring of turns[turn].content


@dataclass
class Backtrack:
    from_segment: int  # index into segments
    to_segment: int
    note: str


@dataclass(frozen=True, slots=True)
class IntentShift:
    segment: int
    kind: str
    cause_turn: int | None = None
    note: str = ""


@dataclass
class Compaction:
    """A compaction to replay while seeding, so A differs from B."""

    kept_turns: list[int]  # turn indexes that survive into A
    summary: str           # the text compression injects in place of the rest


@dataclass
class GoldSurvival:
    constraint: int  # index into Case.constraints
    status: str      # "present" | "reframed" | "absent"


@dataclass
class Case:
    case_id: str
    title: str
    turns: list[T]
    segments: list[Segment]
    constraints: list[GoldConstraint] = field(default_factory=list)
    backtracks: list[Backtrack] = field(default_factory=list)
    compaction: Compaction | None = None
    survival: list[GoldSurvival] = field(default_factory=list)
    intent_shifts: list[IntentShift] = field(default_factory=list)


def validate_case(case: Case) -> list[str]:
    errors: list[str] = []
    n = len(case.turns)
    for i, turn in enumerate(case.turns):
        if turn.role not in ROLES:
            errors.append(f"turn {i}: invalid role {turn.role!r}")
        if turn.role == "tool" and not turn.tool_name:
            errors.append(f"turn {i}: tool turn missing tool_name")
        if not turn.content or not turn.content.strip():
            errors.append(f"turn {i}: empty content")
    cursor = 0
    for si, seg in enumerate(case.segments):
        if seg.start != cursor:
            errors.append(f"segment {si} ({seg.name}): starts at {seg.start}, expected {cursor}")
        if seg.end < seg.start:
            errors.append(f"segment {si} ({seg.name}): end < start")
        cursor = seg.end + 1
    if case.segments and cursor != n:
        errors.append(f"segments cover turns 0..{cursor - 1} but case has {n} turns")
    for ci, gc in enumerate(case.constraints):
        if not (0 <= gc.turn < n):
            errors.append(f"constraint {ci}: turn index {gc.turn} out of range")
        elif gc.text not in case.turns[gc.turn].content:
            errors.append(f"constraint {ci}: text is not an exact substring of turn {gc.turn}")
    for bi, bt in enumerate(case.backtracks):
        if not (0 <= bt.to_segment < bt.from_segment < len(case.segments)):
            errors.append(f"backtrack {bi}: needs to_segment < from_segment, both valid segment indexes")
    for ii, shift in enumerate(case.intent_shifts):
        valid_segment = type(shift.segment) is int and 1 <= shift.segment < len(case.segments)
        if not valid_segment:
            errors.append(f"intent shift {ii}: segment {shift.segment} must be in 1..{len(case.segments) - 1}")
        if shift.kind not in ("drift", "return"):
            errors.append(f"intent shift {ii}: invalid kind {shift.kind!r}")
        if shift.cause_turn is not None and (
            type(shift.cause_turn) is not int
            or not (0 <= shift.cause_turn < n)
            or (valid_segment and shift.cause_turn > case.segments[shift.segment].start)
        ):
            errors.append(
                f"intent shift {ii}: cause_turn must be in range and no later than segment {shift.segment} start"
            )
    if case.compaction:
        for kt in case.compaction.kept_turns:
            if not (0 <= kt < n):
                errors.append(f"compaction: kept turn index {kt} out of range")
        if sorted(case.compaction.kept_turns) != case.compaction.kept_turns:
            errors.append("compaction: kept_turns must be in transcript order")
    for si, gs in enumerate(case.survival):
        if gs.status not in {"present", "reframed", "absent"}:
            errors.append(f"survival {si}: invalid status {gs.status!r}")
        if not (0 <= gs.constraint < len(case.constraints)):
            errors.append(f"survival {si}: constraint index {gs.constraint} out of range")
            continue
        if not case.compaction:
            errors.append(f"survival {si}: gold survival needs a compaction to survive")
            continue
        text = case.constraints[gs.constraint].text
        kept = gs.constraint < len(case.constraints) and any(
            case.constraints[gs.constraint].turn == kt for kt in case.compaction.kept_turns
        )
        if gs.status == "reframed":
            # A reframing means restated in DIFFERENT words. If the constraint
            # text survives verbatim anywhere in A, the honest answer is
            # "present", and the case would be testing the wrong branch.
            if text in case.compaction.summary or kept:
                errors.append(f"survival {si}: marked reframed but the text survives verbatim in A")
        if gs.status == "present" and not (kept or text in case.compaction.summary):
            errors.append(f"survival {si}: marked present but the text is nowhere in A")
        if gs.status == "absent" and (kept or text in case.compaction.summary):
            errors.append(f"survival {si}: marked absent but the text is still in A")
    return errors


def case_stats(case: Case) -> dict:
    total_chars = sum(len(t.content) for t in case.turns)
    return {
        "case_id": case.case_id,
        "turns": len(case.turns),
        "chars": total_chars,
        "segments": len(case.segments),
        "constraints": len(case.constraints),
        "backtracks": len(case.backtracks),
        "intent_shifts": len(case.intent_shifts),
    }
