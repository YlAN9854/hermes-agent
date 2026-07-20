from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant", "tool"]
SurvivalStatus = Literal["present", "reframed", "absent", "unknown"]
Fidelity = Literal["observed", "reconstructed"]


@dataclass(frozen=True)
class Turn:
    turn_id: str
    role: Role
    content: str
    tool_name: str | None
    timestamp: float


@dataclass(frozen=True)
class SpanRef:
    turn_id: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ActiveEntry:
    """One entry of A, the mutable context the model currently sees.

    Deliberately has no ``turn_id``: A is mutable, so nothing may point into
    it. ``origin_turn_id`` traces back to B when the entry came from there and
    is None for content compression authored (summaries). Never build a
    SpanRef out of this type.
    """

    role: Role
    content: str
    origin_turn_id: str | None
    synthetic: bool
    tool_name: str | None = None


@dataclass(frozen=True)
class ActiveContext:
    """A snapshot of the active context.

    ``fidelity="observed"`` means observed as of the agent's last flush to
    durable storage — a live session mid-turn may lag by a turn. It does not
    mean "live".
    """

    entries: list[ActiveEntry]
    fidelity: Fidelity = "observed"


@dataclass(frozen=True)
class CompressionEvent:
    """One compression, described only by references into immutable B.

    ``kept_turn_ids`` / ``dropped_turn_ids`` name B turns, so they stay valid
    forever — the same invariant SpanRef relies on. ``summary_text`` is the
    one thing not recoverable from B later, so it is carried in full.
    """

    event_id: str
    timestamp: float
    sequence: int
    fidelity: Fidelity
    kept_turn_ids: list[str]
    dropped_turn_ids: list[str]
    summary_text: str | None
    summary_truncated: bool = False
    note: str | None = None


@dataclass
class SurvivalState:
    """Provenance for a computed survival pass.

    ``active_fingerprint`` lets a reader tell that stored statuses were
    computed against a different A than the current one, so a stale badge can
    be labelled stale instead of silently presented as current.
    """

    computed_at: float
    fidelity: Fidelity | None
    event_count: int
    active_fingerprint: str
    note: str | None = None


@dataclass
class SummarySentence:
    text: str
    source_spans: list[SpanRef]


@dataclass
class SalientInfo:
    info_id: str
    kind: Literal["user_stated_constraint", "tool_output_constraint", "other"]
    detected_text: str
    span_in_B: SpanRef
    status_in_A: SurvivalStatus = "unknown"
    reframed_text_in_A: str | None = None
    confidence: Literal["reliable", "ai_guessed"] = "reliable"
    occurrences: int = 1  # times the same constraint text appears in B; span_in_B is the first


@dataclass
class SemanticUnit:
    unit_id: str
    title: str
    summary_sentences: list[SummarySentence]
    covered_turns: list[str]
    salient_infos: list[SalientInfo] = field(default_factory=list)
    frozen: bool = True
    created_at_turn: str = ""


@dataclass
class AggregateNode:
    node_id: str
    title: str
    child_unit_ids: list[str]
    origin: Literal["llm_draft", "user_edited"] = "llm_draft"
    intent_tag: str | None = None


@dataclass
class BacktrackLink:
    from_unit_id: str
    to_unit_id: str
    note: str


@dataclass
class ContextVisModel:
    units: list[SemanticUnit] = field(default_factory=list)
    aggregates: list[AggregateNode] = field(default_factory=list)
    decision_aggregates: list[AggregateNode] = field(default_factory=list)
    decision_intent: str | None = None
    backlinks: list[BacktrackLink] = field(default_factory=list)
    tier: Literal[1, 2, 3] = 1
    revision: int = 0
    legacy_transcript_warning: str | None = None
    survival: SurvivalState | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextAdapter(Protocol):
    tier: int
    session_id: str
    legacy_warning: str | None

    def get_full_transcript(self) -> list[Turn]: ...
    def get_active_context(self) -> ActiveContext | None: ...
    def get_compression_events(self) -> list[CompressionEvent]: ...
    def llm_complete(self, prompt: str, **opts: Any) -> str: ...


def validate_model(model: ContextVisModel, transcript: list[Turn]) -> None:
    turns = {t.turn_id: t for t in transcript}
    unit_ids: set[str] = set()
    covered_order: list[str] = []
    for unit in model.units:
        if unit.unit_id in unit_ids:
            raise ValueError(f"duplicate unit_id: {unit.unit_id}")
        unit_ids.add(unit.unit_id)
        if not unit.covered_turns or any(t not in turns for t in unit.covered_turns):
            raise ValueError(f"unit {unit.unit_id} references an unknown turn")
        covered_order.extend(unit.covered_turns)
        for sentence in unit.summary_sentences:
            if not sentence.text.strip() or not sentence.source_spans:
                raise ValueError("summary sentences require text and source spans")
            for span in sentence.source_spans:
                turn = turns.get(span.turn_id)
                if turn is None or span.char_start < 0 or span.char_end <= span.char_start or span.char_end > len(turn.content):
                    raise ValueError("source span does not resolve into transcript B")
        for info in unit.salient_infos:
            turn = turns.get(info.span_in_B.turn_id)
            span = info.span_in_B
            if turn is None or turn.content[span.char_start:span.char_end] != info.detected_text:
                raise ValueError("salient info must be an exact quote from transcript B")
    transcript_order = {turn.turn_id: i for i, turn in enumerate(transcript)}
    indexes = [transcript_order[t] for t in covered_order]
    if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
        raise ValueError("units must cover turns once and in transcript order")
    for nodes in (model.aggregates, model.decision_aggregates):
        flattened = [uid for node in nodes for uid in node.child_unit_ids]
        expected_units = [unit.unit_id for unit in model.units]
        if flattened and flattened != expected_units:
            raise ValueError("aggregate nodes must be an ordered partition of all semantic units")
    positions = {u.unit_id: i for i, u in enumerate(model.units)}
    for link in model.backlinks:
        if link.from_unit_id not in positions or link.to_unit_id not in positions:
            raise ValueError("backlink references an unknown unit")
        if positions[link.from_unit_id] <= positions[link.to_unit_id] or not link.note.strip():
            raise ValueError("backlinks must point from a later unit to an earlier unit")
