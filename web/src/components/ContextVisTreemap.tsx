import { formatTokenCount } from "@/lib/format";
import { squarify } from "@/lib/contextvis/treemap";
import { CV_BANDS } from "@/lib/contextvis/theme";
import type { TreemapMode, ChunkType, ContextChunk, ContextSnapshot } from "@/lib/contextvis/types";
import type { FateMap } from "@/lib/contextvis/plan";

const VB_W = 408;
const VB_H = 320;
const LABEL_FS = 12;
const TOKEN_FS = 10;

/** 命运 → treemap 描边色（Tailwind 语义 token）。 */
const FATE_STROKE: Record<string, string> = {
  keep: "stroke-success",
  fold: "stroke-warning",
  drop: "stroke-destructive",
};
const FATE_LABEL: Record<string, string> = {
  keep: "保留",
  fold: "折叠",
  drop: "丢弃",
};

function fitText(label: string, w: number): string {
  const max = Math.floor((w - 8) / 7);
  if (max <= 1) return "";
  return label.length > max ? label.slice(0, max - 1) + "\u2026" : label;
}

export function ContextVisTreemap({
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

  const BANDS = CV_BANDS as { type: ChunkType; color: string }[];

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
        const fillOpacity = fate === "drop" ? 0.3 : isSel ? 0.95 : 0.8;
        const strokeClass = isSel
          ? "stroke-current"
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
