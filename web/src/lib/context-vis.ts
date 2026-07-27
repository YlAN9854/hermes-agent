import type {
  ContextVisInfo,
  ContextVisIntentSegment,
  ContextVisSpan,
  ContextVisTurn,
  ContextVisUnit,
} from "./api";

export type ConversationMode = "transcript" | "model" | "live";

export interface LedgerRow {
  readonly info: ContextVisInfo;
  readonly unitId: string;
  readonly unitTitle: string;
}

export interface LedgerRows {
  readonly reliable: readonly LedgerRow[];
  readonly guessed: readonly LedgerRow[];
}

export type ModelTranscriptGroup =
  | { readonly kind: "live"; readonly turn: ContextVisTurn }
  | { readonly kind: "dead"; readonly turns: readonly ContextVisTurn[] };

export type IntentLaneRole = "start" | "mid" | "end" | "single";

export interface IntentLaneMark {
  readonly role: IntentLaneRole;
  readonly segment: ContextVisIntentSegment;
}

export type IntentValidationResult =
  | { readonly valid: true }
  | {
    readonly valid: false;
    readonly code:
      | "blank_id"
      | "blank_label"
      | "duplicate_id"
      | "unknown_unit"
      | "reversed_range"
      | "out_of_order"
      | "overlap";
    readonly message: string;
  };

export function assertNever(value: never): never {
  return value;
}

/** The most severe survival status among a set of infos, for coloring a unit's
 *  status rail. absent > reframed > present. Null below Tier 2 or when nothing
 *  is known — so a Tier 1 unit gets no status color, not a misleading "present". */
export function dominantSurvival(infos: ContextVisInfo[], tier: number): "present" | "reframed" | "absent" | null {
  if (tier < 2) return null;
  const known = new Set(infos.map((info) => info.status_in_A));
  if (known.has("absent")) return "absent";
  if (known.has("reframed")) return "reframed";
  if (known.has("present")) return "present";
  return null;
}

/** Whether any turn a unit covers is currently pinned against compaction. */
export function unitIsPinned(unit: ContextVisUnit, preserved: readonly string[]): boolean {
  if (!preserved.length) return false;
  const set = new Set(preserved);
  return unit.covered_turns.some((t) => set.has(t));
}

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

export function buildHighlightSegments(content: string, spans: readonly ContextVisSpan[], turnId: string) {
  const relevant = spans.filter((s) => s.turn_id === turnId).sort((a, b) => a.char_start - b.char_start);
  if (!relevant.length) return [{ text: content, highlighted: false }];
  const parts: Array<{ text: string; highlighted: boolean }> = [];
  let cursor = 0;
  relevant.forEach((span) => {
    if (span.char_start > cursor) parts.push({ text: sliceCodePoints(content, cursor, span.char_start), highlighted: false });
    parts.push({ text: sliceCodePoints(content, span.char_start, span.char_end), highlighted: true });
    cursor = Math.max(cursor, span.char_end);
  });
  if (cursor < Array.from(content).length) parts.push({ text: sliceCodePoints(content, cursor), highlighted: false });
  return parts;
}

export function sliceCodePoints(
  content: string,
  start: number,
  end?: number,
): string {
  return Array.from(content).slice(start, end).join("");
}

export function buildLedgerRows(
  units: readonly ContextVisUnit[],
  tier: number,
): LedgerRows {
  const rows = units.flatMap((unit) => unit.salient_infos.map((item) => ({
    info: item,
    unitId: unit.unit_id,
    unitTitle: unit.title,
  })));
  const reliable = rows.filter((row) => row.info.confidence === "reliable");
  const guessed = rows.filter((row) => row.info.confidence === "ai_guessed");
  if (tier < 2) return { reliable, guessed };
  const rank: Readonly<Record<ContextVisInfo["status_in_A"], number>> = {
    absent: 0,
    reframed: 1,
    present: 2,
    unknown: 3,
  };
  return {
    reliable: reliable.toSorted((left, right) => rank[left.info.status_in_A] - rank[right.info.status_in_A]),
    guessed: guessed.toSorted((left, right) => rank[left.info.status_in_A] - rank[right.info.status_in_A]),
  };
}

export function groupTranscriptForALens(
  transcript: readonly ContextVisTurn[],
  liveTurnIds: readonly string[] | null,
): readonly ModelTranscriptGroup[] | null {
  if (liveTurnIds === null) return null;
  const live = new Set(liveTurnIds);
  const groups: ModelTranscriptGroup[] = [];
  let deadTurns: ContextVisTurn[] = [];
  for (const item of transcript) {
    if (live.has(item.turn_id)) {
      if (deadTurns.length > 0) {
        groups.push({ kind: "dead", turns: deadTurns });
        deadTurns = [];
      }
      groups.push({ kind: "live", turn: item });
    } else {
      deadTurns.push(item);
    }
  }
  if (deadTurns.length > 0) groups.push({ kind: "dead", turns: deadTurns });
  return groups;
}

export function unitAliveness(
  unit: ContextVisUnit,
  liveTurnIds: readonly string[] | null,
): { readonly alive: number; readonly total: number } | null {
  if (liveTurnIds === null) return null;
  const live = new Set(liveTurnIds);
  return {
    alive: unit.covered_turns.filter((turnId) => live.has(turnId)).length,
    total: unit.covered_turns.length,
  };
}

export function intentLaneMarks(
  units: readonly ContextVisUnit[],
  segments: readonly ContextVisIntentSegment[],
): readonly (IntentLaneMark | null)[] {
  const positions = new Map(units.map((unit, index) => [unit.unit_id, index]));
  const marks: Array<IntentLaneMark | null> = units.map(() => null);
  for (const segment of segments) {
    const start = positions.get(segment.from_unit_id);
    const end = positions.get(segment.to_unit_id);
    if (start === undefined || end === undefined || start > end) continue;
    for (let index = start; index <= end; index += 1) {
      const role = start === end
        ? "single"
        : index === start
          ? "start"
          : index === end
            ? "end"
            : "mid";
      marks[index] = { role, segment };
    }
  }
  return marks;
}

export function validateIntentSegments(
  units: readonly ContextVisUnit[],
  segments: readonly ContextVisIntentSegment[],
): IntentValidationResult {
  const positions = new Map(units.map((unit, index) => [unit.unit_id, index]));
  const ids = new Set<string>();
  let previousStart = -1;
  let previousEnd = -1;
  for (const segment of segments) {
    const id = segment.segment_id.trim();
    if (!id) return { valid: false, code: "blank_id", message: "Every intent segment needs a stable ID." };
    if (ids.has(id)) return { valid: false, code: "duplicate_id", message: `Intent segment ID “${id}” is duplicated.` };
    ids.add(id);
    if (!segment.label.trim()) return { valid: false, code: "blank_label", message: "Every intent segment needs a label." };
    const start = positions.get(segment.from_unit_id);
    const end = positions.get(segment.to_unit_id);
    if (start === undefined || end === undefined) {
      return { valid: false, code: "unknown_unit", message: `Intent segment “${segment.label}” references an unavailable unit.` };
    }
    if (start > end) return { valid: false, code: "reversed_range", message: `Intent segment “${segment.label}” must end at or after it starts.` };
    if (start < previousStart) return { valid: false, code: "out_of_order", message: "Intent segments must follow unit order." };
    if (start <= previousEnd) return { valid: false, code: "overlap", message: `Intent segment “${segment.label}” overlaps an earlier segment.` };
    previousStart = start;
    previousEnd = end;
  }
  return { valid: true };
}

export function wholeTurnTrigger(turn: ContextVisTurn): ContextVisSpan | null {
  const charEnd = Array.from(turn.content).length;
  return charEnd === 0
    ? null
    : { turn_id: turn.turn_id, char_start: 0, char_end: charEnd };
}

export function normaliseConversationMode(
  mode: ConversationMode,
  compressionAvailable: boolean,
  sessionChanged: boolean,
): ConversationMode {
  if (sessionChanged || (mode === "model" && !compressionAvailable)) return "transcript";
  return mode;
}
