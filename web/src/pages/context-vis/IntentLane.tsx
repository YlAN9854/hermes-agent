import { CornerDownRight } from "lucide-react";
import type { ContextVisSpan } from "@/lib/api";
import type { IntentLaneMark } from "@/lib/context-vis";
import { Pill } from "./shared";

export interface IntentLaneCellProps {
  readonly mark: IntentLaneMark | null;
}

export function IntentLaneCell({ mark }: IntentLaneCellProps) {
  if (!mark) return <span aria-hidden className="block min-h-full w-5" />;
  const rounded = mark.role === "single"
    ? "rounded-full"
    : mark.role === "start"
      ? "rounded-t-full"
      : mark.role === "end"
        ? "rounded-b-full"
        : "";
  return (
    <span
      aria-label={`${mark.segment.label}, ${mark.role} of intent segment`}
      className="flex min-h-full w-5 justify-center"
    >
      <span
        aria-hidden
        className={`block min-h-full w-1 ${rounded}`}
        style={{ background: "var(--cv-accent-2)" }}
      />
    </span>
  );
}

export interface IntentLaneHeadingProps {
  readonly mark: IntentLaneMark;
  readonly onLocate: (span: ContextVisSpan) => void;
}

export function IntentLaneHeading({
  mark,
  onLocate,
}: IntentLaneHeadingProps) {
  if (mark.role !== "start" && mark.role !== "single") return null;
  return (
    <div className="mb-1 flex min-w-0 flex-wrap items-center gap-1.5 px-1">
      <strong
        className="min-w-0 text-xs"
        style={{ color: "var(--cv-accent-2)", overflowWrap: "anywhere" }}
      >
        {mark.segment.label}
      </strong>
      <Pill>{mark.segment.origin === "llm_draft" ? "AI draft" : "user edited"}</Pill>
      {mark.segment.trigger_span && (
        <button
          aria-label={`Locate lane trigger for ${mark.segment.label}`}
          className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[11px]"
          onClick={() => {
            if (mark.segment.trigger_span) onLocate(mark.segment.trigger_span);
          }}
          style={{ color: "var(--cv-accent)" }}
          type="button"
        >
          <CornerDownRight className="h-3 w-3" />
          trigger
        </button>
      )}
    </div>
  );
}
