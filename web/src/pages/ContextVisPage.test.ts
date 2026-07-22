import { describe, expect, it } from "vitest";
import { buildHighlightSegments, summariseSurvival, dominantSurvival, unitIsPinned } from "@/lib/context-vis";
import type { ContextVisInfo, ContextVisUnit } from "@/lib/api";

const info = (status: ContextVisInfo["status_in_A"]): ContextVisInfo => ({
  info_id: `i-${status}-${Math.random()}`, kind: "user_stated_constraint", detected_text: "x",
  span_in_B: { turn_id: "t1", char_start: 0, char_end: 1 },
  status_in_A: status, reframed_text_in_A: null, confidence: "reliable",
});

describe("ContextVis transcript linkage", () => {
  it("highlights only spans belonging to the rendered truth-layer turn", () => {
    expect(buildHighlightSegments("keep this exact text", [
      { turn_id: "t1", char_start: 5, char_end: 15 },
      { turn_id: "t2", char_start: 0, char_end: 4 },
    ], "t1")).toEqual([
      { text: "keep ", highlighted: false },
      { text: "this exact", highlighted: true },
      { text: " text", highlighted: false },
    ]);
  });

  it("leaves the original text untouched without a matching span", () => {
    expect(buildHighlightSegments("truth", [], "t1")).toEqual([{ text: "truth", highlighted: false }]);
  });
});

describe("ContextVis survival roll-up", () => {
  it("counts each survival status", () => {
    expect(summariseSurvival([info("present"), info("reframed"), info("absent"), info("present")], 2))
      .toEqual({ total: 4, present: 2, reframed: 1, absent: 1 });
  });

  it("renders nothing below Tier 2, so the Tier 1 view is unchanged", () => {
    expect(summariseSurvival([info("present"), info("absent")], 1)).toBeNull();
  });

  it("renders nothing when no status is known, rather than a row of zeroes", () => {
    expect(summariseSurvival([info("unknown"), info("unknown")], 2)).toBeNull();
  });

  it("ignores unknown entries when some statuses are known", () => {
    expect(summariseSurvival([info("unknown"), info("reframed")], 2))
      .toEqual({ total: 1, present: 0, reframed: 1, absent: 0 });
  });
});

describe("ContextVis spine encoding", () => {
  it("dominantSurvival returns the most severe known status", () => {
    expect(dominantSurvival([info("present"), info("reframed"), info("absent")], 2)).toBe("absent");
    expect(dominantSurvival([info("present"), info("reframed")], 2)).toBe("reframed");
    expect(dominantSurvival([info("present"), info("unknown")], 2)).toBe("present");
  });

  it("dominantSurvival stays null below Tier 2 or with nothing known, so no misleading color", () => {
    expect(dominantSurvival([info("absent")], 1)).toBeNull();
    expect(dominantSurvival([info("unknown")], 2)).toBeNull();
    expect(dominantSurvival([], 2)).toBeNull();
  });

  it("unitIsPinned is true iff a covered turn is preserved", () => {
    const unit = { covered_turns: ["t1", "t2", "t3"] } as ContextVisUnit;
    expect(unitIsPinned(unit, ["t2"])).toBe(true);
    expect(unitIsPinned(unit, ["t9"])).toBe(false);
    expect(unitIsPinned(unit, [])).toBe(false);
  });
});
