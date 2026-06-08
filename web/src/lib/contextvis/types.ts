/**
 * ContextVis — 形态无关的数据契约（见根目录 CLAUDE.md「概念模型」）。
 *
 * 这是**模型**，与渲染无关：同一个 ContextSnapshot 可渲染成储液瓶、终端
 * 块槽或别的皮肤。契约的可信度系于 `tokens` / `budget` 必须是真实计数与
 * 真实窗口 —— 任何无法拿到真实值的字段宁可留空，也不放估算值冒充。
 *
 * 档1（当前实现）只填聚合层：budget / used / percent / history / compactions。
 * 逐块层 `chunks` 留空，待档3 由后端 RPC 暴露 agent 真实 prompt 分块后填入；
 * 届时上层渲染据 `chunks` 是否非空切换到按类型树图，契约本身不变。
 */

/** 内容的固定小类型，在所有形态中以恒定方式区分。 */
export type ChunkType =
  | "system"
  | "user"
  | "assistant"
  | "tool_call"
  | "tool_result"
  | "file";

/** 块：类型 · token 量级 · 所属轮次 · 可选原文 · 可选命运。 */
export interface ContextChunk {
  id: string;
  type: ChunkType;
  tokens: number;
  turn: number;
  label: string;
  raw?: string;
  fate?: "keep" | "fold" | "drop";
}

/** 压缩事件：给历史块分配命运后，容器占用的一次骤降。 */
export interface CompactionEvent {
  turn: number;
  beforeTokens: number;
  afterTokens: number;
  removed: number;
  summary?: string;
}

/** 逐轮演变的一帧采样（sparkline 的一个点）。 */
export interface ContextSample {
  turn: number;
  used: number;
  percent: number;
}

/** 容器 = 一组块，填进一个有预算上限的容器。 */
export interface ContextSnapshot {
  /** 模型窗口大小（usage.context_max）—— 真实窗口。 */
  budget: number;
  /** 当前 prompt 占用（usage.context_used）—— 真实计数。 */
  used: number;
  /** usage.context_percent。 */
  percent: number;
  /** 轮次轴（usage.calls，回退为采样序号）。 */
  turn: number;
  /** 档1：逐轮占用采样，环形截断。 */
  history: ContextSample[];
  /** 观测到的压缩事件（靠 session.info 采样推断）。 */
  compactions: CompactionEvent[];
  /** 档1 留空；档3 填真值。非空时上层渲染按类型树图。 */
  chunks: ContextChunk[];
}

/** 空快照：尚未收到任何带真实窗口的 session.info 时的初始态。 */
export const EMPTY_SNAPSHOT: ContextSnapshot = {
  budget: 0,
  used: 0,
  percent: 0,
  turn: 0,
  history: [],
  compactions: [],
  chunks: [],
};
