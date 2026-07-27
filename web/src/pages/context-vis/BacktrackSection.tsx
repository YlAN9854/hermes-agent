import { Link2 } from "lucide-react";
import { useState } from "react";
import type { ContextVisBacklink, ContextVisSessionResponse } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";

export interface BacktrackSectionProps {
  readonly detail: ContextVisSessionResponse;
  readonly onSave: (patch: { readonly backlinks: ContextVisBacklink[] }) => Promise<void>;
  readonly onChange: (detail: ContextVisSessionResponse) => void;
}

export function BacktrackSection({
  detail,
  onSave,
  onChange,
}: BacktrackSectionProps) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [rowKeys, setRowKeys] = useState(() => (
    detail.model.backlinks.map(() => crypto.randomUUID())
  ));
  const keyedBacklinks = detail.model.backlinks.map((backlink, position) => ({
    backlink,
    position,
    rowKey: rowKeys[position]
      ?? `${backlink.from_unit_id}:${backlink.to_unit_id}:${backlink.note}`,
  }));
  const updateBacklinks = (backlinks: ContextVisBacklink[]): void => {
    onChange({ ...detail, model: { ...detail.model, backlinks } });
  };

  return (
    <section aria-label="Backtrack links" className="cv-panel space-y-2 p-2">
      <h2
        className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wide"
        style={{ color: "var(--cv-text-dim)" }}
      >
        <Link2 className="h-3 w-3" />
        Backtrack links
      </h2>
      {keyedBacklinks.map(({ backlink, position, rowKey }) => (
        <div className="flex items-center gap-1 text-xs" key={rowKey}>
          <Input
            aria-label={`Backtrack note ${position + 1}`}
            onChange={(event) => updateBacklinks(detail.model.backlinks.map((item, itemPosition) => (
              itemPosition === position ? { ...item, note: event.target.value } : item
            )))}
            value={backlink.note}
          />
          <Button onClick={() => void onSave({ backlinks: detail.model.backlinks })} outlined size="sm">
            Save
          </Button>
          <Button
            destructive
            onClick={() => {
              setRowKeys((keys) => keys.filter((_, keyPosition) => keyPosition !== position));
              void onSave({
                backlinks: detail.model.backlinks.filter(
                  (_, itemPosition) => itemPosition !== position,
                ),
              });
            }}
            size="sm"
          >
            Delete
          </Button>
        </div>
      ))}
      <div className="flex flex-col gap-1">
        <select
          aria-label="Backtrack from unit"
          className="rounded p-1.5 text-xs"
          onChange={(event) => setFrom(event.target.value)}
          style={{
            background: "var(--cv-surface)",
            border: "1px solid var(--cv-border)",
            color: "var(--cv-text)",
          }}
          value={from}
        >
          <option value="">From later unit…</option>
          {detail.model.units.map((unit) => (
            <option key={unit.unit_id} value={unit.unit_id}>{unit.title}</option>
          ))}
        </select>
        <select
          aria-label="Backtrack to unit"
          className="rounded p-1.5 text-xs"
          onChange={(event) => setTo(event.target.value)}
          style={{
            background: "var(--cv-surface)",
            border: "1px solid var(--cv-border)",
            color: "var(--cv-text)",
          }}
          value={to}
        >
          <option value="">To earlier unit…</option>
          {detail.model.units.map((unit) => (
            <option key={unit.unit_id} value={unit.unit_id}>{unit.title}</option>
          ))}
        </select>
        <Input
          onChange={(event) => setNote(event.target.value)}
          placeholder="Why this thought was resumed"
          value={note}
        />
        <Button
          disabled={!from || !to || !note.trim()}
          onClick={() => {
            const backlinks = [
              ...detail.model.backlinks,
              { from_unit_id: from, to_unit_id: to, note: note.trim() },
            ];
            setRowKeys((keys) => [...keys, crypto.randomUUID()]);
            void onSave({ backlinks }).then(() => setNote(""));
          }}
          size="sm"
        >
          Add backlink
        </Button>
      </div>
    </section>
  );
}
