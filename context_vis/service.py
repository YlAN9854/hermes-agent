from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .codec import model_from_dict
from .domain import (
    AggregateNode, BacktrackLink, ContextVisModel, SalientInfo, SemanticUnit,
    SpanRef, SummarySentence, Turn, validate_model,
)
from .repository import ContextVisRepository

CONSTRAINT_RE = re.compile(r"(?:必须|不要|始终|禁止|务必|不得|请勿|must\b|never\b|always\b|do not\b|don't\b)", re.I)


def _turn_payload(turns: list[Turn]) -> str:
    return json.dumps([{"turn_id": t.turn_id, "role": t.role, "content": t.content} for t in turns], ensure_ascii=False)


def _turn_batches(turns: list[Turn], max_chars: int = 60_000) -> list[list[Turn]]:
    batches: list[list[Turn]] = []
    current: list[Turn] = []
    size = 0
    for turn in turns:
        turn_size = len(turn.content) + 200
        if current and size + turn_size > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(turn)
        size += turn_size
    if current:
        batches.append(current)
    return batches


def _without_markdown_decorators(text: str) -> tuple[str, list[int]]:
    """Return text normalized for quote matching plus raw offsets.

    LLMs frequently copy rendered text rather than the literal source: inline
    Markdown decorators disappear (``**label**: `value``` becomes
    ``label: value``) and hard line wraps inside prose are quoted as a single
    space (``no such\\nproblem`` becomes ``no such problem``). Both defeat an
    exact ``str.find``. Strip decorators and fold whitespace runs into one
    space; the offset map lets quote resolution still produce a SpanRef into
    the immutable raw transcript rather than into a normalized copy.
    """
    normalized: list[str] = []
    raw_offsets: list[int] = []
    for index, char in enumerate(text):
        if char in {"*", "`"}:
            continue
        if char.isspace():
            if normalized and normalized[-1] == " ":
                continue
            normalized.append(" ")
        else:
            normalized.append(char)
        raw_offsets.append(index)
    return "".join(normalized), raw_offsets


def _resolve_quote(turn: Turn, quote: str, start_hint: int | None = None) -> SpanRef:
    if not quote:
        raise ValueError("empty source quote")
    if start_hint is not None and turn.content[start_hint:start_hint + len(quote)] == quote:
        return SpanRef(turn.turn_id, start_hint, start_hint + len(quote))
    first = turn.content.find(quote)
    if first < 0:
        normalized_content, raw_offsets = _without_markdown_decorators(turn.content)
        normalized_quote, _ = _without_markdown_decorators(quote)
        normalized_first = normalized_content.find(normalized_quote)
        if (
            normalized_quote
            and normalized_first >= 0
            and normalized_content.find(normalized_quote, normalized_first + 1) < 0
        ):
            raw_start = raw_offsets[normalized_first]
            raw_end = raw_offsets[normalized_first + len(normalized_quote) - 1] + 1
            return SpanRef(turn.turn_id, raw_start, raw_end)
        raise ValueError(f"source quote is absent from turn {turn.turn_id}: {quote!r}")
    if turn.content.find(quote, first + 1) >= 0:
        raise ValueError(
            f"source quote is ambiguous in turn {turn.turn_id}; provide a valid char_start: {quote!r}"
        )
    return SpanRef(turn.turn_id, first, first + len(quote))


class ContextVisService:
    def __init__(self, adapter: Any, repository: ContextVisRepository):
        self.adapter = adapter
        self.repo = repository

    def load(self) -> tuple[ContextVisModel, list[Turn], str | None]:
        transcript = self.adapter.get_full_transcript()
        raw, last = self.repo.load(self.adapter.session_id)
        model = model_from_dict(raw)
        model.tier = self.adapter.tier
        model.legacy_transcript_warning = self.adapter.legacy_warning
        return model, transcript, last

    def generate_units(self, incremental: bool) -> dict[str, Any]:
        model, transcript, last = self.load()
        if incremental and last:
            ids = [t.turn_id for t in transcript]
            turns = transcript[ids.index(last) + 1:] if last in ids else transcript
        else:
            if model.units and not incremental:
                raise ValueError("semantic units already exist; use incremental update")
            turns = transcript
        if not turns:
            return model.to_dict()
        new_units: list[SemanticUnit] = []
        for batch in _turn_batches(turns):
            base_prompt = f"""Split the transcript into topic/task-coherent semantic units. Do not infer intent, abandonment, or backtracking. Preserve turn order and cover every supplied turn exactly once. Titles must be at most 15 characters. Each short summary sentence needs one or more exact verbatim source quotes.
For every source, copy quote directly from the specified turn. The quote should be long enough to occur exactly once in that turn. Also return char_start, the zero-based Python character offset where quote begins; it is required when the same quote occurs more than once.
Return JSON: {{"units":[{{"title":"...","covered_turn_ids":["..."],"summary_sentences":[{{"text":"...","sources":[{{"turn_id":"...","quote":"exact substring","char_start":0}}]}}]}}]}}.
TRANSCRIPT_JSON:\n{_turn_payload(batch)}"""
            turn_map = {t.turn_id: t for t in batch}
            last_error: Exception | None = None
            previous_response: str | None = None
            for attempt in range(2):
                batch_units = []
                prompt = base_prompt
                if attempt:
                    prompt += (
                        f"\nYour previous response was invalid: {last_error}."
                        " Correct that JSON; do not repeat an absent quote. Use a longer exact quote or a valid char_start"
                        " when a quote repeats, and keep coverage exact."
                        f"\nPREVIOUS_RESPONSE_JSON:\n{previous_response}"
                    )
                # Transport/provider failures are not semantic-response failures.
                # Let the job fail promptly instead of multiplying a full request
                # timeout by the semantic validation retry budget.
                previous_response = self.adapter.llm_complete(prompt)
                try:
                    raw = json.loads(previous_response)
                    for item in raw.get("units", []):
                        covered = item.get("covered_turn_ids") or []
                        if not covered or any(t not in turn_map for t in covered):
                            raise ValueError("LLM returned unknown or empty covered turns")
                        sentences = []
                        for sentence in item.get("summary_sentences", []):
                            spans = [_resolve_quote(turn_map[src["turn_id"]], src["quote"], src.get("char_start")) for src in sentence.get("sources", [])]
                            sentences.append(SummarySentence(sentence["text"].strip(), spans))
                        batch_units.append(SemanticUnit(
                            unit_id=f"unit-{uuid.uuid4().hex}", title=str(item.get("title", ""))[:15],
                            summary_sentences=sentences, covered_turns=covered, frozen=True,
                            created_at_turn=batch[-1].turn_id,
                        ))
                    if [tid for unit in batch_units for tid in unit.covered_turns] != [t.turn_id for t in batch]:
                        raise ValueError("LLM unit coverage must exactly match the supplied transcript")
                    break
                except Exception as exc:
                    last_error = exc
            else:
                raise ValueError(f"semantic unit response remained invalid after retry: {last_error}")
            new_units.extend(batch_units)
        model.units.extend(new_units)
        if model.aggregates:
            model.aggregates.append(AggregateNode(f"aggregate-{uuid.uuid4().hex}", "New conversation", [u.unit_id for u in new_units]))
        if model.decision_aggregates:
            model.decision_aggregates.append(AggregateNode(
                f"aggregate-{uuid.uuid4().hex}", "New conversation",
                [u.unit_id for u in new_units], intent_tag=model.decision_intent,
            ))
        validate_model(model, transcript)
        revision = self.repo.save(self.adapter.session_id, model.to_dict(), transcript[-1].turn_id)
        model.revision = revision
        return model.to_dict()

    def detect_salient(self) -> dict[str, Any]:
        model, transcript, last = self.load()
        turns = {t.turn_id: t for t in transcript}
        for unit in model.units:
            reliable: list[SalientInfo] = []
            for tid in unit.covered_turns:
                turn = turns[tid]
                if turn.role not in {"user", "tool"}:
                    continue
                for line_match in re.finditer(r"[^。.!?\n]+[。.!?]?", turn.content):
                    text = line_match.group(0).strip()
                    if text and CONSTRAINT_RE.search(text):
                        start = turn.content.find(text, line_match.start())
                        reliable.append(SalientInfo(
                            info_id=f"info-{uuid.uuid4().hex}",
                            kind="user_stated_constraint" if turn.role == "user" else "tool_output_constraint",
                            detected_text=text, span_in_B=SpanRef(tid, start, start + len(text)), confidence="reliable",
                        ))
            unit.salient_infos = reliable
        prompt = f"""Find only subtle high-impact constraints or rules missed by obvious imperative keywords. It is acceptable to return none. Every result must be an exact quote.
Return JSON: {{"items":[{{"turn_id":"...","quote":"exact substring","kind":"other"}}]}}.
TRANSCRIPT_JSON:\n{_turn_payload(transcript)}"""
        guessed = json.loads(self.adapter.llm_complete(prompt, max_tokens=3000)).get("items", [])
        unit_by_turn = {tid: unit for unit in model.units for tid in unit.covered_turns}
        for item in guessed:
            turn = turns.get(item.get("turn_id"))
            unit = unit_by_turn.get(item.get("turn_id"))
            if not turn or not unit:
                continue
            try:
                span = _resolve_quote(turn, item.get("quote", ""))
            except ValueError:
                continue
            if any(i.detected_text == item["quote"] and i.span_in_B == span for i in unit.salient_infos):
                continue
            unit.salient_infos.append(SalientInfo(
                info_id=f"info-{uuid.uuid4().hex}", kind="other", detected_text=item["quote"],
                span_in_B=span, confidence="ai_guessed",
            ))
        validate_model(model, transcript)
        model.revision = self.repo.save(self.adapter.session_id, model.to_dict(), last)
        return model.to_dict()

    def draft_aggregates(self, mode: str, intent: str | None) -> dict[str, Any]:
        model, transcript, last = self.load()
        if not model.units:
            raise ValueError("generate semantic units first")
        if mode == "decision" and not (intent or "").strip():
            raise ValueError("decision aggregation requires an intent")
        units = [{"unit_id": u.unit_id, "title": u.title, "summary": [s.text for s in u.summary_sentences]} for u in model.units]
        cap = "Create at most 8 nodes." if mode == "overview" else "Use uneven detail according to the stated intent; no node cap."
        prompt = f"""Group the ordered semantic units into consecutive, non-overlapping nodes that cover every unit exactly once. {cap}
Intent: {intent or 'none'}
Return JSON: {{"nodes":[{{"title":"...","child_unit_ids":["..."]}}]}}.
UNITS_JSON:\n{json.dumps(units, ensure_ascii=False)}"""
        raw = json.loads(self.adapter.llm_complete(prompt, max_tokens=3000))
        nodes = [AggregateNode(f"aggregate-{uuid.uuid4().hex}", str(n.get("title", ""))[:30], n.get("child_unit_ids", []), "llm_draft", intent if mode == "decision" else None) for n in raw.get("nodes", [])]
        expected = [u.unit_id for u in model.units]
        if [uid for n in nodes for uid in n.child_unit_ids] != expected or (mode == "overview" and len(nodes) > 8):
            raise ValueError("aggregate draft must be an ordered partition of all units")
        if mode == "overview": model.aggregates = nodes
        else:
            model.decision_aggregates = nodes
            model.decision_intent = intent
        validate_model(model, transcript)
        model.revision = self.repo.save(self.adapter.session_id, model.to_dict(), last)
        return model.to_dict()

    def save_edits(self, payload: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        model, transcript, last = self.load()
        for field in ("aggregates", "decision_aggregates"):
            if field in payload:
                setattr(model, field, [AggregateNode(**{**n, "origin": "user_edited"}) for n in payload[field]])
        if "decision_intent" in payload:
            model.decision_intent = payload["decision_intent"]
        if "backlinks" in payload:
            model.backlinks = [BacktrackLink(**b) for b in payload["backlinks"]]
        validate_model(model, transcript)
        model.revision = self.repo.save(self.adapter.session_id, model.to_dict(), last, expected_revision)
        return model.to_dict()
