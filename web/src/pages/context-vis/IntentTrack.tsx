import { Flag } from "lucide-react";
import { useEffect, useState } from "react";
import type {
  ContextVisIntentSegment,
  ContextVisSpan,
  ContextVisTurn,
  ContextVisUnit,
} from "@/lib/api";
import {
  validateIntentSegments,
  wholeTurnTrigger,
} from "@/lib/context-vis";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  ExistingIntentEditor,
  NewIntentForm,
} from "./IntentTrackForms";
import { Pill } from "./shared";

export type TurnCaptureHandler = (turn: ContextVisTurn) => void;

export interface IntentTrackSaveResult {
  readonly segments: readonly ContextVisIntentSegment[];
  readonly revision: number;
}

export interface IntentTrackProps {
  readonly units: readonly ContextVisUnit[];
  readonly segments: readonly ContextVisIntentSegment[];
  readonly disabled: boolean;
  readonly onSave: (
    segments: readonly ContextVisIntentSegment[],
  ) => Promise<IntentTrackSaveResult>;
  readonly onLocate: (span: ContextVisSpan) => void;
  readonly onCaptureHandler: (handler: TurnCaptureHandler | null) => void;
}

export function IntentTrack({
  units,
  segments,
  disabled,
  onSave,
  onLocate,
  onCaptureHandler,
}: IntentTrackProps) {
  const [draft, setDraft] = useState<readonly ContextVisIntentSegment[]>(segments);
  const [newId, setNewId] = useState(() => `intent-user-${crypto.randomUUID()}`);
  const [newLabel, setNewLabel] = useState("");
  const [newNote, setNewNote] = useState("");
  const [newFrom, setNewFrom] = useState("");
  const [newTo, setNewTo] = useState("");
  const [newTrigger, setNewTrigger] = useState<ContextVisSpan | null>(null);
  const [armedTarget, setArmedTarget] = useState<string | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setDraft(segments);
      setEditorError(null);
    });
    return () => {
      active = false;
    };
  }, [segments]);
  useEffect(
    () => () => onCaptureHandler(null),
    [onCaptureHandler],
  );

  const saveCandidate = async (
    candidate: readonly ContextVisIntentSegment[],
  ): Promise<boolean> => {
    const validation = validateIntentSegments(units, candidate);
    if (!validation.valid) {
      setEditorError(validation.message);
      setSaveStatus(null);
      return false;
    }
    setSaving(true);
    setEditorError(null);
    setSaveStatus(null);
    try {
      const result = await onSave(candidate);
      setDraft(result.segments);
      setSaveStatus(`Intent track saved at revision ${result.revision}.`);
      return true;
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : String(caught));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const armCapture = (
    targetId: string,
    button: HTMLButtonElement,
    apply: (span: ContextVisSpan) => void,
  ): void => {
    setArmedTarget(targetId);
    setEditorError(null);
    onCaptureHandler((turn) => {
      const span = wholeTurnTrigger(turn);
      if (span) apply(span);
      else setEditorError("An empty turn cannot be used as an intent trigger.");
      setArmedTarget(null);
      onCaptureHandler(null);
      queueMicrotask(() => button.focus());
    });
  };

  const cancelCapture = (button: HTMLButtonElement): void => {
    setArmedTarget(null);
    onCaptureHandler(null);
    queueMicrotask(() => button.focus());
  };

  const addSegment = async (): Promise<void> => {
    const positions = new Map(units.map((unit, index) => [unit.unit_id, index]));
    const candidate = [...draft, {
      segment_id: newId,
      label: newLabel.trim(),
      from_unit_id: newFrom,
      to_unit_id: newTo,
      trigger_span: newTrigger,
      note: newNote.trim(),
      origin: "user_edited",
    } satisfies ContextVisIntentSegment].toSorted((left, right) => (
      (positions.get(left.from_unit_id) ?? Number.MAX_SAFE_INTEGER)
      - (positions.get(right.from_unit_id) ?? Number.MAX_SAFE_INTEGER)
    ));
    if (!await saveCandidate(candidate)) return;
    setNewId(`intent-user-${crypto.randomUUID()}`);
    setNewLabel("");
    setNewNote("");
    setNewFrom("");
    setNewTo("");
    setNewTrigger(null);
  };

  const busy = disabled || saving;
  return (
    <section aria-label="Intent track editor" className="cv-panel min-w-0 space-y-2 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Flag className="h-4 w-4" style={{ color: "var(--cv-accent-2)" }} />
        <h2 className="text-xs font-semibold" style={{ color: "var(--cv-text)" }}>
          Manual intent track
        </h2>
        <Pill>{draft.length} segments</Pill>
      </div>

      {draft.map((segment, index) => (
        <ExistingIntentEditor
          armed={armedTarget === segment.segment_id}
          busy={busy}
          index={index}
          key={segment.segment_id}
          onChange={(nextSegment) => setDraft((current) => current.map((item) => (
            item.segment_id === segment.segment_id ? nextSegment : item
          )))}
          onDelete={() => void saveCandidate(
            draft.filter((item) => item.segment_id !== segment.segment_id),
          )}
          onLocate={onLocate}
          onToggleCapture={(button) => {
            if (armedTarget === segment.segment_id) cancelCapture(button);
            else {
              armCapture(segment.segment_id, button, (span) => {
                setDraft((current) => current.map((item) => (
                  item.segment_id === segment.segment_id
                      ? { ...item, trigger_span: span, origin: "user_edited" }
                      : item
                )));
              });
            }
          }}
          segment={segment}
        />
      ))}

      {draft.length > 0 && (
        <Button size="sm" outlined disabled={busy} onClick={() => void saveCandidate(draft)}>
          Save intent changes
        </Button>
      )}

      <NewIntentForm
        armed={armedTarget === newId}
        busy={busy}
        from={newFrom}
        label={newLabel}
        note={newNote}
        onFromChange={setNewFrom}
        onLabelChange={setNewLabel}
        onNoteChange={setNewNote}
        onSubmit={() => void addSegment()}
        onToChange={setNewTo}
        onToggleCapture={(button) => {
          if (armedTarget === newId) cancelCapture(button);
          else armCapture(newId, button, setNewTrigger);
        }}
        to={newTo}
        trigger={newTrigger}
        units={units}
      />

      {editorError && (
        <p className="text-xs" role="alert" style={{ color: "var(--cv-absent)" }}>
          {editorError}
        </p>
      )}
      {saveStatus && (
        <p
          aria-label="Intent save status"
          className="text-xs"
          role="status"
          style={{ color: "var(--cv-present)" }}
        >
          {saveStatus}
        </p>
      )}
      {armedTarget && (
        <p className="text-xs" role="status" style={{ color: "var(--cv-reframed)" }}>
          Trigger capture is armed. Choose one transcript turn, or cancel.
        </p>
      )}
    </section>
  );
}
