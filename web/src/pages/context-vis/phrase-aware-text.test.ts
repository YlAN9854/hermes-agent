import { describe, expect, it } from "vitest";
import {
  inferCjkLanguage,
  phraseAwareChunks,
} from "./phrase-aware-text";

describe("phrase-aware CJK transcript wrapping", () => {
  it("preserves text while keeping short semantic Chinese phrases together", () => {
    const content = "研究方法需要同时保留问题边界、数据来源与可复现步骤，避免丢失关键约束。";
    const chunks = phraseAwareChunks(content);
    const kept = chunks.filter((chunk) => chunk.keepTogether).map((chunk) => chunk.text);

    expect(chunks.map((chunk) => chunk.text).join("")).toBe(content);
    for (const phrase of ["研究方法", "问题边界", "数据来源", "可复现步骤", "关键约束"]) {
      expect(kept.some((chunk) => chunk.includes(phrase))).toBe(true);
    }
  });

  it("infers Japanese, Korean, Chinese, and non-CJK content without coercion", () => {
    expect(inferCjkLanguage("かな漢字")).toBe("ja");
    expect(inferCjkLanguage("한글")).toBe("ko");
    expect(inferCjkLanguage("研究")).toBe("zh");
    expect(inferCjkLanguage("research")).toBeUndefined();
    expect(phraseAwareChunks("research")).toEqual([
      { text: "research", keepTogether: false },
    ]);
  });
});
