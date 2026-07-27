import { ExternalLink, MessageSquareText, Terminal } from "lucide-react";
import type {
  ContextVisSessionResponse,
  ContextVisSpan,
  ContextVisTurn,
} from "@/lib/api";
import {
  assertNever,
  type ConversationMode,
} from "@/lib/context-vis";
import { Button } from "@nous-research/ui/ui/components/button";
import { ModelViewTranscript } from "./ModelViewTranscript";
import { TranscriptView } from "./TranscriptView";
import {
  Empty,
  SegToggle,
} from "./shared";

export interface ConversationPanelProps {
  readonly detail: ContextVisSessionResponse | null;
  readonly selected: string | null;
  readonly mode: ConversationMode;
  readonly activeSpans: readonly ContextVisSpan[];
  readonly activeUnitTurns: ReadonlySet<string>;
  readonly onModeChange: (mode: ConversationMode) => void;
  readonly onSelectTurn: (turn: ContextVisTurn) => void;
  readonly onOpenLive: () => void;
}

export function ConversationPanel({
  detail,
  selected,
  mode,
  activeSpans,
  activeUnitTurns,
  onModeChange,
  onSelectTurn,
  onOpenLive,
}: ConversationPanelProps) {
  const options = [
    {
      v: "transcript",
      label: "Transcript",
      icon: <MessageSquareText className="h-3.5 w-3.5" />,
    },
    ...(detail?.compression
      ? [{ v: "model" as const, label: "Model", ariaLabel: "Model view" }]
      : []),
    {
      v: "live",
      label: "Live",
      icon: <Terminal className="h-3.5 w-3.5" />,
    },
  ] as const;

  let content: React.ReactNode;
  switch (mode) {
    case "transcript":
      content = detail
        ? (
          <TranscriptView
            activeSpans={activeSpans}
            activeUnitTurns={activeUnitTurns}
            onSelectTurn={onSelectTurn}
            transcript={detail.transcript}
          />
        )
        : <Empty>Select a session.</Empty>;
      break;
    case "model":
      content = detail?.compression
        ? (
          <ModelViewTranscript
            activeSpans={activeSpans}
            activeUnitTurns={activeUnitTurns}
            compression={detail.compression}
            onSelectTurn={onSelectTurn}
            transcript={detail.transcript}
          />
        )
        : <Empty>Model context is unavailable for this session.</Empty>;
      break;
    case "live":
      content = (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <Terminal className="h-8 w-8" style={{ color: "var(--cv-accent)" }} />
          <p className="text-sm" style={{ color: "var(--cv-text-dim)" }}>
            Drive this conversation in the live terminal.
          </p>
          <Button disabled={!selected} onClick={onOpenLive} outlined>
            <ExternalLink className="mr-1 h-4 w-4" />
            Open live terminal
          </Button>
          <p className="text-[11px]" style={{ color: "var(--cv-text-faint)" }}>
            Opens the full terminal with this session resumed.
          </p>
        </div>
      );
      break;
    default:
      content = assertNever(mode);
  }

  return (
    <section
      aria-label="Conversation"
      className="cv-conversation-panel flex min-h-0 min-w-0 flex-col border-r"
      style={{ borderColor: "var(--cv-border)", width: "35%" }}
    >
      <div
        className="flex shrink-0 flex-wrap items-center gap-1 border-b px-3 py-2"
        style={{ borderColor: "var(--cv-border)" }}
      >
        <SegToggle
          label="Conversation view"
          onChange={onModeChange}
          options={options}
          value={mode}
        />
        <span className="ml-auto shrink-0 text-[11px] font-mono" style={{ color: "var(--cv-text-dim)" }}>
          {detail ? `${detail.transcript.length} turns` : ""}
        </span>
      </div>
      {content}
    </section>
  );
}
