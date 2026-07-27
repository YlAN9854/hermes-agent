"""Negative regression: ordinary user text must not be misclassified as a
merged-summary carrier.

Gate review blocker T4-P2-NO-FALSE-BOUNDARY-ON-USER-TEXT:
``_split_merged_summary_text`` previously matched any text containing the
delimiter followed by a summary prefix, causing ``_strip_summary_prefix``
and ``_is_context_summary_content`` to misclassify ordinary user content
quoting those patterns.

These tests verify that user text containing the delimiter + prefix
combination is treated verbatim — not stripped, not detected as a summary.
Positive tests verify that legitimate merged carriers still work.
"""

import pytest

from agent.context_compressor import (
    LEGACY_SUMMARY_PREFIX,
    SUMMARY_PREFIX,
    ContextCompressor,
    _HISTORICAL_SUMMARY_PREFIXES,
    _MERGED_PRIOR_CONTEXT_HEADER,
    _MERGED_SUMMARY_DELIMITER,
    _SUMMARY_END_MARKER,
    _split_merged_summary_text,
)


# ---------------------------------------------------------------------------
# _split_merged_summary_text: the helper itself
# ---------------------------------------------------------------------------


def test_split_returns_none_for_plain_user_text():
    """User text with no delimiter returns None."""
    assert _split_merged_summary_text("Hello, this is a normal message.") is None


def test_split_returns_none_for_text_without_prefix_after_delimiter():
    """Delimiter present but no summary prefix after it → no match."""
    text = f"Some text {_MERGED_SUMMARY_DELIMITER} and then just more text"
    assert _split_merged_summary_text(text) is None


def test_split_detects_real_merged_carrier_text():
    """A real merged carrier (header + old content + delimiter + summary) is detected."""
    summary_body = f"{SUMMARY_PREFIX}\nThe user asked about X."
    text = (
        f"{_MERGED_PRIOR_CONTEXT_HEADER}\n"
        f"Old tail content here.\n\n"
        f"{_MERGED_SUMMARY_DELIMITER}\n\n"
        f"{summary_body}"
    )
    result = _split_merged_summary_text(text)
    assert result is not None
    prior, summary = result
    assert "Old tail content here." in prior
    assert summary.startswith(SUMMARY_PREFIX)


# ---------------------------------------------------------------------------
# _strip_summary_prefix: must NOT strip ordinary user text
# ---------------------------------------------------------------------------


class TestStripSummaryPrefixFalseBoundary:
    """_strip_summary_prefix must leave ordinary user text verbatim."""

    @pytest.mark.parametrize(
        "prefix_label,prefix",
        [
            ("current", SUMMARY_PREFIX),
            ("legacy", LEGACY_SUMMARY_PREFIX),
            *[
                (f"historical_{i}", p)
                for i, p in enumerate(_HISTORICAL_SUMMARY_PREFIXES)
            ],
        ],
        ids=lambda x: x if isinstance(x, str) else "",
    )
    def test_user_text_quoting_delimiter_and_prefix_is_untouched(
        self, prefix_label, prefix
    ):
        """User content quoting the delimiter + any summary prefix must pass through."""
        user_text = (
            f"I found this pattern in the code:\n"
            f"{_MERGED_SUMMARY_DELIMITER}\n"
            f"{prefix}\n"
            f"THIS IS QUOTED USER TEXT"
        )
        result = ContextCompressor._strip_summary_prefix(user_text)
        # The text must NOT be stripped — it should survive verbatim
        # (whitespace normalization is acceptable, content loss is not).
        assert "THIS IS QUOTED USER TEXT" in result
        assert "I found this pattern in the code" in result
        # The delimiter should still be present (not split out).
        assert _MERGED_SUMMARY_DELIMITER in result

    def test_user_text_with_only_delimiter_no_prefix_is_untouched(self):
        """Delimiter without a following prefix is never a carrier."""
        user_text = f"Just mentioning {_MERGED_SUMMARY_DELIMITER} in passing."
        result = ContextCompressor._strip_summary_prefix(user_text)
        assert result == user_text.strip()

    def test_legitimate_merged_carrier_is_still_stripped(self):
        """A real merged-carrier text (starting with the header) IS stripped."""
        summary_body = f"{SUMMARY_PREFIX}\nCompact summary of prior work."
        carrier_text = (
            f"{_MERGED_PRIOR_CONTEXT_HEADER}\n"
            f"Old tail content.\n\n"
            f"{_MERGED_SUMMARY_DELIMITER}\n\n"
            f"{summary_body}\n\n"
            f"{_SUMMARY_END_MARKER}"
        )
        result = ContextCompressor._strip_summary_prefix(carrier_text)
        # The summary body should survive; header + old content + delimiter should be gone.
        assert "Compact summary of prior work." in result
        assert _MERGED_PRIOR_CONTEXT_HEADER not in result
        assert "Old tail content." not in result
        # The end marker is also stripped.
        assert _SUMMARY_END_MARKER not in result

    def test_standalone_summary_is_still_stripped(self):
        """A standalone summary (starting directly with the prefix) is stripped."""
        text = f"{SUMMARY_PREFIX}\nThis is a standalone summary body."
        result = ContextCompressor._strip_summary_prefix(text)
        assert "This is a standalone summary body." in result
        assert SUMMARY_PREFIX not in result


# ---------------------------------------------------------------------------
# _is_context_summary_content: must NOT detect ordinary user text
# ---------------------------------------------------------------------------


class TestIsContextSummaryContentFalseBoundary:
    """_is_context_summary_content must not flag ordinary user turns."""

    @pytest.mark.parametrize(
        "prefix_label,prefix",
        [
            ("current", SUMMARY_PREFIX),
            ("legacy", LEGACY_SUMMARY_PREFIX),
            *[
                (f"historical_{i}", p)
                for i, p in enumerate(_HISTORICAL_SUMMARY_PREFIXES)
            ],
        ],
        ids=lambda x: x if isinstance(x, str) else "",
    )
    def test_user_text_quoting_delimiter_and_prefix_is_not_summary(
        self, prefix_label, prefix
    ):
        """User content quoting delimiter + prefix is NOT a context summary."""
        user_text = (
            f"Let me quote this pattern:\n"
            f"{_MERGED_SUMMARY_DELIMITER}\n"
            f"{prefix}\n"
            f"End of quote."
        )
        assert ContextCompressor._is_context_summary_content(user_text) is False

    def test_user_text_with_delimiter_only_is_not_summary(self):
        """Delimiter without a following prefix is not a summary."""
        user_text = f"I noticed the marker {_MERGED_SUMMARY_DELIMITER} in the output."
        assert ContextCompressor._is_context_summary_content(user_text) is False

    def test_legitimate_merged_carrier_is_detected(self):
        """A real merged-carrier message IS detected as a context summary."""
        carrier_text = (
            f"{_MERGED_PRIOR_CONTEXT_HEADER}\n"
            f"Old tail content here.\n\n"
            f"{_MERGED_SUMMARY_DELIMITER}\n\n"
            f"{SUMMARY_PREFIX}\nSummary body."
        )
        assert ContextCompressor._is_context_summary_content(carrier_text) is True

    def test_standalone_summary_is_detected(self):
        """A standalone summary (starting with prefix) IS detected."""
        assert ContextCompressor._is_context_summary_content(
            f"{SUMMARY_PREFIX}\nSummary body."
        ) is True

    def test_legacy_standalone_summary_is_detected(self):
        """A legacy-format standalone summary IS detected."""
        assert ContextCompressor._is_context_summary_content(
            f"{LEGACY_SUMMARY_PREFIX}\nLegacy summary."
        ) is True

    def test_plain_user_text_is_not_summary(self):
        """Ordinary user text with no markers is not a summary."""
        assert ContextCompressor._is_context_summary_content(
            "Please help me with this task."
        ) is False

    def test_multimodal_list_user_content_is_not_summary(self):
        """A multimodal content list with user text is not a summary."""
        content = [
            {"type": "text", "text": f"Here is a reference: {_MERGED_SUMMARY_DELIMITER}"},
            {"type": "text", "text": f"{SUMMARY_PREFIX}"},
            {"type": "text", "text": "But this is all just user discussion."},
        ]
        assert ContextCompressor._is_context_summary_content(content) is False
