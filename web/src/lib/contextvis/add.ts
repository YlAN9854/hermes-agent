/**
 * ContextVis v2 —— `add` 操作的纯函数投影（核心层，形态无关）。
 *
 * `add` 是操作集里唯一的"**写**"：用户从审查员（keep/drop/fold 治理机器写的内容）
 * 升为 **co-author**（自己往 context 注入信息）。这是剃刀的存在性证明——只有当注入的
 * 是"压缩器/agent 在决策时结构上拿不到的信息"（未来意图 / 外部真相）时才有价值。
 * 见 [v2/principle.md](../../../context-vis/v2/principle.md)、[[contextvis-research-framing]]。
 *
 * 本模块**只投影、零副作用**（对偶于 plan.ts 的 `projectFates`）：给定一条草稿，
 * 算出"若注入，context 会变成什么样"——追加一个合成 chunk + 抬高占用。真正落地到
 * 后端 session / system-prompt 是另一条 mutation 路（Layer 2，`session.branch` 验证），
 * 本模块绝不触碰真实上下文。fixture 重放下，整套 add 预览交互都跑在这上面、零 token。
 *
 * 放置轴（v2 两轴里的"放置"）：
 *   · inline —— 随历史注入当前位置，**会被正常压缩**（短暂澄清/纠偏）。
 *   · pin    —— 持久免压缩区，**扛过后续压缩**（如"生产周五前只读"这种要长期生效的约束）。
 *   · system-prompt 归到 `promote` 操作，单独设计，不在本模块。
 */

import type { ContextChunk, ContextSnapshot } from "@/lib/contextvis/types";

/** add 的放置轴（system-prompt = promote，另设）。 */
export type AddPlacement = "inline" | "pin";

/** 用户经 add 写的一条草稿（co-author 的"写"）。 */
export interface AddDraft {
  /** 用户写的内容（原文）。 */
  text: string;
  /** 放置：inline（随历史、可被压缩）/ pin（持久、免压缩）。 */
  placement: AddPlacement;
}

/**
 * token 估算 = chars/4，对齐 Hermes 既有口径（用户不关注计数精度，只关注分块）。
 * 空串 → 0；非空至少 1（注入即占位）。
 */
export function estimateTokens(text: string): number {
  const n = text.length;
  if (n === 0) return 0;
  return Math.max(1, Math.ceil(n / 4));
}

/**
 * 把一条草稿投影成合成 chunk（纯函数）。注入"现在"发生 → turn = 当前最大轮 +1
 * （= 你刚写下的最新一轮）；pin 的持久性体现在 `pinned` 标记（免压缩），不靠位置。
 * `added` 标记让渲染层把它与机器写的历史区分开。无 sourceRefs（草稿未落地、无消息背书）。
 */
export function draftToChunk(
  draft: AddDraft,
  snapshot: ContextSnapshot,
): ContextChunk {
  const turn =
    snapshot.chunks.reduce((m, c) => Math.max(m, c.turn), 0) + 1;
  const firstLine = draft.text.trim().split("\n")[0] || "用户注入";
  return {
    id: `add:draft:${draft.placement}`,
    type: "history",
    tokens: estimateTokens(draft.text),
    turn,
    label: firstLine.slice(0, 60),
    sourceRefs: [],
    raw: draft.text,
    added: true,
    pinned: draft.placement === "pin",
  };
}

/** add 的预览成本（供 composer 显示"注入会占多少 / 占用涨到几 %"）。 */
export interface AddCost {
  /** 注入这条会占的 token。 */
  tokens: number;
  /** 注入后预计占用 token。 */
  projectedUsed: number;
  /** 注入后预计占用百分比（0–100，整数）。 */
  projectedPercent: number;
}

/** 算 add 的诚实成本（不产生 chunk，只给数字）。 */
export function addCost(snapshot: ContextSnapshot, draft: AddDraft): AddCost {
  const tokens = estimateTokens(draft.text);
  const projectedUsed = snapshot.used + tokens;
  const projectedPercent =
    snapshot.budget > 0
      ? Math.round((projectedUsed / snapshot.budget) * 100)
      : snapshot.percent;
  return { tokens, projectedUsed, projectedPercent };
}

/**
 * 把 add 草稿投影到 snapshot 上：追加合成 chunk + 抬高占用。纯函数、可逆
 * （丢弃草稿即还原）。空草稿 → 原样返回（上层据此决定是否走预览）。
 * 返回的增广 snapshot 直接喂给画布 / 占用条 —— 注入块自动作为新一轮渲染。
 */
export function projectAdd(
  snapshot: ContextSnapshot,
  draft: AddDraft | null,
): ContextSnapshot {
  if (!draft || !draft.text.trim()) return snapshot;
  const chunk = draftToChunk(draft, snapshot);
  const used = snapshot.used + chunk.tokens;
  return {
    ...snapshot,
    chunks: [...snapshot.chunks, chunk],
    used,
    percent:
      snapshot.budget > 0
        ? Math.round((used / snapshot.budget) * 100)
        : snapshot.percent,
  };
}
