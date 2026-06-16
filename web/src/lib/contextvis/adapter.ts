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
  history_version?: number;
  // 压缩后立即补发的快照携带占用(常规 snapshot 的占用来自 session.info)。
  used?: number;
  percent?: number;
  budget?: number;
  /** 压缩后补发携带真实累计压缩次数,让「压缩 ×N」mid-turn 即时累加。 */
  compressions?: number;
}

/** context.compaction_request 载荷（对齐 agent/compaction_gate.request_compaction_decision）。 */
interface CompactionRequestPayload {
  system_fate?: Record<string, "keep" | "fold" | "drop">;
  current_tokens?: number;
  current_percent?: number;
  est_after_tokens?: number;
  est_after_percent?: number;
  fold_turns?: number;
  /** 两级门控放行的任务态标记("task")+ 原因(供闸门条标"检测到主线任务")。 */
  regime?: string;
  collision_reason?: string;
  /** R 后续①:检测出的主线焦点,前端只读显示"将按此焦点压"(确认后喂 focus_topic)。 */
  focus?: string;
  /** 闸门时刻(turn 中途)的新鲜 chunks + 窗口,用来把 treemap/占用刷成与 banner 一致。 */
  chunks?: ContextChunk[];
  budget?: number;
}

interface EventFrame {
  method?: string;
  params?: {
    type?: string;
    /** 真实会话 id —— 每帧都带（tui_gateway _emit），阶段 3 apply 据此定位真实 agent。 */
    session_id?: string;
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

        // 压缩闸门:auto-compress 触发,后端 push 系统计划等用户确认。
        if (evType === "context.compaction_request") {
          const p = frame.params?.payload as CompactionRequestPayload | undefined;
          if (p && p.system_fate) {
            setSnapshot((prev) => ({
              ...prev,
              // 闸门 turn 中途触发:用这一刻的新鲜 chunks + 占用刷新视图,
              // 让 treemap / 占用条与 banner、system_fate 对齐(否则停在轮初旧值)。
              ...(Array.isArray(p.chunks) ? { chunks: p.chunks } : {}),
              ...(typeof p.current_tokens === "number"
                ? { used: p.current_tokens }
                : {}),
              ...(typeof p.current_percent === "number"
                ? { percent: p.current_percent }
                : {}),
              ...(p.budget && p.budget > 0 ? { budget: p.budget } : {}),
              pendingCompaction: {
                systemFate: p.system_fate ?? {},
                currentTokens: p.current_tokens ?? prev.used,
                currentPercent: p.current_percent ?? prev.percent,
                estAfterTokens: p.est_after_tokens ?? 0,
                estAfterPercent: p.est_after_percent ?? 0,
                foldTurns: p.fold_turns ?? 0,
                regime: p.regime,
                focus: p.focus,
              },
            }));
          }
          return;
        }

        // ContextVis 档3：逐块构成。与 session.info 合并进同一 snapshot
        // （budget/used/percent 仍来自 session.info）。
        if (evType === "context.snapshot") {
          const chunks = frame.params?.payload?.chunks;
          if (Array.isArray(chunks)) {
            const pl = frame.params?.payload;
            const compactAt = pl?.compact_at;
            const sessionId = frame.params?.session_id;
            const historyVersion = pl?.history_version;
            // 压缩后立即补发的快照会带占用(used/percent/budget),让 treemap header /
            // 占用条即时回落,不等整轮结束的 session.info。常规快照不带,占用仍由 session.info 管。
            const pushedUsed = pl?.used;
            const pushedPercent = pl?.percent;
            const pushedBudget = pl?.budget;
            const pushedCompressions = pl?.compressions;
            setSnapshot((prev) => {
              // resume 场景：agent 刚重建，compressor.last_prompt_tokens 未恢复，
              // session.info 的真实 used=0；但 chunks 来自真实已载入的
              // session["history"] → 用 chunk 总和补出占用，避免显示 0。
              // 首轮之后真实 usage>0，session.info 会以真实值覆盖（见下）。
              const chunkTotal = chunks.reduce((s, c) => s + (c.tokens || 0), 0);
              const useEstimate =
                (prev.used || 0) <= 0 && chunkTotal > 0 && prev.budget > 0;
              return {
                ...prev,
                chunks,
                compactAt,
                // 新快照 = 闸门时刻已过(压缩跑了 / 推迟后继续)→ 清待决态。
                pendingCompaction: undefined,
                ...(sessionId ? { sessionId } : {}),
                ...(typeof historyVersion === "number" ? { historyVersion } : {}),
                ...(typeof pushedCompressions === "number"
                  ? { compressionCount: pushedCompressions }
                  : {}),
                ...(pushedBudget && pushedBudget > 0 ? { budget: pushedBudget } : {}),
                ...(typeof pushedUsed === "number"
                  ? {
                      used: pushedUsed,
                      percent:
                        typeof pushedPercent === "number"
                          ? pushedPercent
                          : prev.budget > 0
                            ? Math.round((pushedUsed / prev.budget) * 100)
                            : prev.percent,
                    }
                  : useEstimate
                    ? {
                        used: chunkTotal,
                        percent: Math.min(
                          100,
                          Math.round((chunkTotal / prev.budget) * 100),
                        ),
                      }
                    : {}),
              };
            });
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

          // chunks / compactAt / sessionId / historyVersion 由 context.snapshot
          // 事件维护，这里保留上一帧不清空（sessionId 也可从本帧补获）。
          return {
            budget,
            used,
            percent,
            turn,
            history,
            compactions,
            chunks: prev.chunks,
            compactAt: prev.compactAt,
            // 真实累计压缩次数(权威值,「压缩 ×N」用它,不用推断的事件数组长度)。
            compressionCount: compressions,
            sessionId: frame.params?.session_id ?? prev.sessionId,
            historyVersion: prev.historyVersion,
            // 闸门只会在两次 session.info 之间(agent 阻塞期)挂起;新 session.info
            // = 决定已落 → 清待决态(兜底 chunks 为空、无 snapshot co-emit 的情形)。
            pendingCompaction: undefined,
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
