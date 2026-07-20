"""Optional dump of compaction boundaries, for offline context analysis.

Disabled unless ``HERMES_CONTEXT_VIS_PROBE`` is set. When enabled, each
completed compaction appends one JSONL record under HERMES_HOME describing
which transcript turns survived, which were dropped, and the summary text
that replaced them.

Only turn ids and the summary are recorded, never message bodies: the bodies
are already in state.db, addressable by the ids recorded here, and copying
them would duplicate the durable transcript. The summary is the one artefact
a later compaction can supersede beyond recovery, so it is kept in full.

This module must not import anything from the consumer that reads its output
-- it is a generic dump, and readers are on their own side of the boundary.
Marker strings are re-declared locally rather than imported from
``context_compressor`` for the same reason: a local copy that falls back to
the whole message body degrades safely if the markers change upstream.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

ENV_FLAG = "HERMES_CONTEXT_VIS_PROBE"
RECORD_VERSION = 1
SUMMARY_CHAR_CAP = 64_000
MAX_FILE_BYTES = 8 * 1024 * 1024

_TRANSCRIPT_TURN_ID = "_transcript_turn_id"
_COMPRESSED_SUMMARY = "_compressed_summary"

# Local copies; see the module docstring for why these are not imported.
_SUMMARY_START_MARKERS = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]",
    "[CONTEXT COMPACTION - REFERENCE ONLY]",
    "[CONTEXT SUMMARY]:",
    "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]",
    "[END OF PRIOR CONTEXT - COMPACTION SUMMARY BELOW]",
)
_SUMMARY_END_MARKERS = (
    "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---",
    "--- END OF CONTEXT SUMMARY - respond to the message below, not the summary above ---",
)


def is_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("text"))
    return str(content or "")


def _turn_ids(messages: Sequence[Mapping[str, Any]]) -> tuple[list[str], int]:
    """Return (ordered turn ids, count of messages carrying no id)."""
    ids: list[str] = []
    unlinked = 0
    for message in messages:
        turn_id = message.get(_TRANSCRIPT_TURN_ID)
        if turn_id:
            ids.append(str(turn_id))
        else:
            unlinked += 1
    return ids, unlinked


def _extract_summary(messages: Sequence[Mapping[str, Any]]) -> str | None:
    """Pull the compaction summary out of the post-compaction messages.

    Handles both shapes the compressor emits: a standalone summary message,
    and a summary concatenated into the first surviving tail message (which
    keeps its own transcript id, so the summary must be sliced back out).
    """
    for message in messages:
        if not message.get(_COMPRESSED_SUMMARY):
            continue
        content = _text(message.get("content"))
        if not content:
            continue
        if message.get(_TRANSCRIPT_TURN_ID):
            for marker in _SUMMARY_START_MARKERS:
                index = content.find(marker)
                if index >= 0:
                    content = content[index:]
                    break
        for marker in _SUMMARY_END_MARKERS:
            index = content.find(marker)
            if index >= 0:
                content = content[:index]
                break
        return content.strip()
    return None


def _probe_dir() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()) / "context-vis" / "compaction"


def _rotate_if_large(path: Path) -> None:
    if path.exists() and path.stat().st_size >= MAX_FILE_BYTES:
        path.replace(path.with_suffix(path.suffix + ".1"))


def record_compaction(
    *,
    session_id: str,
    boundary_parent_session_id: str,
    in_place: bool,
    messages_before: Sequence[Mapping[str, Any]],
    messages_after: Sequence[Mapping[str, Any]],
    compression_count: int,
) -> None:
    """Append one compaction record. No-ops when disabled. Never raises."""
    try:
        if not is_enabled():
            return
        before_ids, unlinked_before = _turn_ids(messages_before)
        after_ids, unlinked_after = _turn_ids(messages_after)
        summary = _extract_summary(messages_after)
        truncated = bool(summary and len(summary) > SUMMARY_CHAR_CAP)
        record = {
            "v": RECORD_VERSION,
            "event_id": f"cvce-{uuid.uuid4().hex}",
            "ts": time.time(),
            "session_id": session_id,
            "boundary_parent_session_id": boundary_parent_session_id or session_id,
            "in_place": bool(in_place),
            "compression_count": int(compression_count),
            "before_turn_ids": before_ids,
            "after_turn_ids": after_ids,
            "before_count": len(messages_before),
            "after_count": len(messages_after),
            "unlinked_before": unlinked_before,
            "unlinked_after": unlinked_after,
            "summary_text": summary[:SUMMARY_CHAR_CAP] if summary else None,
            "summary_truncated": truncated,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        directory = _probe_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record['boundary_parent_session_id']}.jsonl"
        _rotate_if_large(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except BaseException as exc:  # never break a compaction
        logger.debug("compaction probe skipped: %s", exc)
