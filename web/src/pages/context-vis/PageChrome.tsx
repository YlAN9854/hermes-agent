import { Network, Pin, RefreshCw, X } from "lucide-react";
import type {
  ContextVisSessionResponse,
  ContextVisSessionsResponse,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Pill } from "./shared";
import { SessionSwitcher } from "./SessionSwitcher";

export interface PageChromeProps {
  readonly sessions: ContextVisSessionsResponse["sessions"];
  readonly selected: string | null;
  readonly detail: ContextVisSessionResponse | null;
  readonly loading: boolean;
  readonly working: boolean;
  readonly error: string | null;
  readonly notice: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly onRefreshSurvival: () => void;
  readonly onDismissError: () => void;
  readonly onDismissNotice: () => void;
  readonly onClose: () => void;
}

export function PageChrome({
  sessions,
  selected,
  detail,
  loading,
  working,
  error,
  notice,
  onSelect,
  onRefreshSurvival,
  onDismissError,
  onDismissNotice,
  onClose,
}: PageChromeProps) {
  return (
    <>
      <header
        className="cv-page-header flex shrink-0 flex-wrap items-center gap-3 border-b px-4 py-2.5"
        style={{
          background: "var(--cv-bg-2)",
          borderColor: "var(--cv-border)",
        }}
      >
        <div className="flex items-center gap-2">
          <Network className="h-5 w-5" style={{ color: "var(--cv-accent)" }} />
          <span
            className="text-sm font-semibold tracking-wide font-mono"
            style={{ color: "var(--cv-text)" }}
          >
            ContextVis
          </span>
        </div>
        <div className="h-5 w-px" style={{ background: "var(--cv-border)" }} />
        <SessionSwitcher onSelect={onSelect} selected={selected} sessions={sessions} />
        <div className="ml-auto flex items-center gap-2">
          {detail && (
            <>
              <Pill color="var(--cv-accent)" title="capability tier">
                tier {detail.capabilities.tier}
              </Pill>
              {detail.capabilities.compression_fidelity === "reconstructed" && (
                <Pill title="history reconstructed from archived rows">reconstructed</Pill>
              )}
              {detail.survival_stale && (
                <Button
                  disabled={working}
                  onClick={onRefreshSurvival}
                  outlined
                  size="sm"
                  title="context changed since statuses were computed"
                >
                  <RefreshCw className="mr-1 h-3 w-3" />
                  refresh survival
                </Button>
              )}
            </>
          )}
          {(loading || working) && <Spinner />}
          <button
            aria-label="Back to dashboard"
            className="rounded p-1.5"
            onClick={onClose}
            style={{ color: "var(--cv-text-dim)" }}
            title="Back to dashboard"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>
      {error && (
        <div
          className="flex shrink-0 items-center gap-2 px-4 py-2 text-xs font-mono"
          role="alert"
          style={{
            background: "color-mix(in srgb, var(--cv-absent) 10%, transparent)",
            color: "var(--cv-absent)",
          }}
        >
          <span className="flex-1">{error}</span>
          <button aria-label="Dismiss error" onClick={onDismissError} type="button">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {notice && (
        <div
          className="flex shrink-0 items-center gap-2 px-4 py-2 text-xs"
          role="status"
          style={{
            background: "color-mix(in srgb, var(--cv-reframed) 10%, transparent)",
            color: "var(--cv-reframed)",
          }}
        >
          <Pin className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--cv-pin)" }} />
          <span className="flex-1">{notice}</span>
          <button aria-label="Dismiss notice" onClick={onDismissNotice} type="button">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </>
  );
}
