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
# Calibrated on genuine reframings (0.38-0.90) against unrelated text
# (0.0-0.41, the non-zero ones being character noise such as "and the ").
# 0.50 rejects every measured false match, at the cost of missing the most
# heavily reworded paraphrase. The asymmetry is deliberate per 铁律 6: a false
# "reframed" tells the user the model still knows a constraint when it does
# not, whereas a false "absent" merely under-claims.
REFRAME_MATCH_THRESHOLD = 0.50

# Matching text must cover this fraction of the constraint before a fragment is
# scored at all: a cheap reject that stops a handful of shared stopwords from
# manufacturing a "reframing". Measured over ALL common blocks, not just the
# longest: a heavily reworded paraphrase matches in several short runs, and
# gating on the longest run alone rejected genuine reframings.
MIN_ANCHOR_COVERAGE = 0.35

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


def _best_fragment(needle: str, entry_norm: str, offsets: list[int], raw: str) -> tuple[float, str]:
    """Score the best window of ``entry_norm`` against ``needle``.

    Returns (score, raw_fragment). ``autojunk=False`` is load-bearing: the
    default treats any character appearing in >1% of a >=200-char haystack as
    junk, which for prose silently discards spaces and most vowels.
    """
    matcher = SequenceMatcher(None, needle, entry_norm, autojunk=False)
    blocks = matcher.get_matching_blocks()
    if sum(block.size for block in blocks) < MIN_ANCHOR_COVERAGE * len(needle):
        return 0.0, ""
    # The longest block positions the window even though the gate above spans
    # all of them: it is the most reliable centre for the restated text.
    anchor = max(blocks, key=lambda block: block.size)
    width = max(int(len(needle) * FRAGMENT_WINDOW_SCALE), anchor.size)
    centre = anchor.b + anchor.size // 2
    best_score, best_bounds = 0.0, None
    for shift in (0, -width // 4, width // 4):
        low = max(0, min(centre + shift - width // 2, len(entry_norm) - 1))
        high = min(len(entry_norm), low + width)
        if high <= low:
            continue
        score = SequenceMatcher(None, needle, entry_norm[low:high], autojunk=False).ratio()
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
