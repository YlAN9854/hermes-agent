/**
 * turn 聚合（纯函数）—— 把按类型成块的 chunks 折成「按轮」的 turn 格。
 *
 * ContextVis 主视图主轴翻转的数据地基:treemap 按**类型**组织(5 带),turn 被撕成
 * 多块、看不出时间序;turn 带反过来,**按 `chunk.turn` 分组**,纵向时间序铺开。
 * 设计见 context-vis/turn-band.md。本函数零渲染依赖,只吃 snapshot 产出 TurnCell[]。
 *
 * 数据事实(见 agent/contextvis/chunking.py):
 *   · `turn=0`  = 系统底座(system + tool_schema,不属任何对话轮)。
 *   · `turn≥1`  = 对话轮(每个 user 消息 +1):该轮 history 块 + 各 file/tool_result 块。
 * 每个 chunk 都带正确 `turn`(history 已按轮成块;file/tool_result 逐条但各自保留 turn),
 * 故按 `chunk.turn` 分组干净且忠实。
 */

import type { ChunkType, ContextChunk, ContextSnapshot } from "./types";

/** 一个 turn 折成的格:时间序的一格,token 量级 ∝ 高度。 */
export interface TurnCell {
  /** 轮次(0=系统底座,≥1=对话轮;折叠块取其所在位置的轮号)。 */
  turn: number;
  /** 本格全部 chunk 的 token 之和(量级编码)。 */
  tokens: number;
  /** 本格包含的 chunk id(选中判定:命中其一即本格选中)。 */
  chunkIds: string[];
  /** 代表 chunk id —— 点格选它(复用「选中=chunkId→inspector」链路)。 */
  repId: string;
  /** 展示标签(底座固定文案;对话轮取 history 块「第N轮 · 首句」;折叠块「已折叠摘要」)。 */
  label: string;
  /** 是否系统底座(turn 0):渲染时略作区分。 */
  isBase: boolean;
  /** 是否压缩折叠产物:turn 带画成「已折叠」块,不混进对话轮。 */
  isFolded: boolean;
  /** 本格各类型 token 细分(本刀算好,备第三刀 inspector 类型细分用)。 */
  types: Partial<Record<ChunkType, number>>;
  /** 排序键:最小 messageIndex(底座=-1,无引用=Infinity);破 (turn,folded) 同序。 */
  order: number;
}

/** chunk 组的最小 messageIndex(无引用 → Infinity)。 */
function minMsgIndex(chunks: ContextChunk[]): number {
  let m = Infinity;
  for (const c of chunks)
    for (const r of c.sourceRefs)
      if (typeof r.messageIndex === "number") m = Math.min(m, r.messageIndex);
  return m;
}

/**
 * 把 snapshot.chunks 聚合成时间序的 turn 格。对话轮按 `chunk.turn` 合并;**压缩折叠
 * 产物(`folded`)各自单独成格**,不混进对话轮。排序:turn 升序 → 非折叠先于折叠 →
 * messageIndex(让折叠摘要落在它真实的时间位置:在被保护头部之后、当前轮之前)。
 */
export function buildTurnCells(snapshot: ContextSnapshot): TurnCell[] {
  const byTurn = new Map<number, ContextChunk[]>();
  const cells: TurnCell[] = [];

  for (const c of snapshot.chunks) {
    if (c.folded) {
      cells.push({
        turn: c.turn,
        tokens: c.tokens,
        chunkIds: [c.id],
        repId: c.id,
        label: c.label,
        isBase: false,
        isFolded: true,
        types: { [c.type]: c.tokens },
        order: minMsgIndex([c]),
      });
      continue;
    }
    const g = byTurn.get(c.turn);
    if (g) g.push(c);
    else byTurn.set(c.turn, [c]);
  }

  for (const [turn, group] of byTurn) {
    const tokens = group.reduce((s, c) => s + c.tokens, 0);
    const types: Partial<Record<ChunkType, number>> = {};
    for (const c of group) types[c.type] = (types[c.type] ?? 0) + c.tokens;

    // 代表块:优先该轮 history 块(承载提问+回复,inspector 显得最有意义),否则最大块。
    const rep =
      group.find((c) => c.type === "history") ??
      group.reduce((a, b) => (b.tokens > a.tokens ? b : a));

    const isBase = turn === 0;
    const histLabel = group.find((c) => c.type === "history")?.label;
    const label = isBase ? "系统底座" : histLabel ?? group[0].label;

    cells.push({
      turn,
      tokens,
      chunkIds: group.map((c) => c.id),
      repId: rep.id,
      label,
      isBase,
      isFolded: false,
      types,
      order: isBase ? -1 : minMsgIndex(group),
    });
  }

  cells.sort(
    (a, b) =>
      a.turn - b.turn ||
      (a.isFolded ? 1 : 0) - (b.isFolded ? 1 : 0) ||
      a.order - b.order,
  );
  return cells;
}
