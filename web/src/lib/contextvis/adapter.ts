/**
 * ContextVis 适配器（宿主专属）—— 三层隔离的第一层。
 *
 * 唯一碰宿主事件结构的地方：把 Hermes gateway 的真实 `session.info.usage`
 * 折成形态无关的 {@link ContextSnapshot}。渲染层只吃 snapshot，绝不到这里来。
 *
 * 数据来源 —— **事件通道**，不是 sidecar：
 *   dashboard 的 Chat 正文是 PTY 子进程跑的 TUI；该子进程的 gateway 把**每一次
 *   emit**（含 `session.info`）镜像到 `/api/pub`（见 tui_gateway/event_publisher.py），
 *   服务端 `pub_ws` 再逐帧 verbatim 扇出到 `/api/events?channel=`。所以真实占用
 *   随每轮 `session.info` 到达这条 feed —— 与 ChatSidebar 取 tool.* 是同一条。
 *   反观 ChatSidebar 的 JSON-RPC sidecar(`gw`) 跑的是它自建的 throwaway 会话，
 *   其 `session.info.usage` 恒为零，**不可用**。
 *
 * Best-effort：WS 失败时静默保留上一帧快照（面板自身降级显示），不打扰对话。
 */

import { useEffect, useRef, useState } from "react";

import { HERMES_BASE_PATH, buildWsAuthParam } from "@/lib/api";
import {
  EMPTY_SNAPSHOT,
  type CompactionEvent,
  type ContextChunk,
  type ContextSnapshot,
} from "@/lib/contextvis/types";

/** session.info.usage 的最小字段形状（对齐 tui_gateway 的 _get_usage 输出）。 */
interface SessionUsage {
  context_used?: number;
  context_max?: number;
  context_percent?: number;
  compressions?: number;
  calls?: number;
}

/** context.snapshot 载荷（对齐 agent/contextvis/chunking.build_snapshot_chunks）。 */
interface ContextSnapshotPayload {
  chunks?: ContextChunk[];
  compact_at?: number;
}

interface EventFrame {
  method?: string;
  params?: {
    type?: string;
    payload?: { usage?: SessionUsage } & ContextSnapshotPayload;
  };
}

/** sparkline 采样的环形上限。 */
const HISTORY_CAP = 120;
/** 占用回落超过此比例(相对窗口)即便 compressions 计数没动也判定为一次压缩。 */
const DROP_FRACTION = 0.05;

/**
 * 订阅 chat 标签的事件通道，产出实时 ContextSnapshot。
 *
 * @param channel ChatPage 生成、绑定本标签 PTY 子进程的通道 id。
 */
export function useContextSnapshot(channel: string): ContextSnapshot {
  const [snapshot, setSnapshot] = useState<ContextSnapshot>(EMPTY_SNAPSHOT);
  // 上一次见到的累计压缩计数，用来判定「这一帧发生了压缩」。-1 = 尚未见过。
  const lastCompressionsRef = useRef<number>(-1);

  useEffect(() => {
    if (!channel) return;

    let unmounting = false;
    let ws: WebSocket | null = null;

    void (async () => {
      const [authName, authValue] = await buildWsAuthParam();
      if (!authValue || unmounting) return;

      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const qs = new URLSearchParams({ [authName]: authValue, channel });
      ws = new WebSocket(
        `${proto}//${window.location.host}${HERMES_BASE_PATH}/api/events?${qs.toString()}`,
      );

      ws.addEventListener("message", (ev) => {
        let frame: EventFrame;
        try {
          frame = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (frame.method !== "event") return;
        const evType = frame.params?.type;

        // ContextVis 档3：逐块构成。与 session.info 合并进同一 snapshot
        // （budget/used/percent 仍来自 session.info）。
        if (evType === "context.snapshot") {
          const chunks = frame.params?.payload?.chunks;
          if (Array.isArray(chunks)) {
            const compactAt = frame.params?.payload?.compact_at;
            setSnapshot((prev) => ({ ...prev, chunks, compactAt }));
          }
          return;
        }

        if (evType !== "session.info") return;
        const usage = frame.params?.payload?.usage;
        // 无真实窗口不更新 —— 可信度系于真实计数，宁可不显示也不假装。
        if (!usage || !usage.context_max) return;

        const used = usage.context_used ?? 0;
        const budget = usage.context_max;
        const percent = usage.context_percent ?? Math.round((used / budget) * 100);
        const compressions = usage.compressions ?? 0;

        setSnapshot((prev) => {
          const turn = usage.calls ?? prev.turn + 1;

          // 压缩推断：累计计数增加，或占用相对窗口明显回落。
          const prevCount = lastCompressionsRef.current;
          const countRose = prevCount >= 0 && compressions > prevCount;
          const droppedHard =
            prev.used > 0 && prev.used - used > budget * DROP_FRACTION;
          lastCompressionsRef.current = compressions;

          let compactions = prev.compactions;
          if (countRose || droppedHard) {
            const event: CompactionEvent = {
              turn,
              beforeTokens: prev.used,
              afterTokens: used,
              removed: Math.max(0, prev.used - used),
            };
            compactions = [...prev.compactions, event];
          }

          const history = [
            ...prev.history,
            { turn, used, percent },
          ].slice(-HISTORY_CAP);

          // chunks / compactAt 由 context.snapshot 事件维护，这里保留上一帧不清空。
          return {
            budget,
            used,
            percent,
            turn,
            history,
            compactions,
            chunks: prev.chunks,
            compactAt: prev.compactAt,
          };
        });
      });
    })();

    return () => {
      unmounting = true;
      ws?.close();
    };
  }, [channel]);

  return snapshot;
}
