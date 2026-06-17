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
  | "continue" // 接受系统方案,照常位置式压缩
  | "defer" // 本轮不压
  | "apply_plan" // 闸门内编辑后的有效计划(fold+drop)直接落地,跳过位置式压缩(方案 A)
  | "edit_only"; // 仅删除(drop)、不折叠、跳过位置式压缩

/**
 * 应答压缩闸门。`dropChunkIds`/`foldChunkIds` 为闸门内编辑(二阶段)的有效计划——后端经
 * 应答带回、由循环线程 apply_gate_plan 作用于本地 messages(见 compaction-gate.md);
 * continue/defer 不传。
 */
export async function respondCompaction(
  sessionId: string,
  choice: CompactionChoice,
  dropChunkIds?: string[],
  foldChunkIds?: string[],
): Promise<void> {
  const gw = await ensureClient();
  await gw.request("compaction.respond", {
    session_id: sessionId,
    choice,
    drop_chunk_ids: dropChunkIds ?? [],
    fold_chunk_ids: foldChunkIds ?? [],
  });
}
