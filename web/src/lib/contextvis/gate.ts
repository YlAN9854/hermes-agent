/**
 * ContextVis 压缩闸门 —— 应答路（前端侧）。
 *
 * auto-compress 触发时,后端阻塞 agent 线程、push 一份系统压缩计划(见
 * context-vis/compaction-gate.md);用户在 dashboard 点「继续 / 推迟」→ 这里经
 * `/api/ws` 调 `compaction.respond` 解阻塞。复用 apply.ts 的同一条 GatewayClient
 * 连接(按 sid 定位真实会话)。
 */

import { ensureClient } from "@/lib/contextvis/apply";

export type CompactionChoice =
  | "continue" // 接受系统方案,照常压缩
  | "defer" // 本轮不压
  | "edit_compress" // 闸门内编辑(drop)后再系统压
  | "edit_only"; // 闸门内编辑(drop)后跳过系统压

/**
 * 应答压缩闸门。`dropChunkIds` 为闸门内编辑(二阶段)选中要删的块——后端经应答带回、
 * 作用于循环本地 messages(见 compaction-gate.md);continue/defer 不传。
 */
export async function respondCompaction(
  sessionId: string,
  choice: CompactionChoice,
  dropChunkIds?: string[],
): Promise<void> {
  const gw = await ensureClient();
  await gw.request("compaction.respond", {
    session_id: sessionId,
    choice,
    drop_chunk_ids: dropChunkIds ?? [],
  });
}
