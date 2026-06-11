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

import { X } from "lucide-react";

import { formatTokenCount } from "@/lib/format";
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

export function ChunkInspector({
  chunk,
  onClose,
}: {
  chunk: ContextChunk | null;
  onClose: () => void;
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
