import { formatTokenCount } from "@/lib/format";
import { buildTurnCells, type TurnCell } from "@/lib/contextvis/turns";
import {
  CV_SURFACE,
  CV_TYPE_FILL,
  CV_TYPE_LABEL,
} from "@/lib/contextvis/theme";
import { aggregateCellFate, type FateMap } from "@/lib/contextvis/plan";
import type {
  TreemapMode,
  ChunkType,
  ContextChunk,
  ContextSnapshot,
} from "@/lib/contextvis/types";
import type { RegimeColors, ReferenceGraph } from "@/lib/contextvis/apply";

type ChunkTopicMap = RegimeColors["chunk_topics"];

/** 命运 → treemap 描边色（Tailwind 语义 token）。 */
const FATE_STROKE: Record<string, string> = {
  keep: "stroke-success",
  fold: "stroke-warning",
  drop: "stroke-destructive",
};
const FATE_FILL: Record<string, string> = {
  keep: "fill-success",
  fold: "fill-warning",
  drop: "fill-destructive",
};
const FATE_LABEL: Record<string, string> = {
  keep: "保留",
  fold: "折叠",
  drop: "丢弃",
};

const TURN_MIN_H = 12;
const VB_W = 408;
const VB_H = 320;
const ARC_GUTTER = 22;
const LABEL_FS = 12;
const TOKEN_FS = 10;
const EXPAND_H = 96;

const TURN_BASE_COLOR = CV_SURFACE.rowBase;
const TURN_CELL_COLOR = CV_SURFACE.rowTurn;
const TURN_FOLD_COLOR = CV_SURFACE.rowFold;

/** 残值 drop 来由 → 中文标签(轮次版角标 tooltip)。 */
const RESIDUAL_LABEL: Record<string, string> = {
  superseded_read: "被取代旧读",
  failed_tool: "失败工具",
  chitchat: "闲聊",
};

function fitText(label: string, w: number): string {
  const max = Math.floor((w - 8) / 7);
  if (max <= 1) return "";
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

export function ContextVisTurnBand({
  snapshot,
  mode,
  selected,
  onSelect,
  chunkTopics,
  cellColors,
  onActivateTurn,
  fateMap,
  fateReasons,
  gateActive = false,
  referenceGraph = null,
}: {
  snapshot: ContextSnapshot;
  mode: TreemapMode;
  selected: string | null;
  onSelect: (id: string | null) => void;
  chunkTopics: ChunkTopicMap | null;
  cellColors: Record<string, string> | null;
  onActivateTurn?: (turn: number) => void;
  fateMap: FateMap;
  fateReasons?: Record<string, string>;
  gateActive?: boolean;
  referenceGraph?: ReferenceGraph | null;
}) {
  const { percent, budget, compactAt } = snapshot;
  const cells = buildTurnCells(snapshot);
  const typeById = new Map<string, ChunkType>();
  for (const c of snapshot.chunks) typeById.set(c.id, c.type);
  const total = cells.reduce((s, c) => s + c.tokens, 0);
  if (total <= 0) return null;

  const usedFrac =
    mode === "actual" ? Math.min(1, Math.max(0, percent / 100)) : 1;
  const fillH = VB_H * usedFrac;

  const expandedCell =
    selected
      ? cells.find(
          (c) =>
            !c.isBase &&
            !c.isFolded &&
            c.chunkIds.length >= 2 &&
            c.chunkIds.includes(selected),
        ) ?? null
      : null;
  const minH = Math.min(TURN_MIN_H, fillH / Math.max(1, cells.length));
  const reserve = expandedCell ? Math.min(EXPAND_H, fillH * 0.7) : 0;
  const otherCells = cells.filter((c) => c !== expandedCell);
  const otherTokens = otherCells.reduce((s, c) => s + c.tokens, 0) || 1;
  const pool = Math.max(0, fillH - reserve - minH * otherCells.length);
  const laid: { cell: TurnCell; y: number; h: number }[] = [];
  let yCursor = 0;
  for (const cell of cells) {
    const h =
      cell === expandedCell ? reserve : minH + (cell.tokens / otherTokens) * pool;
    laid.push({ cell, y: yCursor, h });
    yCursor += h;
  }

  const chunkById = new Map<string, ContextChunk>(
    snapshot.chunks.map((c) => [c.id, c] as [string, ContextChunk]),
  );
  const minMi = (c: ContextChunk) => {
    let m = Infinity;
    for (const r of c.sourceRefs)
      if (typeof r.messageIndex === "number") m = Math.min(m, r.messageIndex);
    return m;
  };
  const expandedSub: {
    id: string;
    y: number;
    h: number;
    type: ChunkType;
    tokens: number;
  }[] = [];
  const exLaid = expandedCell ? laid.find((l) => l.cell === expandedCell) : null;
  if (expandedCell && exLaid) {
    const HEADER = 14;
    const members = expandedCell.chunkIds
      .map((id) => chunkById.get(id))
      .filter((c): c is ContextChunk => !!c)
      .sort((a, b) => minMi(a) - minMi(b));
    const totTok = members.reduce((s, c) => s + Math.max(1, c.tokens), 0) || 1;
    const avail = Math.max(0, exLaid.h - HEADER);
    const subMin = Math.min(8, members.length ? avail / members.length : 0);
    const subExtra = Math.max(0, avail - subMin * members.length);
    let sy = exLaid.y + HEADER;
    for (const c of members) {
      const sh = subMin + (Math.max(1, c.tokens) / totTok) * subExtra;
      expandedSub.push({ id: c.id, y: sy, h: sh, type: c.type, tokens: c.tokens });
      sy += sh;
    }
  }
  const chunkCenter = new Map<string, number>();
  for (const s of expandedSub) chunkCenter.set(s.id, s.y + s.h / 2);

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
      viewBox={`0 0 ${VB_W + ARC_GUTTER} ${VB_H}`}
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
        const ct =
          chunkTopics && !cell.isBase && !cell.isFolded
            ? chunkTopics[cell.repId]
            : undefined;
        const cellColor =
          !cell.isBase && !cell.isFolded ? cellColors?.[cell.repId] : undefined;
        const offthread = ct ? !ct.mainline : false;
        const fill = cell.isFolded
          ? TURN_FOLD_COLOR
          : cell.isBase
            ? TURN_BASE_COLOR
            : cellColor ?? TURN_CELL_COLOR;
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
        const { full: fullFate, partial: partialFate, mixed: mixedMark, dropCount } =
          aggregateCellFate(cell, typeById, fateMap);
        const hasPartial = partialFate !== null || mixedMark;
        let dropReasonText = "";
        if (dropCount > 0) {
          const counts: Record<string, number> = {};
          for (const id of cell.chunkIds) {
            if (fateMap[id] !== "drop") continue;
            const reason = fateReasons?.[id];
            if (reason) counts[reason] = (counts[reason] ?? 0) + 1;
          }
          const parts = Object.entries(counts).map(
            ([r, n]) => `${RESIDUAL_LABEL[r] ?? r}×${n}`,
          );
          dropReasonText = parts.length
            ? ` · 丢弃 ${dropCount}:${parts.join("、")}`
            : ` · 丢弃 ${dropCount}`;
        }
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
            }${fateText}${foldReason}${dropReasonText}`;
        return (
          <g
            key={cell.isFolded ? cell.repId : `turn-${cell.turn}`}
            onClick={() => {
              onSelect(isSel ? null : cell.repId);
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
                    ? 0.42
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
            {(fullFate || hasPartial || dropCount > 0) && (
              <rect
                x={0}
                y={y}
                width={fullFate ? 4 : 3}
                height={Math.max(0, h)}
                className={
                  fullFate
                    ? FATE_FILL[fullFate]
                    : dropCount > 0
                      ? FATE_FILL.drop
                      : partialFate
                        ? FATE_FILL[partialFate]
                        : "fill-current/40"
                }
              />
            )}
            {dropCount > 0 && !fullFate && h >= 14 && (
              <text
                x={VB_W - 3}
                y={y + h - 3}
                fontSize={TOKEN_FS}
                textAnchor="end"
                className="pointer-events-none fill-destructive font-semibold"
              >
                {`✕${dropCount}`}
              </text>
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
      {expandedSub.length > 0 && (
        <g>
          {expandedSub.map((s) => {
            const subSel = s.id === selected;
            return (
              <g key={`sub-${s.id}`}>
                <rect
                  x={6}
                  y={s.y}
                  width={VB_W - 8}
                  height={Math.max(0, s.h - 0.5)}
                  onClick={() => onSelect(subSel ? null : s.id)}
                  className="cursor-pointer"
                  fill={CV_TYPE_FILL[s.type] ?? TURN_CELL_COLOR}
                  fillOpacity={subSel ? 0.95 : 0.78}
                  stroke={subSel ? CV_SURFACE.ink : CV_SURFACE.cellStroke}
                  strokeWidth={subSel ? 1.5 : 0.5}
                  vectorEffect="non-scaling-stroke"
                />
                {s.h > 9 && (
                  <text
                    x={10}
                    y={s.y + s.h / 2 + 3}
                    fontSize={TOKEN_FS}
                    className="pointer-events-none fill-black/75"
                  >
                    {`${CV_TYPE_LABEL[s.type] ?? s.type} · ${formatTokenCount(s.tokens)}`}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      )}
      {referenceGraph && referenceGraph.edges.length > 0 && (() => {
        const idToLaid = new Map<string, { cell: TurnCell; y: number; h: number }>();
        for (const l of laid) for (const id of l.cell.chunkIds) idToLaid.set(id, l);
        const miToLaid = new Map<number, { cell: TurnCell; y: number; h: number }>();
        for (const c of snapshot.chunks)
          for (const r of c.sourceRefs)
            if (typeof r.messageIndex === "number") {
              const l = idToLaid.get(c.id);
              if (l) miToLaid.set(r.messageIndex, l);
            }
        const resolve = (id: string | null, mi: number) =>
          (id ? idToLaid.get(id) : undefined) ?? miToLaid.get(mi);
        const sel = selected ? idToLaid.get(selected) ?? null : null;
        const pairKey = (
          a: { cell: TurnCell; y: number; h: number },
          b: { cell: TurnCell; y: number; h: number },
        ) => {
          const ai = laid.indexOf(a);
          const bi = laid.indexOf(b);
          return ai < bi ? `${ai}-${bi}` : `${bi}-${ai}`;
        };
        const toolPairs = new Set<string>();
        for (const e of referenceGraph.edges) {
          if (e.kind !== "tool") continue;
          const s = resolve(e.src, e.src_mi);
          const d = resolve(e.dst, e.dst_mi);
          if (s && d && s !== d) toolPairs.add(pairKey(s, d));
        }
        return (
          <g>
            {referenceGraph.edges.map((e, i) => {
              const s = resolve(e.src, e.src_mi);
              const d = resolve(e.dst, e.dst_mi);
              if (!s || !d) return null;
              const isLex = e.kind === "lexical";
              if (isLex && toolPairs.has(pairKey(s, d))) return null;
              const y1 = chunkCenter.get(e.src ?? "") ?? s.y + s.h / 2;
              const y2 = chunkCenter.get(e.dst ?? "") ?? d.y + d.h / 2;
              if (y1 === y2) return null;
              const downstream = !!sel && s === sel;
              const upstream = !!sel && d === sel;
              const touches = downstream || upstream;
              const cls = !sel
                ? isLex
                  ? "stroke-current/10"
                  : "stroke-current/20"
                : downstream
                  ? "stroke-rose-500"
                  : upstream
                    ? "stroke-sky-500"
                    : "stroke-current/10";
              return (
                <path
                  key={`arc-${i}`}
                  d={`M ${VB_W} ${y1} Q ${VB_W + ARC_GUTTER} ${(y1 + y2) / 2} ${VB_W} ${y2}`}
                  fill="none"
                  className={cls}
                  strokeWidth={touches ? (isLex ? 1.25 : 1.75) : isLex ? 0.75 : 1}
                  strokeDasharray={isLex ? "3 2" : undefined}
                  vectorEffect="non-scaling-stroke"
                >
                  <title>
                    {`${e.via}${isLex ? "(共现)" : e.rel === "revision" ? "(修订)" : "(读取)"}${downstream ? " — 下游" : upstream ? " — 上游" : ""}`}
                  </title>
                </path>
              );
            })}
          </g>
        );
      })()}
    </svg>
  );
}
