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

/**
 * 渲染带（chunk 的类型，5 个）—— 概念图的 5 个区域。
 *
 * 服务端把细粒度 segment（user/assistant/tool_call…）聚合进这 5 个带；细分只
 * 在服务端 segment 层保留，给 provenance / 未来语义聚类用。「类型恒定可辨」。
 */
export type ChunkType =
  | "system"
  | "tool_schema"
  | "history"
  | "file"
  | "tool_result";

/** provenance：指回真实会话单元，是"只读视图"升级"可编辑视图"的地基。 */
export interface SegmentRef {
  messageIndex?: number;
  part?: string;
}

/** 块：类型 · token 量级 · 所属轮次 · 来源引用 · 可选分组/命运。 */
export interface ContextChunk {
  id: string;
  type: ChunkType;
  tokens: number;
  /** 代表轮次（用于时间轴排序）。语义主题可跨非连续轮，见 turnSpan。 */
  turn: number;
  label: string;
  /** provenance：组成本块的源 segment 引用。 */
  sourceRefs: SegmentRef[];
  /** 分组标签（v1：toolset 名；未来：主题名）。 */
  group?: string;
  /** 折叠了几个 segment（v1：一轮的消息数；未来：主题成员数）。 */
  members?: number;
  /** 代表轮次的跨度，[起,止]。 */
  turnSpan?: [number, number];
  /** 预留：未来交互式压缩的命运标记，v1 恒空。 */
  fate?: "keep" | "fold" | "drop";
  raw?: string;
  /** 压缩折叠产物（摘要消息）：turn 带画成「已折叠」块，不计为对话轮。 */
  folded?: boolean;
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

/**
 * 压缩闸门待决态（阶段 A 对偶）：auto-compress 触发时,后端把"系统的压缩计划"
 * push 过来,等用户确认。见 context-vis/compaction-gate.md。
 */
export interface PendingCompaction {
  /** 系统计划:chunkId → 命运(fold/keep)。用 treemap fate 叠加渲染。 */
  systemFate: Record<string, "keep" | "fold" | "drop">;
  currentTokens: number;
  currentPercent: number;
  estAfterTokens: number;
  estAfterPercent: number;
  /** 将折叠的对话轮数（用于计划文字）。 */
  foldTurns: number;
  /** 两级门控:检测到的任务态（"task"）。森林态不会弹闸门,故有值即 task。 */
  regime?: string;
  /** R 后续①:检测出的主线焦点。非空时闸门显「将按焦点压缩: …」,确认后喂压缩 focus_topic。 */
  focus?: string;
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
  /** 观测到的压缩事件（靠 session.info 采样推断,best-effort，用于 sparkline 标记）。 */
  compactions: CompactionEvent[];
  /**
   * 真实累计压缩次数（来自 usage.compressions / comp.compression_count）。
   * 用于显示「压缩 ×N」—— 一轮内多次 mid-turn 压缩,session.info 只采样一次,
   * 推断事件会少计,故次数以此真实值为准。
   */
  compressionCount?: number;
  /** 档1 留空；档3 填真值。非空时上层渲染按类型树图。 */
  chunks: ContextChunk[];
  /** 压缩阈值（绝对 token，与 budget 同尺度）。「实际占用」模式据此画 compact 线。 */
  compactAt?: number;
  /** 阶段 3：事件帧携带的真实会话 id，apply 按它定位真实 agent。 */
  sessionId?: string;
  /** 阶段 3：history 版本，apply 回传做陈旧校验（其间发生 turn → 版本变 → 拒绝）。 */
  historyVersion?: number;
  /** 压缩闸门待决：非空时面板弹闸门、treemap 画系统计划。用户应答 / 新快照后清空。 */
  pendingCompaction?: PendingCompaction;
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
