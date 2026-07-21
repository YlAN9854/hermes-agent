from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from typing import Any

from .codec import model_from_dict
from .domain import (
    ActiveContext, AggregateNode, BacktrackLink, ContextVisModel, SalientInfo, SemanticUnit,
    SpanRef, SummarySentence, SurvivalState, Turn, validate_model,
)
from .repository import ContextVisRepository
from .survival import update_survival

CONSTRAINT_RE = re.compile(r"(?:必须|不要|不能|始终|禁止|务必|不得|绝不|切勿|请勿|must\b|never\b|always\b|do not\b|don't\b)", re.I)

# CJK enders (including the full-width semicolon ；, which separates clauses
# in enumerations like "第一，…；第二，…") always break. The full-width form is
# Chinese punctuation and never appears in code, so it is safe here; the ASCII
# ";" is left out because it is common in code and logs. ASCII enders count
# only before whitespace/EOL so decimals and version numbers ("Python 3.10")
# stay inside one sentence.
_SENTENCE_BREAK_RE = re.compile(r"(?<=[。！？；])|(?<=[.!?])(?=\s|$)")


def _constraint_sentences(content: str):
    """Yield (char_offset, text) sentence fragments of a turn's content."""
    line_start = 0
    for line in content.split("\n"):
        offset = 0
        for fragment in _SENTENCE_BREAK_RE.split(line):
            stripped = fragment.strip()
            if stripped:
                yield line_start + offset + (len(fragment) - len(fragment.lstrip())), stripped
            offset += len(fragment)
        line_start += len(line) + 1


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


def _spans_overlap(a: SpanRef, b: SpanRef) -> bool:
    return a.turn_id == b.turn_id and a.char_start < b.char_end and b.char_start < a.char_end


def _norm_salient_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _clamp_title(raw: Any, max_width: int = 30) -> str:
    """Clamp a title by display width (CJK=2, Latin=1) without mid-word cuts.

    The spec's "≤15 字" cap is CJK-oriented; 15 Latin characters hold only two
    or three words, and a blind ``[:15]`` slice cut English titles mid-word.
    """
    title = " ".join(str(raw).split())
    if sum(_char_width(char) for char in title) <= max_width:
        return title
    kept: list[str] = []
    width = 0
    for char in title:
        if width + _char_width(char) > max_width - 1:
            if char.isalnum() and kept and kept[-1].isalnum() and " " in kept:
                while kept and kept[-1] != " ":
                    kept.pop()
            break
        kept.append(char)
        width += _char_width(char)
    return "".join(kept).rstrip() + "…"


def _resolve_quote(turn: Turn, quote: str, start_hint: int | None = None, allow_ambiguous_first: bool = False) -> SpanRef:
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
        # Every occurrence of an identical quote carries the same evidence
        # text; on the retry attempt, anchoring to the first occurrence beats
        # failing the whole batch over an unattainable char_start.
        if allow_ambiguous_first:
            return SpanRef(turn.turn_id, first, first + len(quote))
        raise ValueError(
            f"source quote is ambiguous in turn {turn.turn_id}; provide a valid char_start: {quote!r}"
        )
    return SpanRef(turn.turn_id, first, first + len(quote))


def active_fingerprint(active: ActiveContext | None) -> str:
    """Cheap identity of A, so stored statuses can be told apart from stale ones."""
    if active is None:
        return ""
    digest = hashlib.sha256()
    for entry in active.entries:
        digest.update(entry.content.encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()


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

    def _active(self) -> ActiveContext | None:
        """A, or None for a Tier 1 adapter that does not implement it.

        Spec §1 requires only get_full_transcript + llm_complete of a Tier 1
        adapter, so the Tier 2 methods may legitimately be absent.
        """
        getter = getattr(self.adapter, "get_active_context", None)
        return getter() if callable(getter) else None

    def _events(self) -> list[Any]:
        getter = getattr(self.adapter, "get_compression_events", None)
        return list(getter()) if callable(getter) else []

    def survival_is_stale(self, model: ContextVisModel) -> bool:
        """Whether stored statuses were computed against a different A.

        Read-side only: recomputing here would persist on every GET, bumping
        the revision under the user and turning their next save into a 409.
        """
        if not any(unit.salient_infos for unit in model.units):
            return False
        if model.tier < 2:
            return False
        if model.survival is None:
            return True
        return model.survival.active_fingerprint != active_fingerprint(self._active())

    def _apply_survival(self, model: ContextVisModel, transcript: list[Turn]) -> None:
        active = self._active()
        events = self._events()
        update_survival(model, transcript, active)
        reconstructed = [e for e in events if e.fidelity == "reconstructed"]
        model.survival = SurvivalState(
            computed_at=time.time(),
            fidelity=(active.fidelity if active else None),
            event_count=len(events),
            active_fingerprint=active_fingerprint(active),
            note=(
                f"{len(reconstructed)} of {len(events)} compaction(s) were reconstructed from archived "
                "rows rather than observed, so their boundaries are approximate."
                if reconstructed else None
            ),
        )

    def refresh_survival(self) -> dict[str, Any]:
        model, transcript, last = self.load()
        self._apply_survival(model, transcript)
        validate_model(model, transcript)
        model.revision = self.repo.save(self.adapter.session_id, model.to_dict(), last)
        return model.to_dict()

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
            base_prompt = f"""Split the transcript into topic/task-coherent semantic units. Do not infer intent, abandonment, or backtracking. Preserve turn order and cover every supplied turn exactly once. A unit spans one complete task or topic arc — including its attempts, results, and follow-up fixes. Open a new unit when the work moves to a different sub-goal, component, bug, or deliverable, even within the same overall project; do not open one merely because the same piece of work advances a step. A typical unit covers roughly 3-12 consecutive turns; one unit per turn and one unit spanning a whole long transcript are both wrong. Titles must be short: at most 15 CJK characters, or about four words for Latin text. Each summary sentence must be short and state exactly one fact; put separate facts in separate sentences, and give every sentence source quotes covering each claim it makes.
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
                            spans = [
                                _resolve_quote(turn_map[src["turn_id"]], src["quote"], src.get("char_start"), allow_ambiguous_first=bool(attempt))
                                for src in sentence.get("sources", [])
                            ]
                            sentences.append(SummarySentence(sentence["text"].strip(), spans))
                        batch_units.append(SemanticUnit(
                            unit_id=f"unit-{uuid.uuid4().hex}", title=_clamp_title(item.get("title", "")),
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
        new_units = self._merge_pass(new_units)
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

    def _merge_pass(self, units: list[SemanticUnit]) -> list[SemanticUnit]:
        """Merge adjacent same-topic units among the freshly generated ones.

        Batch-wise generation cannot see across batch boundaries and tends to
        fragment long sessions. Merging afterwards is safe: it only touches
        units created in this call (never previously frozen ones) and leaves
        every SpanRef untouched. The pass is an optimisation — any invalid
        merge response falls back to the unmerged units instead of failing.
        """
        if len(units) < 2:
            return units
        listing = [{"index": i, "title": u.title, "summary": [s.text for s in u.summary_sentences]} for i, u in enumerate(units)]
        prompt = f"""Below is an ordered list of semantic units summarising consecutive parts of one conversation. Merge adjacent units that belong to the same task or topic arc; keep units apart when the work moves to a different sub-goal, component, bug, or deliverable. Groups must be consecutive index runs covering every index exactly once, in order. Give every group a short title (at most 15 CJK characters, or about four words for Latin text).
Return JSON: {{"groups":[{{"indexes":[0,1],"title":"..."}}]}}.
UNITS_JSON:\n{json.dumps(listing, ensure_ascii=False)}"""
        try:
            raw = json.loads(self.adapter.llm_complete(prompt, max_tokens=3000))
            groups = [(list(g.get("indexes", [])), str(g.get("title", ""))) for g in raw.get("groups", [])]
        except Exception:
            return units
        if [i for indexes, _ in groups for i in indexes] != list(range(len(units))):
            return units
        merged: list[SemanticUnit] = []
        for indexes, title in groups:
            group = [units[i] for i in indexes]
            if len(group) == 1:
                merged.append(group[0])
                continue
            merged.append(SemanticUnit(
                unit_id=f"unit-{uuid.uuid4().hex}",
                title=_clamp_title(title or group[0].title),
                summary_sentences=[s for u in group for s in u.summary_sentences],
                covered_turns=[tid for u in group for tid in u.covered_turns],
                frozen=True,
                created_at_turn=group[-1].created_at_turn,
            ))
        return merged

    def detect_salient(self) -> dict[str, Any]:
        model, transcript, last = self.load()
        turns = {t.turn_id: t for t in transcript}
        # The same constraint text can occur at several places in B (repeated
        # tool warnings, restated rules). Keep the first occurrence only and
        # count the rest — span overlap cannot catch cross-position repeats.
        first_seen: dict[str, SalientInfo] = {}
        for unit in model.units:
            reliable: list[SalientInfo] = []
            for tid in unit.covered_turns:
                turn = turns[tid]
                if turn.role not in {"user", "tool"}:
                    continue
                for start, text in _constraint_sentences(turn.content):
                    if CONSTRAINT_RE.search(text):
                        earlier = first_seen.get(_norm_salient_text(text))
                        if earlier is not None:
                            earlier.occurrences += 1
                            continue
                        info = SalientInfo(
                            info_id=f"info-{uuid.uuid4().hex}",
                            kind="user_stated_constraint" if turn.role == "user" else "tool_output_constraint",
                            detected_text=text, span_in_B=SpanRef(tid, start, start + len(text)), confidence="reliable",
                        )
                        first_seen[_norm_salient_text(text)] = info
                        reliable.append(info)
            unit.salient_infos = reliable
        already_detected = [info.detected_text for u in model.units for info in u.salient_infos]
        prompt = f"""Find only subtle high-impact constraints or rules missed by obvious imperative keywords: implicit requirements, licensing/compliance limits, value whitelists, dependencies other work relies on. It is acceptable to return none. Every result must be an exact quote. Do not repeat or re-quote anything in ALREADY_DETECTED_JSON.
Return JSON: {{"items":[{{"turn_id":"...","quote":"exact substring","kind":"other"}}]}}.
ALREADY_DETECTED_JSON:\n{json.dumps(already_detected, ensure_ascii=False)}
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
            # Overlap, not equality: the exploratory pass often re-quotes a
            # reliable hit with slightly different bounds, which previously
            # slipped through dedup and inflated the ai_guessed count.
            if any(_spans_overlap(i.span_in_B, span) for i in unit.salient_infos):
                continue
            earlier = first_seen.get(_norm_salient_text(item["quote"]))
            if earlier is not None:
                earlier.occurrences += 1
                continue
            info = SalientInfo(
                info_id=f"info-{uuid.uuid4().hex}", kind="other", detected_text=item["quote"],
                span_in_B=span, confidence="ai_guessed",
            )
            first_seen[_norm_salient_text(item["quote"])] = info
            unit.salient_infos.append(info)
        # Compute statuses in the same save that creates the infos, so a fresh
        # detection is never shown as a full column of "unknown".
        self._apply_survival(model, transcript)
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
