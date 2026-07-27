import type { ReactNode } from "react";
import type {
  ContextVisSpan,
  ContextVisTurn,
} from "@/lib/api";
import { buildHighlightSegments } from "@/lib/context-vis";
import {
  inferCjkLanguage,
  phraseAwareChunks,
} from "./phrase-aware-text";

const ROLE_COLOR: Readonly<Record<ContextVisTurn["role"], string>> = {
  user: "var(--cv-accent)",
  assistant: "var(--cv-text)",
  tool: "var(--cv-text-dim)",
};

export interface PillProps {
  readonly children: ReactNode;
  readonly color?: string;
  readonly title?: string;
}

export function Pill({ children, color, title }: PillProps) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide"
      style={{
        color: color ?? "var(--cv-text-dim)",
        background: "color-mix(in srgb, currentColor 12%, transparent)",
      }}
    >
      {children}
    </span>
  );
}

export interface SegmentOption<T extends string> {
  readonly v: T;
  readonly label: string;
  readonly ariaLabel?: string;
  readonly icon?: ReactNode;
}

export interface SegToggleProps<T extends string> {
  readonly value: T;
  readonly onChange: (value: T) => void;
  readonly options: readonly SegmentOption<T>[];
  readonly label: string;
}

export function SegToggle<T extends string>({
  value,
  onChange,
  options,
  label,
}: SegToggleProps<T>) {
  return (
    <div
      aria-label={label}
      className="inline-flex min-w-0 max-w-full flex-wrap rounded-md p-0.5"
      role="group"
      style={{
        background: "var(--cv-surface)",
        border: "1px solid var(--cv-border)",
      }}
    >
      {options.map((option) => (
        <button
          aria-label={option.ariaLabel}
          aria-pressed={value === option.v}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors"
          key={option.v}
          onClick={() => onChange(option.v)}
          style={value === option.v
            ? { background: "var(--cv-accent)", color: "var(--cv-on-accent)" }
            : { color: "var(--cv-text-dim)" }}
          type="button"
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { readonly children: ReactNode }) {
  return (
    <div
      className="flex flex-1 items-center justify-center p-6 text-sm"
      style={{ color: "var(--cv-text-dim)" }}
    >
      {children}
    </div>
  );
}

interface HighlightedTextProps {
  readonly content: string;
  readonly spans: readonly ContextVisSpan[];
  readonly turnId: string;
}

function HighlightedText({
  content,
  spans,
  turnId,
}: HighlightedTextProps) {
  const language = inferCjkLanguage(content);
  return (
    <>
      {buildHighlightSegments(content, spans, turnId).map((part, index) => (
        part.highlighted
          ? (
            <mark
              key={`${index}-${part.text}`}
              style={{
                background: "color-mix(in srgb, var(--cv-accent) 30%, transparent)",
                color: "var(--cv-text)",
              }}
            >
              {phraseAwareChunks(part.text, language).map((chunk, chunkIndex) => (
                <span
                  className={chunk.keepTogether ? "cv-cjk-phrase" : undefined}
                  key={`${chunkIndex}-${chunk.text}`}
                >
                  {chunk.text}
                </span>
              ))}
            </mark>
          )
          : (
            <span key={`${index}-${part.text}`}>
              {phraseAwareChunks(part.text, language).map((chunk, chunkIndex) => (
                <span
                  className={chunk.keepTogether ? "cv-cjk-phrase" : undefined}
                  key={`${chunkIndex}-${chunk.text}`}
                >
                  {chunk.text}
                </span>
              ))}
            </span>
          )
      ))}
    </>
  );
}

export interface TranscriptTurnCardProps {
  readonly turn: ContextVisTurn;
  readonly turnNumber: number;
  readonly active: boolean;
  readonly muted?: boolean;
  readonly spans: readonly ContextVisSpan[];
  readonly onSelect: (turn: ContextVisTurn) => void;
}

export function TranscriptTurnCard({
  turn,
  turnNumber,
  active,
  muted = false,
  spans,
  onSelect,
}: TranscriptTurnCardProps) {
  const contentLanguage = inferCjkLanguage(turn.content);
  return (
    <article
      className="min-w-0 rounded-lg"
      id={`cv-turn-${turn.turn_id}`}
      style={{
        background: active
          ? "color-mix(in srgb, var(--cv-accent) 8%, var(--cv-surface))"
          : "var(--cv-surface)",
        border: `1px solid ${active ? "var(--cv-accent)" : "var(--cv-border)"}`,
        opacity: muted ? 0.7 : 1,
      }}
    >
      <button
        aria-label={`Select turn ${turnNumber}: ${turn.role}`}
        className="cv-turn-button block min-w-0 w-full cursor-pointer px-3 py-2 text-left transition-colors"
        onClick={() => onSelect(turn)}
        type="button"
      >
        <span
          className="mb-1 flex items-center gap-2 text-[10px] font-mono uppercase tracking-wide"
          style={{ color: ROLE_COLOR[turn.role] }}
        >
          <span>{turn.role}</span>
          {turn.tool_name && (
            <span style={{ color: "var(--cv-text-dim)" }}>
              · {turn.tool_name}
            </span>
          )}
        </span>
        <pre
          className="cv-turn-content max-h-64 min-w-0 max-w-full overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed"
          lang={contentLanguage}
          style={{
            color: turn.role === "tool"
              ? "var(--cv-text-dim)"
              : "var(--cv-text)",
          }}
        >
          <HighlightedText
            content={turn.content}
            spans={spans}
            turnId={turn.turn_id}
          />
        </pre>
      </button>
    </article>
  );
}
