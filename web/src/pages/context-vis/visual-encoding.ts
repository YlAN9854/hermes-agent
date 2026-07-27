import type { ContextVisInfo } from "@/lib/api";

type KnownSurvival = Exclude<ContextVisInfo["status_in_A"], "unknown">;

export const SURVIVAL: Readonly<Record<KnownSurvival, {
  readonly color: string;
  readonly icon: string;
  readonly label: string;
}>> = {
  present: {
    color: "var(--cv-present)",
    icon: "●",
    label: "still visible",
  },
  reframed: {
    color: "var(--cv-reframed)",
    icon: "◐",
    label: "reframed",
  },
  absent: {
    color: "var(--cv-absent)",
    icon: "○",
    label: "no longer visible",
  },
};
