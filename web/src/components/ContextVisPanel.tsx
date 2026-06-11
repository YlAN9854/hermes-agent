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
import { useState } from "react";

import { formatTokenCount } from "@/lib/format";
import { squarify } from "@/lib/contextvis/treemap";
import type {
  ChunkType,
  ContextChunk,
  ContextSnapshot,
} from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

type TreemapMode = "proportional" | "actual";

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
}: {
  snapshot: ContextSnapshot;
  mode: TreemapMode;
  selected: string | null;
  onSelect: (id: string | null) => void;
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
        const showLabel = w > 44 && h > 26;
        const label = fitText(chunk.label, w);
        return (
          <g
            key={chunk.id}
            onClick={() => onSelect(isSel ? null : chunk.id)}
            className="cursor-pointer"
          >
            <title>{`${chunk.label} · ${formatTokenCount(chunk.tokens)} tok${chunk.group ? ` · ${chunk.group}` : ""}${chunk.members && chunk.members > 1 ? ` · ${chunk.members} 项` : ""}`}</title>
            <rect
              x={x}
              y={y}
              width={Math.max(0, w)}
              height={Math.max(0, h)}
              fill={color}
              fillOpacity={isSel ? 0.95 : 0.8}
              className="stroke-background-base"
              strokeWidth={isSel ? 2 : 0.75}
              vectorEffect="non-scaling-stroke"
            />
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

export function ContextVisPanel({
  snapshot,
  selected,
  onSelect,
  onCollapse,
}: {
  snapshot: ContextSnapshot;
  /** 受控选中：选中态上提到挂载壳，与右侧栏 inspector 共享。 */
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** 挂载壳传入：渲染一个折叠按钮（核心渲染本身不关心折叠语义）。 */
  onCollapse?: () => void;
}) {
  const [mode, setMode] = useState<TreemapMode>("proportional");
  const { budget, used, percent, compactions, chunks } = snapshot;
  const ready = budget > 0;
  const tone = occupancyTone(percent);
  const hasChunks = chunks.length > 0;
  const lastDrop = compactions.length ? compactions[compactions.length - 1].removed : 0;

  return (
    <Card className="flex flex-none flex-col gap-2 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-display text-xs tracking-wider text-text-tertiary">context</div>
        <div className="flex items-center gap-2">
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
          {/* 占用对抗上限：始终可读的细条。 */}
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-current/10"
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
          </div>

          <div className="flex items-center justify-between text-xs tabular-nums text-text-secondary">
            <span>
              {formatTokenCount(used)}
              <span className="text-text-tertiary"> / {formatTokenCount(budget)}</span>
            </span>
            {compactions.length > 0 && (
              <span className="text-text-tertiary">
                压缩 ×{compactions.length}
                {lastDrop > 0 && (
                  <span className="text-destructive"> −{formatTokenCount(lastDrop)}</span>
                )}
              </span>
            )}
          </div>

          {hasChunks && (
            <Treemap snapshot={snapshot} mode={mode} selected={selected} onSelect={onSelect} />
          )}

          <Sparkline snapshot={snapshot} />
        </>
      )}
    </Card>
  );
}
