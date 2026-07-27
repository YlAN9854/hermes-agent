import { useMemo, useState } from "react";
import type {
  ContextVisSessionResponse,
  ContextVisSpan,
  ContextVisUnit,
} from "@/lib/api";
import {
  intentLaneMarks,
  unitAliveness,
} from "@/lib/context-vis";
import {
  IntentLaneCell,
  IntentLaneHeading,
} from "./IntentLane";
import {
  SalientRow,
  SpineUnit,
} from "./SpineUnit";

export interface SpineUnitListProps {
  readonly detail: ContextVisSessionResponse;
  readonly activeUnit: string | null;
  readonly onSelectUnit: (unit: ContextVisUnit) => void;
  readonly onTogglePin: (unit: ContextVisUnit) => void;
  readonly onLocate: (span: ContextVisSpan) => void;
  readonly onHoverSpans: (spans: readonly ContextVisSpan[]) => void;
}

export function SpineUnitList({
  detail,
  activeUnit,
  onSelectUnit,
  onTogglePin,
  onLocate,
  onHoverSpans,
}: SpineUnitListProps) {
  const [inspecting, setInspecting] = useState<string | null>(null);
  const units = detail.model.units;
  const tier = detail.capabilities.tier;
  const laneMarks = useMemo(
    () => intentLaneMarks(units, detail.model.intent_segments),
    [detail.model.intent_segments, units],
  );
  const compression = detail.compression;
  const alivenessAvailable = compression !== null && compression.events.length > 0;
  const approximateAliveness = compression?.fidelity === "reconstructed"
    || (compression?.unlinked_live_count ?? 0) > 0;
  const turnNumber = (turnId: string): number => (
    detail.transcript.findIndex((turn) => turn.turn_id === turnId) + 1
  );

  return (
    <div className="space-y-2">
      {units.map((unit, index) => {
        const mark = laneMarks[index] ?? null;
        return (
          <div
            className="grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] gap-1"
            key={unit.unit_id}
          >
            <IntentLaneCell mark={mark} />
            <div className="min-w-0">
              {mark && <IntentLaneHeading mark={mark} onLocate={onLocate} />}
              <SpineUnit
                active={activeUnit === unit.unit_id}
                aliveness={unitAliveness(
                  unit,
                  alivenessAvailable && compression ? compression.live_turn_ids : null,
                )}
                approximateAliveness={approximateAliveness}
                detail={(
                  <div className="space-y-2">
                    {unit.summary_sentences.map((sentence, sentenceIndex) => (
                      <p
                        className="text-xs leading-relaxed"
                        key={`${unit.unit_id}-summary-${sentenceIndex}`}
                        onMouseEnter={() => onHoverSpans(sentence.source_spans)}
                        onMouseLeave={() => onHoverSpans([])}
                        style={{
                          color: "var(--cv-text-dim)",
                          overflowWrap: "anywhere",
                        }}
                      >
                        {sentence.text}
                      </p>
                    ))}
                    {unit.salient_infos.map((info) => (
                      <SalientRow
                        info={info}
                        key={info.info_id}
                        onLocate={() => onLocate(info.span_in_B)}
                        onToggle={() => setInspecting((current) => (
                          current === info.info_id ? null : info.info_id
                        ))}
                        open={inspecting === info.info_id}
                        tier={tier}
                        turn={detail.transcript.find(
                          (turn) => turn.turn_id === info.span_in_B.turn_id,
                        )}
                        turnNumber={turnNumber(info.span_in_B.turn_id)}
                      />
                    ))}
                  </div>
                )}
                onSelect={() => onSelectUnit(unit)}
                onTogglePin={() => onTogglePin(unit)}
                preserved={detail.model.preserved}
                tier={tier}
                unit={unit}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
