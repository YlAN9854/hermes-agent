import { Pin, PinOff } from "lucide-react";
import type {
  ContextVisInfo,
  ContextVisTurn,
  ContextVisUnit,
} from "@/lib/api";
import {
  dominantSurvival,
  sliceCodePoints,
  summariseSurvival,
  unitIsPinned,
} from "@/lib/context-vis";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Pill,
} from "./shared";
import { SURVIVAL } from "./visual-encoding";

export function SpineLegend({ tier }: { readonly tier: number }) {
  if (tier < 2) return null;
  return (
    <div
      className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-1.5 text-[10px] font-mono"
      style={{
        background: "var(--cv-surface-2)",
        borderColor: "var(--cv-border)",
        color: "var(--cv-text-faint)",
      }}
    >
      <span className="uppercase tracking-wide">Encoding</span>
      {Object.values(SURVIVAL).map((status) => (
        <span
          className="inline-flex items-center gap-1"
          key={status.label}
          style={{ color: "var(--cv-text-dim)" }}
        >
          <span aria-hidden style={{ color: status.color }}>{status.icon}</span>
          {status.label}
        </span>
      ))}
      {tier >= 3 && (
        <span className="inline-flex items-center gap-1" style={{ color: "var(--cv-text-dim)" }}>
          <Pin className="h-3 w-3" style={{ color: "var(--cv-pin)" }} />
          pinned
        </span>
      )}
      <span style={{ color: "var(--cv-text-dim)" }}>left rail = dominant status</span>
    </div>
  );
}

export interface SalientRowProps {
  readonly info: ContextVisInfo;
  readonly turn: ContextVisTurn | undefined;
  readonly turnNumber: number;
  readonly tier: number;
  readonly open: boolean;
  readonly onToggle: () => void;
  readonly onLocate: () => void;
}

export function SalientRow({
  info,
  turn,
  turnNumber,
  tier,
  open,
  onToggle,
  onLocate,
}: SalientRowProps) {
  const status = tier >= 2 && info.status_in_A !== "unknown"
    ? SURVIVAL[info.status_in_A]
    : null;
  const actionable = status !== null && info.status_in_A !== "present";
  const original = turn
    ? sliceCodePoints(turn.content, info.span_in_B.char_start, info.span_in_B.char_end)
    : info.detected_text;
  return (
    <div
      className="min-w-0 rounded-md px-2 py-1.5 text-xs"
      style={{
        background: "var(--cv-bg-2)",
        boxShadow: "inset 2px 0 0 0 var(--cv-border-strong)",
      }}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Pill color={info.confidence === "reliable"
          ? "var(--cv-salient-reliable)"
          : "var(--cv-salient-guessed)"}
        >
          {info.confidence === "reliable" ? "rule" : "AI"}
        </Pill>
        {status && (
          <button
            className={actionable ? "underline decoration-dotted" : ""}
            disabled={!actionable}
            onClick={actionable ? onToggle : undefined}
            style={{ color: status.color }}
            title={actionable ? `${status.label}, open detail` : status.label}
            type="button"
          >
            <span aria-hidden>{status.icon}</span> {status.label}
          </button>
        )}
        <span className="min-w-0" style={{ color: "var(--cv-text)", overflowWrap: "anywhere" }}>
          {info.detected_text}
        </span>
      </div>
      {open && (
        <div
          className="mt-2 min-w-0 rounded border p-2"
          style={{ borderColor: "var(--cv-border)" }}
        >
          {info.status_in_A === "reframed"
            ? (
              <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                <div className="min-w-0">
                  <div className="mb-1" style={{ color: "var(--cv-text-dim)" }}>
                    Original, turn {turnNumber}
                  </div>
                  <p style={{ color: "var(--cv-text)", overflowWrap: "anywhere" }}>{original}</p>
                </div>
                <div className="min-w-0">
                  <div className="mb-1" style={{ color: "var(--cv-text-dim)" }}>
                    How the model now sees it
                  </div>
                  <p style={{ color: "var(--cv-reframed)", overflowWrap: "anywhere" }}>
                    {info.reframed_text_in_A}
                  </p>
                </div>
              </div>
            )
            : (
              <p style={{ color: "var(--cv-text)" }}>
                The model can no longer see this. The original remains in turn {turnNumber}.
              </p>
            )}
          <Button className="mt-2" onClick={onLocate} outlined size="sm">
            Show me in the transcript
          </Button>
        </div>
      )}
    </div>
  );
}

export interface SpineUnitProps {
  readonly unit: ContextVisUnit;
  readonly tier: number;
  readonly preserved: readonly string[];
  readonly active: boolean;
  readonly aliveness: { readonly alive: number; readonly total: number } | null;
  readonly approximateAliveness: boolean;
  readonly onSelect: () => void;
  readonly onTogglePin: () => void;
  readonly detail: React.ReactNode;
}

export function SpineUnit({
  unit,
  tier,
  preserved,
  active,
  aliveness,
  approximateAliveness,
  onSelect,
  onTogglePin,
  detail,
}: SpineUnitProps) {
  const dominant = dominantSurvival(unit.salient_infos, tier);
  const railColor = dominant ? SURVIVAL[dominant].color : "var(--cv-border-strong)";
  const pinned = unitIsPinned(unit, preserved);
  const rollup = summariseSurvival(unit.salient_infos, tier);
  const reliable = unit.salient_infos.filter((info) => info.confidence === "reliable").length;
  const guessed = unit.salient_infos.filter((info) => info.confidence === "ai_guessed").length;
  return (
    <article
      className="min-w-0 rounded-lg transition-colors"
      id={`cv-unit-${unit.unit_id}`}
      style={{
        background: active
          ? "color-mix(in srgb, var(--cv-accent) 8%, var(--cv-surface))"
          : "var(--cv-surface)",
        border: `1px solid ${active ? "var(--cv-accent)" : "var(--cv-border)"}`,
        boxShadow: `inset 3px 0 0 0 ${railColor}`,
      }}
    >
      <button className="w-full min-w-0 px-3 py-2 text-left" onClick={onSelect} type="button">
        <span className="flex min-w-0 items-start justify-between gap-2">
          <strong
            className="min-w-0 text-sm"
            style={{ color: "var(--cv-text)", overflowWrap: "anywhere" }}
          >
            {unit.title || "Untitled unit"}
          </strong>
          <span className="flex shrink-0 items-center gap-1">
            {pinned && <Pin className="h-3.5 w-3.5" style={{ color: "var(--cv-pin)" }} />}
            {rollup && rollup.reframed + rollup.absent > 0 && (
              <span className="text-[10px] font-mono">
                <span className="cv-reframed">{rollup.reframed}◐</span>
                {" "}
                <span className="cv-absent">{rollup.absent}○</span>
              </span>
            )}
          </span>
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1">
          {reliable > 0 && <Pill title="rule-matched constraints">{reliable} rule</Pill>}
          {guessed > 0 && (
            <Pill color="var(--cv-salient-guessed)" title="AI-guessed constraints">
              {guessed} AI
            </Pill>
          )}
          <Pill title="turns covered">{unit.covered_turns.length} turns</Pill>
          {aliveness && (
            <Pill title={approximateAliveness ? "approximate current-context coverage" : "current-context coverage"}>
              {approximateAliveness ? "~" : ""}{aliveness.alive}/{aliveness.total} in context
            </Pill>
          )}
          {!unit.frozen && <Pill color="var(--cv-accent)">draft</Pill>}
        </span>
      </button>
      {active && (
        <div className="border-t px-3 py-2" style={{ borderColor: "var(--cv-border)" }}>
          {detail}
        </div>
      )}
      {active && tier >= 3 && (
        <div
          className="flex flex-wrap items-center gap-2 border-t px-3 py-2"
          style={{ borderColor: "var(--cv-border)" }}
        >
          <Button onClick={onTogglePin} outlined size="sm">
            {pinned
              ? <><PinOff className="mr-1 h-3 w-3" />Unpin from context</>
              : <><Pin className="mr-1 h-3 w-3" style={{ color: "var(--cv-pin)" }} />Preserve through compaction</>}
          </Button>
          <span className="text-[11px]" style={{ color: "var(--cv-text-dim)" }}>
            {pinned
              ? "Kept verbatim when the model compacts."
              : "Pin so compaction does not summarize it away."}
          </span>
        </div>
      )}
    </article>
  );
}
