import { ChevronDown, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  ContextVisCompression,
  ContextVisSpan,
  ContextVisTurn,
} from "@/lib/api";
import {
  assertNever,
  groupTranscriptForALens,
} from "@/lib/context-vis";
import {
  Empty,
  Pill,
  TranscriptTurnCard,
} from "./shared";

export interface ModelViewTranscriptProps {
  readonly transcript: readonly ContextVisTurn[];
  readonly compression: ContextVisCompression;
  readonly activeSpans: readonly ContextVisSpan[];
  readonly activeUnitTurns: ReadonlySet<string>;
  readonly onSelectTurn: (turn: ContextVisTurn) => void;
}

export function ModelViewTranscript({
  transcript,
  compression,
  activeSpans,
  activeUnitTurns,
  onSelectTurn,
}: ModelViewTranscriptProps) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const groups = groupTranscriptForALens(transcript, compression.live_turn_ids) ?? [];
  const turnNumbers = useMemo(
    () => new Map(transcript.map((turn, index) => [turn.turn_id, index + 1])),
    [transcript],
  );
  const uncertain = compression.fidelity === "reconstructed"
    || compression.unlinked_live_count > 0;

  return (
    <div className="h-full min-h-0 space-y-2 overflow-auto px-3 py-3">
      {compression.synthetic_entries.map((entry, index) => (
        <section
          aria-label={`Synthetic context entry ${index + 1}`}
          className="min-w-0 rounded-lg border border-dashed px-3 py-2"
          key={`${entry.role}:${entry.content}`}
          style={{
            background: "var(--cv-accent-dim)",
            borderColor: "var(--cv-accent)",
          }}
        >
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <strong className="text-xs" style={{ color: "var(--cv-text)" }}>
              Synthetic summary
            </strong>
            <Pill color="var(--cv-accent)">{compression.fidelity}</Pill>
            <Pill>{entry.role}</Pill>
          </div>
          <p className="mb-2 text-[11px]" style={{ color: "var(--cv-text-dim)" }}>
            Written by compaction; this text is not part of the immutable transcript.
          </p>
          <pre
            className="max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed"
            style={{ color: "var(--cv-text)", overflowWrap: "anywhere" }}
          >
            {entry.content}
          </pre>
        </section>
      ))}

      {uncertain && (
        <div
          aria-label="Model context uncertainty"
          className="flex items-start gap-2 rounded-lg px-3 py-2 text-xs"
          role="status"
          style={{
            background: "var(--cv-reframed-dim)",
            color: "var(--cv-reframed)",
          }}
        >
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            This context was reconstructed and {compression.unlinked_live_count} live
            {compression.unlinked_live_count === 1 ? " entry cannot" : " entries cannot"} be
            linked back to a transcript turn. Missing links below are uncertain, not proof
            that a turn is absent.
            {compression.events.length === 0 && " No observed compression event history is available."}
          </span>
        </div>
      )}

      {compression.events.length === 0 && !uncertain && (
        <div
          className="rounded-lg px-3 py-2 text-xs"
          role="status"
          style={{
            background: "var(--cv-present-dim)",
            color: "var(--cv-present)",
          }}
        >
          This context has never been compacted — the model sees the full transcript.
        </div>
      )}

      {transcript.length === 0 && <Empty>No transcript turns.</Empty>}
      {groups.map((group) => {
        switch (group.kind) {
          case "live":
            return (
              <TranscriptTurnCard
                active={activeUnitTurns.has(group.turn.turn_id)}
                key={`live-${group.turn.turn_id}`}
                onSelect={onSelectTurn}
                spans={activeSpans}
                turn={group.turn}
                turnNumber={turnNumbers.get(group.turn.turn_id) ?? 0}
              />
            );
          case "dead": {
            const first = group.turns[0];
            const last = group.turns.at(-1);
            if (!first || !last) return null;
            const groupId = `${first.turn_id}:${last.turn_id}`;
            const isExpanded = expanded.has(groupId);
            const count = group.turns.length;
            const stateLabel = uncertain
              ? `${count} ${count === 1 ? "turn" : "turns"} not linked to reconstructed context`
              : `${count} ${count === 1 ? "turn" : "turns"} no longer in context`;
            return (
              <section className="min-w-0 space-y-2" key={`dead-${groupId}`}>
                <button
                  aria-expanded={isExpanded}
                  aria-label={`${stateLabel}; ${isExpanded ? "collapse" : "expand"}`}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs"
                  onClick={() => setExpanded((current) => {
                    const next = new Set(current);
                    if (isExpanded) next.delete(groupId);
                    else next.add(groupId);
                    return next;
                  })}
                  style={{
                    background: "var(--cv-bg-2)",
                    border: "1px dashed var(--cv-border-strong)",
                    color: "var(--cv-text-dim)",
                  }}
                  type="button"
                >
                  <ChevronDown
                    className={`h-4 w-4 shrink-0 ${isExpanded ? "rotate-180" : ""}`}
                  />
                  <span>{stateLabel}</span>
                </button>
                {isExpanded && group.turns.map((turn) => (
                  <TranscriptTurnCard
                    active={activeUnitTurns.has(turn.turn_id)}
                    key={turn.turn_id}
                    muted
                    onSelect={onSelectTurn}
                    spans={activeSpans}
                    turn={turn}
                    turnNumber={turnNumbers.get(turn.turn_id) ?? 0}
                  />
                ))}
              </section>
            );
          }
          default:
            return assertNever(group);
        }
      })}
    </div>
  );
}
