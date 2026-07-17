import type { ContextVisSpan } from "./api";

export function buildHighlightSegments(content: string, spans: ContextVisSpan[], turnId: string) {
  const relevant = spans.filter((s) => s.turn_id === turnId).sort((a, b) => a.char_start - b.char_start);
  if (!relevant.length) return [{ text: content, highlighted: false }];
  const parts: Array<{ text: string; highlighted: boolean }> = [];
  let cursor = 0;
  relevant.forEach((span) => {
    if (span.char_start > cursor) parts.push({ text: content.slice(cursor, span.char_start), highlighted: false });
    parts.push({ text: content.slice(span.char_start, span.char_end), highlighted: true });
    cursor = Math.max(cursor, span.char_end);
  });
  if (cursor < content.length) parts.push({ text: content.slice(cursor), highlighted: false });
  return parts;
}
