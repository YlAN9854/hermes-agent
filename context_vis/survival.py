"""Agent-neutral Tier 2 survival comparison.

Decides, for each salient info, whether the constraint it captured is still
visible to the model: present verbatim in A, reframed (restated in different
words, typically inside a compaction summary), or absent.

The needle always comes from B via ``span_in_B`` — the truth layer — never
from the possibly-stale ``detected_text``. Matches found in A are stored as
plain text only: A is mutable, so no offset or pointer into it may be kept.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .domain import ActiveContext, ContextVisModel, Turn

# A reframing is accepted when the best-matching FRAGMENT of an active entry
# is at least this similar to the constraint. Scoring against whole entries is
# invalid: SequenceMatcher.ratio() is 2*M/T over the combined length, so a
# 43-char constraint inside a 2.8k-char summary scores ~0.02 even when the
# summary genuinely restates it. Fragment scoring restores the intended
# semantics.
#
# A window scores as the mean of two signals (see _window_score): character
# sequence similarity and token containment. Neither works alone. Sequence
# similarity alone fails on Chinese, where paraphrase reorders characters and
# leaves only short contiguous runs (a genuine restatement measured 0.36 while
# unrelated English text reached 0.44). Containment alone is weak on English,
# where shared stopwords inflate it. Blended, genuine reframings measured
# 0.51-0.82 and unrelated text 0.0-0.29 across both scripts, so 0.40 sits in
# the gap. Erring toward rejection is deliberate per 铁律 6: a false
# "reframed" tells the user the model still knows a constraint when it does
# not, whereas a false "absent" merely under-claims.
REFRAME_MATCH_THRESHOLD = 0.40

# Cheap whole-entry prefilter before the window scan: an entry sharing less
# than this fraction of the constraint's tokens cannot contain a restatement.
MIN_ENTRY_CONTAINMENT = 0.25

# Fragment window width, as a multiple of the constraint length.
FRAGMENT_WINDOW_SCALE = 1.6

# Constraints shorter than this are matched by containment only; fragment
# scoring on very short needles is noise.
MIN_FRAGMENT_NEEDLE_CHARS = 12

# Candidate entries kept by the cheap token prefilter before fragment scoring.
MAX_SCORED_CANDIDATES = 5

# Cap on the stored reframing, as a multiple of the constraint length, so the
# side-by-side view shows a comparable fragment rather than a wall of text.
MAX_REFRAME_SCALE = 4

# Latin/digit runs plus individual CJK characters, so the prefilter works for
# both scripts (``\w+`` alone would swallow a whole Chinese clause as one token).
_TOKEN_RE = re.compile(r"[a-z0-9]+|[^\W\s_]", re.UNICODE)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _normalise_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalise for matching while keeping a map back into the raw text.

    Same convention as ``service._without_markdown_decorators``: match on a
    normalised copy, but resolve results against the raw original. Whitespace
    runs collapse to one space and characters are casefolded; a casefold that
    expands to several characters maps all of them to the same raw index, so
    the offset list stays parallel to the normalised string.
    """
    normalised: list[str] = []
    offsets: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = bool(normalised)
            continue
        if pending_space:
            normalised.append(" ")
            offsets.append(index)
            pending_space = False
        for folded in char.casefold():
            normalised.append(folded)
            offsets.append(index)
    return "".join(normalised), offsets


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text))


def _snap_to_word_bounds(text: str, start: int, end: int, budget: int = 32) -> tuple[int, int]:
    """Grow a raw slice outward to whole words so it reads as a sentence."""
    limit = start - budget
    while start > 0 and start > limit and (text[start - 1].isalnum() or text[start - 1] in "-_"):
        start -= 1
    limit = end + budget
    while end < len(text) and end < limit and (text[end].isalnum() or text[end] in "-_"):
        end += 1
    return start, end


def _containment(needle_tokens: set[str], text: str) -> float:
    """Fraction of the constraint's tokens present in ``text``."""
    return len(needle_tokens & _tokens(text)) / len(needle_tokens) if needle_tokens else 0.0


def _window_score(needle: str, needle_tokens: set[str], window: str) -> float:
    """Blend character similarity with token containment. See the threshold note.

    ``autojunk=False`` is load-bearing: the default treats any character
    appearing in >1% of a >=200-char haystack as junk, which for prose
    silently discards spaces and most vowels.
    """
    sequence = SequenceMatcher(None, needle, window, autojunk=False).ratio()
    return (sequence + _containment(needle_tokens, window)) / 2


def _best_fragment(needle: str, entry_norm: str, offsets: list[int], raw: str) -> tuple[float, str]:
    """Score the best-matching window of ``entry_norm``. Returns (score, raw fragment)."""
    needle_tokens = _tokens(needle)
    if _containment(needle_tokens, entry_norm) < MIN_ENTRY_CONTAINMENT:
        return 0.0, ""
    width = max(int(len(needle) * FRAGMENT_WINDOW_SCALE), 1)
    step = max(1, len(needle) // 3)
    best_score, best_bounds = 0.0, None
    for low in range(0, max(len(entry_norm) - width, 0) + 1, step):
        high = min(len(entry_norm), low + width)
        if high <= low:
            continue
        score = _window_score(needle, needle_tokens, entry_norm[low:high])
        if score > best_score:
            best_score, best_bounds = score, (low, high)
    if best_bounds is None:
        return 0.0, ""
    low, high = best_bounds
    raw_start, raw_end = _snap_to_word_bounds(raw, offsets[low], offsets[high - 1] + 1)
    return best_score, raw[raw_start:raw_end]


def update_survival(model: ContextVisModel, transcript: list[Turn], active: ActiveContext | None) -> None:
    if model.tier < 2 or active is None:
        for unit in model.units:
            for info in unit.salient_infos:
                info.status_in_A = "unknown"
                info.reframed_text_in_A = None
        return
    truth = {t.turn_id: t for t in transcript}
    prepared = []
    for entry in active.entries:
        entry_norm, offsets = _normalise_with_offsets(entry.content)
        if entry_norm:
            prepared.append((entry_norm, offsets, entry.content, _tokens(entry_norm)))
    for unit in model.units:
        for info in unit.salient_infos:
            source = truth.get(info.span_in_B.turn_id)
            original = source.content[info.span_in_B.char_start:info.span_in_B.char_end] if source else info.detected_text
            needle = _normalise(original)
            if not needle:
                info.status_in_A, info.reframed_text_in_A = "absent", None
                continue
            # Verbatim in A — including verbatim inside a summary, which the
            # model genuinely still sees.
            if any(needle in entry_norm for entry_norm, _, _, _ in prepared):
                info.status_in_A, info.reframed_text_in_A = "present", None
                continue
            if len(needle) < MIN_FRAGMENT_NEEDLE_CHARS:
                info.status_in_A, info.reframed_text_in_A = "absent", None
                continue
            needle_tokens = _tokens(needle)
            candidates = sorted(
                (p for p in prepared if needle_tokens & p[3]),
                key=lambda p: len(needle_tokens & p[3]) / len(needle_tokens | p[3]),
                reverse=True,
            )[:MAX_SCORED_CANDIDATES]
            best_score, best_fragment = 0.0, ""
            for entry_norm, offsets, raw, _ in candidates:
                score, fragment = _best_fragment(needle, entry_norm, offsets, raw)
                if score > best_score:
                    best_score, best_fragment = score, fragment
            if best_score >= REFRAME_MATCH_THRESHOLD and best_fragment:
                info.status_in_A = "reframed"
                info.reframed_text_in_A = best_fragment[:MAX_REFRAME_SCALE * len(original)]
            else:
                info.status_in_A, info.reframed_text_in_A = "absent", None
