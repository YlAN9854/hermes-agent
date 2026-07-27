import type {
  ContextVisSpan,
  ContextVisTurn,
} from "@/lib/api";
import {
  Empty,
  TranscriptTurnCard,
} from "./shared";

export interface TranscriptViewProps {
  readonly transcript: readonly ContextVisTurn[];
  readonly activeSpans: readonly ContextVisSpan[];
  readonly activeUnitTurns: ReadonlySet<string>;
  readonly onSelectTurn: (turn: ContextVisTurn) => void;
}

export function TranscriptView({
  transcript,
  activeSpans,
  activeUnitTurns,
  onSelectTurn,
}: TranscriptViewProps) {
  if (transcript.length === 0) return <Empty>No transcript turns.</Empty>;
  return (
    <div className="h-full min-h-0 space-y-2 overflow-auto px-3 py-3">
      {transcript.map((turn, index) => (
        <TranscriptTurnCard
          active={activeUnitTurns.has(turn.turn_id)}
          key={turn.turn_id}
          onSelect={onSelectTurn}
          spans={activeSpans}
          turn={turn}
          turnNumber={index + 1}
        />
      ))}
    </div>
  );
}
