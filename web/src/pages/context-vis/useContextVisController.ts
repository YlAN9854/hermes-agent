import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  ContextVisEditRequest,
  ContextVisIntentSegment,
  ContextVisJobRequest,
  ContextVisModel,
  ContextVisSessionResponse,
  ContextVisSessionsResponse,
  ContextVisSpan,
  ContextVisTurn,
  ContextVisUnit,
} from "@/lib/api";
import {
  normaliseConversationMode,
  type ConversationMode,
} from "@/lib/context-vis";
import type {
  IntentTrackSaveResult,
  TurnCaptureHandler,
} from "./IntentTrack";
import { scrollToContextVisElement } from "./navigation";

type EditPatch = Omit<ContextVisEditRequest, "revision">;

export function useContextVisController(profile: string) {
  const [sessions, setSessions] = useState<ContextVisSessionsResponse["sessions"]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContextVisSessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeUnit, setActiveUnit] = useState<string | null>(null);
  const [activeSpans, setActiveSpans] = useState<readonly ContextVisSpan[]>([]);
  const [conversationMode, setConversationMode] = useState<ConversationMode>("transcript");
  const captureTurnRef = useRef<TurnCaptureHandler | null>(null);
  const detailRequestRef = useRef(0);

  const loadSessions = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getContextVisSessions(profile);
      setSessions(result.sessions);
      setSelected((current) => current ?? result.sessions[0]?.id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [profile]);
  const loadDetail = useCallback(async (sessionId: string): Promise<void> => {
    const request = detailRequestRef.current + 1;
    detailRequestRef.current = request;
    setError(null);
    try {
      const result = await api.getContextVisSession(sessionId, profile);
      if (detailRequestRef.current === request) setDetail(result);
    } catch (caught) {
      if (detailRequestRef.current === request) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    }
  }, [profile]);

  useEffect(() => {
    queueMicrotask(() => void loadSessions());
  }, [loadSessions]);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setDetail(null);
      setActiveUnit(null);
      setActiveSpans([]);
      captureTurnRef.current = null;
      setConversationMode((current) => normaliseConversationMode(current, false, true));
      if (selected) void loadDetail(selected);
    });
    return () => { active = false; };
  }, [loadDetail, selected]);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setConversationMode((current) => normaliseConversationMode(
        current,
        detail?.compression !== null && detail?.compression !== undefined,
        false,
      ));
    });
    return () => { active = false; };
  }, [detail?.compression]);

  const runJob = async (body: ContextVisJobRequest): Promise<void> => {
    if (!selected) return;
    setWorking(true);
    setError(null);
    try {
      const created = await api.createContextVisJob(selected, body, profile);
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        const job = await api.getContextVisJob(created.job_id, profile);
        if (job.status === "failed") {
          throw new Error(job.error || "Context Vis job failed");
        }
        if (job.status === "succeeded") break;
      }
      await Promise.all([loadDetail(selected), loadSessions()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorking(false);
    }
  };
  const saveModel = async (patch: EditPatch): Promise<ContextVisModel> => {
    if (!selected || !detail) throw new Error("Select a loaded session before saving.");
    setWorking(true);
    setError(null);
    try {
      const result = await api.saveContextVisModel(
        selected,
        { revision: detail.model.revision, ...patch },
        profile,
      );
      setDetail((current) => (
        current?.session_id === selected ? { ...current, model: result.model } : current
      ));
      return result.model;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    } finally {
      setWorking(false);
    }
  };
  const saveEdits = async (
    patch: Omit<EditPatch, "intent_segments">,
  ): Promise<void> => {
    try {
      await saveModel(patch);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };
  const saveIntent = async (
    segments: readonly ContextVisIntentSegment[],
  ): Promise<IntentTrackSaveResult> => {
    const model = await saveModel({ intent_segments: segments });
    return { segments: model.intent_segments, revision: model.revision };
  };
  const togglePin = async (unit: ContextVisUnit): Promise<void> => {
    if (!selected || !detail) return;
    const next = new Set(detail.model.preserved);
    const alreadyPinned = unit.covered_turns.some((turnId) => next.has(turnId));
    for (const turnId of unit.covered_turns) {
      if (alreadyPinned) next.delete(turnId);
      else next.add(turnId);
    }
    setWorking(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.preserveContextVisTurns(
        selected,
        { revision: detail.model.revision, turn_ids: [...next] },
        profile,
      );
      setDetail((current) => (
        current?.session_id === selected ? { ...current, model: result.model } : current
      ));
      if (result.result.rejected_turn_ids.length > 0 && result.result.note) {
        setNotice(result.result.note);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorking(false);
    }
  };

  const unitByTurn = useMemo(
    () => new Map(detail?.model.units.flatMap((unit) => (
      unit.covered_turns.map((turnId) => [turnId, unit.unit_id] as const)
    )) ?? []),
    [detail?.model.units],
  );
  const activeUnitTurns = useMemo(() => {
    const unit = detail?.model.units.find((candidate) => candidate.unit_id === activeUnit);
    return new Set(unit?.covered_turns ?? []);
  }, [activeUnit, detail?.model.units]);
  const locateSpan = useCallback((span: ContextVisSpan): void => {
    setActiveSpans([span]);
    setConversationMode("transcript");
    const elementId = `cv-turn-${span.turn_id}`;
    if (document.getElementById(elementId)) scrollToContextVisElement(elementId);
    else queueMicrotask(() => scrollToContextVisElement(elementId));
  }, []);
  const selectUnit = useCallback((unit: ContextVisUnit): void => {
    setActiveUnit((current) => current === unit.unit_id ? null : unit.unit_id);
    setActiveSpans([]);
    const firstTurn = unit.covered_turns[0];
    if (firstTurn) queueMicrotask(() => scrollToContextVisElement(`cv-turn-${firstTurn}`));
  }, []);
  const selectTurn = useCallback((turn: ContextVisTurn): void => {
    const capture = captureTurnRef.current;
    if (capture) {
      captureTurnRef.current = null;
      capture(turn);
      return;
    }
    const unitId = unitByTurn.get(turn.turn_id) ?? null;
    setActiveUnit(unitId);
    if (unitId) queueMicrotask(() => scrollToContextVisElement(`cv-unit-${unitId}`));
  }, [unitByTurn]);
  const registerCapture = useCallback((handler: TurnCaptureHandler | null): void => {
    captureTurnRef.current = handler;
  }, []);

  return {
    sessions,
    selected,
    setSelected,
    detail,
    setDetail,
    loading,
    working,
    error,
    setError,
    notice,
    setNotice,
    activeUnit,
    activeSpans,
    setActiveSpans,
    conversationMode,
    setConversationMode,
    runJob,
    saveEdits,
    saveIntent,
    togglePin,
    activeUnitTurns,
    locateSpan,
    selectUnit,
    selectTurn,
    registerCapture,
  };
}
