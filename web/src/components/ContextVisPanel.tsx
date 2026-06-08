/**
 * ContextVisPanel —— ContextVis 的核心渲染（形态无关层的「一种渲染」）。
 *
 * 只吃 {@link ContextSnapshot}，绝不碰 gateway / 宿主数据结构（耦合全收敛在
 * adapter 与挂载壳）。皮肤可换，理念不变：本面板讲清**占用 / 累积 / 命运**。
 *
 *   占用对抗上限  → 水平占用条（长度编码 token 量级）+ used/budget/percent
 *   逐轮演变      → 占用率 sparkline（内联 SVG，无新依赖）
 *   压缩（命运）  → 占用条骤降 + sparkline 回落标记 + 「压缩 ×N」
 *
 * 档1 不渲染按类型构成（snapshot.chunks 为空）；档3 后端补真值后再据 chunks
 * 切换到树图，本组件与契约不变。
 */

import { Card } from "@nous-research/ui/ui/components/card";

import { formatTokenCount } from "@/lib/format";
import type { ContextSnapshot } from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

/** 占用率 → 配色档位（白盒克制：仅以颜色提示离上限多远）。 */
function occupancyTone(percent: number): {
  bar: string;
  text: string;
} {
  if (percent >= 90) return { bar: "bg-destructive", text: "text-destructive" };
  if (percent >= 70) return { bar: "bg-warning", text: "text-warning" };
  return { bar: "bg-success", text: "text-success" };
}

/** 内联 SVG sparkline：占用率随轮次。压缩点（回落）描红。 */
function Sparkline({ snapshot }: { snapshot: ContextSnapshot }) {
  const { history, compactions } = snapshot;
  if (history.length < 2) return null;

  const W = 240;
  const H = 32;
  const n = history.length;
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * W);
  const y = (pct: number) => H - (Math.max(0, Math.min(100, pct)) / 100) * H;

  const line = history
    .map((s, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(s.percent).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;

  // 压缩发生的轮次 → 在 sparkline 上对应采样点画一个回落标记。
  const compactTurns = new Set(compactions.map((c) => c.turn));
  const marks = history
    .map((s, i) => (compactTurns.has(s.turn) ? { cx: x(i), cy: y(s.percent) } : null))
    .filter((m): m is { cx: number; cy: number } => m !== null);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="h-8 w-full"
      role="img"
      aria-label="context occupancy over turns"
    >
      <path d={area} className="fill-current/10" />
      <path
        d={line}
        fill="none"
        className="stroke-current"
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
      {marks.map((m, i) => (
        <circle
          key={i}
          cx={m.cx}
          cy={m.cy}
          r={2.5}
          className="fill-destructive stroke-background-base"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

export function ContextVisPanel({ snapshot }: { snapshot: ContextSnapshot }) {
  const { budget, used, percent, compactions } = snapshot;
  const ready = budget > 0;
  const tone = occupancyTone(percent);
  const lastDrop = compactions.length
    ? compactions[compactions.length - 1].removed
    : 0;

  return (
    <Card className="flex flex-none flex-col gap-2 px-3 py-2">
      <div className="flex items-baseline justify-between">
        <div className="text-display text-xs tracking-wider text-text-tertiary">
          context
        </div>
        {ready && (
          <div className={cn("text-sm font-medium tabular-nums", tone.text)}>
            {percent}%
          </div>
        )}
      </div>

      {!ready ? (
        <div className="py-2 text-center text-xs text-text-secondary">
          等待上下文…
        </div>
      ) : (
        <>
          {/* 占用对抗上限：长度编码 token 量级 */}
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

          {/* 逐轮演变 */}
          <Sparkline snapshot={snapshot} />
        </>
      )}
    </Card>
  );
}
