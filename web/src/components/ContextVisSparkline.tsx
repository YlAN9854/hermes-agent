import type { ContextSnapshot } from "@/lib/contextvis/types";

/** 占用率 sparkline（占用率随轮次；压缩点描红）。 */
export function ContextVisSparkline({ snapshot }: { snapshot: ContextSnapshot }) {
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
