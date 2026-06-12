/**
 * ContextVis 命运投影（核心层,形态无关纯函数）。
 *
 * 这是 roadmap 命名的 `context.plan` 的**纯预览投影**:给定一组用户标记的命运
 * （keep/fold/drop）,在**不触碰真实上下文**的前提下,算出"若照此压缩能释放多少
 * token、占用降到几 %"。阶段 1+2 只到投影为止;阶段 3 的"应用"(真正驱动后端
 * compress())是另一条路,本模块绝不产生副作用。
 *
 * 释放量估算对齐 Hermes 既有压缩语义（agent/context_compressor.py,
 * summary_target_ratio=0.20,见 context-vis/compression-baseline.md）:
 *   · drop → 整块移除,释放 100%
 *   · fold → 摘要成 ~20%,释放 ~80%
 *   · keep → 保护,释放 0
 * 与逐块绝对 token 一样,这是**比例真实、总量自洽**的投影,不冒充精确值。
 */

import type { ContextChunk, ContextSnapshot } from "@/lib/contextvis/types";

/** 用户为单个 chunk 标记的命运。复用契约 union,不另造类型。 */
export type Fate = NonNullable<ContextChunk["fate"]>;

/** chunkId → 命运。用户意图,前端持有,不写回 snapshot。 */
export type FateMap = Record<string, Fate>;

/**
 * 有 message 背书、可经历史压缩落地的类型。
 * system / tool_schema 的 sourceRefs 只有 `part`、无 messageIndex,**不可 apply**
 * （它们每轮由 agent 重建,删不掉）——阶段 3 apply 只作用于这三类。
 */
export const MESSAGE_BACKED_TYPES: ReadonlySet<ContextChunk["type"]> = new Set([
  "history",
  "file",
  "tool_result",
]);

/** 当前标记为 drop 且可落地（message 背书）的 chunk id —— 阶段 3 apply 的输入。 */
export function droppableChunkIds(
  snapshot: ContextSnapshot,
  fateMap: FateMap,
): string[] {
  return snapshot.chunks
    .filter(
      (c) => fateMap[c.id] === "drop" && MESSAGE_BACKED_TYPES.has(c.type),
    )
    .map((c) => c.id);
}

/** fold 后保留的比例(摘要 ≈ 原文的 20%),对齐 Hermes summary_target_ratio。 */
const SUMMARY_RATIO = 0.2;

/** 单块在给定命运下预计释放的 token（无命运/keep = 0）。 */
export function freedTokens(chunk: ContextChunk, fate: Fate | undefined): number {
  if (fate === "drop") return chunk.tokens;
  if (fate === "fold") return chunk.tokens * (1 - SUMMARY_RATIO);
  return 0; // keep | undefined
}

export interface ProjectedPlan {
  /** 预计释放的 token 总量(向下取整)。 */
  freed: number;
  /** 应用后预计占用 token。 */
  projectedUsed: number;
  /** 应用后预计占用百分比(0–100,整数)。 */
  projectedPercent: number;
  /** 各命运的 chunk 计数。 */
  counts: { keep: number; fold: number; drop: number };
  /** 是否有任何标记(空 fateMap → false,上层据此决定是否显示预览)。 */
  hasMarks: boolean;
}

/**
 * 把 fateMap 投影到 snapshot 上,产出预览。纯函数,只读当前 chunks——
 * fateMap 里指向已消失 chunk 的孤儿条目天然被忽略,不影响结果。
 */
export function projectFates(
  snapshot: ContextSnapshot,
  fateMap: FateMap,
): ProjectedPlan {
  const counts = { keep: 0, fold: 0, drop: 0 };
  let freed = 0;
  for (const chunk of snapshot.chunks) {
    const fate = fateMap[chunk.id];
    if (!fate) continue;
    counts[fate] += 1;
    freed += freedTokens(chunk, fate);
  }
  freed = Math.floor(freed);
  const projectedUsed = Math.max(0, snapshot.used - freed);
  const projectedPercent =
    snapshot.budget > 0
      ? Math.round((projectedUsed / snapshot.budget) * 100)
      : 0;
  return {
    freed,
    projectedUsed,
    projectedPercent,
    counts,
    hasMarks: counts.keep + counts.fold + counts.drop > 0,
  };
}
