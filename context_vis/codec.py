from __future__ import annotations

from typing import Any

from .domain import (
    AggregateNode, BacktrackLink, ContextVisModel, SalientInfo,
    SemanticUnit, SpanRef, SummarySentence, SurvivalState,
)


def model_from_dict(data: dict[str, Any] | None) -> ContextVisModel:
    data = data or {}
    units: list[SemanticUnit] = []
    for raw in data.get("units", []):
        sentences = [SummarySentence(s["text"], [SpanRef(**p) for p in s.get("source_spans", [])]) for s in raw.get("summary_sentences", [])]
        infos = [SalientInfo(**{**i, "span_in_B": SpanRef(**i["span_in_B"])}) for i in raw.get("salient_infos", [])]
        units.append(SemanticUnit(**{**raw, "summary_sentences": sentences, "salient_infos": infos}))
    return ContextVisModel(
        units=units,
        aggregates=[AggregateNode(**n) for n in data.get("aggregates", [])],
        decision_aggregates=[AggregateNode(**n) for n in data.get("decision_aggregates", [])],
        decision_intent=data.get("decision_intent"),
        backlinks=[BacktrackLink(**b) for b in data.get("backlinks", [])],
        tier=data.get("tier", 1),
        revision=data.get("revision", 0),
        legacy_transcript_warning=data.get("legacy_transcript_warning"),
        survival=SurvivalState(**data["survival"]) if data.get("survival") else None,
    )
