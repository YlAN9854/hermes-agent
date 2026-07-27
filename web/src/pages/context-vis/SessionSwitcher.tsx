import { ChevronDown, MessageSquareText, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ContextVisSessionsResponse } from "@/lib/api";
import { Input } from "@nous-research/ui/ui/components/input";

export interface SessionSwitcherProps {
  readonly sessions: ContextVisSessionsResponse["sessions"];
  readonly selected: string | null;
  readonly onSelect: (sessionId: string) => void;
}

export function SessionSwitcher({
  sessions,
  selected,
  onSelect,
}: SessionSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const current = sessions.find((session) => session.id === selected);
  const filtered = sessions.filter((session) => (
    `${session.title ?? ""} ${session.preview ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase())
  ));

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent): void => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, [open]);

  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm"
        onClick={() => setOpen((currentOpen) => !currentOpen)}
        style={{
          background: "var(--cv-surface-2)",
          border: "1px solid var(--cv-border)",
          maxWidth: "min(22rem, calc(100vw - 2rem))",
        }}
        type="button"
      >
        <MessageSquareText className="h-4 w-4 shrink-0" style={{ color: "var(--cv-accent)" }} />
        <span className="truncate" style={{ color: "var(--cv-text)" }}>
          {current?.title || current?.preview || selected || "Select a session"}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0" style={{ color: "var(--cv-text-dim)" }} />
      </button>
      {open && (
        <div
          aria-label="Choose session"
          className="cv-panel cv-session-menu absolute z-30 mt-1 max-h-[70vh] overflow-hidden rounded-lg p-2 shadow-2xl"
          role="dialog"
          style={{
            maxWidth: "26rem",
            width: "calc(100vw - 2rem)",
          }}
        >
          <div className="relative mb-2">
            <Search className="absolute left-2 top-2.5 h-4 w-4" style={{ color: "var(--cv-text-dim)" }} />
            <Input
              autoFocus
              className="pl-8"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search sessions…"
              value={query}
            />
          </div>
          <div className="max-h-[58vh] space-y-1 overflow-auto">
            {filtered.map((session) => (
              <button
                aria-current={session.id === selected ? "true" : undefined}
                className="w-full rounded px-2 py-1.5 text-left"
                key={session.id}
                onClick={() => {
                  onSelect(session.id);
                  setOpen(false);
                }}
                style={session.id === selected
                  ? {
                    background: "color-mix(in srgb, var(--cv-accent) 14%, transparent)",
                    outline: "1px solid var(--cv-accent)",
                  }
                  : { background: "transparent" }}
                type="button"
              >
                <div className="truncate text-sm" style={{ color: "var(--cv-text)" }}>
                  {session.title || session.preview || "Untitled"}
                </div>
                <div className="text-[11px] font-mono" style={{ color: "var(--cv-text-dim)" }}>
                  {session.context_vis.generated
                    ? `${session.context_vis.unit_count} units`
                    : "not generated"}
                  {session.message_count != null ? ` · ${session.message_count} msgs` : ""}
                </div>
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="px-2 py-2 text-sm" style={{ color: "var(--cv-text-dim)" }}>
                No sessions.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
