import { ChevronDown, History } from "lucide-react";
import { useState } from "react";
import type { ContextVisCompressionEvent } from "@/lib/api";
import { Pill } from "./shared";

export interface CompressionEventsProps {
  readonly events: readonly ContextVisCompressionEvent[];
}

export function CompressionEvents({ events }: CompressionEventsProps) {
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;
  return (
    <section className="cv-panel min-w-0 overflow-hidden">
      <button
        aria-expanded={open}
        aria-label={`Compression events (${events.length})`}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <History className="h-4 w-4 shrink-0" style={{ color: "var(--cv-accent)" }} />
        <span className="text-xs font-semibold" style={{ color: "var(--cv-text)" }}>
          Compression events
        </span>
        <Pill>{events.length}</Pill>
        <ChevronDown
          className={`ml-auto h-4 w-4 ${open ? "rotate-180" : ""}`}
          style={{ color: "var(--cv-text-dim)" }}
        />
      </button>
      {open && (
        <div
          className="space-y-2 border-t p-2"
          style={{ borderColor: "var(--cv-border)" }}
        >
          {events.map((event) => (
            <details
              className="rounded-md px-2 py-1.5"
              key={event.event_id}
              style={{
                background: "var(--cv-bg-2)",
                color: "var(--cv-text)",
              }}
            >
              <summary className="cursor-pointer text-xs">
                <span className="font-mono">#{event.sequence}</span>
                {" · "}
                <time dateTime={new Date(event.timestamp * 1000).toISOString()}>
                  {new Date(event.timestamp * 1000).toLocaleString()}
                </time>
                {" · "}
                <Pill>{event.fidelity}</Pill>
                {" · "}
                <span>{event.kept_turn_ids.length} kept</span>
                {" / "}
                <span>{event.dropped_turn_ids.length} compacted</span>
              </summary>
              <div className="mt-2 space-y-1 text-xs" style={{ color: "var(--cv-text-dim)" }}>
                {event.summary_text
                  ? (
                    <pre
                      className="max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words font-mono"
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {event.summary_text}
                    </pre>
                  )
                  : <p>No summary text was recorded for this event.</p>}
                {event.summary_truncated && <p>Recorded summary text is truncated.</p>}
                {event.note && <p>{event.note}</p>}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
