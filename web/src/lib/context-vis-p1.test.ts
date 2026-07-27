import { describe, expect, it } from "vitest";
import type {
  ContextVisInfo,
  ContextVisIntentSegment,
  ContextVisTurn,
  ContextVisUnit,
} from "./api";
import {
  buildLedgerRows,
  groupTranscriptForALens,
  intentLaneMarks,
  normaliseConversationMode,
  unitAliveness,
  validateIntentSegments,
  wholeTurnTrigger,
} from "./context-vis";

function turn(turnId: string, content = turnId): ContextVisTurn {
  return {
    turn_id: turnId,
    role: "user",
    content,
    tool_name: null,
    timestamp: 1,
  };
}

function info(
  infoId: string,
  status: ContextVisInfo["status_in_A"],
  confidence: ContextVisInfo["confidence"],
): ContextVisInfo {
  return {
    info_id: infoId,
    kind: "user_stated_constraint",
    detected_text: infoId,
    span_in_B: { turn_id: `turn-${infoId}`, char_start: 0, char_end: 1 },
    status_in_A: status,
    reframed_text_in_A: null,
    confidence,
  };
}

function unit(
  unitId: string,
  coveredTurns: readonly string[],
  salientInfos: readonly ContextVisInfo[] = [],
): ContextVisUnit {
  return {
    unit_id: unitId,
    title: `Unit ${unitId}`,
    summary_sentences: [],
    covered_turns: [...coveredTurns],
    salient_infos: [...salientInfos],
    frozen: true,
    created_at_turn: coveredTurns.at(-1) ?? "",
  };
}

function segment(
  segmentId: string,
  fromUnitId: string,
  toUnitId: string,
): ContextVisIntentSegment {
  return {
    segment_id: segmentId,
    label: `Segment ${segmentId}`,
    from_unit_id: fromUnitId,
    to_unit_id: toUnitId,
    trigger_span: null,
    note: "",
    origin: "user_edited",
  };
}

describe("ContextVis constraint ledger", () => {
  it("keeps reliable and AI-guessed rows separate while sorting known Tier 2 loss first", () => {
    // Given
    const units = [
      unit("one", ["t1"], [
        info("reliable-present", "present", "reliable"),
        info("guessed-absent", "absent", "ai_guessed"),
      ]),
      unit("two", ["t2"], [
        info("reliable-absent", "absent", "reliable"),
        info("guessed-reframed", "reframed", "ai_guessed"),
      ]),
    ];

    // When
    const rows = buildLedgerRows(units, 2);

    // Then
    expect(rows.reliable.map((row) => row.info.info_id)).toEqual([
      "reliable-absent",
      "reliable-present",
    ]);
    expect(rows.guessed.map((row) => row.info.info_id)).toEqual([
      "guessed-absent",
      "guessed-reframed",
    ]);
  });

  it("preserves transcript order at Tier 1 instead of sorting on unavailable survival truth", () => {
    // Given
    const units = [
      unit("one", ["t1"], [info("first-present", "present", "reliable")]),
      unit("two", ["t2"], [info("second-absent", "absent", "reliable")]),
    ];

    // When
    const rows = buildLedgerRows(units, 1);

    // Then
    expect(rows.reliable.map((row) => row.info.info_id)).toEqual([
      "first-present",
      "second-absent",
    ]);
  });
});

describe("ContextVis Model/A lens", () => {
  it("groups only contiguous dead turns and preserves every live turn as an anchor", () => {
    // Given
    const transcript = ["t1", "t2", "t3", "t4", "t5"].map((id) => turn(id));

    // When
    const groups = groupTranscriptForALens(transcript, ["t3", "t5"]);

    // Then
    expect(groups?.map((group) => (
      group.kind === "live"
        ? { kind: group.kind, id: group.turn.turn_id }
        : { kind: group.kind, ids: group.turns.map((item) => item.turn_id) }
    ))).toEqual([
      { kind: "dead", ids: ["t1", "t2"] },
      { kind: "live", id: "t3" },
      { kind: "dead", ids: ["t4"] },
      { kind: "live", id: "t5" },
    ]);
  });

  it("passes through all-live transcripts and returns null without compression truth", () => {
    // Given
    const transcript = [turn("t1"), turn("t2")];

    // When
    const allLive = groupTranscriptForALens(transcript, ["t1", "t2"]);
    const unsupported = groupTranscriptForALens(transcript, null);

    // Then
    expect(allLive?.every((group) => group.kind === "live")).toBe(true);
    expect(unsupported).toBeNull();
  });

  it("reports unit aliveness only when live-turn truth exists", () => {
    // Given
    const target = unit("one", ["t1", "t2", "t3"]);

    // When
    const observed = unitAliveness(target, ["t2", "t3"]);
    const unavailable = unitAliveness(target, null);

    // Then
    expect(observed).toEqual({ alive: 2, total: 3 });
    expect(unavailable).toBeNull();
  });
});

describe("ContextVis intent ranges", () => {
  it("marks closed sparse ranges without filling honest gaps", () => {
    // Given
    const units = ["u1", "u2", "u3", "u4", "u5"].map((id) => unit(id, [id]));
    const segments = [segment("s1", "u1", "u2"), segment("s2", "u4", "u4")];

    // When
    const marks = intentLaneMarks(units, segments);

    // Then
    expect(marks.map((mark) => mark?.role ?? null)).toEqual([
      "start",
      "end",
      null,
      "single",
      null,
    ]);
  });

  it.each([
    {
      name: "duplicate IDs",
      segments: [segment("same", "u1", "u1"), segment("same", "u2", "u2")],
      code: "duplicate_id",
    },
    {
      name: "overlapping ranges",
      segments: [segment("first", "u1", "u2"), segment("second", "u2", "u3")],
      code: "overlap",
    },
    {
      name: "reversed ranges",
      segments: [segment("reverse", "u3", "u1")],
      code: "reversed_range",
    },
  ])("rejects $name before sending an edit", ({ segments, code }) => {
    // Given
    const units = ["u1", "u2", "u3"].map((id) => unit(id, [id]));

    // When
    const result = validateIntentSegments(units, segments);

    // Then
    expect(result).toMatchObject({ valid: false, code });
  });

  it("captures a whole Unicode turn in code-point offsets and rejects an empty trigger", () => {
    // Given
    const unicodeTurn = turn("t-unicode", "A😀𠜎é");
    const emptyTurn = turn("t-empty", "");

    // When
    const unicode = wholeTurnTrigger(unicodeTurn);
    const empty = wholeTurnTrigger(emptyTurn);

    // Then
    expect(unicode).toEqual({ turn_id: "t-unicode", char_start: 0, char_end: 5 });
    expect(empty).toBeNull();
  });
});

describe("ContextVis conversation mode normalization", () => {
  it("returns Model view to transcript when compression truth disappears", () => {
    // Given
    const current = "model";

    // When
    const normalized = normaliseConversationMode(current, false, false);

    // Then
    expect(normalized).toBe("transcript");
  });

  it("returns every conversation mode to transcript after a session change", () => {
    // Given
    const current = "live";

    // When
    const normalized = normaliseConversationMode(current, true, true);

    // Then
    expect(normalized).toBe("transcript");
  });
});
