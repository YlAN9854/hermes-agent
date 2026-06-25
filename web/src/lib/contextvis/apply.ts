/**
 * ContextVis 方向 A 阶段 3 —— 「应用」命令路（前端侧）。
 *
 * 把用户标记的 drop **落地到真实 agent 的上下文**。通道在阶段 3 调研里已坐实
 * (见 context-vis/phase3-channel.md):dashboard 下 PTY 走 attach 模式,真实 agent
 * 就在 web_server 进程的 `_sessions`,前端新开 `/api/ws` 按 sid 即可调 `context.apply`。
 *
 * - sid 从事件帧免费拿到(`snapshot.sessionId`,见 adapter.ts);
 * - `historyVersion` 回传做陈旧校验(其间发生 turn → 后端拒绝,前端提示刷新);
 * - 复用 {@link GatewayClient}(connect 一次、单例复用),与 dashboard 自身 sidecar
 *   各开各的连接,互不干扰——我们只按 sid 定位 TUI 那个真实会话。
 *
 * drop（确定性、零 LLM）与 fold（A-v2,跑辅助模型摘要）共用这条命令路。
 */

import { activeFixture } from "@/lib/contextvis/fixtures";
import { GatewayClient } from "@/lib/gatewayClient";

export interface ApplyResult {
  status: string;
  removed: number;
  before_messages: number;
  after_messages: number;
  before_tokens: number;
  after_tokens: number;
  dropped_chunk_ids: string[];
}

export interface FoldResult {
  status: string;
  folded: number;
  before_messages: number;
  after_messages: number;
  before_tokens: number;
  after_tokens: number;
  folded_chunk_ids: string[];
}

export interface UndoResult {
  status: string;
  messages: number;
}

// 单例:apply / undo / 压缩闸门应答共用一条按需建立的 /api/ws 连接。
let _client: GatewayClient | null = null;

export async function ensureClient(): Promise<GatewayClient> {
  if (!_client) _client = new GatewayClient();
  if (_client.state !== "open") {
    // 连接断了(close/error)就重建一个干净的。
    if (_client.state === "closed" || _client.state === "error") {
      _client = new GatewayClient();
    }
    await _client.connect();
  }
  return _client;
}

/** 落地 drop:删除这些 chunk 背后的真实消息。成功后后端会 re-emit，UI 自动刷新。 */
export async function applyDrops(
  sessionId: string,
  historyVersion: number | undefined,
  dropChunkIds: string[],
): Promise<ApplyResult> {
  const gw = await ensureClient();
  return gw.request<ApplyResult>("context.apply", {
    session_id: sessionId,
    history_version: historyVersion,
    drop_chunk_ids: dropChunkIds,
  });
}

/**
 * 落地 fold（A-v2）:把这些 chunk 背后的消息折成一条摘要（单隐式组）。
 * `focusPrompt` 可空,告诉摘要重心。后端跑辅助模型,可能耗时数秒;失败整笔中止。
 * 成功后后端会 re-emit，UI 自动刷新;复用同一条 `context.undo` 撤销路。
 */
export async function applyFold(
  sessionId: string,
  historyVersion: number | undefined,
  foldChunkIds: string[],
  focusPrompt: string,
): Promise<FoldResult> {
  const gw = await ensureClient();
  return gw.request<FoldResult>("context.fold", {
    session_id: sessionId,
    history_version: historyVersion,
    fold_chunk_ids: foldChunkIds,
    focus_prompt: focusPrompt,
  });
}

/** 调试:对当前 session 跑任务态检测器,返回完整拆解(只读)。console 用。 */
export async function debugRegime(sessionId: string): Promise<Record<string, unknown>> {
  const gw = await ensureClient();
  return gw.request<Record<string, unknown>>("context.regime", {
    session_id: sessionId,
  });
}

/** turn 带主题着色:chunkId → 该块的逐轮 topic + 是否主线。 */
export interface RegimeColors {
  regime: string;
  focus: string;
  engine: string;
  reason: string;
  chunk_topics: Record<
    string,
    { topic: string; mainline: boolean; done?: boolean }
  >;
  /** v2 引用图(层① 工具溯源边):read 连其前最近一次同路径 write。后端可能不带(旧版)→ 可选。 */
  reference_graph?: ReferenceGraph;
}

/** v2 引用图。层① = 工具溯源(write→read 同路径,有向、高精度);后续叠层②文字/层③LLM。 */
export interface ReferenceEdge {
  src: string | null; // 源 chunkId(messageIndex 解析不到为 null)
  dst: string | null; // 目标 chunkId
  src_mi: number; // 源 messageIndex
  dst_mi: number; // 目标 messageIndex
  kind: string; // "tool"(层①) | 后续 "lexical" 等
  rel?: string; // "read"(写后读=数据流) | "revision"(写后写=修订链)
  via: string; // 这条边因何成立(如文件路径)——守不变量 #6:每条边可解释
  weight: number;
}
export interface ReferenceArtifact {
  key: string; // 产物标识(如文件路径)
  kind: string; // "file" 等
  messageIndices: number[];
  chunks: string[];
  n: number; // 被几条消息触及
}
/** 产物索引项:工具触及过的文件路径(≥1)→ 它的 chunkIds(右栏「产物优先」+ 路径追踪)。 */
export interface ReferenceFile {
  key: string; // 文件路径
  chunks: string[]; // 触及它的 chunkIds(tool_result/file 块)
  n: number; // 触及块数
  tokens: number; // 这些块的总 token(膨胀量级,降序排)
}
/** 关键词索引项:复现 salient token → 它出现的 chunkIds(token-中心路径追踪入口)。 */
export interface ReferenceKeyword {
  key: string; // salient token
  chunks: string[]; // 出现它的 chunkIds(≥2)
  n: number; // 出现块数
}
export interface ReferenceGraph {
  edges: ReferenceEdge[];
  artifacts: ReferenceArtifact[];
  files?: ReferenceFile[]; // Stage 3 产物优先:全部触及文件 → 路径追踪
  keywords?: ReferenceKeyword[]; // Stage 3:关键词索引列 + 路径追踪
  layers: string[]; // 已建的层,如 ["tool"]
}

/**
 * 拉取 turn 带主题着色数据(按需、只读)。后端跑任务态检测器(可能调 aux 模型,
 * 已缓存)并 join 到 chunk。前端缓存结果,historyVersion 变才重取——故非每帧调用。
 */
export async function fetchRegimeColors(sessionId: string): Promise<RegimeColors> {
  // Fixture 重放（dev）:返回冻结的检测器判定（着色 + 引用图），不发 RPC、不跑 aux LLM。
  const fx = activeFixture();
  if (fx) return fx.regimeColors;
  const gw = await ensureClient();
  return gw.request<RegimeColors>("context.regime_colors", {
    session_id: sessionId,
  });
}

/** 一步撤销上一次 apply(其间未发生新 turn 时有效)。 */
export async function undoApply(sessionId: string): Promise<UndoResult> {
  const gw = await ensureClient();
  return gw.request<UndoResult>("context.undo", { session_id: sessionId });
}

export interface AddResult {
  status: string;
  placement: "inline" | "pin";
  added_tokens: number;
  before_messages: number;
  after_messages: number;
  before_tokens: number;
  after_tokens: number;
}

/**
 * v2 `add`（落地）：把用户 co-author 注入的一条信息写进真实上下文。
 * `placement` = inline（随历史、正常受压）/ pin（打免压标记，压缩器永不碰）。
 * 成功后后端 re-emit `session.info` + `context.snapshot`，UI 自动刷新出真实注入块。
 */
export async function applyAdd(
  sessionId: string,
  historyVersion: number | undefined,
  text: string,
  placement: "inline" | "pin",
): Promise<AddResult> {
  const gw = await ensureClient();
  return gw.request<AddResult>("context.add", {
    session_id: sessionId,
    history_version: historyVersion,
    text,
    placement,
  });
}
