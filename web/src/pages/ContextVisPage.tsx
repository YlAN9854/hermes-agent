import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, ChevronDown, GitMerge, Link2, Network, Pin, PinOff,
  RefreshCw, Search, Sparkles, Terminal, MessageSquareText, ExternalLink, X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  ContextVisAggregate, ContextVisBacklink, ContextVisInfo, ContextVisSentence,
  ContextVisSessionResponse, ContextVisSessionsResponse, ContextVisSpan, ContextVisTurn, ContextVisUnit,
} from "@/lib/api";
import { buildHighlightSegments, summariseSurvival, dominantSurvival, unitIsPinned } from "@/lib/context-vis";
import { useProfileScope } from "@/contexts/useProfileScope";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import "@/context-vis-theme.css";

type Mode = "overview" | "decision";
type ConvMode = "transcript" | "live";

// Survival encoding → a color token + glyph, one source of truth.
const SURVIVAL: Record<string, { v: string; icon: string; label: string }> = {
  present: { v: "var(--cv-present)", icon: "●", label: "still visible" },
  reframed: { v: "var(--cv-reframed)", icon: "◐", label: "reframed" },
  absent: { v: "var(--cv-absent)", icon: "○", label: "no longer visible" },
};

/* ---------------------------------------------------------------- pills */

function Pill({ children, color, title }: { children: React.ReactNode; color?: string; title?: string }) {
  return <span title={title} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide"
    style={{ color: color ?? "var(--cv-text-dim)", background: "color-mix(in srgb, currentColor 12%, transparent)" }}>{children}</span>;
}

function HighlightedText({ content, spans, turnId }: { content: string; spans: ContextVisSpan[]; turnId: string }) {
  return <>{buildHighlightSegments(content, spans, turnId).map((part, i) => part.highlighted
    ? <mark key={i} style={{ background: "color-mix(in srgb, var(--cv-accent) 30%, transparent)", color: "var(--cv-text)" }}>{part.text}</mark>
    : <span key={i}>{part.text}</span>)}</>;
}

/* ---------------------------------------------------------------- top bar session switcher */

function SessionSwitcher({ sessions, selected, onSelect }: {
  sessions: ContextVisSessionsResponse["sessions"]; selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const current = sessions.find((s) => s.id === selected);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const filtered = sessions.filter((s) => `${s.title ?? ""} ${s.preview ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="relative" ref={ref}>
    <button onClick={() => setOpen((v) => !v)}
      className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm max-w-[22rem]"
      style={{ background: "var(--cv-surface-2)", border: "1px solid var(--cv-border)" }}>
      <MessageSquareText className="h-4 w-4 shrink-0" style={{ color: "var(--cv-accent)" }} />
      <span className="truncate" style={{ color: "var(--cv-text)" }}>{current?.title || current?.preview || (selected ? selected : "Select a session")}</span>
      <ChevronDown className="h-4 w-4 shrink-0" style={{ color: "var(--cv-text-dim)" }} />
    </button>
    {open && <div className="absolute z-30 mt-1 w-[26rem] max-h-[70vh] overflow-hidden rounded-lg cv-panel p-2 shadow-2xl">
      <div className="relative mb-2">
        <Search className="absolute left-2 top-2.5 h-4 w-4" style={{ color: "var(--cv-text-dim)" }} />
        <Input autoFocus className="pl-8" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search sessions…" />
      </div>
      <div className="space-y-1 overflow-auto max-h-[58vh]">
        {filtered.map((s) => <button key={s.id} onClick={() => { onSelect(s.id); setOpen(false); }}
          className="w-full text-left rounded px-2 py-1.5"
          style={s.id === selected ? { background: "color-mix(in srgb, var(--cv-accent) 14%, transparent)", outline: "1px solid var(--cv-accent)" } : { background: "transparent" }}
          onMouseEnter={(e) => { if (s.id !== selected) e.currentTarget.style.background = "var(--cv-surface-2)"; }}
          onMouseLeave={(e) => { if (s.id !== selected) e.currentTarget.style.background = "transparent"; }}>
          <div className="truncate text-sm" style={{ color: "var(--cv-text)" }}>{s.title || s.preview || "Untitled"}</div>
          <div className="text-[11px] font-mono" style={{ color: "var(--cv-text-dim)" }}>
            {s.context_vis.generated ? `${s.context_vis.unit_count} units` : "not generated"}
            {s.message_count != null ? ` · ${s.message_count} msgs` : ""}
          </div>
        </button>)}
        {!filtered.length && <p className="px-2 py-2 text-sm" style={{ color: "var(--cv-text-dim)" }}>No sessions.</p>}
      </div>
    </div>}
  </div>;
}

/* ---------------------------------------------------------------- conversation panel (transcript) */

function TranscriptView({ transcript, activeSpans, activeUnitTurns, onSelectTurn }: {
  transcript: ContextVisTurn[]; activeSpans: ContextVisSpan[]; activeUnitTurns: Set<string>;
  onSelectTurn: (turnId: string) => void;
}) {
  return <div className="space-y-2 overflow-auto h-full px-3 py-3">
    {transcript.map((turn) => {
      const covered = activeUnitTurns.has(turn.turn_id);
      const isTool = turn.role === "tool";
      const roleColor = turn.role === "user" ? "var(--cv-accent)" : turn.role === "assistant" ? "var(--cv-text)" : "var(--cv-text-dim)";
      return <article key={turn.turn_id} id={`cv-turn-${turn.turn_id}`} onClick={() => onSelectTurn(turn.turn_id)}
        className="rounded-lg px-3 py-2 cursor-pointer transition-colors"
        style={{
          background: covered ? "color-mix(in srgb, var(--cv-accent) 8%, var(--cv-surface))" : "var(--cv-surface)",
          border: `1px solid ${covered ? "var(--cv-accent)" : "var(--cv-border)"}`,
        }}>
        <div className="mb-1 flex items-center gap-2 text-[10px] font-mono uppercase tracking-wide" style={{ color: roleColor }}>
          <span>{turn.role}</span>
          {turn.tool_name && <span style={{ color: "var(--cv-text-dim)" }}>· {turn.tool_name}</span>}
        </div>
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed max-h-64 overflow-auto"
          style={{ color: isTool ? "var(--cv-text-dim)" : "var(--cv-text)" }}>
          <HighlightedText content={turn.content} spans={activeSpans} turnId={turn.turn_id} />
        </pre>
      </article>;
    })}
  </div>;
}

/* ---------------------------------------------------------------- aggregate editor (ported, restyled) */

function AggregateEditor({ nodes, units, tier, onChange }: {
  nodes: ContextVisAggregate[]; units: ContextVisUnit[]; tier: number;
  onChange: (nodes: ContextVisAggregate[]) => void;
}) {
  const unitTitle = Object.fromEntries(units.map((u) => [u.unit_id, u.title]));
  const unitInfo = Object.fromEntries(units.map((u) => [u.unit_id, u.salient_infos]));
  const update = (idx: number, node: ContextVisAggregate) => onChange(nodes.map((n, i) => i === idx ? { ...node, origin: "user_edited" } : n));
  const move = (idx: number, direction: -1 | 1) => {
    const target = idx + direction;
    if (target < 0 || target >= nodes.length) return;
    const next = nodes.map((n) => ({ ...n, child_unit_ids: [...n.child_unit_ids], origin: "user_edited" as const }));
    const sourceIds = next[idx].child_unit_ids;
    const id = direction < 0 ? sourceIds.shift() : sourceIds.pop();
    if (!id || sourceIds.length === 0) return;
    if (direction < 0) next[target].child_unit_ids.push(id); else next[target].child_unit_ids.unshift(id);
    onChange(next);
  };
  const merge = (idx: number) => {
    if (idx >= nodes.length - 1) return;
    const merged = { ...nodes[idx], child_unit_ids: [...nodes[idx].child_unit_ids, ...nodes[idx + 1].child_unit_ids], origin: "user_edited" as const };
    onChange([...nodes.slice(0, idx), merged, ...nodes.slice(idx + 2)]);
  };
  const split = (idx: number) => {
    const node = nodes[idx];
    if (node.child_unit_ids.length < 2) return;
    const cut = Math.ceil(node.child_unit_ids.length / 2);
    const left = { ...node, child_unit_ids: node.child_unit_ids.slice(0, cut), origin: "user_edited" as const };
    const right = { ...node, node_id: `aggregate-user-${crypto.randomUUID()}`, title: `${node.title} 2`, child_unit_ids: node.child_unit_ids.slice(cut), origin: "user_edited" as const };
    onChange([...nodes.slice(0, idx), left, right, ...nodes.slice(idx + 1)]);
  };
  return <div className="space-y-2">
    {nodes.map((node, idx) => {
      const infos = node.child_unit_ids.flatMap((id) => unitInfo[id] ?? []);
      const roll = summariseSurvival(infos, tier);
      return <div key={node.node_id} className="cv-panel-2 rounded-lg p-2" style={{ border: "1px solid var(--cv-border)" }}>
        <div className="flex gap-1 items-center">
          <Input value={node.title} onChange={(e) => update(idx, { ...node, title: e.target.value })} />
          <Button size="sm" outlined onClick={() => move(idx, -1)} aria-label="Move boundary left"><ArrowLeft className="h-3 w-3" /></Button>
          <Button size="sm" outlined onClick={() => move(idx, 1)} aria-label="Move boundary right"><ArrowRight className="h-3 w-3" /></Button>
          <Button size="sm" outlined onClick={() => split(idx)}>Split</Button>
          <Button size="sm" outlined onClick={() => merge(idx)}><GitMerge className="h-3 w-3" /></Button>
        </div>
        <p className="text-xs mt-1" style={{ color: "var(--cv-text-dim)" }}>{node.child_unit_ids.map((id) => unitTitle[id] ?? id).join(" · ")}</p>
        {roll && (roll.reframed + roll.absent > 0) && <p className="text-[11px] font-mono mt-1">
          <span className="cv-reframed">{roll.reframed} reframed</span> · <span className="cv-absent">{roll.absent} gone</span>
        </p>}
      </div>;
    })}
  </div>;
}

/* ---------------------------------------------------------------- unit block + detail (the spine) */

function UnitBlock({ unit, tier, preserved, active, onSelect, onTogglePin, detail }: {
  unit: ContextVisUnit; tier: number; preserved: string[]; active: boolean;
  onSelect: () => void; onTogglePin: () => void; detail: React.ReactNode;
}) {
  const dom = dominantSurvival(unit.salient_infos, tier);
  const railColor = dom ? SURVIVAL[dom].v : "var(--cv-border-strong)";
  const pinned = unitIsPinned(unit, preserved);
  const roll = summariseSurvival(unit.salient_infos, tier);
  const reliable = unit.salient_infos.filter((i) => i.confidence === "reliable").length;
  const guessed = unit.salient_infos.filter((i) => i.confidence === "ai_guessed").length;
  return <div id={`cv-unit-${unit.unit_id}`} className="rounded-lg transition-colors"
    style={{ background: active ? "color-mix(in srgb, var(--cv-accent) 8%, var(--cv-surface))" : "var(--cv-surface)",
      border: `1px solid ${active ? "var(--cv-accent)" : "var(--cv-border)"}`, boxShadow: `inset 3px 0 0 0 ${railColor}` }}>
    <button onClick={onSelect} className="w-full text-left px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <strong className="text-sm" style={{ color: "var(--cv-text)" }}>{unit.title || "Untitled unit"}</strong>
        <span className="flex items-center gap-1 shrink-0">
          {pinned && <Pin className="h-3.5 w-3.5" style={{ color: "var(--cv-pin)" }} />}
          {roll && (roll.reframed + roll.absent > 0) && <span className="text-[10px] font-mono">
            <span className="cv-reframed">{roll.reframed}◐</span> <span className="cv-absent">{roll.absent}○</span>
          </span>}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-1 flex-wrap">
        {reliable > 0 && <Pill title="rule-matched constraints">{reliable} rule</Pill>}
        {guessed > 0 && <Pill title="AI-guessed constraints" color="var(--cv-salient-reliable)">{guessed} ai</Pill>}
        <Pill title="turns covered">{unit.covered_turns.length} turns</Pill>
        {!unit.frozen && <Pill color="var(--cv-accent)">draft</Pill>}
      </div>
    </button>
    {active && <div className="border-t px-3 py-2" style={{ borderColor: "var(--cv-border)" }}>{detail}</div>}
    {active && tier >= 3 && <div className="border-t px-3 py-2 flex items-center gap-2" style={{ borderColor: "var(--cv-border)" }}>
      <Button size="sm" outlined onClick={onTogglePin}>
        {pinned ? <><PinOff className="h-3 w-3 mr-1" />Unpin from context</> : <><Pin className="h-3 w-3 mr-1" style={{ color: "var(--cv-pin)" }} />Preserve through compaction</>}
      </Button>
      <span className="text-[11px]" style={{ color: "var(--cv-text-dim)" }}>{pinned ? "kept verbatim when the model compacts" : "pin so compaction won't summarize it away"}</span>
    </div>}
  </div>;
}

/* ---------------------------------------------------------------- page */

export default function ContextVisPage() {
  const { profile } = useProfileScope();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ContextVisSessionsResponse["sessions"]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContextVisSessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeUnit, setActiveUnit] = useState<string | null>(null);
  const [activeSpans, setActiveSpans] = useState<ContextVisSpan[]>([]);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("overview");
  const [convMode, setConvMode] = useState<ConvMode>("transcript");
  const [intent, setIntent] = useState("");

  const loadSessions = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const result = await api.getContextVisSessions(profile);
      setSessions(result.sessions);
      setSelected((cur) => cur ?? result.sessions[0]?.id ?? null);
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  }, [profile]);

  const loadDetail = useCallback(async (id: string) => {
    setError(null);
    try { setDetail(await api.getContextVisSession(id, profile)); }
    catch (e) { setError(String(e)); }
  }, [profile]);

  useEffect(() => { queueMicrotask(() => void loadSessions()); }, [loadSessions]);
  useEffect(() => { if (selected) { setActiveUnit(null); setInspecting(null); queueMicrotask(() => void loadDetail(selected)); } }, [selected, loadDetail]);

  const runJob = async (body: Parameters<typeof api.createContextVisJob>[1]) => {
    if (!selected) return;
    setWorking(true); setError(null);
    try {
      const created = await api.createContextVisJob(selected, body, profile);
      for (;;) {
        await new Promise((r) => window.setTimeout(r, 700));
        const job = await api.getContextVisJob(created.job_id, profile);
        if (job.status === "failed") throw new Error(job.error || "Context Vis job failed");
        if (job.status === "succeeded") break;
      }
      await Promise.all([loadDetail(selected), loadSessions()]);
    } catch (e) { setError(String(e)); } finally { setWorking(false); }
  };

  const saveEdits = async (patch: { aggregates?: ContextVisAggregate[]; decision_aggregates?: ContextVisAggregate[]; decision_intent?: string | null; backlinks?: ContextVisBacklink[] }) => {
    if (!selected || !detail) return;
    setWorking(true);
    try {
      const result = await api.saveContextVisModel(selected, { revision: detail.model.revision, ...patch }, profile);
      setDetail({ ...detail, model: result.model });
    } catch (e) { setError(String(e)); } finally { setWorking(false); }
  };

  const togglePin = async (unit: ContextVisUnit) => {
    if (!selected || !detail) return;
    const current = new Set(detail.model.preserved);
    const covered = unit.covered_turns;
    const already = covered.some((t) => current.has(t));
    // Wholesale set: send the new desired pin set (toggle this unit's turns).
    const next = new Set(current);
    if (already) covered.forEach((t) => next.delete(t));
    else covered.forEach((t) => next.add(t));
    setWorking(true); setError(null); setNotice(null);
    try {
      const res = await api.preserveContextVisTurns(selected, { revision: detail.model.revision, turn_ids: [...next] }, profile);
      setDetail({ ...detail, model: res.model });
      // A unit's tool-only turns can't be preserved verbatim — that's expected,
      // and the text turns still pinned, so it's a notice, not an error.
      if (res.result.rejected_turn_ids.length && res.result.note) setNotice(res.result.note);
    } catch (e) { setError(String(e)); } finally { setWorking(false); }
  };

  const tier = detail?.capabilities.tier ?? 1;
  const model = detail?.model;
  const unitByTurn = useMemo(() => new Map(model?.units.flatMap((u) => u.covered_turns.map((id) => [id, u.unit_id])) ?? []), [model]);
  const turnNumber = useCallback((turnId: string) => (detail?.transcript.findIndex((t) => t.turn_id === turnId) ?? -1) + 1, [detail]);
  const aggregates = detail ? (mode === "overview" ? detail.model.aggregates : detail.model.decision_aggregates) : [];

  const locateTurn = useCallback((turnId: string, span?: ContextVisSpan) => {
    setActiveSpans(span ? [span] : []);
    document.getElementById(`cv-turn-${turnId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);
  const selectUnit = useCallback((unitId: string, firstTurn?: string) => {
    setActiveUnit((cur) => cur === unitId ? null : unitId);
    setActiveSpans([]);
    if (firstTurn) document.getElementById(`cv-turn-${firstTurn}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);
  const selectTurn = useCallback((turnId: string) => {
    const unitId = unitByTurn.get(turnId) ?? null;
    setActiveUnit(unitId);
    if (unitId) document.getElementById(`cv-unit-${unitId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [unitByTurn]);

  const activeUnitTurns = useMemo(() => {
    const u = model?.units.find((x) => x.unit_id === activeUnit);
    return new Set(u?.covered_turns ?? []);
  }, [model, activeUnit]);

  function unitDetail(unit: ContextVisUnit) {
    return <div className="space-y-2">
      {unit.summary_sentences.map((s: ContextVisSentence, i) => <p key={i}
        className="text-xs leading-relaxed cursor-default" style={{ color: "var(--cv-text-dim)" }}
        onMouseEnter={() => setActiveSpans(s.source_spans)} onMouseLeave={() => setActiveSpans([])}>{s.text}</p>)}
      {unit.salient_infos.map((info) => <SalientRow key={info.info_id} info={info}
        turn={detail?.transcript.find((t) => t.turn_id === info.span_in_B.turn_id)}
        turnNo={turnNumber(info.span_in_B.turn_id)} tier={tier}
        open={inspecting === info.info_id} onToggle={() => setInspecting((v) => v === info.info_id ? null : info.info_id)}
        onLocate={() => locateTurn(info.span_in_B.turn_id, info.span_in_B)} />)}
    </div>;
  }

  return <div className="flex h-full flex-col" style={{ background: "var(--cv-bg)", color: "var(--cv-text)" }}>
    {/* top bar */}
    <header className="flex items-center gap-3 px-4 py-2.5 border-b shrink-0" style={{ borderColor: "var(--cv-border)", background: "var(--cv-bg-2)" }}>
      <div className="flex items-center gap-2">
        <Network className="h-5 w-5" style={{ color: "var(--cv-accent)" }} />
        <span className="font-mono text-sm font-semibold tracking-wide" style={{ color: "var(--cv-text)" }}>ContextVis</span>
      </div>
      <div className="h-5 w-px" style={{ background: "var(--cv-border)" }} />
      <SessionSwitcher sessions={sessions} selected={selected} onSelect={setSelected} />
      <div className="ml-auto flex items-center gap-2">
        {detail && <>
          <Pill title="capability tier" color="var(--cv-accent)">tier {tier}</Pill>
          {detail.capabilities.compression_fidelity === "reconstructed" && <Pill title="history reconstructed from archived rows">reconstructed</Pill>}
          {detail.survival_stale && <Button size="sm" outlined disabled={working} onClick={() => void runJob({ action: "refresh_survival" })}
            title="context changed since statuses were computed"><RefreshCw className="h-3 w-3 mr-1" />refresh survival</Button>}
        </>}
        {loading || working ? <Spinner /> : null}
        <button onClick={() => navigate("/")} title="Back to dashboard" className="rounded p-1.5" style={{ color: "var(--cv-text-dim)" }}>
          <X className="h-4 w-4" />
        </button>
      </div>
    </header>

    {error && <div className="px-4 py-2 text-xs font-mono shrink-0 flex items-center gap-2" style={{ color: "var(--cv-absent)", background: "color-mix(in srgb, var(--cv-absent) 10%, transparent)" }}>
      <span className="flex-1">{error}</span><button onClick={() => setError(null)}><X className="h-3.5 w-3.5" /></button></div>}
    {notice && <div className="px-4 py-2 text-xs shrink-0 flex items-center gap-2" style={{ color: "var(--cv-reframed)", background: "color-mix(in srgb, var(--cv-reframed) 10%, transparent)" }}>
      <Pin className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--cv-pin)" }} /><span className="flex-1">{notice}</span><button onClick={() => setNotice(null)}><X className="h-3.5 w-3.5" /></button></div>}

    {/* body: 35% conversation | 65% spine */}
    <div className="flex min-h-0 flex-1">
      {/* conversation panel */}
      <section className="flex min-h-0 flex-col border-r" style={{ width: "35%", borderColor: "var(--cv-border)" }}>
        <div className="flex items-center gap-1 px-3 py-2 border-b shrink-0" style={{ borderColor: "var(--cv-border)" }}>
          <SegToggle value={convMode} onChange={setConvMode} options={[
            { v: "transcript", label: "Transcript", icon: <MessageSquareText className="h-3.5 w-3.5" /> },
            { v: "live", label: "Live", icon: <Terminal className="h-3.5 w-3.5" /> },
          ]} />
          <span className="ml-auto text-[11px] font-mono" style={{ color: "var(--cv-text-dim)" }}>
            {detail ? `${detail.transcript.length} turns` : ""}
          </span>
        </div>
        {convMode === "transcript"
          ? (detail ? <TranscriptView transcript={detail.transcript} activeSpans={activeSpans} activeUnitTurns={activeUnitTurns} onSelectTurn={selectTurn} />
             : <Empty>Select a session.</Empty>)
          : <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
              <Terminal className="h-8 w-8" style={{ color: "var(--cv-accent)" }} />
              <p className="text-sm" style={{ color: "var(--cv-text-dim)" }}>Drive this conversation in the live terminal.</p>
              <Button outlined disabled={!selected} onClick={() => selected && navigate(`/chat?resume=${encodeURIComponent(selected)}`)}>
                <ExternalLink className="h-4 w-4 mr-1" />Open live terminal
              </Button>
              <p className="text-[11px]" style={{ color: "var(--cv-text-faint)" }}>In-page embedded terminal is coming; for now this opens the full terminal.</p>
            </div>}
      </section>

      {/* semantic spine */}
      <section className="flex min-h-0 flex-1 flex-col" style={{ background: "var(--cv-bg)" }}>
        {!detail ? <Empty>Select a session to see its semantic structure.</Empty>
        : !model?.units.length ? <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <Sparkles className="h-8 w-8" style={{ color: "var(--cv-accent)" }} />
            <p className="text-sm" style={{ color: "var(--cv-text-dim)" }}>No semantic view yet for this session.</p>
            <Button disabled={working} onClick={() => void runJob({ action: "generate_units" })}>
              <Sparkles className="h-4 w-4 mr-1" />Generate semantic view
            </Button>
          </div>
        : <>
            {/* action toolbar */}
            <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-b shrink-0" style={{ borderColor: "var(--cv-border)" }}>
              <Button size="sm" outlined disabled={working} onClick={() => void runJob({ action: "generate_units", incremental: true })}>Append turns</Button>
              <Button size="sm" outlined disabled={working} onClick={() => void runJob({ action: "detect_salient" })}>Detect salient</Button>
              <div className="mx-1 h-4 w-px" style={{ background: "var(--cv-border)" }} />
              <SegToggle value={mode} onChange={setMode} options={[{ v: "overview", label: "Overview" }, { v: "decision", label: "Decision" }]} />
              {mode === "decision" && <Input className="h-7 w-40 text-xs" value={intent} onChange={(e) => setIntent(e.target.value)} placeholder="Continue, or turn toward…" />}
              <Button size="sm" outlined disabled={working || (mode === "decision" && !intent.trim())} onClick={() => void runJob({ action: "draft_aggregates", mode, intent })}>Draft aggregation</Button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto px-3 py-3 space-y-3">
              {detail.model.legacy_transcript_warning && <div className="rounded-lg px-3 py-2 text-xs" style={{ color: "var(--cv-reframed)", background: "color-mix(in srgb, var(--cv-reframed) 10%, transparent)" }}>{detail.model.legacy_transcript_warning}</div>}

              {/* aggregation editor */}
              {!!aggregates.length && <div className="cv-panel p-2 space-y-2">
                <div className="text-[11px] font-mono uppercase tracking-wide" style={{ color: "var(--cv-text-dim)" }}>{mode} aggregation</div>
                <AggregateEditor nodes={aggregates} units={detail.model.units} tier={tier}
                  onChange={(nodes) => setDetail({ ...detail, model: { ...detail.model, [mode === "overview" ? "aggregates" : "decision_aggregates"]: nodes } })} />
                <Button size="sm" onClick={() => void saveEdits(mode === "overview" ? { aggregates } : { decision_aggregates: aggregates, decision_intent: detail.model.decision_intent })}>Save aggregation</Button>
              </div>}

              {/* the spine */}
              <div className="space-y-2">
                {detail.model.units.map((unit) => <UnitBlock key={unit.unit_id} unit={unit} tier={tier}
                  preserved={detail.model.preserved} active={activeUnit === unit.unit_id}
                  onSelect={() => selectUnit(unit.unit_id, unit.covered_turns[0])}
                  onTogglePin={() => void togglePin(unit)} detail={unitDetail(unit)} />)}
              </div>

              {/* backtrack links */}
              <BacktrackSection detail={detail} onSave={saveEdits} onChange={setDetail} />
            </div>
          </>}
      </section>
    </div>
  </div>;
}

/* ---------------------------------------------------------------- small pieces */

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-1 items-center justify-center p-6 text-sm" style={{ color: "var(--cv-text-dim)" }}>{children}</div>;
}

function SegToggle<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { v: T; label: string; icon?: React.ReactNode }[];
}) {
  return <div className="inline-flex rounded-md p-0.5" style={{ background: "var(--cv-surface)", border: "1px solid var(--cv-border)" }}>
    {options.map((o) => <button key={o.v} onClick={() => onChange(o.v)}
      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors"
      style={value === o.v ? { background: "var(--cv-accent)", color: "#0b1120" } : { color: "var(--cv-text-dim)" }}>
      {o.icon}{o.label}</button>)}
  </div>;
}

function SalientRow({ info, turn, turnNo, tier, open, onToggle, onLocate }: {
  info: ContextVisInfo; turn: ContextVisTurn | undefined; turnNo: number; tier: number;
  open: boolean; onToggle: () => void; onLocate: () => void;
}) {
  const s = tier >= 2 ? SURVIVAL[info.status_in_A] : undefined;
  const actionable = !!s && info.status_in_A !== "present";
  const original = turn ? turn.content.slice(info.span_in_B.char_start, info.span_in_B.char_end) : info.detected_text;
  return <div className="rounded-md px-2 py-1.5 text-xs" style={{ background: "var(--cv-bg-2)", boxShadow: "inset 2px 0 0 0 var(--cv-border-strong)" }}>
    <div className="flex items-center gap-2 flex-wrap">
      <Pill color={info.confidence === "reliable" ? "var(--cv-text-dim)" : "var(--cv-salient-reliable)"}>{info.confidence === "reliable" ? "rule" : "ai"}</Pill>
      {s && <button disabled={!actionable} onClick={actionable ? onToggle : undefined}
        className={actionable ? "underline decoration-dotted" : ""} style={{ color: s.v }}
        title={actionable ? `${s.label} — click for detail` : s.label}>{s.icon} {s.label}</button>}
      <span style={{ color: "var(--cv-text)" }}>{info.detected_text}</span>
    </div>
    {open && <div className="mt-2 rounded border p-2" style={{ borderColor: "var(--cv-border)" }}>
      {info.status_in_A === "reframed" ? <div className="grid gap-2 sm:grid-cols-2">
        <div><div className="mb-1" style={{ color: "var(--cv-text-dim)" }}>Original — turn {turnNo}</div><p style={{ color: "var(--cv-text)" }}>{original}</p></div>
        <div><div className="mb-1" style={{ color: "var(--cv-text-dim)" }}>How the model now sees it</div><p style={{ color: "var(--cv-reframed)" }}>{info.reframed_text_in_A}</p></div>
      </div> : <p style={{ color: "var(--cv-text)" }}>The model can no longer see this. The original is still in turn {turnNo}.</p>}
      <Button size="sm" outlined className="mt-2" onClick={onLocate}>Show me in the transcript</Button>
    </div>}
  </div>;
}

function BacktrackSection({ detail, onSave, onChange }: {
  detail: ContextVisSessionResponse;
  onSave: (patch: { backlinks?: ContextVisBacklink[] }) => Promise<void>;
  onChange: (d: ContextVisSessionResponse) => void;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  return <div className="cv-panel p-2 space-y-2">
    <div className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wide" style={{ color: "var(--cv-text-dim)" }}>
      <Link2 className="h-3 w-3" />Backtrack links
    </div>
    {detail.model.backlinks.map((b, i) => <div key={`${b.from_unit_id}-${b.to_unit_id}-${i}`} className="flex items-center gap-1 text-xs">
      <Input value={b.note} onChange={(e) => onChange({ ...detail, model: { ...detail.model, backlinks: detail.model.backlinks.map((l, idx) => idx === i ? { ...l, note: e.target.value } : l) } })} />
      <Button size="sm" outlined onClick={() => void onSave({ backlinks: detail.model.backlinks })}>Save</Button>
      <Button size="sm" destructive onClick={() => void onSave({ backlinks: detail.model.backlinks.filter((_, idx) => idx !== i) })}>Del</Button>
    </div>)}
    <div className="flex flex-col gap-1">
      <select className="rounded p-1.5 text-xs" style={{ background: "var(--cv-surface)", border: "1px solid var(--cv-border)", color: "var(--cv-text)" }} value={from} onChange={(e) => setFrom(e.target.value)}>
        <option value="">From later unit…</option>{detail.model.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}
      </select>
      <select className="rounded p-1.5 text-xs" style={{ background: "var(--cv-surface)", border: "1px solid var(--cv-border)", color: "var(--cv-text)" }} value={to} onChange={(e) => setTo(e.target.value)}>
        <option value="">To earlier unit…</option>{detail.model.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}
      </select>
      <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this thought was resumed" />
      <Button size="sm" disabled={!from || !to || !note.trim()}
        onClick={() => void onSave({ backlinks: [...detail.model.backlinks, { from_unit_id: from, to_unit_id: to, note: note.trim() }] }).then(() => setNote(""))}>Add backlink</Button>
    </div>
  </div>;
}
