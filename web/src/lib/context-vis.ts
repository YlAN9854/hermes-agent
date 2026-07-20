import type { ContextVisInfo, ContextVisSpan } from "./api";

/** Roll up survival counts for a set of salient infos.
 *
 * Returns null below Tier 2, or when nothing has a known status, so callers
 * render nothing at all rather than a row of zeroes: with no compression
 * visibility, "0 reframed" would read as a finding rather than an absence
 * of data.
 */
export function summariseSurvival(infos: ContextVisInfo[], tier: number) {
  if (tier < 2) return null;
  const known = infos.filter((i) => i.status_in_A !== "unknown");
  if (!known.length) return null;
  return {
    total: known.length,
    present: known.filter((i) => i.status_in_A === "present").length,
    reframed: known.filter((i) => i.status_in_A === "reframed").length,
    absent: known.filter((i) => i.status_in_A === "absent").length,
  };
}

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
