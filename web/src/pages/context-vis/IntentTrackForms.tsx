import { Crosshair, Trash2 } from "lucide-react";
import type {
  ContextVisIntentSegment,
  ContextVisSpan,
  ContextVisUnit,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Pill } from "./shared";

const selectStyle = {
  background: "var(--cv-surface)",
  border: "1px solid var(--cv-border)",
  color: "var(--cv-text)",
} as const;

export interface ExistingIntentEditorProps {
  readonly segment: ContextVisIntentSegment;
  readonly index: number;
  readonly busy: boolean;
  readonly armed: boolean;
  readonly onChange: (segment: ContextVisIntentSegment) => void;
  readonly onDelete: () => void;
  readonly onToggleCapture: (button: HTMLButtonElement) => void;
  readonly onLocate: (span: ContextVisSpan) => void;
}

export function ExistingIntentEditor({
  segment,
  index,
  busy,
  armed,
  onChange,
  onDelete,
  onToggleCapture,
  onLocate,
}: ExistingIntentEditorProps) {
  return (
    <fieldset className="min-w-0 space-y-1.5 rounded-md p-2" style={{ background: "var(--cv-bg-2)" }}>
      <legend className="px-1 text-[10px] font-mono" style={{ color: "var(--cv-text-dim)" }}>
        {segment.segment_id}
      </legend>
      <Input
        aria-label={`Intent label ${index + 1}`}
        onChange={(event) => onChange({
          ...segment,
          label: event.target.value,
          origin: "user_edited",
        })}
        value={segment.label}
      />
      <Input
        aria-label={`Intent note ${index + 1}`}
        onChange={(event) => onChange({
          ...segment,
          note: event.target.value,
          origin: "user_edited",
        })}
        placeholder="Optional note"
        value={segment.note}
      />
      <div className="flex flex-wrap items-center gap-1">
        <button
          aria-label={armed
            ? `Cancel trigger capture for ${segment.label}`
            : `Arm trigger capture for ${segment.label}`}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs"
          disabled={busy}
          onClick={(event) => onToggleCapture(event.currentTarget)}
          style={{
            border: "1px solid var(--cv-border)",
            color: "var(--cv-accent)",
          }}
          type="button"
        >
          <Crosshair className="h-3 w-3" />
          {armed ? "Cancel capture" : "Arm trigger"}
        </button>
        {segment.trigger_span && (
          <button
            aria-label={`Go to trigger for ${segment.label}`}
            className="rounded px-2 py-1 text-xs"
            onClick={() => {
              if (segment.trigger_span) onLocate(segment.trigger_span);
            }}
            style={{ color: "var(--cv-accent)" }}
            type="button"
          >
            Go to trigger
          </button>
        )}
        <button
          aria-label={`Delete intent segment ${segment.label}`}
          className="ml-auto rounded p-1"
          disabled={busy}
          onClick={onDelete}
          style={{ color: "var(--cv-absent)" }}
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </fieldset>
  );
}

export interface NewIntentFormProps {
  readonly units: readonly ContextVisUnit[];
  readonly label: string;
  readonly note: string;
  readonly from: string;
  readonly to: string;
  readonly trigger: ContextVisSpan | null;
  readonly busy: boolean;
  readonly armed: boolean;
  readonly onLabelChange: (value: string) => void;
  readonly onNoteChange: (value: string) => void;
  readonly onFromChange: (value: string) => void;
  readonly onToChange: (value: string) => void;
  readonly onToggleCapture: (button: HTMLButtonElement) => void;
  readonly onSubmit: () => void;
}

export function NewIntentForm({
  units,
  label,
  note,
  from,
  to,
  trigger,
  busy,
  armed,
  onLabelChange,
  onNoteChange,
  onFromChange,
  onToChange,
  onToggleCapture,
  onSubmit,
}: NewIntentFormProps) {
  return (
    <form
      className="min-w-0 space-y-1.5 border-t pt-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      style={{ borderColor: "var(--cv-border)" }}
    >
      <Input
        aria-label="New segment label"
        onChange={(event) => onLabelChange(event.target.value)}
        placeholder="Intent label"
        value={label}
      />
      <div className="grid min-w-0 gap-1 sm:grid-cols-2">
        <select
          aria-label="New segment start"
          className="min-w-0 rounded p-1.5 text-xs"
          onChange={(event) => onFromChange(event.target.value)}
          style={selectStyle}
          value={from}
        >
          <option value="">From unit...</option>
          {units.map((unit) => <option key={unit.unit_id} value={unit.unit_id}>{unit.title}</option>)}
        </select>
        <select
          aria-label="New segment end"
          className="min-w-0 rounded p-1.5 text-xs"
          onChange={(event) => onToChange(event.target.value)}
          style={selectStyle}
          value={to}
        >
          <option value="">Through unit...</option>
          {units.map((unit) => <option key={unit.unit_id} value={unit.unit_id}>{unit.title}</option>)}
        </select>
      </div>
      <Input
        aria-label="New segment note"
        onChange={(event) => onNoteChange(event.target.value)}
        placeholder="Optional note"
        value={note}
      />
      <div className="flex flex-wrap items-center gap-1">
        <button
          aria-label={armed
            ? "Cancel new-segment trigger capture"
            : "Arm new-segment trigger"}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs"
          disabled={busy}
          onClick={(event) => onToggleCapture(event.currentTarget)}
          style={{
            border: "1px solid var(--cv-border)",
            color: "var(--cv-accent)",
          }}
          type="button"
        >
          <Crosshair className="h-3 w-3" />
          {armed ? "Cancel capture" : "Arm whole-turn trigger"}
        </button>
        {trigger && <Pill>trigger: {trigger.turn_id}</Pill>}
        <Button
          className="ml-auto"
          disabled={busy || !label.trim() || !from || !to}
          size="sm"
          type="submit"
        >
          Add intent segment
        </Button>
      </div>
    </form>
  );
}
