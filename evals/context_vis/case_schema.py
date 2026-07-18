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


@dataclass
class Case:
    case_id: str
    title: str
    turns: list[T]
    segments: list[Segment]
    constraints: list[GoldConstraint] = field(default_factory=list)
    backtracks: list[Backtrack] = field(default_factory=list)


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
    }
