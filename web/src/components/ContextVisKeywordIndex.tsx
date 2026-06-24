import { cn } from "@/lib/utils";
import { CV_ARC } from "@/lib/contextvis/theme";
import { formatTokenCount } from "@/lib/format";
import type { ReferenceFile, ReferenceKeyword } from "@/lib/contextvis/apply";

const TRACE_COLOR = CV_ARC.trace;

function baseName(p: string): string {
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : p;
}

function IndexRow({
  label,
  title,
  meta,
  on,
  onClick,
}: {
  label: string;
  title: string;
  meta: string;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      style={on ? { backgroundColor: `${TRACE_COLOR}33` } : undefined}
      className={cn(
        "flex items-center justify-between gap-1 rounded px-1.5 py-0.5 text-left text-[11px] transition-colors",
        on ? "text-text-primary" : "text-text-secondary hover:bg-current/10",
      )}
    >
      <span className="min-w-0 truncate">{label}</span>
      <span className="shrink-0 tabular-nums text-text-tertiary">{meta}</span>
    </button>
  );
}

export function ContextVisKeywordIndex({
  files,
  keywords,
  traced,
  onTrace,
}: {
  files: ReferenceFile[];
  keywords: ReferenceKeyword[];
  traced: string | null;
  onTrace: (key: string | null) => void;
}) {
  return (
    <div className="flex w-32 shrink-0 flex-col overflow-hidden border-l border-current/10 pl-2">
      <div className="flex items-center justify-between pb-1 text-[10px] tracking-wider text-text-tertiary">
        <span className="text-display">产物/关键词</span>
        {traced && (
          <button
            type="button"
            onClick={() => onTrace(null)}
            className="rounded px-1 text-text-tertiary hover:text-text-secondary"
            title="退出追踪"
          >
            ✕
          </button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {files.map((f) => (
          <IndexRow
            key={`file:${f.key}`}
            label={`📄 ${baseName(f.key)}`}
            title={`文件 ${f.key} · ${f.n} 块 · ${formatTokenCount(f.tokens)} tok — 点击在画布追踪其路径`}
            meta={formatTokenCount(f.tokens)}
            on={f.key === traced}
            onClick={() => onTrace(f.key === traced ? null : f.key)}
          />
        ))}
        {files.length > 0 && keywords.length > 0 && (
          <div className="my-0.5 border-t border-current/10" />
        )}
        {keywords.map((k) => (
          <IndexRow
            key={`kw:${k.key}`}
            label={k.key}
            title={`「${k.key}」出现在 ${k.n} 个块 — 点击在画布追踪其贯穿路径`}
            meta={String(k.n)}
            on={k.key === traced}
            onClick={() => onTrace(k.key === traced ? null : k.key)}
          />
        ))}
      </div>
    </div>
  );
}
