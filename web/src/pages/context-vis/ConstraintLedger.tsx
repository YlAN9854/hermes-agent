import { Crosshair, ListChecks } from "lucide-react";
import type {
  ContextVisInfo,
  ContextVisUnit,
} from "@/lib/api";
import {
  buildLedgerRows,
  summariseSurvival,
  type LedgerRow,
} from "@/lib/context-vis";
import {
  Pill,
} from "./shared";
import { SURVIVAL } from "./visual-encoding";

export interface ConstraintLedgerProps {
  readonly units: readonly ContextVisUnit[];
  readonly tier: number;
  readonly onLocateUnit: (unitId: string) => void;
  readonly onLocateInfo: (info: ContextVisInfo) => void;
}

interface LedgerSectionProps {
  readonly heading: string;
  readonly rows: readonly LedgerRow[];
  readonly tier: number;
  readonly onLocateUnit: (unitId: string) => void;
  readonly onLocateInfo: (info: ContextVisInfo) => void;
}

function LedgerSection({
  heading,
  rows,
  tier,
  onLocateUnit,
  onLocateInfo,
}: LedgerSectionProps) {
  return (
    <section aria-label={heading} className="space-y-1.5">
      <div className="flex items-center gap-2">
        <h3
          className="text-[11px] font-mono uppercase tracking-wide"
          style={{ color: "var(--cv-text-dim)" }}
        >
          {heading}
        </h3>
        <Pill>{rows.length}</Pill>
      </div>
      {rows.length === 0
        ? <p className="text-xs" style={{ color: "var(--cv-text-faint)" }}>None detected.</p>
        : rows.map((row) => {
          const status = row.info.status_in_A === "unknown"
            ? null
            : SURVIVAL[row.info.status_in_A];
          return (
            <article
              className="min-w-0 rounded-md px-2 py-1.5"
              key={row.info.info_id}
              style={{
                background: "var(--cv-bg-2)",
                boxShadow: `inset 2px 0 0 0 ${status?.color ?? "var(--cv-border-strong)"}`,
              }}
            >
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <button
                  className="max-w-full truncate rounded px-1.5 py-0.5 text-[10px] font-mono"
                  onClick={() => onLocateUnit(row.unitId)}
                  style={{
                    background: "var(--cv-surface)",
                    color: "var(--cv-accent-2)",
                  }}
                  title={row.unitTitle}
                  type="button"
                >
                  {row.unitTitle || "Untitled unit"}
                </button>
                {status && (
                  <span
                    className="text-[10px] font-mono"
                    style={{ color: status.color }}
                  >
                    <span aria-hidden>{status.icon}</span> {status.label}
                  </span>
                )}
                {tier < 2 && <Pill>status unavailable</Pill>}
                <button
                  aria-label={`Show ${row.info.detected_text} in transcript`}
                  className="ml-auto rounded p-1"
                  onClick={() => onLocateInfo(row.info)}
                  style={{ color: "var(--cv-accent)" }}
                  type="button"
                >
                  <Crosshair className="h-3.5 w-3.5" />
                </button>
              </div>
              <p
                className="mt-1 min-w-0 text-xs"
                style={{ color: "var(--cv-text)", overflowWrap: "anywhere" }}
              >
                {row.info.detected_text}
              </p>
            </article>
          );
        })}
    </section>
  );
}

export function ConstraintLedger({
  units,
  tier,
  onLocateUnit,
  onLocateInfo,
}: ConstraintLedgerProps) {
  const rows = buildLedgerRows(units, tier);
  const rollup = summariseSurvival(
    units.flatMap((unit) => unit.salient_infos),
    tier,
  );
  return (
    <section className="cv-panel min-w-0 space-y-3 p-2" aria-label="Constraint ledger">
      <div className="flex flex-wrap items-center gap-2">
        <ListChecks className="h-4 w-4" style={{ color: "var(--cv-accent)" }} />
        <h2 className="text-xs font-semibold" style={{ color: "var(--cv-text)" }}>
          Constraint ledger
        </h2>
        {rollup && (
          <span className="ml-auto flex flex-wrap gap-1">
            <Pill color="var(--cv-present)">{rollup.present} visible</Pill>
            <Pill color="var(--cv-reframed)">{rollup.reframed} reframed</Pill>
            <Pill color="var(--cv-absent)">{rollup.absent} absent</Pill>
          </span>
        )}
      </div>
      <LedgerSection
        heading="Rules (rule-matched)"
        onLocateInfo={onLocateInfo}
        onLocateUnit={onLocateUnit}
        rows={rows.reliable}
        tier={tier}
      />
      <LedgerSection
        heading="AI-guessed, may be incomplete"
        onLocateInfo={onLocateInfo}
        onLocateUnit={onLocateUnit}
        rows={rows.guessed}
        tier={tier}
      />
    </section>
  );
}
