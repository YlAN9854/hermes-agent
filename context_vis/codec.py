from __future__ import annotations

from typing import Any

from .domain import (
    AggregateNode, BacktrackLink, ContextVisModel, IntentSegment, SalientInfo,
    SemanticUnit, SpanRef, SummarySentence, SurvivalState,
)


def model_from_dict(data: dict[str, Any] | None) -> ContextVisModel:
    data = data or {}
    units: list[SemanticUnit] = []
    for raw in data.get("units", []):
        sentences = [
            SummarySentence(
                text=sentence["text"],
                source_spans=[
                    SpanRef(
                        turn_id=span["turn_id"],
                        char_start=span["char_start"],
                        char_end=span["char_end"],
                    )
                    for span in sentence.get("source_spans", [])
                ],
            )
            for sentence in raw.get("summary_sentences", [])
        ]
        infos = [
            SalientInfo(
                info_id=info["info_id"],
                kind=info["kind"],
                detected_text=info["detected_text"],
                span_in_B=SpanRef(
                    turn_id=info["span_in_B"]["turn_id"],
                    char_start=info["span_in_B"]["char_start"],
                    char_end=info["span_in_B"]["char_end"],
                ),
                status_in_A=info.get("status_in_A", "unknown"),
                reframed_text_in_A=info.get("reframed_text_in_A"),
                confidence=info.get("confidence", "reliable"),
                occurrences=info.get("occurrences", 1),
            )
            for info in raw.get("salient_infos", [])
        ]
        units.append(SemanticUnit(
            unit_id=raw["unit_id"],
            title=raw["title"],
            summary_sentences=sentences,
            covered_turns=list(raw["covered_turns"]),
            salient_infos=infos,
            frozen=raw.get("frozen", True),
            created_at_turn=raw.get("created_at_turn", ""),
        ))
    intent_segments: list[IntentSegment] = []
    for segment in data.get("intent_segments", []):
        raw_trigger = segment.get("trigger_span")
        trigger_span = (
            SpanRef(
                turn_id=raw_trigger["turn_id"],
                char_start=raw_trigger["char_start"],
                char_end=raw_trigger["char_end"],
            )
            if raw_trigger
            else None
        )
        intent_segments.append(IntentSegment(
            segment_id=segment["segment_id"],
            label=segment["label"],
            from_unit_id=segment["from_unit_id"],
            to_unit_id=segment["to_unit_id"],
            trigger_span=trigger_span,
            note=segment.get("note", ""),
            origin=segment.get("origin", "user_edited"),
        ))
    return ContextVisModel(
        units=units,
        aggregates=[AggregateNode(**n) for n in data.get("aggregates", [])],
        decision_aggregates=[AggregateNode(**n) for n in data.get("decision_aggregates", [])],
        decision_intent=data.get("decision_intent"),
        backlinks=[BacktrackLink(**b) for b in data.get("backlinks", [])],
        intent_segments=intent_segments,
        tier=data.get("tier", 1),
        revision=data.get("revision", 0),
        legacy_transcript_warning=data.get("legacy_transcript_warning"),
        survival=SurvivalState(**data["survival"]) if data.get("survival") else None,
        preserved=list(data.get("preserved", [])),
        dropped=list(data.get("dropped", [])),
    )
