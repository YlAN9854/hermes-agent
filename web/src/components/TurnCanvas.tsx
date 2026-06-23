/**
 * TurnCanvas —— ContextVis v2 画布化的「轮次」主视图（Stage 2）。
 *
 * 纵向时间序铺开每个 turn（顶老底新，与 TUI 同向），**每个 turn 内部一张类型版小 treemap**
 * （`squarify` 把该轮 chunk 按 token 铺成 2D 子格、按类型上色）。行高 ∝ 该轮 token、内容驱动
 * 总高（小轮保底可读），外层 panel 滚动。引用图弧落到**具体子格 2D 中心**。
 *
 * **等比无拉伸**：用 ResizeObserver 测容器实际像素宽作为 viewBox 宽 → 1 viewBox 单位 = 1px，
 * 横竖都不拉伸（字号真实）。与 TurnBand（旧纵向条带）并存：ContextVisPanel 用 `USE_CANVAS` 切换。
 */
import { useEffect, useRef, useState } from "react";

import { buildTurnCells, type TurnCell } from "@/lib/contextvis/turns";
import { squarify, type Rect } from "@/lib/contextvis/treemap";
import type { ReferenceGraph, RegimeColors } from "@/lib/contextvis/apply";
import type { Fate, FateMap } from "@/lib/contextvis/plan";
import type { ContextChunk, ContextSnapshot } from "@/lib/contextvis/types";
import { formatTokenCount } from "@/lib/format";

type ChunkTopicMap = RegimeColors["chunk_topics"];

/** 类型→色 / 中文标签（与类型版 treemap 同配色）。 */
const TYPE_FILL: Record<string, string> = {
  system: "#8b7fd4",
  tool_schema: "#5fa8a0",
  history: "#7d8aa3",
  file: "#6fae7a",
  tool_result: "#d39a5c",
};
const TYPE_LABEL: Record<string, string> = {
  system: "系统",
  tool_schema: "工具表",
  history: "对话",
  file: "文件",
  tool_result: "工具结果",
};

const DEFAULT_W = 700; // 容器宽测出前的占位（随后 ResizeObserver 校正）
const GAP = 3; // 行间隙
const MIN_ROW = 6; // 每轮最小高（仅保证可点；占用保真，极小轮显薄条）
const HEADER_MIN_H = 26; // 行高 ≥ 此才显标签条，否则薄条（标签进 hover）
// 画布高度**锚定压缩阈值**：自适应面板可用高（vh，ResizeObserver 实测）代表「阈值占比 × 1.2」
// 那么多 token，所有 turn 按真实 budget 占比铺。近阈值时填满、远低时显空余（合「将满才看」理念）。
const DEFAULT_H = 600; // 容器高测出前的占位（随后 ResizeObserver 校正）
const THRESHOLD_OVERSHOOT = 1.2; // 画布顶 = min(100%, 阈值占比 × 1.2)
const DEFAULT_TH_FRAC = 0.8; // 无 compactAt 时的阈值占比兜底
const LABEL_FS = 11;
const TOKEN_FS = 9;
/** 关键词追踪态:被追踪 token 出现的子格高亮 + 贯穿路径,用一个区别于下/上游(rose/sky)的色。 */
const TRACE_COLOR = "#c678dd";

function fit(label: string, w: number, fs = LABEL_FS): string {
  // 可放字符数随字号变宽(≈0.56·fs px/字);故同一格放大字号会少放几个字、自动截断。
  const max = Math.max(1, Math.floor(w / (fs * 0.56)));
  return label.length > max ? label.slice(0, Math.max(1, max - 1)) + "…" : label;
}

/** 命运 → 子格描边色（drop 红 / fold 黄虚线 / keep 绿）；否则默认/选中色。 */
function fateStroke(fate: Fate | undefined, sel: boolean): string {
  if (fate === "drop") return "#e5687a";
  if (fate === "fold") return "#d9a441";
  if (fate === "keep") return "#5fb88a";
  return sel ? "#ffffff" : "rgba(0,0,0,0.3)";
}

type Sub = { chunk: ContextChunk; x: number; y: number; w: number; h: number };
type Row = {
  cell: TurnCell;
  y: number;
  h: number;
  subs: Sub[];
  showHeader: boolean;
  headerFs: number; // 行首标签字号(随该轮高度∝token 适度放大)
};

export function TurnCanvas({
  snapshot,
  selected,
  onSelect,
  chunkTopics,
  fateMap,
  onActivateTurn,
  referenceGraph = null,
  tracedChunks = null,
}: {
  snapshot: ContextSnapshot;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** 主题着色:chunkId → {topic, mainline};用于支线压暗。null=不压暗。 */
  chunkTopics: ChunkTopicMap | null;
  /** 命运标记(用户/系统),驱动子格描边。 */
  fateMap: FateMap;
  /** 点对话轮 → 把 TUI 滚到该轮。 */
  onActivateTurn?: (turn: number) => void;
  /** v2 引用图;弧落子格 2D 中心。null=不画。 */
  referenceGraph?: ReferenceGraph | null;
  /** Stage 3 关键词追踪:某 token 出现的 chunkIds。非空 → 高亮这些子格 + 画贯穿路径、压暗其余、隐去引用弧。 */
  tracedChunks?: Set<string> | null;
}) {
  // 测容器实际像素宽 → 作 viewBox 宽,1:1 不拉伸(setState 在 observer 回调,lint 安全)。
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [vw, setVw] = useState(DEFAULT_W);
  const [vh, setVh] = useState(DEFAULT_H);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (!cr) return;
      if (cr.width > 0) setVw(Math.round(cr.width));
      if (cr.height > 0) setVh(Math.round(cr.height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const cells = buildTurnCells(snapshot);
  const total = cells.reduce((s, c) => s + c.tokens, 0);
  if (total <= 0) return <div ref={wrapRef} className="h-full w-full" />;

  const chunkById = new Map<string, ContextChunk>(
    snapshot.chunks.map((c) => [c.id, c] as [string, ContextChunk]),
  );

  // 画布高锚定压缩阈值:CANVAS_REF_H 代表「阈值占比×1.2」那么多 token,turn 按真实 budget 占比铺。
  const { budget, compactAt } = snapshot;
  const thFrac =
    budget > 0 && compactAt && compactAt > 0 ? compactAt / budget : DEFAULT_TH_FRAC;
  const refFrac = Math.min(1, thFrac * THRESHOLD_OVERSHOOT);
  const scale = vh / Math.max(1, refFrac * budget); // px per token（vh = 面板可用高，自适应）
  const rows: Row[] = [];
  let yCur = 0;
  for (const cell of cells) {
    const h = Math.max(MIN_ROW, cell.tokens * scale);
    const showHeader = h >= HEADER_MIN_H;
    // 行首标签字号随该轮高度(∝token)适度放大(守「量级编码」);标签条高度随之撑开容纳。
    const headerFs = showHeader
      ? Math.min(17, Math.max(LABEL_FS, Math.round(LABEL_FS + (h - HEADER_MIN_H) / 90)))
      : LABEL_FS;
    const top = showHeader ? headerFs + 4 : 1;
    let subs: Sub[] = [];
    if (!cell.isBase && !cell.isFolded) {
      const members = cell.chunkIds
        .map((id) => chunkById.get(id))
        .filter((c): c is ContextChunk => !!c);
      const rect: Rect = {
        x: 2,
        y: yCur + top,
        w: vw - 4,
        h: Math.max(0, h - top - GAP),
      };
      subs = squarify(
        members.map((c) => ({ value: Math.max(1, c.tokens), data: c })),
        rect,
      ).map((tc) => ({ chunk: tc.item, x: tc.x, y: tc.y, w: tc.w, h: tc.h }));
    }
    rows.push({ cell, y: yCur, h, subs, showHeader, headerFs });
    yCur += h;
  }
  // 总高 = max(面板高, 内容高):内容不及阈值×1.2 → 填满面板留空余;超出 → 加长滚动。
  const totalH = Math.max(vh, yCur);
  const thresholdY = compactAt && compactAt > 0 ? compactAt * scale : null;

  // chunkId / messageIndex → 2D 中心(弧落子格);base/folded 无子格 → 整行中心。
  const center = new Map<string, { x: number; y: number }>();
  const miCenter = new Map<number, { x: number; y: number }>();
  for (const r of rows) {
    if (r.subs.length) {
      for (const s of r.subs) {
        const c = { x: s.x + s.w / 2, y: s.y + s.h / 2 };
        center.set(s.chunk.id, c);
        for (const ref of s.chunk.sourceRefs)
          if (typeof ref.messageIndex === "number") miCenter.set(ref.messageIndex, c);
      }
    } else {
      const c = { x: vw / 2, y: r.y + r.h / 2 };
      for (const id of r.cell.chunkIds) center.set(id, c);
    }
  }
  const resolveCenter = (id: string | null, mi: number) =>
    (id ? center.get(id) : undefined) ?? miCenter.get(mi);

  // 选中范围:点整轮(repId)→ 整轮 chunkIds;点子块 → 仅该块。
  const selScope: Set<string> = (() => {
    if (!selected) return new Set();
    const turn = rows.find((r) => r.cell.repId === selected);
    return new Set<string>(turn ? turn.cell.chunkIds : [selected]);
  })();

  // 关键词追踪态:有被追踪块时,画布进入「聚焦该 token 路径」模式(高亮/压暗/隐弧/画线)。
  const tracing = !!tracedChunks && tracedChunks.size > 0;

  return (
    <div ref={wrapRef} className="h-full w-full overflow-y-auto">
      <svg
        viewBox={`0 0 ${vw} ${totalH}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: `${totalH}px` }}
        role="img"
        aria-label="context canvas"
      >
        {yCur < totalH && (
          <rect
            x={0}
            y={yCur}
            width={vw}
            height={totalH - yCur}
            className="fill-current/5"
          />
        )}
        {rows.map((r) => {
          const turnSel =
            selScope.size > 0 && r.cell.chunkIds.some((id) => selScope.has(id));
          // 追踪态:无子格的行(底座/折叠)直接判其 chunkId 是否被追踪 → 描边高亮 / 否则压暗。
          const rowTraced = tracing && r.cell.chunkIds.some((id) => tracedChunks!.has(id));
          return (
            <g key={r.cell.isFolded ? r.cell.repId : `turn-${r.cell.turn}-${r.y.toFixed(0)}`}>
              <rect
                x={0}
                y={r.y}
                width={vw}
                height={Math.max(0, r.h - GAP)}
                onClick={() => {
                  // 「第N轮」头部条(子格之上的留白带)= 导航,不开详情:关掉已开的检视器(它盖在 TUI 上,
                  // 不关则看不到跳转)+ 把 TUI 滚到该轮(老版行为)。底座/折叠无 TUI 锚点 → 点它检视内容。
                  if (r.cell.isBase || r.cell.isFolded) {
                    onSelect(r.cell.repId === selected ? null : r.cell.repId);
                  } else {
                    onSelect(null);
                    onActivateTurn?.(r.cell.turn);
                  }
                }}
                className="cursor-pointer"
                fill={r.cell.isBase ? TYPE_FILL.system : r.cell.isFolded ? "#565d6b" : "#2c333f"}
                fillOpacity={
                  tracing && r.subs.length === 0 && !rowTraced
                    ? 0.18 // 追踪态:无子格且未命中的行(底座/无关折叠)退场
                    : r.cell.isFolded
                      ? 0.5
                      : r.cell.isBase
                        ? 0.5
                        : 0.9
                }
                stroke={turnSel ? "#ffffff" : rowTraced ? TRACE_COLOR : "rgba(0,0,0,0.25)"}
                strokeWidth={turnSel ? 1.25 : rowTraced ? 1.5 : 0.5}
                vectorEffect="non-scaling-stroke"
              >
                <title>{`${r.cell.label} · ${formatTokenCount(r.cell.tokens)}${!r.cell.isBase && !r.cell.isFolded ? " · 点击跳转到该轮对话" : ""}`}</title>
              </rect>
              {r.showHeader && (
                <>
                  <text
                    x={5}
                    y={r.y + r.headerFs}
                    fontSize={r.headerFs}
                    className="pointer-events-none fill-black/80"
                  >
                    {fit(r.cell.label, vw - 72, r.headerFs)}
                  </text>
                  <text
                    x={vw - 4}
                    y={r.y + r.headerFs}
                    fontSize={Math.max(TOKEN_FS, r.headerFs - 2)}
                    textAnchor="end"
                    className="pointer-events-none fill-black/55"
                  >
                    {formatTokenCount(r.cell.tokens)}
                  </text>
                </>
              )}
              {r.subs.map((s) => {
                const sel = selScope.has(s.chunk.id);
                const off = chunkTopics
                  ? chunkTopics[s.chunk.id]?.mainline === false
                  : false;
                const fate = fateMap[s.chunk.id];
                const traced = tracing && tracedChunks!.has(s.chunk.id);
                // 子格标签字号随格子尺寸(∝token)缩放:大块的「文件 11.5K」明显大于小块,守「量级编码」。
                const subFs = Math.max(8, Math.min(16, Math.floor(Math.min(s.h * 0.5, s.w / 4.5))));
                return (
                  <g key={s.chunk.id}>
                    <rect
                      x={s.x}
                      y={s.y}
                      width={Math.max(0, s.w - 0.5)}
                      height={Math.max(0, s.h - 0.5)}
                      onClick={() => onSelect(sel ? null : s.chunk.id)}
                      className="cursor-pointer"
                      fill={TYPE_FILL[s.chunk.type] ?? "#7d8aa3"}
                      fillOpacity={
                        tracing ? (traced ? 0.95 : 0.16) : off ? 0.4 : sel ? 0.95 : 0.82
                      }
                      stroke={traced ? TRACE_COLOR : fateStroke(fate, sel)}
                      strokeWidth={traced ? 2 : fate || sel ? 1.5 : 0.5}
                      strokeDasharray={fate === "fold" ? "3 2" : undefined}
                      vectorEffect="non-scaling-stroke"
                    >
                      <title>{`${TYPE_LABEL[s.chunk.type] ?? s.chunk.type} · ${formatTokenCount(s.chunk.tokens)}${fate ? ` · 标记:${fate}` : ""}`}</title>
                    </rect>
                    {s.w > 30 && s.h > 11 && (
                      <text
                        x={s.x + 3}
                        y={s.y + subFs + 1}
                        fontSize={subFs}
                        className="pointer-events-none fill-black/70"
                      >
                        {fit(
                          `${TYPE_LABEL[s.chunk.type] ?? s.chunk.type} ${formatTokenCount(s.chunk.tokens)}`,
                          s.w - 5,
                          subFs,
                        )}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
        {thresholdY !== null && (
          <g>
            <line
              x1={0}
              y1={thresholdY}
              x2={vw}
              y2={thresholdY}
              className="stroke-warning"
              strokeDasharray="4 3"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
            <text
              x={3}
              y={thresholdY - 2}
              fontSize={TOKEN_FS}
              className="pointer-events-none fill-warning"
            >
              压缩阈值
            </text>
          </g>
        )}
        {!tracing && referenceGraph && referenceGraph.edges.length > 0 && (() => {
          const key = (a: { x: number; y: number }, b: { x: number; y: number }) =>
            a.y <= b.y ? `${a.x},${a.y}_${b.x},${b.y}` : `${b.x},${b.y}_${a.x},${a.y}`;
          const toolPairs = new Set<string>();
          for (const e of referenceGraph.edges) {
            if (e.kind !== "tool") continue;
            const s = resolveCenter(e.src, e.src_mi);
            const d = resolveCenter(e.dst, e.dst_mi);
            if (s && d && (s.x !== d.x || s.y !== d.y)) toolPairs.add(key(s, d));
          }
          const hasSel = selScope.size > 0;
          return (
            <g>
              {referenceGraph.edges.map((e, i) => {
                const s = resolveCenter(e.src, e.src_mi);
                const d = resolveCenter(e.dst, e.dst_mi);
                if (!s || !d || (s.x === d.x && s.y === d.y)) return null;
                const isLex = e.kind === "lexical";
                if (isLex && toolPairs.has(key(s, d))) return null; // 去重:铁证优先
                const down = selScope.has(e.src ?? "");
                const up = selScope.has(e.dst ?? "");
                const touches = down || up;
                const cls = !hasSel
                  ? isLex
                    ? "stroke-current/10"
                    : "stroke-current/25"
                  : down
                    ? "stroke-rose-500"
                    : up
                      ? "stroke-sky-500"
                      : "stroke-current/10";
                const bulge = Math.min(120, 28 + Math.abs(d.y - s.y) * 0.4);
                const cx = Math.min(vw - 2, Math.max(s.x, d.x) + bulge);
                return (
                  <path
                    key={`arc-${i}`}
                    d={`M ${s.x} ${s.y} Q ${cx} ${(s.y + d.y) / 2} ${d.x} ${d.y}`}
                    fill="none"
                    className={cls}
                    strokeWidth={touches ? (isLex ? 1.25 : 2) : isLex ? 0.75 : 1}
                    strokeDasharray={isLex ? "3 2" : undefined}
                    vectorEffect="non-scaling-stroke"
                  >
                    <title>
                      {`${e.via}${isLex ? "(共现)" : e.rel === "revision" ? "(修订)" : "(读取)"}${down ? " — 下游" : up ? " — 上游" : ""}`}
                    </title>
                  </path>
                );
              })}
            </g>
          );
        })()}
        {/* 关键词追踪:把该 token 出现的全部块中心按时间序(y 顶老→底新)串成贯穿路径 + 节点。 */}
        {tracing && (() => {
          const pts = [...tracedChunks!]
            .map((id) => center.get(id))
            .filter((p): p is { x: number; y: number } => !!p)
            .sort((a, b) => a.y - b.y);
          if (pts.length === 0) return null;
          const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
          return (
            <g>
              {pts.length >= 2 && (
                <path
                  d={d}
                  fill="none"
                  stroke={TRACE_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="2 3"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {pts.map((p, i) => (
                <circle
                  key={i}
                  cx={p.x}
                  cy={p.y}
                  r={3}
                  fill={TRACE_COLOR}
                  stroke="#ffffff"
                  strokeWidth={0.75}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </g>
          );
        })()}
      </svg>
    </div>
  );
}
