/**
 * ChunkInspector —— 右侧栏的 chunk 原文检视器（master-detail 的 detail）。
 *
 * 点中间浮层 treemap 的某个 chunk → 这里显示它的**完整原文**:system prompt
 * 节、工具 schema JSON、工具调用详情、文件内容、对话原文…… 这些（尤其
 * system/tools）在终端对话里**根本看不到**,检视器是唯一能读到的地方——把
 * 白盒的「可追溯」补全。
 *
 * 布局(对话轮):上=头部,中=「本轮构成」chip 区(40%,仅 chip 列表内滚),
 * 下=原文区(60%,仅原文内容内滚)。压缩折叠块=终点叶子:无 chip 区,原文占满。
 *
 * 原文随 `context.snapshot` 推送(后端 chunking.py，按 32KB 截断),挂在
 * `chunk.raw`；这里只负责展示。v1 纯原文 `<pre>`，仅 tool_schema 已是 JSON。
 */

import { RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { formatTokenCount } from "@/lib/format";
import {
  freedTokens,
  MESSAGE_BACKED_TYPES,
  type Fate,
  type FateMap,
} from "@/lib/contextvis/plan";
import { CV_ADD, CV_TYPE_FILL } from "@/lib/contextvis/theme";
import type { ContextChunk } from "@/lib/contextvis/types";
import { cn } from "@/lib/utils";

/** 类型徽章配色，与 treemap 带色呼应(单一真相源 theme.ts)。 */
const TYPE_COLOR = CV_TYPE_FILL;

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
 * 本轮构成 chip 区（第三刀细节层）—— 类型堆叠条 + 成员块 chips。
 *
 * 响应侧(assistant + tool_result + file)常远大于提问侧(一句小提问能拽进 20K 工具结果),
 * 让用户看清"这一轮的 N K 里谁在吃 context",并能点成员块钻进它的原文。**只有 chip 列表内滚**。
 */
function Composition({
  members,
  selectedId,
  onSelectChunk,
  fateMap,
}: {
  members: ContextChunk[];
  selectedId: string;
  onSelectChunk?: (id: string) => void;
  fateMap?: FateMap;
}) {
  const total = members.reduce((s, c) => s + c.tokens, 0) || 1;
  const byType = new Map<string, number>();
  for (const c of members) byType.set(c.type, (byType.get(c.type) ?? 0) + c.tokens);
  const turn = members[0]?.turn;

  // chip 排序:history(提问/回复)置顶,其余按 token 降序——大块(谁在吃 context)先露头。
  const ordered = [...members].sort((a, b) => {
    const ah = a.type === "history" ? 0 : 1;
    const bh = b.type === "history" ? 0 : 1;
    return ah - bh || b.tokens - a.tokens;
  });

  return (
    <>
      <div className="flex shrink-0 items-center justify-between text-[11px] text-text-tertiary">
        <span className="text-display tracking-wider">本轮构成</span>
        <span className="tabular-nums">
          {turn ? `第${turn}轮 · ` : ""}
          {members.length} 块 · ~{formatTokenCount(total)} tok
        </span>
      </div>
      {/* 类型堆叠条:面积 ∝ token */}
      <div className="flex h-1.5 w-full shrink-0 overflow-hidden rounded-sm bg-current/5">
        {[...byType.entries()].map(([t, tok]) => (
          <div
            key={t}
            style={{ width: `${(tok / total) * 100}%`, backgroundColor: TYPE_COLOR[t] ?? "#888" }}
            title={`${t} · ${formatTokenCount(tok)}`}
          />
        ))}
      </div>
      {/* 成员块 chips:点击钻进该块原文;右侧小点标该块当前命运。只此处内滚。 */}
      <div className="flex min-h-0 flex-1 flex-wrap content-start gap-1 overflow-y-auto pr-0.5">
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
    </>
  );
}

/**
 * 命运控件（第四刀,合一版）—— **一行 keep/fold/drop**,目标随选中态派生:
 *   · 选中「提问/本轮」块(history)→ 目标 = 整轮全部 message-backed 成员;
 *   · 钻进某个成员(file/tool_result)→ 目标 = 仅该块。
 * 取代原先"整轮一行 + 单块一行"的重复三连(用户反馈浪费空间)。目标用文字明示,行为透明。
 * 落地仍复用浮层既有 `applyFold`/`applyDrops`(铁律:此处只**预填 fateMap**)。
 */
function FateControls({
  members,
  selected,
  fateMap,
  onSetFates,
}: {
  members: ContextChunk[];
  selected: ContextChunk;
  fateMap?: FateMap;
  onSetFates: (ids: string[], fate: Fate | null) => void;
}) {
  const applicable = members.filter((c) => MESSAGE_BACKED_TYPES.has(c.type));
  // 无可落地成员(底座 system/tool_schema)→ 不可标记命运。
  if (applicable.length === 0) {
    const which = selected.type === "system" ? "系统提示" : "工具 schema";
    return (
      <div className="shrink-0 rounded border border-current/10 px-2 py-1.5 text-[11px] leading-snug text-text-tertiary">
        {which}由 agent 每轮重建，不经历史压缩移除——不可标记命运。
      </div>
    );
  }
  const multi = applicable.length > 1;
  // 目标派生:选 history(提问=本轮代表)/ 选中块不可落地 → 整轮;钻进具体成员 → 本块。
  const turnScope =
    selected.type === "history" || !MESSAGE_BACKED_TYPES.has(selected.type);
  const target = multi && !turnScope ? [selected] : applicable;
  const targetIds = target.map((c) => c.id);
  const fates = target.map((c) => fateMap?.[c.id]);
  const aggFate: Fate | null =
    fates.length > 0 && fates.every((f) => f && f === fates[0])
      ? (fates[0] as Fate)
      : null;
  const anyMarked = fates.some(Boolean);

  return (
    <div className="flex shrink-0 flex-col gap-1">
      {multi && (
        <div className="flex items-center gap-1.5 px-0.5 text-[10px] text-text-tertiary">
          <span className="shrink-0">命运 →</span>
          <span
            className="min-w-0 truncate text-text-secondary"
            title={turnScope ? undefined : selected.label}
          >
            {turnScope ? `整轮 · ${applicable.length} 块` : `本块 · ${chipLabel(selected)}`}
          </span>
        </div>
      )}
      <div className="flex items-center gap-1">
        {FATE_ACTIONS.map(({ fate: f, label, active }) => {
          const isActive = aggFate === f;
          const freed = target.reduce((s, c) => s + freedTokens(c, f), 0);
          return (
            <button
              key={f}
              type="button"
              onClick={() => onSetFates(targetIds, isActive ? null : f)}
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
          onClick={() => onSetFates(targetIds, null)}
          disabled={!anyMarked}
          aria-label="恢复（取消标记）"
          title="恢复（取消标记）"
          className={cn(
            "shrink-0 rounded border border-current/15 p-1.5 text-text-tertiary transition-colors",
            anyMarked ? "hover:text-text-secondary" : "cursor-default opacity-40",
          )}
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

/** 原文区:小标题 + 内容（**只有内容区内滚**）。对话轮里占 60%(grow-3 vs 构成 grow-2);
 *  折叠叶子里是唯一可伸长元素 → 占满余下。 */
function RawView({ chunk }: { chunk: ContextChunk }) {
  return (
    <section className="flex min-h-0 grow-3 basis-0 flex-col gap-1">
      <div className="flex shrink-0 items-center gap-2 px-0.5 text-[11px] tabular-nums text-text-tertiary">
        <span className="text-display tracking-wider">原文</span>
        <span>~{formatTokenCount(chunk.tokens)} tok</span>
        {chunk.raw != null && <span>{chunk.raw.length.toLocaleString()} 字符</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded border border-current/10 bg-current/5">
        {chunk.raw ? (
          <pre
            className={cn(
              "min-w-0 whitespace-pre-wrap wrap-break-word p-2",
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
    </section>
  );
}

export function ChunkInspector({
  chunk,
  onClose,
  turnChunks,
  onSelectChunk,
  fateMap,
  onSetFates,
  onPin,
  onPromote,
}: {
  chunk: ContextChunk | null;
  onClose: () => void;
  /** 选中块所属轮的全部 chunk(对话轮显「本轮构成」chip 区);压缩折叠块=终点叶子,传 undefined。 */
  turnChunks?: ContextChunk[];
  /** 点本轮构成里的成员块 → 钻进它。 */
  onSelectChunk?: (id: string) => void;
  /** 全量命运图（chip 命运点 + 命运控件聚合态）。 */
  fateMap?: FateMap;
  /** 命运批量预填(单块=传 [id],整轮=传该轮全部 message-backed id)。 */
  onSetFates?: (ids: string[], fate: Fate | null) => void;
  /** v2 keep-as-pin:把现有 chunk 升级为持久免压(或取消)→ context.pin 落地。 */
  onPin?: (chunkIds: string[], pinned: boolean) => void;
  /** v2 move·promote:把现有 chunk 提升为 system-prompt 常驻规则（move，删源）→ context.promote。 */
  onPromote?: (chunkId: string, text: string) => void;
}) {
  // v2 move·promote 编辑态：null=未编辑；非 null=正在把本块蒸成一条规则（用户自编辑 distill）。
  const [promoteText, setPromoteText] = useState<string | null>(null);

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

  // v2 `add` / `promote`：用户 co-author 块 —— 专用简视图（徽章 + 原文）。区分草稿 / 已落地 /
  // 已提升为规则，给准确提示（草稿不可标命运，无 chip 区）。
  if (chunk.added) {
    const isDraft = chunk.id.startsWith("add:draft:");
    const isPromoted = chunk.type === "system"; // system:sys:promoted = 已提升规则
    const badge = isPromoted
      ? "用户规则 · ⬆ 已提升"
      : `你注入 (add)${chunk.pinned ? " · 📌 pin" : ""}`;
    const hint = isDraft
      ? `草稿预览 · ${chunk.pinned ? "pin 持久免压缩" : "inline 随历史、可被压缩"} · 点下方「注入」落地`
      : isPromoted
        ? "已提升为 system-prompt 常驻规则（权威，下一轮即生效）"
        : chunk.pinned
          ? "已注入上下文 · 📌 持久免压缩"
          : "已注入上下文 · 随历史，会被压缩";
    return (
      <aside className="flex h-full w-full min-w-0 flex-col gap-2 overflow-hidden">
        <div className="flex shrink-0 items-start justify-between gap-2 px-1">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: CV_ADD }}
              />
              <span className="text-display text-xs tracking-wider text-text-tertiary">
                {badge}
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
        <div className="shrink-0 rounded border border-current/10 px-2 py-1 text-[10px] text-text-tertiary">
          {hint}
        </div>
        <RawView chunk={chunk} />
      </aside>
    );
  }

  const color = TYPE_COLOR[chunk.type] ?? "#888";
  // 对话轮(turnChunks 非空)→ 上下 40/60:chip 区 + 原文区;压缩折叠块=终点叶子(无 chip 区)。
  const hasComposition = !!turnChunks && turnChunks.length >= 1;

  return (
    <aside className="flex h-full w-full min-w-0 flex-col gap-2 overflow-hidden">
      {/* 头部：类型 + 标签 + 关闭（固定） */}
      <div className="flex shrink-0 items-start justify-between gap-2 px-1">
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
        <div className="flex shrink-0 items-center gap-1">
          {/* v2 keep-as-pin：现有 message-backed 块 → 持久免压 toggle（统一耐久度轴"护现有块"）。 */}
          {onPin && MESSAGE_BACKED_TYPES.has(chunk.type) && (
            <button
              type="button"
              onClick={() => onPin([chunk.id], !chunk.pinned)}
              className={cn(
                "rounded border px-1.5 py-0.5 text-[10px] tracking-wide transition-colors",
                chunk.pinned
                  ? "border-current/30 bg-current/10 text-text-secondary"
                  : "border-current/15 text-text-tertiary hover:text-text-secondary",
              )}
              title={
                chunk.pinned
                  ? "已钉住（持久免压）—— 点此取消钉住"
                  : "钉住：持久免压，扛过后续压缩（keep-as-pin）"
              }
            >
              {chunk.pinned ? "📌 已钉住" : "📌 钉住"}
            </button>
          )}
          {/* v2 move·promote：把本块提升为 system-prompt 常驻规则（统一耐久度轴顶档）。 */}
          {onPromote && MESSAGE_BACKED_TYPES.has(chunk.type) && (
            <button
              type="button"
              onClick={() =>
                setPromoteText(
                  (chunk.raw || chunk.label || "")
                    .replace(/^\[USER NOTE[^\]]*\]\s*/i, "")
                    .trim()
                    .slice(0, 400),
                )
              }
              className="rounded border border-current/15 px-1.5 py-0.5 text-[10px] tracking-wide text-text-tertiary transition-colors hover:text-text-secondary"
              title="提升为 system-prompt 常驻规则（权威，下一轮即生效；编辑成一条精炼规则，提升后删除原块）"
            >
              ⬆ 提升
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="close inspector"
            className="-mr-1 rounded p-0.5 text-text-tertiary hover:text-text-secondary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* v2 move·promote 编辑：把本块蒸成一条规则（用户自编辑 distill）→ 提升 + 删源。 */}
      {promoteText !== null && (
        <div
          className="flex shrink-0 flex-col gap-1.5 rounded border px-2 py-1.5"
          style={{ borderColor: `${CV_ADD}55` }}
        >
          <span className="text-[10px]" style={{ color: CV_ADD }}>
            ⬆ 提升为 system-prompt 规则 —— 编辑成一条精炼规则（提升后删除原块、下一轮生效）
          </span>
          <textarea
            value={promoteText}
            onChange={(e) => setPromoteText(e.target.value)}
            rows={2}
            className="resize-none rounded border border-current/15 bg-transparent px-1.5 py-1 text-xs text-text-secondary focus:outline-none focus:ring-1 focus:ring-current/20"
          />
          <div className="flex items-center justify-end gap-1.5 text-[10px]">
            <button
              type="button"
              onClick={() => setPromoteText(null)}
              className="rounded px-1.5 py-0.5 text-text-tertiary hover:text-text-secondary"
            >
              取消
            </button>
            <button
              type="button"
              disabled={!promoteText.trim()}
              onClick={() => {
                onPromote?.(chunk.id, promoteText.trim());
                setPromoteText(null);
              }}
              className={cn(
                "rounded border px-2 py-0.5 tracking-wide transition-colors",
                promoteText.trim()
                  ? "border-current/30 text-text-secondary hover:bg-current/10"
                  : "border-current/15 text-text-tertiary/50",
              )}
            >
              ⬆ 提升为规则
            </button>
          </div>
        </div>
      )}

      {hasComposition ? (
        <>
          {/* chip 区(40%):本轮构成 + 命运控件。只有 chip 列表内滚。 */}
          <section className="flex min-h-0 grow-2 basis-0 flex-col gap-1.5 rounded border border-current/10 px-2 py-1.5">
            <Composition
              members={turnChunks!}
              selectedId={chunk.id}
              onSelectChunk={onSelectChunk}
              fateMap={fateMap}
            />
            {onSetFates && (
              <FateControls
                members={turnChunks!}
                selected={chunk}
                fateMap={fateMap}
                onSetFates={onSetFates}
              />
            )}
          </section>
          {/* 原文区(约 50%):只有原文内容区内滚。 */}
          <RawView chunk={chunk} />
        </>
      ) : (
        <>
          {/* 压缩折叠块=终点叶子:无本轮构成,可对该摘要本身标命运,原文占满余下空间。 */}
          {onSetFates && (
            <FateControls
              members={[chunk]}
              selected={chunk}
              fateMap={fateMap}
              onSetFates={onSetFates}
            />
          )}
          <RawView chunk={chunk} />
        </>
      )}
    </aside>
  );
}
