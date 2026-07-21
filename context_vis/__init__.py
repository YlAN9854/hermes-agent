"""Agent-neutral semantic index for long conversation transcripts."""

from .domain import (
    ActiveContext, ActiveEntry, CompressionEvent, ContextVisModel, PreserveResult,
    SpanRef, SurvivalState, Turn,
)

__all__ = [
    "ActiveContext", "ActiveEntry", "CompressionEvent", "ContextVisModel",
    "PreserveResult", "SpanRef", "SurvivalState", "Turn",
]
