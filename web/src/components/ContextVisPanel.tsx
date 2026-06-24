/**
 * ContextVisPanel —— ContextVis 的核心渲染（形态无关层的「一种渲染」）。
 *
 * 只吃 {@link ContextSnapshot}，绝不碰 gateway / 宿主数据结构。讲清**占用 /
 * 构成 / 累积 / 命运**。
 *
 * treemap 两种模式（用户可切）：
 *   · 比例划分(proportional)：填满整块，chunk 间比例真实，始终可读。
 *   · 实际占用(actual)：按 used/budget 决定填充高度，上方留 headroom + token 轴
 *     + compact 阈值线 —— 直观看「离上限多远」（CLAUDE.md：占用对抗上限）。
 *
 * `chunks` 为空 → 退回占用条。选中格子高亮（联动地基）。`fate` 着色留待交互阶段。
 */

import { Card } from "@nous-research/ui/ui/components/card";
import { ChevronUp } from "lucide-react";
import { useEffect, useState } from "react";

import { ContextVisTreemap } from "@/components/ContextVisTreemap";
import { ContextVisTurnBand } from "@/components/ContextVisTurnBand";
import { ContextVisSparkline } from "@/components/ContextVisSparkline";
import { ContextVisKeywordIndex } from "@/components/ContextVisKeywordIndex";
import { formatTokenCount } from "@/lib/format";
import { TurnCanvas } from "@/components/TurnCanvas";
import {
  CV_ARC,
  CV_TOPIC_PALETTE,
} from "@/lib/contextvis/theme";
import {
  droppableChunkIds,
  foldableChunkIds,
  MESSAGE_BACKED_TYPES,
  projectFates,
  type Fate,
  type FateMap,
} from "@/lib/contextvis/plan";
import {
  applyDrops,
  applyFold,
  debugRegime,
  fetchRegimeColors,
  undoApply,
  type RegimeColors,
  type ReferenceGraph,
} from "@/lib/contextvis/apply";
import { respondCompaction, type CompactionChoice } from "@/lib/contextvis/gate";
import type {
  ContextSnapshot,
  TreemapMode,
  ViewKind,
} from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

type ChunkTopicMap = RegimeColors["chunk_topics"];

/** 主题键归一化:吸收 LLM 对同一主题的琐碎改名差异(trim / 小写 / 压空格)。 */
function normalizeTopic(t: string): string {
  return t.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * 按**线程**给每个 chunk 定色,返回 **chunkId → color**。色键 = `(mainline && focus) ? focus : topic`:
 * **主线轮全部收 focus 一色**(粗、稳),**支线轮各自 topic 一色**;逐轮 topic 仅留作标签(tooltip)。
 * 颜色经持久注册表分配——**只增不洗**:首见某色键分下一个空闲色并记下、以后复用、永不重排
 * (根治旧版"排序下标法"一加键就整排重洗 + 每次从零重建无记忆)。
 *
 * 注册表存 localStorage 按 sessionId(浮层折叠/展开会重挂载 panel,内存 ref 会丢 → 必须持久化;
 * 顺带扛页面重载),按**归一化字符串键**(focus / topic)存色,吸收 LLM 琐碎改名。
 * `focus` 空(启发式回退)时主线轮回退按 topic 上色(= 旧行为,不退化为无色)。
 * localStorage 失败(隐私模式/配额)→ 退化为本次内存分配(仍比旧版稳)。
 */
function resolveCellColors(
  ct: ChunkTopicMap,
  focus: string,
  sessionId: string | undefined,
): Record<string, string> {
  const storeKey = sessionId ? `cv-topics:${sessionId}` : "";
  let reg: Record<string, string> = {};
  if (storeKey) {
    try {
      reg = JSON.parse(localStorage.getItem(storeKey) || "{}") || {};
    } catch {
      reg = {};
    }
  }
  const out: Record<string, string> = {};
  let dirty = false;
  for (const [chunkId, v] of Object.entries(ct)) {
    const colorKey = v.mainline && focus ? focus : v.topic;
    if (!colorKey) continue; // 无 focus 且无 topic → 该格中性
    const norm = normalizeTopic(colorKey);
    if (!reg[norm]) {
      reg[norm] = CV_TOPIC_PALETTE[Object.keys(reg).length % CV_TOPIC_PALETTE.length];
      dirty = true;
    }
    out[chunkId] = reg[norm];
  }
  if (dirty && storeKey) {
    try {
      localStorage.setItem(storeKey, JSON.stringify(reg));
    } catch {
      /* 配额/隐私模式:退化为本次内存分配,out 已填好 */
    }
  }
  return out;
}

/** 把一次 regime_colors 结果 + 持久注册表解析,组装成 colorData(三处加载点共用)。 */
function buildColorData(
  r: RegimeColors,
  hv: number | undefined,
  sid: string | undefined,
) {
  return {
    hv,
    topics: r.chunk_topics,
    regime: r.regime,
    focus: r.focus,
    engine: r.engine,
    cellColors: resolveCellColors(r.chunk_topics, r.focus, sid),
    referenceGraph: r.reference_graph ?? null, // v2 引用图(层① 工具溯源边);增量③消费
  };
}

function ModeToggle({
  mode,
  onChange,
}: {
  mode: TreemapMode;
  onChange: (m: TreemapMode) => void;
}) {
  const opt = (m: TreemapMode, label: string) => (
    <button
      type="button"
      onClick={() => onChange(m)}
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] tracking-wide transition-colors",
        mode === m
          ? "bg-current/15 text-text-secondary"
          : "text-text-tertiary hover:text-text-secondary",
      )}
    >
      {label}
    </button>
  );
  return (
    <div className="flex items-center gap-0.5 rounded border border-current/15 p-0.5">
      {opt("proportional", "比例")}
      {opt("actual", "占用")}
    </div>
  );
}

/** 主视图开关:类型带 ⇄ 轮次带（默认轮次,见 turn-band.md §8）。 */
function ViewToggle({
  view,
  onChange,
}: {
  view: ViewKind;
  onChange: (v: ViewKind) => void;
}) {
  const opt = (v: ViewKind, label: string) => (
    <button
      type="button"
      onClick={() => onChange(v)}
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] tracking-wide transition-colors",
        view === v
          ? "bg-current/15 text-text-secondary"
          : "text-text-tertiary hover:text-text-secondary",
      )}
    >
      {label}
    </button>
  );
  return (
    <div className="flex items-center gap-0.5 rounded border border-current/15 p-0.5">
      {opt("turn", "轮次")}
      {opt("type", "类型")}
    </div>
  );
}

/** Stage 2:轮次视图用 2D 画布(TurnCanvas);设 false 回退旧纵向带(TurnBand)。 */
const USE_CANVAS = true;

function occupancyTone(percent: number): { bar: string; text: string } {
  if (percent >= 90) return { bar: "bg-destructive", text: "text-destructive" };
  if (percent >= 70) return { bar: "bg-warning", text: "text-warning" };
  return { bar: "bg-success", text: "text-success" };
}

/** 关键词追踪色(与 TurnCanvas 的 TRACE_COLOR 一致):点关键词高亮其贯穿路径。 */
const TRACE_COLOR = CV_ARC.trace;

export function ContextVisPanel({
  snapshot,
  selected,
  onSelect,
  onCollapse,
  fateMap,
  onClearFates,
  onActivateTurn,
  onSetFates,
}: {
  snapshot: ContextSnapshot;
  /** 受控选中：选中态上提到挂载壳，与右侧栏 inspector 共享。 */
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** 挂载壳传入：渲染一个折叠按钮（核心渲染本身不关心折叠语义）。 */
  onCollapse?: () => void;
  /** 命运标记（用户意图,来自 ChatPage fateMap）—— 驱动叠加渲染与预览。 */
  fateMap: FateMap;
  /** 清除全部命运标记。 */
  onClearFates: () => void;
  /** 第三刀:点对话轮 → 挂载壳把 TUI 滚到该轮(renderer 不碰 xterm)。 */
  onActivateTurn?: (turn: number) => void;
  /** R 后续②:批量预填命运(「建议清理」按 regime 预填 fold)。 */
  onSetFates?: (ids: string[], fate: Fate | null) => void;
}) {
  const [mode, setMode] = useState<TreemapMode>("proportional");
  // 主视图主轴:默认「轮次」(turn 优先,见 turn-band.md);「类型」一键回旧树图。
  const [view, setView] = useState<ViewKind>("turn");
  // Stage 3 关键词追踪:被点选的 token(null=未追踪)。其出现块从 activeGraph.keywords 解析。
  const [tracedKey, setTracedKey] = useState<string | null>(null);
  // 第二刀主题着色:按需拉取 regime 逐轮 topic。着色数据带上拉取时的 historyVersion,
  // 渲染时比对当前值判**新鲜度**(snapshot 推进则失效)——纯派生,无失效 effect。
  const [colorOn, setColorOn] = useState(false);
  const [colorBusy, setColorBusy] = useState(false);
  const [colorData, setColorData] = useState<{
    hv: number | undefined;
    topics: ChunkTopicMap;
    regime: string;
    focus: string;
    engine: string;
    /** 按线程定色后的 chunkId→色(主线收 focus 一色 / 支线按 topic);TurnBand 按 cell.repId 直查。 */
    cellColors: Record<string, string>;
    /** v2 引用图(层① 工具溯源边);后端旧版/建图失败 → null。增量③ TurnBand 弧叠加消费。 */
    referenceGraph: ReferenceGraph | null;
  } | null>(null);
  // 阶段 3「应用」本地状态:确认/进行中、上次释放量(供撤销)、错误。
  // action 原子化:一次只 drop 或只 fold,applyKind 记当前确认/进行中的动作。
  const [applyPhase, setApplyPhase] = useState<"idle" | "confirm" | "running">(
    "idle",
  );
  const [applyKind, setApplyKind] = useState<"drop" | "fold">("drop");
  const [foldPrompt, setFoldPrompt] = useState("");
  const [applyError, setApplyError] = useState<string | null>(null);
  const [lastFreed, setLastFreed] = useState<number | null>(null);
  const { budget, used, percent, compactions, chunks } = snapshot;
  // 「压缩 ×N」用真实累计次数(一轮多次压缩,推断的事件数组会少计)。
  const compactCount = snapshot.compressionCount ?? compactions.length;
  const ready = budget > 0;
  const tone = occupancyTone(percent);
  const hasChunks = chunks.length > 0;
  const lastDrop = compactions.length ? compactions[compactions.length - 1].removed : 0;

  // 命运投影（纯函数,无副作用）:预计释放量 + 应用后占用。
  const projected = projectFates(snapshot, fateMap);
  const projTone = occupancyTone(projected.projectedPercent);
  const markSummary = [
    projected.counts.drop && `丢弃×${projected.counts.drop}`,
    projected.counts.fold && `折叠×${projected.counts.fold}`,
    projected.counts.keep && `保留×${projected.counts.keep}`,
  ]
    .filter(Boolean)
    .join(" ");

  // 阶段 3 / A-v2:可落地的 drop / fold（仅 message 背书的块）+ 真实会话 id 就绪才能应用。
  const droppable = droppableChunkIds(snapshot, fateMap);
  const foldable = foldableChunkIds(snapshot, fateMap);
  const canApply = droppable.length > 0 && !!snapshot.sessionId;
  const canFold = foldable.length > 0 && !!snapshot.sessionId;

  const humanizeApplyError = (e: unknown): string => {
    const m = e instanceof Error ? e.message : String(e);
    if (/busy/i.test(m)) return "对话进行中，请等当前轮结束再应用";
    if (/stale|changed|advanced/i.test(m)) return "上下文已更新，请刷新后重试";
    if (/summary unavailable/i.test(m)) return "摘要生成失败，请稍后重试";
    return m;
  };

  // 进入确认态:记下动作种类(drop/fold),action 原子化。
  const startConfirm = (kind: "drop" | "fold") => {
    setApplyKind(kind);
    setApplyError(null);
    setApplyPhase("confirm");
  };

  const doApply = async () => {
    if (!snapshot.sessionId) return;
    setApplyPhase("running");
    setApplyError(null);
    try {
      const res = await applyDrops(
        snapshot.sessionId,
        snapshot.historyVersion,
        droppable,
      );
      setLastFreed(Math.max(0, res.before_tokens - res.after_tokens));
      onClearFates();
    } catch (e) {
      setApplyError(humanizeApplyError(e));
    } finally {
      setApplyPhase("idle");
    }
  };

  const doFold = async () => {
    if (!snapshot.sessionId) return;
    setApplyPhase("running");
    setApplyError(null);
    try {
      const res = await applyFold(
        snapshot.sessionId,
        snapshot.historyVersion,
        foldable,
        foldPrompt.trim(),
      );
      setLastFreed(Math.max(0, res.before_tokens - res.after_tokens));
      setFoldPrompt("");
      onClearFates();
    } catch (e) {
      setApplyError(humanizeApplyError(e));
    } finally {
      setApplyPhase("idle");
    }
  };

  const doUndo = async () => {
    if (!snapshot.sessionId) return;
    setApplyError(null);
    try {
      await undoApply(snapshot.sessionId);
      setLastFreed(null);
    } catch (e) {
      setApplyError(humanizeApplyError(e));
    }
  };

  // ── 压缩闸门(auto-compress 拦截预览)──────────────────────────────
  // 用"已应答的那个 pending 对象引用"判定,而非布尔 + effect(避开
  // react-hooks/set-state-in-effect)。adapter 每来一份新待决态都是新对象引用,
  // 故新闸门自动重新激活;应答后记下当前引用即隐藏;后端 re-emit 清空 pending。
  const pending = snapshot.pendingCompaction;
  const [respondedPending, setRespondedPending] =
    useState<typeof pending>(undefined);
  // 已应答的选择:用于在"应答后→压缩后快照到达前"那段沉默期显示「应用中」spinner
  // (后端跑 _generate_summary 可达数秒)。沿用 pending 引用比较,无 effect。
  const [respondedChoice, setRespondedChoice] = useState<CompactionChoice | null>(null);
  const gateActive = !!pending && pending !== respondedPending;
  // 应用中 = 已对**当前这份** pending 应答(引用相等)、且非"推迟"(推迟不触发后端工作);
  // 新快照到达 → pending 变新引用/清空 → 自动转 false。gateActive 与 applying 互斥。
  const applying =
    !!pending &&
    pending === respondedPending &&
    respondedChoice !== null &&
    respondedChoice !== "defer";
  const applyingLabel =
    respondedChoice === "edit_only"
      ? "正在删除…"
      : respondedChoice === "continue"
        ? "正在压缩…"
        : "正在应用计划…";
  // 闸门激活时,treemap 画"系统的压缩计划"叠加用户的编辑(二阶段闸门内编辑,用户标记
  // 覆盖系统计划:加折/取消折/删除)→ band/inspector 上看得见有效计划;否则画用户自己的标记。
  const effectiveFateMap = gateActive
    ? { ...pending!.systemFate, ...fateMap }
    : fateMap;
  // 闸门内编辑(二阶段,方案 A):有效计划 = systemFate 中段折 ∪ 用户加折 − 用户 keep。
  // 「应用计划」按这份**有效** fold/drop 列表落地;「仅删除」只取用户自标的 drop(不折)。
  const gateFolds = gateActive ? foldableChunkIds(snapshot, effectiveFateMap) : [];
  const gateDrops = gateActive ? droppableChunkIds(snapshot, effectiveFateMap) : [];
  const userDrops = gateActive ? droppableChunkIds(snapshot, fateMap) : [];
  const userEdited = gateActive && Object.keys(fateMap).length > 0;
  // 系统已有可落地建议(死重折 / 残值删)→ 即便用户没编辑,也该让「应用计划」可见、可一键接受。
  // 否则系统预填的残值 drop / 死重 fold 无处落地(「直接压缩」只走位置式)。
  const systemSuggested =
    gateActive &&
    ((pending?.deadweightTurns ?? 0) > 0 || (pending?.residualDrops ?? 0) > 0);
  const canApplyPlan = userEdited || systemSuggested;
  // 编辑后的占用投影(确认前看得见效果);未编辑回落系统估算。
  // 有可落地计划(用户编辑或系统建议)→ 按**有效**计划投影(含残值 drop 的全量释放);
  // 否则回落后端 estAfter(仅位置式折,后端未计残值)。
  const gatePlanPercent = canApplyPlan
    ? projectFates(snapshot, effectiveFateMap).projectedPercent
    : (pending?.estAfterPercent ?? 0);

  const respondGate = async (choice: CompactionChoice) => {
    setRespondedPending(pending); // 乐观隐藏;后端 re-emit 会清 pendingCompaction
    setRespondedChoice(choice); // 驱动「应用中」spinner(非 defer 时)
    const editing = choice === "apply_plan" || choice === "edit_only";
    if (editing) onClearFates(); // 应用后 chunk id 会变,清掉残留标记
    // 兜底:万一压缩后快照没回来(emit 失败),60s 后撤掉 spinner,不让它永转。
    if (choice !== "defer") {
      window.setTimeout(() => setRespondedChoice(null), 60_000);
    }
    if (snapshot.sessionId) {
      try {
        await respondCompaction(
          snapshot.sessionId,
          choice,
          choice === "apply_plan" ? gateDrops : choice === "edit_only" ? userDrops : undefined,
          choice === "apply_plan" ? gateFolds : undefined,
        );
      } catch {
        /* 失败也别卡住:超时后端会按 continue 自动压 */
      }
    }
  };

  // 调试钩子:console 里敲 __cvRegime() 即对当前 session 跑任务态检测器,
  // 打印完整拆解 + linking_tokens 表(看谁把无关 turn 串成了假主线)。
  const sid = snapshot.sessionId;
  useEffect(() => {
    if (!sid) return;
    (window as unknown as Record<string, unknown>).__cvRegime = async () => {
      const r = await debugRegime(sid);
      console.log("[regime]", r);
      const lt = (r as { linking_tokens?: unknown }).linking_tokens;
      if (Array.isArray(lt)) console.table(lt);
      const turns = (r as { turns?: unknown }).turns;
      if (Array.isArray(turns)) console.table(turns);
      return r;
    };
  }, [sid]);

  // 着色新鲜度:仅用于按钮文案(hv 推进 → 提示"重新着色"可纳入最新轮);**不再门控显示**。
  // 显示一旦着色就**持续**(跨普通新轮/压缩后的 hv 二次跳动都不回退);chunkId 重构(压缩/删/折)
  // 由下方"结构变更重取"effect 兜底贴合新历史。见 turn-band.md §4 / roadmap §6。
  const colorsFresh = !!colorData && colorData.hv === snapshot.historyVersion;
  const wantColor = colorOn || gateActive;
  const activeTopics = wantColor && colorData ? colorData.topics : null;
  const activeCellColors = wantColor && colorData ? colorData.cellColors : null;
  const activeMeta = wantColor && colorData ? colorData : null;
  // 引用图随着色一并就绪(同一 regime_colors 往返);wantColor 关 → 不画弧。
  const activeGraph = wantColor && colorData ? colorData.referenceGraph : null;
  // Stage 3 产物/关键词索引(随引用图一并就绪);点一项 → tracedChunks 喂 TurnCanvas 高亮+贯穿路径。
  // 产物优先(文件路径,按 token 量级)在前、关键词(salient token)在后;tracedKey 在两者里找。
  // 解析不到(着色关/会话推进)→ tracedChunks=null,画布自动退出追踪态。
  const activeFiles = activeGraph?.files ?? [];
  const activeKeywords = activeGraph?.keywords ?? [];
  const tracedFile = tracedKey
    ? activeFiles.find((f) => f.key === tracedKey) ?? null
    : null;
  const tracedKeyword = tracedKey
    ? activeKeywords.find((k) => k.key === tracedKey) ?? null
    : null;
  const tracedEntry = tracedFile
    ? { key: tracedFile.key, n: tracedFile.chunks.length, chunks: tracedFile.chunks }
    : tracedKeyword;
  const tracedChunks = tracedEntry ? new Set(tracedEntry.chunks) : null;
  // 着色是否已过期 = 此前着色的某 chunkId 在当前 chunks 中消失(= 压缩/删/折重构了 id)。
  // 与下方"结构变更重取"effect **同判据**:为真即后台正按新历史重检测着色(此刻仍显示旧色),
  // 据此给用户一个"主题检测中"的提示——纯 render 派生,无 effect 置态,lint 安全。
  const colorStale = (() => {
    if (!wantColor || !colorData) return false;
    const ids = new Set(snapshot.chunks.map((c) => c.id));
    return Object.keys(colorData.topics).some((id) => !ids.has(id));
  })();
  // 着色后台在跑(显式按钮/建议清理触发的 colorBusy,或压缩后结构重取的 colorStale)→ 提示。
  const coloringPending = wantColor && (colorBusy || colorStale);

  const loadColors = async () => {
    if (!sid) return;
    setColorBusy(true);
    try {
      const r = await fetchRegimeColors(sid);
      setColorData(buildColorData(r, snapshot.historyVersion, sid));
    } catch {
      setColorData(null);
    } finally {
      setColorBusy(false);
    }
  };

  // 闸门一弹 → 自动拉取着色(此刻 assess 已在缓存,命中即免费;闸门与着色同一个脑)。
  // 异步 fetch、在 .then 里 setState(非 effect 体内同步置态),lint 安全。
  useEffect(() => {
    if (!gateActive || !sid) return;
    let cancelled = false;
    fetchRegimeColors(sid)
      .then((r) => {
        if (cancelled) return;
        setColorData(buildColorData(r, snapshot.historyVersion, sid));
        setColorOn(true); // 粘滞:关闸/压缩后仍保持着色(否则 wantColor 回 false → 中性)
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [gateActive, sid, snapshot.historyVersion]);

  // 结构变更自动重取着色:仅当**此前着过色的某个 chunkId 在当前 chunks 中消失**(= 压缩 / 删除 /
  // 折叠重构了 chunkId,**纯追加新轮不会**)才重取一次,贴合新历史。追加 → 旧 id 仍在 → 不取(零逐轮成本)。
  // 这比"按压缩次数"更稳:压缩后 hv 会二次跳动,而结构判据只认 chunkId 实际变化。注册表保证重取颜色一致。
  useEffect(() => {
    if (!colorOn || !sid || !colorData) return;
    const currentIds = new Set(snapshot.chunks.map((c) => c.id));
    const structural = Object.keys(colorData.topics).some((id) => !currentIds.has(id));
    if (!structural) return;
    let cancelled = false;
    fetchRegimeColors(sid)
      .then((r) => {
        if (cancelled) return;
        setColorData(buildColorData(r, snapshot.historyVersion, sid));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [snapshot.chunks, colorData, colorOn, sid, snapshot.historyVersion]);

  const toggleColor = () => {
    if (colorOn && colorsFresh) {
      setColorOn(false); // 已新鲜着色 → 关
    } else {
      setColorOn(true); // 未着色 / 已失效 → 开并(按需)重取
      if (!colorsFresh) loadColors();
    }
  };

  // R 后续②「建议清理」:跑 regime → 挑「已完成的支线」(done ∧ 非主线 ∧ message-backed)→
  // 预填 fateMap=fold + 顺带着色;此后复用既有 fate 预览 +「应用 fold (N)」落地。
  // 检测层只产"选什么",落地一行不改(铁律)。
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  const suggestCleanup = async () => {
    if (!sid || !onSetFates) return;
    setSuggestBusy(true);
    setSuggestNote(null);
    try {
      const r = await fetchRegimeColors(sid);
      setColorData(buildColorData(r, snapshot.historyVersion, sid));
      setColorOn(true); // 顺带着色,让用户复核时看清主题分布
      const msgBacked = new Set(
        chunks.filter((c) => MESSAGE_BACKED_TYPES.has(c.type)).map((c) => c.id),
      );
      const ids = Object.entries(r.chunk_topics)
        .filter(([id, v]) => v.done && !v.mainline && msgBacked.has(id))
        .map(([id]) => id);
      if (ids.length > 0) {
        onSetFates(ids, "fold");
      } else {
        setSuggestNote(
          r.engine === "llm"
            ? "未发现已完成的支线可折"
            : "需语义检测(开启 LLM)才能建议清理",
        );
      }
    } catch {
      setSuggestNote("建议清理失败，请重试");
    } finally {
      setSuggestBusy(false);
    }
  };

  return (
    <Card className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-display text-xs tracking-wider text-text-tertiary">context</div>
        <div className="flex items-center gap-2">
          {hasChunks && <ViewToggle view={view} onChange={setView} />}
          {hasChunks && view === "turn" && (
            <button
              type="button"
              onClick={toggleColor}
              disabled={colorBusy}
              className={cn(
                "rounded border border-current/15 px-1.5 py-0.5 text-[10px] tracking-wide transition-colors",
                wantColor && colorsFresh
                  ? "bg-current/15 text-text-secondary"
                  : "text-text-tertiary hover:text-text-secondary",
              )}
              title="按 regime 逐轮主题着色（按需，调用辅助模型；闸门触发时自动着色；新一轮对话后失效）"
            >
              {colorBusy
                ? "分析中…"
                : colorOn && !colorsFresh
                  ? "重新着色"
                  : "主题着色"}
            </button>
          )}
          {hasChunks && view === "turn" && onSetFates && (
            <button
              type="button"
              onClick={suggestCleanup}
              disabled={suggestBusy || colorBusy}
              className="rounded border border-current/15 px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary transition-colors hover:text-text-secondary"
              title="按 regime 自动挑出「已完成的支线」预填折叠，复核后点「应用 fold」（调用辅助模型）"
            >
              {suggestBusy ? "分析中…" : "建议清理"}
            </button>
          )}
          {hasChunks && <ModeToggle mode={mode} onChange={setMode} />}
          {ready && (
            <span className={cn("text-sm font-medium tabular-nums", tone.text)}>{percent}%</span>
          )}
          {onCollapse && (
            <button
              type="button"
              onClick={onCollapse}
              aria-label="collapse context panel"
              className="-mr-1 rounded p-0.5 text-text-tertiary hover:text-text-secondary"
            >
              <ChevronUp className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {!ready ? (
        <div className="py-2 text-center text-xs text-text-secondary">等待上下文…</div>
      ) : (
        <>
          {/* 压缩闸门：auto-compress 拦截预览。treemap 已画系统计划(中段折叠/首尾保留)。 */}
          {gateActive && (
            <div className="flex flex-col gap-1.5 rounded border border-warning/40 bg-warning/10 px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-xs font-medium text-warning">
                <span className="text-display tracking-wider">上下文将压缩</span>
                <span className="tabular-nums text-text-secondary">
                  {pending!.currentPercent}%
                  <span className="text-text-tertiary">→</span>
                  ~{gatePlanPercent}%
                  {userEdited && (
                    <span className="ml-1 text-[10px] text-text-tertiary">（按你的计划）</span>
                  )}
                </span>
              </div>
              {pending!.regime === "task" && (
                <div className="text-[10px] leading-snug text-text-tertiary">
                  检测到主线任务 · 本次压缩将触及主线,故请你把关(森林态会静默自动压)。
                </div>
              )}
              {pending!.focus && (
                <div className="text-[10px] leading-snug text-text-tertiary">
                  将按焦点压缩:
                  <span className="text-text-secondary">{pending!.focus}</span>
                </div>
              )}
              {(pending!.deadweightTurns ?? 0) > 0 && (
                <div className="text-[10px] leading-snug text-text-tertiary">
                  其中{" "}
                  <span className="text-text-secondary">
                    {pending!.deadweightTurns} 个为已完成支线
                  </span>
                  （语义识别，含首尾，折它们最安全）+ 位置式中段。
                </div>
              )}
              {(pending!.residualDrops ?? 0) > 0 && (
                <div className="text-[10px] leading-snug text-text-tertiary">
                  另有{" "}
                  <span className="text-destructive">
                    {pending!.residualDrops} 处残值建议丢弃
                  </span>
                  （被取代旧读 / 失败工具 / 闲聊，轮次版红角标，可在下方取消）。
                </div>
              )}
              <div className="text-[11px] leading-snug text-text-secondary">
                系统计划:折叠 {pending!.foldTurns} 轮为摘要
                <span className="text-text-tertiary">
                  （预计释放 ~
                  {formatTokenCount(
                    Math.max(0, pending!.currentTokens - pending!.estAfterTokens),
                  )}
                  ）
                </span>
                。下方 treemap 命运沟已画出折/留。
              </div>
              <div className="text-[10px] leading-snug text-text-tertiary">
                {userEdited
                  ? `已编辑计划：折 ${gateFolds.length} 块 / 删 ${gateDrops.length} 块 —— 「应用计划」直接落地`
                  : systemSuggested
                    ? `系统已备计划：折 ${gateFolds.length} 块 / 删 ${gateDrops.length} 块 —— 「应用计划」一键落地，或在下方/右栏微调。`
                    : "可在下方/右栏标记：加折支线、取消折中段某轮、或删掉垃圾，再「应用计划」。"}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => respondGate("continue")}
                  className="rounded bg-warning/90 px-2 py-0.5 text-[11px] font-medium tracking-wide text-black hover:bg-warning"
                >
                  直接压缩
                </button>
                {canApplyPlan && (
                  <button
                    type="button"
                    onClick={() => respondGate("apply_plan")}
                    className="rounded border border-warning/50 px-2 py-0.5 text-[11px] tracking-wide text-warning hover:bg-warning/10"
                  >
                    应用计划（折{gateFolds.length}删{gateDrops.length}）
                  </button>
                )}
                {userDrops.length > 0 && (
                  <button
                    type="button"
                    onClick={() => respondGate("edit_only")}
                    className="rounded border border-destructive/50 px-2 py-0.5 text-[11px] tracking-wide text-destructive hover:bg-destructive/10"
                  >
                    仅删除 ({userDrops.length})
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => respondGate("defer")}
                  className="rounded border border-current/25 px-2 py-0.5 text-[11px] tracking-wide text-text-secondary hover:text-text-primary"
                >
                  推迟
                </button>
              </div>
            </div>
          )}

          {/* 应用中:应答后→压缩后快照到达前的沉默期(后端跑摘要可达数秒),给在途反馈。 */}
          {applying && (
            <div className="flex items-center gap-1.5 rounded border border-warning/40 bg-warning/10 px-2 py-1.5 text-xs text-warning">
              <span
                className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-warning border-t-transparent"
                aria-hidden
              />
              <span className="text-display tracking-wider">{applyingLabel}</span>
              <span className="text-[10px] text-text-tertiary">
                生成摘要 / 重组上下文中，完成后下方 treemap 会回落
              </span>
            </div>
          )}

          {/* 占用对抗上限：始终可读的细条。 */}
          <div
            className="relative h-2 w-full overflow-hidden rounded-full bg-current/10"
            role="meter"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="context occupancy"
          >
            <div
              className={cn("h-full rounded-full transition-[width] duration-300", tone.bar)}
              style={{ width: `${Math.max(2, Math.min(100, percent))}%` }}
            />
            {/* 命运预览:将释放区(虚化)+ 幽灵目标刻度,直观看占用会降到哪。 */}
            {projected.hasMarks && projected.freed > 0 && (
              <>
                <div
                  className="absolute inset-y-0 bg-background-base/55"
                  style={{
                    left: `${projected.projectedPercent}%`,
                    width: `${Math.max(0, percent - projected.projectedPercent)}%`,
                  }}
                />
                <div
                  className="absolute inset-y-0 w-px bg-current/70"
                  style={{ left: `${projected.projectedPercent}%` }}
                />
              </>
            )}
          </div>

          <div className="flex items-center justify-between text-xs tabular-nums text-text-secondary">
            <span>
              {formatTokenCount(used)}
              <span className="text-text-tertiary"> / {formatTokenCount(budget)}</span>
            </span>
            {compactCount > 0 && (
              <span className="text-text-tertiary">
                压缩 ×{compactCount}
                {lastDrop > 0 && (
                  <span className="text-destructive"> −{formatTokenCount(lastDrop)}</span>
                )}
              </span>
            )}
          </div>

          {/* 命运预览行：标记构成 + 预计释放 + 占用投影 + 清除。 */}
          {projected.hasMarks && (
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="min-w-0 truncate tabular-nums text-text-secondary">
                {markSummary} · 预计释放{" "}
                <span className="text-warning">~{formatTokenCount(projected.freed)}</span>
                {projected.freed > 0 && (
                  <>
                    {" "}· <span className={tone.text}>{percent}%</span>
                    <span className="text-text-tertiary">→</span>
                    <span className={projTone.text}>{projected.projectedPercent}%</span>
                  </>
                )}
              </span>
              <div className="flex shrink-0 items-center gap-1">
                {applyPhase === "idle" && canFold && (
                  <button
                    type="button"
                    onClick={() => startConfirm("fold")}
                    className="rounded border border-warning/40 px-1.5 py-0.5 text-[10px] tracking-wide text-warning hover:bg-warning/10"
                  >
                    应用 fold ({foldable.length})
                  </button>
                )}
                {applyPhase === "idle" && canApply && (
                  <button
                    type="button"
                    onClick={() => startConfirm("drop")}
                    className="rounded border border-destructive/40 px-1.5 py-0.5 text-[10px] tracking-wide text-destructive hover:bg-destructive/10"
                  >
                    应用 drop ({droppable.length})
                  </button>
                )}
                {applyPhase === "confirm" && (
                  <>
                    <button
                      type="button"
                      onClick={applyKind === "fold" ? doFold : doApply}
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] tracking-wide text-white",
                        applyKind === "fold"
                          ? "bg-warning/90 hover:bg-warning"
                          : "bg-destructive/90 hover:bg-destructive",
                      )}
                    >
                      {applyKind === "fold" ? "确认折叠" : "确认删除"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setApplyPhase("idle")}
                      className="rounded px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary hover:text-text-secondary"
                    >
                      取消
                    </button>
                  </>
                )}
                {applyPhase === "running" && (
                  <span className="px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary">
                    {applyKind === "fold" ? "折叠中…" : "应用中…"}
                  </span>
                )}
                <button
                  type="button"
                  onClick={onClearFates}
                  className="rounded px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary hover:text-text-secondary"
                >
                  清除标记
                </button>
              </div>
            </div>
          )}

          {/* 确认态明细（不可逆操作透明）。fold 多一个"重心 prompt"输入框。 */}
          {applyPhase === "confirm" && applyKind === "drop" && (
            <div className="text-[10px] leading-snug text-text-tertiary">
              将从真实上下文删除 {droppable.length} 块 · ~
              {formatTokenCount(projected.freed)} tok，<span className="text-destructive">不可逆</span>
              （可一步撤销）。
            </div>
          )}
          {applyPhase === "confirm" && applyKind === "fold" && (
            <div className="flex flex-col gap-1">
              <input
                type="text"
                value={foldPrompt}
                onChange={(e) => setFoldPrompt(e.target.value)}
                placeholder="可选：摘要重心，如『只留与 X 函数相关的结论』"
                className="w-full rounded border border-current/15 bg-current/5 px-1.5 py-1 text-[11px] text-text-secondary placeholder:text-text-tertiary focus:border-warning/50 focus:outline-none"
              />
              <div className="text-[10px] leading-snug text-text-tertiary">
                将把 {foldable.length} 块折成一条摘要 · 跑辅助模型，约数秒 ·{" "}
                <span className="text-warning">不可逆</span>（可一步撤销）。
              </div>
            </div>
          )}
          {lastFreed !== null && (
            <div className="flex items-center justify-between gap-2 text-xs text-text-secondary">
              <span className="tabular-nums">
                已释放 <span className="text-success">~{formatTokenCount(lastFreed)}</span>
              </span>
              <button
                type="button"
                onClick={doUndo}
                className="shrink-0 rounded border border-current/20 px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary hover:text-text-secondary"
              >
                撤销
              </button>
            </div>
          )}
          {applyError && (
            <div className="flex items-center justify-between gap-2 text-[11px] text-destructive">
              <span className="min-w-0">{applyError}</span>
              <button
                type="button"
                onClick={() => setApplyError(null)}
                aria-label="dismiss error"
                className="shrink-0 rounded px-1 text-text-tertiary hover:text-text-secondary"
              >
                ✕
              </button>
            </div>
          )}

          {view === "turn" && activeMeta && (
            <div className="text-[10px] text-text-tertiary">
              {activeMeta.regime === "task"
                ? `主线: ${activeMeta.focus || "—"}`
                : "森林（无主线）"}
              {" · "}
              {activeMeta.engine === "llm" ? "语义" : "启发式"}
            </div>
          )}
          {/* 着色后台在跑(压缩后结构重取 / 显式着色)→ 提示,避免用户误以为当前颜色已是最终态。 */}
          {view === "turn" && coloringPending && (
            <div className="flex items-center gap-1 text-[10px] text-warning">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
              {colorStale ? "主题已变,正在重测着色…" : "主题检测中…"}
            </div>
          )}
          {suggestNote && (
            <div className="text-[10px] text-text-tertiary">{suggestNote}</div>
          )}
          {/* 引用图图例:白盒要求每条连线可解释(#6)。常驻说明实线/虚线/红蓝的含义,
              具体共享来由(文件/token)悬停弧看。仅 turn 带 + 有边时显示。 */}
          {view === "turn" && activeGraph && activeGraph.edges.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-text-tertiary">
              <span className="text-text-secondary">引用图</span>
              <span className="inline-flex items-center gap-1">
                <svg width={16} height={6} aria-hidden="true">
                  <line x1={1} y1={3} x2={15} y2={3} className="stroke-current/70" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                </svg>
                工具(写→读/修订)
              </span>
              <span className="inline-flex items-center gap-1">
                <svg width={16} height={6} aria-hidden="true">
                  <line x1={1} y1={3} x2={15} y2={3} className="stroke-current/70" strokeWidth={1.5} strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
                </svg>
                文字共现
              </span>
              <span className="inline-flex items-center gap-1">
                <svg width={16} height={6} aria-hidden="true">
                  <line x1={1} y1={3} x2={15} y2={3} className="stroke-rose-500" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                </svg>
                下游
              </span>
              <span className="inline-flex items-center gap-1">
                <svg width={16} height={6} aria-hidden="true">
                  <line x1={1} y1={3} x2={15} y2={3} className="stroke-sky-500" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                </svg>
                上游
              </span>
              <span className="text-text-tertiary/70">选中轮高亮 · 悬停弧看共享来由</span>
            </div>
          )}
          {/* 关键词追踪态提示:解释画布上的紫色贯穿路径来由(白盒 #6:每条连线可解释)。 */}
          {view === "turn" && tracedEntry && (
            <div
              className="flex items-center gap-1.5 text-[10px]"
              style={{ color: TRACE_COLOR }}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: TRACE_COLOR }}
              />
              追踪「{tracedEntry.key}」· {tracedEntry.n} 块高亮 + 贯穿路径(紫线）· 右栏再点取消
            </div>
          )}
          <div className="flex min-h-0 flex-1 gap-2">
            <div className="min-h-0 flex-1">
            {hasChunks &&
              (view === "turn" ? (
                USE_CANVAS ? (
                  <TurnCanvas
                    snapshot={snapshot}
                    selected={selected}
                    onSelect={onSelect}
                    chunkTopics={activeTopics}
                    fateMap={effectiveFateMap}
                    onActivateTurn={onActivateTurn}
                    referenceGraph={activeGraph}
                    tracedChunks={tracedChunks}
                  />
                ) : (
                  <ContextVisTurnBand
                    snapshot={snapshot}
                    mode={mode}
                    selected={selected}
                    onSelect={onSelect}
                    chunkTopics={activeTopics}
                    cellColors={activeCellColors}
                    onActivateTurn={onActivateTurn}
                    fateMap={effectiveFateMap}
                    fateReasons={gateActive ? pending?.fateReasons : undefined}
                    gateActive={gateActive}
                    referenceGraph={activeGraph}
                  />
                )
              ) : (
                <ContextVisTreemap
                  snapshot={snapshot}
                  mode={mode}
                  selected={selected}
                  onSelect={onSelect}
                  fateMap={effectiveFateMap}
                />
              ))}
            </div>
            {hasChunks &&
              view === "turn" &&
              USE_CANVAS &&
              (activeFiles.length > 0 || activeKeywords.length > 0) && (
                <ContextVisKeywordIndex
                  files={activeFiles}
                  keywords={activeKeywords}
                  traced={tracedKey}
                  onTrace={setTracedKey}
                />
              )}
          </div>

          <ContextVisSparkline snapshot={snapshot} />
        </>
      )}
    </Card>
  );
}
