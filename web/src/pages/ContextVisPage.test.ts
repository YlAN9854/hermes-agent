import { describe, expect, it } from "vitest";
import { buildHighlightSegments } from "@/lib/context-vis";

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
