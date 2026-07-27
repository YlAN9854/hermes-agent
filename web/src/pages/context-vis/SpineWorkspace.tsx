import { ListChecks, Sparkles } from "lucide-react";
import { useState } from "react";
import type {
  ContextVisAggregate,
  ContextVisEditRequest,
  ContextVisIntentSegment,
  ContextVisSessionResponse,
  ContextVisSpan,
  ContextVisUnit,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { AggregateEditor } from "./AggregateEditor";
import { BacktrackSection } from "./BacktrackSection";
import { CompressionEvents } from "./CompressionEvents";
import { ConstraintLedger } from "./ConstraintLedger";
import {
  IntentTrack,
  type IntentTrackSaveResult,
  type TurnCaptureHandler,
} from "./IntentTrack";
import { SpineLegend } from "./SpineUnit";
import { SpineUnitList } from "./SpineUnitList";
import {
  Empty,
  SegToggle,
} from "./shared";

type SpineMode = "overview" | "decision";
type EditPatch = Omit<ContextVisEditRequest, "revision" | "intent_segments">;

export interface SpineWorkspaceProps {
  readonly detail: ContextVisSessionResponse | null;
  readonly working: boolean;
  readonly activeUnit: string | null;
  readonly onDetailChange: (detail: ContextVisSessionResponse) => void;
  readonly onRunJob: (body: {
    readonly action: "generate_units" | "detect_salient" | "draft_aggregates";
    readonly incremental?: boolean;
    readonly mode?: SpineMode;
    readonly intent?: string;
  }) => void;
  readonly onSaveEdits: (patch: EditPatch) => Promise<void>;
  readonly onSaveIntent: (
    segments: readonly ContextVisIntentSegment[],
  ) => Promise<IntentTrackSaveResult>;
  readonly onTogglePin: (unit: ContextVisUnit) => void;
  readonly onSelectUnit: (unit: ContextVisUnit) => void;
  readonly onLocate: (span: ContextVisSpan) => void;
  readonly onHoverSpans: (spans: readonly ContextVisSpan[]) => void;
  readonly onCaptureHandler: (handler: TurnCaptureHandler | null) => void;
}

export function SpineWorkspace({
  detail,
  working,
  activeUnit,
  onDetailChange,
  onRunJob,
  onSaveEdits,
  onSaveIntent,
  onTogglePin,
  onSelectUnit,
  onLocate,
  onHoverSpans,
  onCaptureHandler,
}: SpineWorkspaceProps) {
  const [mode, setMode] = useState<SpineMode>("overview");
  const [intent, setIntent] = useState("");
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const units = detail?.model.units ?? [];
  const tier = detail?.capabilities.tier ?? 1;
  const aggregates = detail
    ? (mode === "overview"
      ? detail.model.aggregates
      : detail.model.decision_aggregates)
    : [];

  if (!detail) return <Empty>Select a session to see its semantic structure.</Empty>;
  if (units.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <Sparkles className="h-8 w-8" style={{ color: "var(--cv-accent)" }} />
        <p className="text-sm" style={{ color: "var(--cv-text-dim)" }}>
          No semantic view yet for this session.
        </p>
        <Button
          disabled={working}
          onClick={() => onRunJob({ action: "generate_units" })}
        >
          <Sparkles className="mr-1 h-4 w-4" />
          Generate semantic view
        </Button>
      </div>
    );
  }

  const updateAggregates = (nodes: ContextVisAggregate[]): void => {
    const field = mode === "overview" ? "aggregates" : "decision_aggregates";
    onDetailChange({
      ...detail,
      model: { ...detail.model, [field]: nodes },
    });
  };
  const compression = detail.compression;

  return (
    <>
      <div
        className="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-3 py-2"
        style={{ borderColor: "var(--cv-border)" }}
      >
        <Button
          disabled={working}
          onClick={() => onRunJob({ action: "generate_units", incremental: true })}
          outlined
          size="sm"
        >
          Append turns
        </Button>
        <Button
          disabled={working}
          onClick={() => onRunJob({ action: "detect_salient" })}
          outlined
          size="sm"
        >
          Detect salient
        </Button>
        <Button
          aria-pressed={ledgerOpen}
          onClick={() => setLedgerOpen((open) => !open)}
          outlined
          size="sm"
        >
          <ListChecks className="mr-1 h-3.5 w-3.5" />
          Ledger
        </Button>
        <div className="mx-1 h-4 w-px" style={{ background: "var(--cv-border)" }} />
        <SegToggle
          label="Spine aggregation mode"
          onChange={setMode}
          options={[
            { v: "overview", label: "Overview" },
            { v: "decision", label: "Decision" },
          ]}
          value={mode}
        />
        {mode === "decision" && (
          <Input
            className="h-7 w-40 text-xs"
            onChange={(event) => setIntent(event.target.value)}
            placeholder="Continue, or turn toward…"
            value={intent}
          />
        )}
        <Button
          disabled={working || (mode === "decision" && !intent.trim())}
          onClick={() => onRunJob({ action: "draft_aggregates", mode, intent })}
          outlined
          size="sm"
        >
          Draft aggregation
        </Button>
      </div>
      <SpineLegend tier={tier} />
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-3 py-3">
        {detail.model.legacy_transcript_warning && (
          <div
            className="rounded-lg px-3 py-2 text-xs"
            style={{
              background: "color-mix(in srgb, var(--cv-reframed) 10%, transparent)",
              color: "var(--cv-reframed)",
            }}
          >
            {detail.model.legacy_transcript_warning}
          </div>
        )}
        {ledgerOpen && (
          <ConstraintLedger
            onLocateInfo={(info) => onLocate(info.span_in_B)}
            onLocateUnit={(unitId) => {
              const unit = units.find((candidate) => candidate.unit_id === unitId);
              if (unit) onSelectUnit(unit);
            }}
            tier={tier}
            units={units}
          />
        )}
        {aggregates.length > 0 && (
          <section aria-label={`${mode} aggregation`} className="cv-panel space-y-2 p-2">
            <h2
              className="text-[11px] font-mono uppercase tracking-wide"
              style={{ color: "var(--cv-text-dim)" }}
            >
              {mode} aggregation
            </h2>
            <AggregateEditor
              nodes={aggregates}
              onChange={updateAggregates}
              tier={tier}
              units={units}
            />
            <Button
              onClick={() => void onSaveEdits(mode === "overview"
                ? { aggregates }
                : {
                  decision_aggregates: aggregates,
                  decision_intent: detail.model.decision_intent,
                })}
              size="sm"
            >
              Save aggregation
            </Button>
          </section>
        )}
        <SpineUnitList
          activeUnit={activeUnit}
          detail={detail}
          onHoverSpans={onHoverSpans}
          onLocate={onLocate}
          onSelectUnit={onSelectUnit}
          onTogglePin={onTogglePin}
        />
        {compression && <CompressionEvents events={compression.events} />}
        <IntentTrack
          disabled={working}
          onCaptureHandler={onCaptureHandler}
          onLocate={onLocate}
          onSave={onSaveIntent}
          segments={detail.model.intent_segments}
          units={units}
        />
        <BacktrackSection
          detail={detail}
          onChange={onDetailChange}
          onSave={onSaveEdits}
        />
      </div>
    </>
  );
}
