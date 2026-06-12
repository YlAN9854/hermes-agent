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
 * v1 只做 drop(确定性、零 LLM);fold/keep 见 roadmap。
 */

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

export interface UndoResult {
  status: string;
  messages: number;
}

// 单例:apply / undo 共用一条按需建立的 /api/ws 连接。
let _client: GatewayClient | null = null;

async function ensureClient(): Promise<GatewayClient> {
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

/** 一步撤销上一次 apply(其间未发生新 turn 时有效)。 */
export async function undoApply(sessionId: string): Promise<UndoResult> {
  const gw = await ensureClient();
  return gw.request<UndoResult>("context.undo", { session_id: sessionId });
}
