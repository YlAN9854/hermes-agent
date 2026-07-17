"""Agent-neutral Tier 2 survival comparison.

Hermes V1 advertises Tier 1 until an event probe exists, so this module is
deliberately not called by the Hermes adapter yet. It is kept pure for future
adapters that can supply an actual active-context snapshot.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .domain import ContextVisModel, Turn


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def update_survival(model: ContextVisModel, transcript: list[Turn], active: list[Turn] | None) -> None:
    if model.tier < 2 or active is None:
        for unit in model.units:
            for info in unit.salient_infos:
                info.status_in_A = "unknown"
                info.reframed_text_in_A = None
        return
    truth = {t.turn_id: t for t in transcript}
    active_texts = [_normalise(t.content) for t in active]
    for unit in model.units:
        for info in unit.salient_infos:
            source = truth.get(info.span_in_B.turn_id)
            original = source.content[info.span_in_B.char_start:info.span_in_B.char_end] if source else info.detected_text
            needle = _normalise(original)
            if any(needle and needle in text for text in active_texts):
                info.status_in_A, info.reframed_text_in_A = "present", None
                continue
            candidate = max(active_texts, key=lambda text: SequenceMatcher(None, needle, text).ratio(), default="")
            if candidate and SequenceMatcher(None, needle, candidate).ratio() >= 0.62:
                info.status_in_A, info.reframed_text_in_A = "reframed", candidate
            else:
                info.status_in_A, info.reframed_text_in_A = "absent", None
