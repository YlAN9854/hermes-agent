/**
 * ChunkInspector —— 右侧栏的 chunk 原文检视器（master-detail 的 detail）。
 *
 * 点中间浮层 treemap 的某个 chunk → 这里显示它的**完整原文**:system prompt
 * 节、工具 schema JSON、工具调用详情、文件内容、对话原文…… 这些（尤其
 * system/tools）在终端对话里**根本看不到**,检视器是唯一能读到的地方——把
 * 白盒的「可追溯」补全。
 *
 * 原文随 `context.snapshot` 推送(后端 chunking.py，按 32KB 截断),挂在
 * `chunk.raw`；这里只负责展示。v1 纯原文 `<pre>`，仅 tool_schema 已是 JSON。
 */

import { RotateCcw, X } from "lucide-react";

import { formatTokenCount } from "@/lib/format";
import {
  freedTokens,
  MESSAGE_BACKED_TYPES,
  type Fate,
  type FateMap,
} from "@/lib/contextvis/plan";
import type { ContextChunk } from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

/** 类型徽章配色，与 treemap 带色呼应。 */
const TYPE_COLOR: Record<string, string> = {
  system: "#8b7fd4",
  tool_schema: "#5fa8a0",
  history: "#7d8aa3",
  file: "#6fae7a",
  tool_result: "#d39a5c",
};

/** 命运动作配置:标签 + 选中态配色（呼应 treemap 叠加色）。 */
const FATE_ACTIONS: { fate: Fate; label: string; active: string }[] = [
  { fate: "keep", label: "保留", active: "border-success bg-success/15 text-success" },
  { fate: "fold", label: "折叠", active: "border-warning bg-warning/15 text-warning" },
  { fate: "drop", label: "丢弃", active: "border-destructive bg-destructive/15 text-destructive" },
];

/** 命运圆点配色（成员 chip 上标当前命运,呼应 treemap/按钮）。 */
const FATE_DOT: Record<Fate, string> = {
  keep: "bg-success",
  fold: "bg-warning",
  drop: "bg-destructive",
};

/**
 * 成员 chip 的紧凑标签:文件路径取末两段(`tui_gateway/server.py`),免整条全路径占满一行
 * (CSS 从右截断会把最有用的文件名切掉)。完整路径仍留在 chip 的 title 里。
 */
function chipLabel(c: ContextChunk): string {
  if (c.type === "file" && c.label.includes("/")) {
    return c.label.split("/").filter(Boolean).slice(-2).join("/");
  }
  return c.label;
}

/**
 * 本轮构成（第三刀细节层）—— 选中的是对话轮时,显示该轮的类型细分 + 成员块。
 *
 * 响应侧(assistant + tool_result + file)常远大于提问侧(一句小提问能拽进 20K 工具结果),
 * 这一段让用户看清"这一轮的 N K 里谁在吃 context",并能点成员块钻进它的原文。
 */
function TurnComposition({
  chunks,
  selectedId,
  onSelectChunk,
  fateMap,
  onSetFates,
}: {
  chunks: ContextChunk[];
  selectedId: string;
  onSelectChunk?: (id: string) => void;
  /** 第四刀:读各成员命运 → chip 标点 + 整轮聚合态。 */
  fateMap?: FateMap;
  /** 第四刀:整轮命运 → 批量给全部 message-backed 成员预填 fateMap。 */
  onSetFates?: (ids: string[], fate: Fate | null) => void;
}) {
  const total = chunks.reduce((s, c) => s + c.tokens, 0) || 1;
  const byType = new Map<string, number>();
  for (const c of chunks) byType.set(c.type, (byType.get(c.type) ?? 0) + c.tokens);
  const turn = chunks[0]?.turn;

  // chip 排序:history(提问/回复)置顶,其余按 token 降序——大块(谁在吃 context)先露头,
  // 配合下方限高滚动,工具调用再多也不挤占原文视图。
  const ordered = [...chunks].sort((a, b) => {
    const ah = a.type === "history" ? 0 : 1;
    const bh = b.type === "history" ? 0 : 1;
    return ah - bh || b.tokens - a.tokens;
  });

  // 第四刀:可落地(message 背书)的成员才能整轮 fold/drop;底座(system/tool_schema)无。
  const applicable = chunks.filter((c) => MESSAGE_BACKED_TYPES.has(c.type));
  const applicableIds = applicable.map((c) => c.id);
  const fates = applicable.map((c) => fateMap?.[c.id]);
  // 整轮聚合态:全部成员同命运才算"整轮已标该命运",否则 null(含混合/部分)。
  const turnFate: Fate | null =
    applicable.length > 0 && fates.every((f) => f && f === fates[0])
      ? (fates[0] as Fate)
      : null;
  const anyMarked = fates.some(Boolean);
  const showTurnFate = !!onSetFates && applicable.length > 0;

  return (
    <div className="flex shrink-0 flex-col gap-1.5 rounded border border-current/10 px-2 py-1.5">
      <div className="flex items-center justify-between text-[11px] text-text-tertiary">
        <span className="text-display tracking-wider">本轮构成</span>
        <span className="tabular-nums">
          第{turn}轮 · {chunks.length} 块 · ~{formatTokenCount(total)} tok
        </span>
      </div>
      {/* 类型堆叠条:面积 ∝ token */}
      <div className="flex h-1.5 w-full overflow-hidden rounded-sm bg-current/5">
        {[...byType.entries()].map(([t, tok]) => (
          <div
            key={t}
            style={{ width: `${(tok / total) * 100}%`, backgroundColor: TYPE_COLOR[t] ?? "#888" }}
            title={`${t} · ${formatTokenCount(tok)}`}
          />
        ))}
      </div>
      {/* 成员块 chips:点击钻进该块原文;右侧小点标该块当前命运。
          限高 + 滚动:工具调用再多也只占这一块、不挤占下方原文视图(用户诉求)。 */}
      <div className="flex max-h-[120px] flex-wrap gap-1 overflow-y-auto pr-0.5">
        {ordered.map((c) => {
          const isSel = c.id === selectedId;
          const cFate = fateMap?.[c.id];
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => onSelectChunk?.(c.id)}
              title={`${c.label} · ${formatTokenCount(c.tokens)} tok`}
              className={cn(
                "flex h-fit min-w-0 max-w-[210px] items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] transition-colors",
                isSel
                  ? "border-current/40 bg-current/10 text-text-secondary"
                  : "border-current/15 text-text-tertiary hover:text-text-secondary",
              )}
            >
              <span
                className="inline-block h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: TYPE_COLOR[c.type] ?? "#888" }}
              />
              <span className="truncate">{chipLabel(c)}</span>
              <span className="shrink-0 tabular-nums opacity-70">
                {formatTokenCount(c.tokens)}
              </span>
              {cFate && (
                <span
                  className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", FATE_DOT[cFate])}
                />
              )}
            </button>
          );
        })}
      </div>
      {/* 整轮命运（第四刀）:一键给该轮全部 message-backed 成员预填命运 →
          复用浮层既有「应用 fold/drop」落地。单块细修仍走下方按钮。 */}
      {showTurnFate && (
        <div className="flex items-center gap-1">
          <span className="shrink-0 text-[10px] tracking-wide text-text-tertiary">整轮</span>
          {FATE_ACTIONS.map(({ fate: f, label, active }) => {
            const isActive = turnFate === f;
            const freed = applicable.reduce((s, c) => s + freedTokens(c, f), 0);
            return (
              <button
                key={f}
                type="button"
                onClick={() => onSetFates!(applicableIds, isActive ? null : f)}
                aria-pressed={isActive}
                className={cn(
                  "flex flex-1 flex-col items-center rounded border px-1.5 py-0.5 text-[10px] transition-colors",
                  isActive
                    ? active
                    : "border-current/15 text-text-tertiary hover:text-text-secondary",
                )}
              >
                <span className="font-medium">{label}</span>
                <span className="tabular-nums opacity-70">
                  {freed > 0 ? `~${formatTokenCount(Math.floor(freed))}` : "保护"}
                </span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => onSetFates!(applicableIds, null)}
            disabled={!anyMarked}
            aria-label="清除整轮标记"
            title="清除整轮标记"
            className={cn(
              "shrink-0 rounded border border-current/15 p-1 text-text-tertiary transition-colors",
              anyMarked ? "hover:text-text-secondary" : "cursor-default opacity-40",
            )}
          >
            <RotateCcw className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}

export function ChunkInspector({
  chunk,
  fate,
  onSetFate,
  onClose,
  turnChunks,
  onSelectChunk,
  fateMap,
  onSetFates,
}: {
  chunk: ContextChunk | null;
  /** 该块当前标记的命运（用户意图,来自 ChatPage fateMap）。 */
  fate?: Fate;
  /** 标记/改命运;传 null = 恢复（取消标记,交还系统自动压缩）。 */
  onSetFate: (id: string, fate: Fate | null) => void;
  onClose: () => void;
  /** 第三刀:选中块所属轮的全部 chunk(>1 时显「本轮构成」);单块(底座/压缩块)不传或长度 1。 */
  turnChunks?: ContextChunk[];
  /** 点本轮构成里的成员块 → 钻进它。 */
  onSelectChunk?: (id: string) => void;
  /** 第四刀:全量命运图（本轮构成据此标 chip 命运点 + 整轮聚合态）。 */
  fateMap?: FateMap;
  /** 第四刀:整轮命运批量预填。 */
  onSetFates?: (ids: string[], fate: Fate | null) => void;
}) {
  if (!chunk) {
    return (
      <aside className="flex h-full w-full flex-col items-center justify-center px-4 text-center">
        <div className="text-display text-xs tracking-wider text-text-tertiary">
          context inspector
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          点击左侧上下文视图中的任一块，
          <br />
          在此查看它的完整原文。
        </p>
      </aside>
    );
  }

  const color = TYPE_COLOR[chunk.type] ?? "#888";
  // system / tool_schema 无 message 背书,不经历史压缩移除 → 命运标记不可应用。
  const applicable = MESSAGE_BACKED_TYPES.has(chunk.type);

  return (
    <aside className="flex h-full w-full min-w-0 flex-col gap-2 overflow-hidden">
      {/* 头部：类型 + 标签 + 度量 + 关闭 */}
      <div className="flex items-start justify-between gap-2 px-1">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: color }}
            />
            <span className="text-display text-xs tracking-wider text-text-tertiary">
              {chunk.type}
            </span>
          </div>
          <div
            className="mt-0.5 wrap-break-word text-sm font-medium text-text-secondary"
            title={chunk.label}
          >
            {chunk.label}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="close inspector"
          className="-mr-1 shrink-0 rounded p-0.5 text-text-tertiary hover:text-text-secondary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-1 text-xs tabular-nums text-text-tertiary">
        <span>~{formatTokenCount(chunk.tokens)} tok</span>
        {chunk.members && chunk.members > 1 && <span>{chunk.members} 项</span>}
        {chunk.group && <span>{chunk.group}</span>}
        {chunk.raw != null && <span>{chunk.raw.length.toLocaleString()} 字符</span>}
      </div>

      {/* 本轮构成（第三刀细节层）：选中对话轮时显示类型细分 + 成员块钻取。
          底座 / 压缩块为单块，turnChunks 长度 1 → 不显，行为同前(只看原文)。 */}
      {turnChunks && turnChunks.length > 1 && (
        <TurnComposition
          chunks={turnChunks}
          selectedId={chunk.id}
          onSelectChunk={onSelectChunk}
          fateMap={fateMap}
          onSetFates={onSetFates}
        />
      )}

      {/* 命运标记（方向 A）:标 keep/fold/drop → 浮层预览释放量;drop 可经
          「应用」落地真实上下文(阶段 3)。system/tool_schema 不可应用,禁用。 */}
      {!applicable ? (
        <div className="rounded border border-current/10 px-2 py-1.5 text-[11px] leading-snug text-text-tertiary">
          {chunk.type === "system" ? "系统提示" : "工具 schema"}由 agent
          每轮重建，不经历史压缩移除——不可标记命运。
        </div>
      ) : (
      <div className="flex items-center gap-1 px-1">
        {FATE_ACTIONS.map(({ fate: f, label, active }) => {
          const isActive = fate === f;
          const freed = freedTokens(chunk, f);
          return (
            <button
              key={f}
              type="button"
              onClick={() => onSetFate(chunk.id, isActive ? null : f)}
              aria-pressed={isActive}
              className={cn(
                "flex flex-1 flex-col items-center rounded border px-1.5 py-1 text-xs transition-colors",
                isActive
                  ? active
                  : "border-current/15 text-text-tertiary hover:text-text-secondary",
              )}
            >
              <span className="font-medium">{label}</span>
              <span className="text-[10px] tabular-nums opacity-70">
                {freed > 0 ? `释放 ~${formatTokenCount(Math.floor(freed))}` : "保护"}
              </span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => onSetFate(chunk.id, null)}
          disabled={!fate}
          aria-label="恢复（取消标记）"
          title="恢复（取消标记）"
          className={cn(
            "shrink-0 rounded border border-current/15 p-1.5 text-text-tertiary transition-colors",
            fate ? "hover:text-text-secondary" : "cursor-default opacity-40",
          )}
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>
      )}

      {/* 原文 */}
      <div className="min-h-0 flex-1 overflow-auto rounded border border-current/10 bg-black/20">
        {chunk.raw ? (
          <pre
            className={cn(
              "min-w-0 whitespace-pre-wrap break-words p-2",
              "font-mono text-[11px] leading-relaxed text-text-secondary",
            )}
          >
            {chunk.raw}
          </pre>
        ) : (
          <div className="p-3 text-xs text-text-tertiary">
            （此块未携带原文 —— 可能已被 HERMES_CONTEXTVIS_RAW 关闭）
          </div>
        )}
      </div>
    </aside>
  );
}
