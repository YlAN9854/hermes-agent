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
import { useEffect, useRef, useState } from "react";

import { formatTokenCount } from "@/lib/format";
import { squarify } from "@/lib/contextvis/treemap";
import { buildTurnCells, type TurnCell } from "@/lib/contextvis/turns";
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
} from "@/lib/contextvis/apply";
import { respondCompaction, type CompactionChoice } from "@/lib/contextvis/gate";
import type {
  ChunkType,
  ContextChunk,
  ContextSnapshot,
} from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

type TreemapMode = "proportional" | "actual";
/** 主视图主轴:类型带(旧树图)⇄ 轮次带(纵向时间序)。见 context-vis/turn-band.md。 */
type ViewKind = "type" | "turn";

/** turn 带配色(本刀不按主题着色;仅区分系统底座 / 对话轮 / 折叠产物)。 */
const TURN_BASE_COLOR = "#8b7fd4"; // 系统底座 = system 紫
const TURN_CELL_COLOR = "#7d8aa3"; // 对话轮 = history 灰蓝
const TURN_FOLD_COLOR = "#565d6b"; // 已折叠摘要 = 压暗灰(虚线边区分)

/** 主题着色色板(第二刀):逐轮 topic 各分一色;mainline 饱和、offthread 靠透明度压暗。 */
const TOPIC_PALETTE = [
  "#d98c5f", "#5fa8a0", "#8b7fd4", "#6fae7a",
  "#c97b9c", "#7d9cc4", "#c0a85f", "#9c7bc9",
];

type ChunkTopicMap = RegimeColors["chunk_topics"];

/** 主题键归一化:吸收 LLM 对同一主题的琐碎改名差异(trim / 小写 / 压空格)。 */
function normalizeTopic(t: string): string {
  return t.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * 持久「主题→色」注册表:**只增不洗**——首次见某主题分下一个空闲色并记下,以后复用,
 * 永不重排(根治旧版"排序下标法"一加新主题就整排重洗 + 每次从零重建无记忆)。
 *
 * 存 localStorage 按 sessionId(浮层折叠/展开会重挂载 panel,内存 ref 会丢 → 必须持久化;
 * 顺带扛页面重载)。归一化键吸收 LLM 改名。返回 **原始 topic 串 → color**(供按 `ct.topic` 原串查)。
 * localStorage 失败(隐私模式/配额)→ 退化为本次内存分配(仍比旧版稳)。
 */
function assignTopicColors(
  ct: ChunkTopicMap,
  sessionId: string | undefined,
): Record<string, string> {
  const key = sessionId ? `cv-topics:${sessionId}` : "";
  let reg: Record<string, string> = {};
  if (key) {
    try {
      reg = JSON.parse(localStorage.getItem(key) || "{}") || {};
    } catch {
      reg = {};
    }
  }
  const out: Record<string, string> = {};
  let dirty = false;
  for (const v of Object.values(ct)) {
    const topic = v.topic;
    if (!topic) continue;
    const norm = normalizeTopic(topic);
    if (!reg[norm]) {
      reg[norm] = TOPIC_PALETTE[Object.keys(reg).length % TOPIC_PALETTE.length];
      dirty = true;
    }
    out[topic] = reg[norm];
  }
  if (dirty && key) {
    try {
      localStorage.setItem(key, JSON.stringify(reg));
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
    colorMap: assignTopicColors(r.chunk_topics, sid),
  };
}
/** turn 格最小高度(保证极小轮仍可点;轻微破「高∝token」严格比例,见 doc §10)。 */
const TURN_MIN_H = 12;

/**
 * 第四刀:逐格聚合成员 chunk 的命运（纯函数,免在 .map 里改累加量触发 immutability 规则）。
 *   · full    = 该轮全部 message-backed 成员同一命运（整轮已标）→ 强叠加。
 *   · partial = 单一命运但未标全 → 弱提示（还没标全,诚实区分）。
 *   · mixed   = 成员标了不同命运 → 弱提示（中性）。
 * 底座/折叠块不参与（无可落地成员 / 已是压缩产物）。
 */
function aggregateCellFate(
  cell: TurnCell,
  typeById: Map<string, ChunkType>,
  fateMap: FateMap,
): { full: Fate | null; partial: Fate | null; mixed: boolean } {
  const none = { full: null, partial: null, mixed: false };
  if (cell.isBase || cell.isFolded) return none;
  const msgIds = cell.chunkIds.filter((id) => {
    const t = typeById.get(id);
    return t !== undefined && MESSAGE_BACKED_TYPES.has(t);
  });
  const marked = msgIds.map((id) => fateMap[id]).filter((f): f is Fate => !!f);
  if (marked.length === 0) return none;
  if (new Set(marked).size > 1) return { full: null, partial: null, mixed: true };
  const f = marked[0];
  return marked.length === msgIds.length
    ? { full: f, partial: null, mixed: false }
    : { full: null, partial: f, mixed: false };
}

/** 命运 → treemap 描边色（Tailwind 语义 token,与检视器按钮呼应）。 */
const FATE_STROKE: Record<Fate, string> = {
  keep: "stroke-success",
  fold: "stroke-warning",
  drop: "stroke-destructive",
};
/** 命运填充色（turn 带部分标记的左缘竖条）。 */
const FATE_FILL: Record<Fate, string> = {
  keep: "fill-success",
  fold: "fill-warning",
  drop: "fill-destructive",
};
const FATE_LABEL: Record<Fate, string> = {
  keep: "保留",
  fold: "折叠",
  drop: "丢弃",
};

/** 渲染带的顺序与配色（自顶向下；紫/teal 顶、绿文件、橙结果）。 */
const BANDS: { type: ChunkType; color: string }[] = [
  { type: "system", color: "#8b7fd4" },
  { type: "tool_schema", color: "#5fa8a0" },
  { type: "history", color: "#7d8aa3" },
  { type: "file", color: "#6fae7a" },
  { type: "tool_result", color: "#d39a5c" },
];

// treemap 坐标系：viewBox 贴近浮层实际像素宽度，减少 preserveAspectRatio="none"
// 带来的文字横向拉伸。
const VB_W = 408;
const VB_H = 320;
const LABEL_FS = 12;
const TOKEN_FS = 10;

function occupancyTone(percent: number): { bar: string; text: string } {
  if (percent >= 90) return { bar: "bg-destructive", text: "text-destructive" };
  if (percent >= 70) return { bar: "bg-warning", text: "text-warning" };
  return { bar: "bg-success", text: "text-success" };
}

/** 估算单元宽度能放下的字符数（viewBox 单位 ≈ 像素；字号 12 ≈ 7px/字）。 */
function fitText(label: string, w: number): string {
  const max = Math.floor((w - 8) / 7);
  if (max <= 1) return "";
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

function Treemap({
  snapshot,
  mode,
  selected,
  onSelect,
  fateMap,
}: {
  snapshot: ContextSnapshot;
  mode: TreemapMode;
  selected: string | null;
  onSelect: (id: string | null) => void;
  fateMap: FateMap;
}) {
  const { chunks, percent, budget, compactAt } = snapshot;
  const total = chunks.reduce((s, c) => s + c.tokens, 0);
  if (total <= 0) return null;

  const usedFrac =
    mode === "actual" ? Math.min(1, Math.max(0, percent / 100)) : 1;
  const fillH = VB_H * usedFrac;
  const fillTop = VB_H - fillH;

  const cells: {
    x: number;
    y: number;
    w: number;
    h: number;
    chunk: ContextChunk;
    color: string;
  }[] = [];

  let yCursor = fillTop;
  for (const band of BANDS) {
    const bandChunks = chunks.filter((c) => c.type === band.type);
    const bandTokens = bandChunks.reduce((s, c) => s + c.tokens, 0);
    if (bandTokens <= 0) continue;
    const bandH = (bandTokens / total) * fillH;
    const rects = squarify(
      bandChunks.map((c) => ({ value: c.tokens, data: c })),
      { x: 0, y: yCursor, w: VB_W, h: bandH },
    );
    for (const r of rects) {
      cells.push({ x: r.x, y: r.y, w: r.w, h: r.h, chunk: r.item, color: band.color });
    }
    yCursor += bandH;
  }

  // 实际占用模式：token 轴刻度 + compact 阈值线（都在 headroom 区，不挡 chunk）。
  const axis: { y: number; label: string }[] = [];
  let compactLineY: number | null = null;
  if (mode === "actual" && budget > 0) {
    for (const frac of [0.25, 0.5, 0.75, 1]) {
      axis.push({ y: VB_H - frac * VB_H, label: formatTokenCount(budget * frac) });
    }
    if (compactAt && compactAt > 0 && compactAt <= budget) {
      compactLineY = VB_H - (compactAt / budget) * VB_H;
    }
  }

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="none"
      className="h-[300px] w-full"
      role="img"
      aria-label="context composition treemap"
    >
      {mode === "actual" && (
        <>
          <rect x={0} y={0} width={VB_W} height={fillTop} className="fill-current/5" />
          {axis.map((a, i) => (
            <g key={`ax-${i}`}>
              <line
                x1={0}
                y1={a.y}
                x2={VB_W}
                y2={a.y}
                className="stroke-current/15"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={VB_W - 3}
                y={a.y + TOKEN_FS}
                fontSize={TOKEN_FS}
                textAnchor="end"
                className="pointer-events-none fill-current/40"
              >
                {a.label}
              </text>
            </g>
          ))}
          {compactLineY !== null && (
            <g>
              <line
                x1={0}
                y1={compactLineY}
                x2={VB_W}
                y2={compactLineY}
                className="stroke-warning"
                strokeDasharray="4 3"
                strokeWidth={1.25}
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={3}
                y={compactLineY - 3}
                fontSize={TOKEN_FS}
                className="pointer-events-none fill-warning"
              >
                compact
              </text>
            </g>
          )}
        </>
      )}
      {cells.map(({ x, y, w, h, chunk, color }) => {
        const isSel = chunk.id === selected;
        const fate = fateMap[chunk.id];
        const showLabel = w > 44 && h > 26;
        const label = fitText(chunk.label, w);
        // 命运叠加:drop 降不透明度 + 红斜划;fold 虚线边;keep 实线边。
        // 选中环优先(stroke-background-base@2),命运仍靠 dim/strike/dash 可辨。
        const fillOpacity = fate === "drop" ? 0.3 : isSel ? 0.95 : 0.8;
        const strokeClass = isSel
          ? "stroke-background-base"
          : fate
            ? FATE_STROKE[fate]
            : "stroke-background-base";
        return (
          <g
            key={chunk.id}
            onClick={() => onSelect(isSel ? null : chunk.id)}
            className="cursor-pointer"
          >
            <title>{`${chunk.label} · ${formatTokenCount(chunk.tokens)} tok${chunk.group ? ` · ${chunk.group}` : ""}${chunk.members && chunk.members > 1 ? ` · ${chunk.members} 项` : ""}${fate ? ` · 标记:${FATE_LABEL[fate]}` : ""}`}</title>
            <rect
              x={x}
              y={y}
              width={Math.max(0, w)}
              height={Math.max(0, h)}
              fill={color}
              fillOpacity={fillOpacity}
              className={strokeClass}
              strokeWidth={isSel ? 2 : fate ? 1.5 : 0.75}
              strokeDasharray={fate === "fold" ? "3 2" : undefined}
              vectorEffect="non-scaling-stroke"
            />
            {fate === "drop" && (
              <>
                <line
                  x1={x}
                  y1={y}
                  x2={x + w}
                  y2={y + h}
                  className="stroke-destructive"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
                <line
                  x1={x}
                  y1={y + h}
                  x2={x + w}
                  y2={y}
                  className="stroke-destructive"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              </>
            )}
            {showLabel && (
              <text
                x={x + 4}
                y={y + LABEL_FS + 1}
                fontSize={LABEL_FS}
                className="pointer-events-none fill-black/85"
              >
                {label}
                <tspan x={x + 4} dy={LABEL_FS + 1} className="fill-black/55" fontSize={TOKEN_FS}>
                  {formatTokenCount(chunk.tokens)}
                </tspan>
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * 轮次带（turn band）—— 纵向、与 TUI 同向的时间序视图。
 *
 * 主轴从「类型」翻成「turn」:按 chunk.turn 聚合,顶=系统底座→往下逐轮(顶老底新,
 * 与 TUI 滚动同向),格高 ∝ 该轮 token。占用模式下纵轴同时是占用轴(顶=0、底=budget,
 * 底部留余量 + compact 线)。本刀不按主题着色,只区分底座/对话轮。见 turn-band.md。
 */
function TurnBand({
  snapshot,
  mode,
  selected,
  onSelect,
  chunkTopics,
  topicColors,
  onActivateTurn,
  fateMap,
  gateActive = false,
}: {
  snapshot: ContextSnapshot;
  mode: TreemapMode;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** 第二刀主题着色:chunkId → {topic, mainline};null=未着色(中性结构)。 */
  chunkTopics: ChunkTopicMap | null;
  /** 持久注册表解析出的 主题→色(原始 topic 串);null=未着色。同主题跨多次着色稳定同色。 */
  topicColors: Record<string, string> | null;
  /** 第三刀:点对话轮 → 把 TUI 滚到该轮(底座/折叠块无锚点,不触发)。 */
  onActivateTurn?: (turn: number) => void;
  /** 第四刀:命运叠加(平时=用户标记;闸门时=systemFate 碰撞高亮)。逐格聚合成员命运。 */
  fateMap: FateMap;
  /** 死重喂闸门(点 3):闸门激活时,fold 格悬浮标来由(已完成支线 / 位置式中段)。 */
  gateActive?: boolean;
}) {
  const { percent, budget, compactAt } = snapshot;
  const cells = buildTurnCells(snapshot);
  // 第四刀:chunkId → 类型,用于逐格筛出 message-backed 成员(只有它们能被 fold/drop)。
  const typeById = new Map<string, ChunkType>();
  for (const c of snapshot.chunks) typeById.set(c.id, c.type);
  const total = cells.reduce((s, c) => s + c.tokens, 0);
  if (total <= 0) return null;

  const usedFrac =
    mode === "actual" ? Math.min(1, Math.max(0, percent / 100)) : 1;
  const fillH = VB_H * usedFrac;

  // 顶=最老(底座)→ 往下逐轮累积。布局:每格先得**保底高**,余下空间再按 token 占比分配,
  // 使所有格之和**恰为 fillH**——这样最小高不会累加溢出、把最新的轮挤出视口下沿(时间轴视图
  // 绝不能丢掉"现在",这正是 resume + 多轮时第三轮在带里消失的根因)。格太多(n·保底 > fillH)
  // 时保底自动缩小到 fillH/n,保证仍全部可见(代价:极端时比例略失真,见 doc §10)。
  // for-of 而非 .map:避免在渲染期闭包里改累加量(react-hooks/immutability)。
  const minH = Math.min(TURN_MIN_H, fillH / Math.max(1, cells.length));
  const extra = Math.max(0, fillH - minH * cells.length);
  const laid: { cell: TurnCell; y: number; h: number }[] = [];
  let yCursor = 0;
  for (const cell of cells) {
    const h = minH + (total > 0 ? (cell.tokens / total) * extra : 0);
    laid.push({ cell, y: yCursor, h });
    yCursor += h;
  }

  // 占用模式:底部余量(headroom)+ 仅在余量区画 token 轴刻度 + compact 阈值线
  // (顶=0 token、底=budget;不让刻度线穿过上方的 turn 格)。
  const axis: { y: number; label: string }[] = [];
  let compactLineY: number | null = null;
  if (mode === "actual" && budget > 0) {
    for (const frac of [0.25, 0.5, 0.75, 1]) {
      const y = frac * VB_H;
      if (y >= fillH) axis.push({ y, label: formatTokenCount(budget * frac) });
    }
    if (compactAt && compactAt > 0 && compactAt <= budget) {
      compactLineY = (compactAt / budget) * VB_H;
    }
  }

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="none"
      className="h-[300px] w-full"
      role="img"
      aria-label="context turn band"
    >
      {mode === "actual" && fillH < VB_H && (
        <rect x={0} y={fillH} width={VB_W} height={VB_H - fillH} className="fill-current/5" />
      )}
      {axis.map((a, i) => (
        <g key={`ax-${i}`}>
          <line
            x1={0}
            y1={a.y}
            x2={VB_W}
            y2={a.y}
            className="stroke-current/15"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={VB_W - 3}
            y={a.y - 2}
            fontSize={TOKEN_FS}
            textAnchor="end"
            className="pointer-events-none fill-current/40"
          >
            {a.label}
          </text>
        </g>
      ))}
      {compactLineY !== null && (
        <g>
          <line
            x1={0}
            y1={compactLineY}
            x2={VB_W}
            y2={compactLineY}
            className="stroke-warning"
            strokeDasharray="4 3"
            strokeWidth={1.25}
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={3}
            y={compactLineY - 3}
            fontSize={TOKEN_FS}
            className="pointer-events-none fill-warning"
          >
            compact
          </text>
        </g>
      )}
      {laid.map(({ cell, y, h }) => {
        const isSel = selected !== null && cell.chunkIds.includes(selected);
        const showLabel = h > 18;
        // 主题着色:对话轮(非底座/折叠)按 topic 取色;mainline 饱和、offthread 压暗。
        const ct =
          chunkTopics && !cell.isBase && !cell.isFolded
            ? chunkTopics[cell.repId]
            : undefined;
        const topicColor = ct && ct.topic ? topicColors?.[ct.topic] : undefined;
        const offthread = ct ? !ct.mainline : false;
        const fill = cell.isFolded
          ? TURN_FOLD_COLOR
          : cell.isBase
            ? TURN_BASE_COLOR
            : topicColor ?? TURN_CELL_COLOR;
        const baseOpacity = cell.isFolded
          ? 0.55
          : offthread
            ? 0.4
            : ct
              ? 0.9
              : 0.8;
        const label = fitText(
          cell.isFolded ? `⊟ ${cell.label}` : cell.label,
          VB_W - 56,
        );
        // 命运叠加(第四刀):整轮强叠加 / 部分·混合弱提示。闸门时 fateMap=systemFate → 碰撞高亮。
        const { full: fullFate, partial: partialFate, mixed: mixedMark } =
          aggregateCellFate(cell, typeById, fateMap);
        const hasPartial = partialFate !== null || mixedMark;
        const fateText = fullFate
          ? ` · 整轮标记:${FATE_LABEL[fullFate]}`
          : mixedMark
            ? " · 部分标记（混合）"
            : partialFate
              ? ` · 部分标记:${FATE_LABEL[partialFate]}`
              : "";
        const strokeClass = isSel
          ? "stroke-background-base"
          : fullFate
            ? FATE_STROKE[fullFate]
            : "stroke-background-base";
        // 死重喂闸门(点 3):闸门时 fold 格标来由——已完成支线(死重,语义识别)/ 位置式中段。
        const foldReason =
          gateActive && fullFate === "fold"
            ? ct && ct.done
              ? " · 建议折:已完成支线"
              : " · 建议折:位置式中段"
            : "";
        const tip = cell.isFolded
          ? `${cell.label}（压缩折叠产物）· ${formatTokenCount(cell.tokens)}`
          : `${cell.label} · ${formatTokenCount(cell.tokens)}${cell.isBase ? "" : ` · 第${cell.turn}轮`}${
              ct && ct.topic ? ` · ${ct.topic}${ct.mainline ? "（主线）" : "（支线）"}` : ""
            }${fateText}${foldReason}`;
        return (
          <g
            key={cell.isFolded ? cell.repId : `turn-${cell.turn}`}
            onClick={() => {
              onSelect(isSel ? null : cell.repId);
              // 对话轮才跳 TUI:底座/折叠块无终端锚点(见 plan §3b)。
              if (!cell.isBase && !cell.isFolded) onActivateTurn?.(cell.turn);
            }}
            className="cursor-pointer"
          >
            <title>{tip}</title>
            <rect
              x={0}
              y={y}
              width={VB_W}
              height={Math.max(0, h)}
              fill={fill}
              fillOpacity={
                fullFate === "drop"
                  ? 0.3
                  : fullFate === "fold"
                    ? 0.42 // 折叠=将被压缩→压暗后退(对比 keep 的满色,闸门里一眼分清)
                    : isSel
                      ? 0.95
                      : baseOpacity
              }
              className={strokeClass}
              strokeWidth={isSel ? 2 : fullFate ? 1.5 : cell.isFolded ? 1.25 : 0.75}
              strokeDasharray={
                cell.isFolded ? "4 3" : fullFate === "fold" ? "3 2" : undefined
              }
              vectorEffect="non-scaling-stroke"
            />
            {/* 整轮 drop:红斜划(照搬 Treemap),与压暗共同表"这一轮要删"。 */}
            {fullFate === "drop" && (
              <>
                <line
                  x1={0}
                  y1={y}
                  x2={VB_W}
                  y2={y + h}
                  className="stroke-destructive"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
                <line
                  x1={0}
                  y1={y + h}
                  x2={VB_W}
                  y2={y}
                  className="stroke-destructive"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              </>
            )}
            {/* 命运左缘竖条 = "命运沟":整轮命运 4px 实色(keep 绿/fold 橙/drop 红——
                闸门时每轮都被 systemFate 派了命运,这条沟让折/留一眼分清);部分/混合 3px
                弱提示(还没标全,诚实区分,不整格压暗)。 */}
            {(fullFate || hasPartial) && (
              <rect
                x={0}
                y={y}
                width={fullFate ? 4 : 3}
                height={Math.max(0, h)}
                className={
                  fullFate
                    ? FATE_FILL[fullFate]
                    : partialFate
                      ? FATE_FILL[partialFate]
                      : "fill-current/40"
                }
              />
            )}
            {showLabel && (
              <>
                <text
                  x={4}
                  y={y + LABEL_FS + 1}
                  fontSize={LABEL_FS}
                  className="pointer-events-none fill-black/85"
                >
                  {label}
                </text>
                <text
                  x={VB_W - 3}
                  y={y + LABEL_FS + 1}
                  fontSize={TOKEN_FS}
                  textAnchor="end"
                  className="pointer-events-none fill-black/55"
                >
                  {formatTokenCount(cell.tokens)}
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** 占用率 sparkline（占用率随轮次；压缩点描红）。 */
function Sparkline({ snapshot }: { snapshot: ContextSnapshot }) {
  const { history, compactions } = snapshot;
  if (history.length < 2) return null;
  const W = 240;
  const H = 28;
  const n = history.length;
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * W);
  const y = (p: number) => H - (Math.max(0, Math.min(100, p)) / 100) * H;
  const line = history
    .map((s, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(s.percent).toFixed(1)}`)
    .join(" ");
  const compactTurns = new Set(compactions.map((c) => c.turn));
  const marks = history
    .map((s, i) => (compactTurns.has(s.turn) ? { cx: x(i), cy: y(s.percent) } : null))
    .filter((m): m is { cx: number; cy: number } => m !== null);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-7 w-full" role="img" aria-label="occupancy over turns">
      <path d={`${line} L${W},${H} L0,${H} Z`} className="fill-current/10" />
      <path d={line} fill="none" className="stroke-current" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      {marks.map((m, i) => (
        <circle key={i} cx={m.cx} cy={m.cy} r={2.5} className="fill-destructive stroke-background-base" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
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
    /** 持久注册表解析出的 主题→色(原始 topic 串);TurnBand 直接查,不再排序下标分色。 */
    colorMap: Record<string, string>;
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
  // 编辑后的占用投影(确认前看得见效果);未编辑回落系统估算。
  const gatePlanPercent = userEdited
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

  // 着色新鲜度:数据的 hv 与当前一致才有效(snapshot 推进 → 自动失效,band 回中性)。
  // 闸门激活时**强制着色**(无须手点):压缩前的脑(assess)就是着色的脑,把关时
  // 直接带上"主线/支线"语义画面,理解"为什么问我"。见 regime.md / turn-band.md §4。
  const colorsFresh = !!colorData && colorData.hv === snapshot.historyVersion;
  const wantColor = colorOn || gateActive;
  const activeTopics = wantColor && colorsFresh ? colorData!.topics : null;
  const activeColorMap = wantColor && colorsFresh ? colorData!.colorMap : null;
  const activeMeta = wantColor && colorsFresh ? colorData : null;

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

  // 压缩后自动重取着色:压缩重写历史(chunkId 变)→ colorsFresh 失效会打回中性。仅在
  // **压缩次数增加**时重取一次(非每轮,无逐轮成本);注册表保证重取的颜色与闸门时一致。
  const prevCompRef = useRef(snapshot.compressionCount ?? 0);
  useEffect(() => {
    const cc = snapshot.compressionCount ?? 0;
    const grew = cc > prevCompRef.current;
    prevCompRef.current = cc;
    if (!grew || !colorOn || !sid) return;
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
  }, [snapshot.compressionCount, colorOn, sid, snapshot.historyVersion]);

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
    <Card className="flex flex-none flex-col gap-2 px-3 py-2">
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
                  ? `已编辑计划：折 ${gateFolds.length} 块 / 删 ${userDrops.length} 块 —— 「应用计划」直接落地`
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
                {userEdited && (
                  <button
                    type="button"
                    onClick={() => respondGate("apply_plan")}
                    className="rounded border border-warning/50 px-2 py-0.5 text-[11px] tracking-wide text-warning hover:bg-warning/10"
                  >
                    应用计划（折{gateFolds.length}删{userDrops.length}）
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
          {suggestNote && (
            <div className="text-[10px] text-text-tertiary">{suggestNote}</div>
          )}
          {hasChunks &&
            (view === "turn" ? (
              <TurnBand
                snapshot={snapshot}
                mode={mode}
                selected={selected}
                onSelect={onSelect}
                chunkTopics={activeTopics}
                topicColors={activeColorMap}
                onActivateTurn={onActivateTurn}
                fateMap={effectiveFateMap}
                gateActive={gateActive}
              />
            ) : (
              <Treemap
                snapshot={snapshot}
                mode={mode}
                selected={selected}
                onSelect={onSelect}
                fateMap={effectiveFateMap}
              />
            ))}

          <Sparkline snapshot={snapshot} />
        </>
      )}
    </Card>
  );
}
