import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, GitMerge, Link2, RefreshCw, Search, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ContextVisAggregate, ContextVisBacklink, ContextVisInfo, ContextVisModel, ContextVisSentence,
  ContextVisSessionResponse, ContextVisSessionsResponse, ContextVisSpan, ContextVisTurn,
} from "@/lib/api";
import { buildHighlightSegments, summariseSurvival } from "@/lib/context-vis";
import { useProfileScope } from "@/contexts/useProfileScope";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";

type Mode = "overview" | "decision";

function HighlightedText({ content, spans, turnId }: { content: string; spans: ContextVisSpan[]; turnId: string }) {
  return <>{buildHighlightSegments(content, spans, turnId).map((part, i) => part.highlighted
    ? <mark key={i} className="bg-warning/30 text-text-primary">{part.text}</mark>
    : <span key={i}>{part.text}</span>)}</>;
}

const SURVIVAL_LABEL: Record<string, { icon: string; text: string; className: string }> = {
  present: { icon: "✅", text: "still visible", className: "text-success" },
  reframed: { icon: "⚠️", text: "reframed", className: "text-warning" },
  absent: { icon: "❌", text: "no longer visible", className: "text-destructive" },
};

/** Survival badge. Renders nothing below Tier 2 or without a known status,
 *  so a Tier 1 session looks exactly as it did before compression visibility. */
function SurvivalBadge({ info, tier, onClick }: { info: ContextVisInfo; tier: number; onClick: () => void }) {
  const label = tier >= 2 ? SURVIVAL_LABEL[info.status_in_A] : undefined;
  if (!label) return null;
  const actionable = info.status_in_A !== "present";
  return <button
    type="button"
    disabled={!actionable}
    onClick={(e) => { e.stopPropagation(); if (actionable) onClick(); }}
    title={actionable ? `In the model's current context: ${label.text} — click for detail` : "Still visible to the model verbatim"}
    className={`${label.className} ${actionable ? "underline decoration-dotted" : ""}`}
  >{label.icon} {label.text}</button>;
}

/** Side-by-side B original vs the wording A now carries (spec 5.3). The left
 *  column is sliced out of the transcript, not from detected_text: the truth
 *  layer is the source, and the index is only an index. */
function SurvivalDetail({ info, turn, turnNumber, onLocate }: {
  info: ContextVisInfo; turn: ContextVisTurn | undefined; turnNumber: number; onLocate: () => void;
}) {
  const original = turn ? turn.content.slice(info.span_in_B.char_start, info.span_in_B.char_end) : info.detected_text;
  return <div className="mt-2 border border-border p-2 text-xs">
    {info.status_in_A === "reframed" ? <div className="grid gap-2 sm:grid-cols-2">
      <div><div className="text-text-secondary mb-1">Original — transcript turn {turnNumber}</div>
        <p className="text-text-primary">{original}</p></div>
      <div><div className="text-text-secondary mb-1">How the model now sees it</div>
        <p className="text-warning">{info.reframed_text_in_A}</p></div>
    </div> : <p className="text-text-primary">
      The model can no longer see this. The original is still in turn {turnNumber} of the transcript.
    </p>}
    <Button size="sm" outlined className="mt-2" onClick={(e) => { e.stopPropagation(); onLocate(); }}>
      Show me in the transcript
    </Button>
  </div>;
}

function AggregateEditor({ nodes, units, tier, onChange }: {
  nodes: ContextVisAggregate[]; units: ContextVisModel["units"]; tier: number;
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
    {nodes.map((node, idx) => <div key={node.node_id} className="border border-border p-2">
      <div className="flex gap-1 items-center">
        <Input value={node.title} onChange={(e) => update(idx, { ...node, title: e.target.value })} />
        <Button size="sm" outlined onClick={() => move(idx, -1)} aria-label="Move boundary left"><ArrowLeft className="h-3 w-3" /></Button>
        <Button size="sm" outlined onClick={() => move(idx, 1)} aria-label="Move boundary right"><ArrowRight className="h-3 w-3" /></Button>
        <Button size="sm" outlined onClick={() => split(idx)}>Split</Button>
        <Button size="sm" outlined onClick={() => merge(idx)}><GitMerge className="h-3 w-3" /></Button>
      </div>
      <p className="text-xs text-text-secondary mt-1">{node.child_unit_ids.map((id) => unitTitle[id] ?? id).join(" · ")}</p>
      <p className="text-xs text-text-secondary mt-1">Rule matches: {node.child_unit_ids.flatMap((id) => unitInfo[id] ?? []).filter((i) => i.confidence === "reliable").length} · AI guesses: {node.child_unit_ids.flatMap((id) => unitInfo[id] ?? []).filter((i) => i.confidence === "ai_guessed").length}</p>
      {(() => {
        const roll = summariseSurvival(node.child_unit_ids.flatMap((id) => unitInfo[id] ?? []), tier);
        return roll && <p className="text-xs text-text-secondary mt-1">
          {roll.total} tracked here · <span className="text-warning">{roll.reframed} reframed</span> · <span className="text-destructive">{roll.absent} no longer visible</span>
        </p>;
      })()}
    </div>)}
  </div>;
}

export default function ContextVisPage() {
  const { profile } = useProfileScope();
  const [sessions, setSessions] = useState<ContextVisSessionsResponse["sessions"]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContextVisSessionResponse | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeUnit, setActiveUnit] = useState<string | null>(null);
  const [activeSpans, setActiveSpans] = useState<ContextVisSpan[]>([]);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("overview");
  const [intent, setIntent] = useState("");
  const [backlinkFrom, setBacklinkFrom] = useState("");
  const [backlinkTo, setBacklinkTo] = useState("");
  const [backlinkNote, setBacklinkNote] = useState("");

  const loadSessions = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const result = await api.getContextVisSessions(profile);
      setSessions(result.sessions);
      setSelected(result.sessions[0]?.id ?? null);
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  }, [profile]);

  const loadDetail = useCallback(async (id: string) => {
    setError(null);
    try { setDetail(await api.getContextVisSession(id, profile)); }
    catch (e) { setError(String(e)); }
  }, [profile]);

  useEffect(() => { queueMicrotask(() => void loadSessions()); }, [loadSessions]);
  useEffect(() => { if (selected) queueMicrotask(() => void loadDetail(selected)); }, [selected, loadDetail]);

  const runJob = async (body: Parameters<typeof api.createContextVisJob>[1]) => {
    if (!selected) return;
    setWorking(true); setError(null);
    try {
      const created = await api.createContextVisJob(selected, body, profile);
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
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

  const filtered = sessions.filter((s) => `${s.title ?? ""} ${s.preview ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const unitByTurn = useMemo(() => new Map(detail?.model.units.flatMap((u) => u.covered_turns.map((id) => [id, u.unit_id])) ?? []), [detail]);
  const tier = detail?.capabilities.tier ?? 1;
  const turnById = useMemo(() => new Map((detail?.transcript ?? []).map((t) => [t.turn_id, t])), [detail]);
  const turnNumber = useCallback((turnId: string) => (detail?.transcript.findIndex((t) => t.turn_id === turnId) ?? -1) + 1, [detail]);
  const locateInTranscript = useCallback((span: ContextVisSpan) => {
    setActiveSpans([span]);
    document.getElementById(`turn-${span.turn_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);
  const aggregates = detail ? (mode === "overview" ? detail.model.aggregates : detail.model.decision_aggregates) : [];

  return <div className="space-y-3">
    <div className="flex items-center justify-between">
      <div><h1 className="font-expanded text-2xl text-text-primary">Context Vis</h1><p className="text-sm text-text-secondary">Semantic index over immutable conversation transcripts</p></div>
      <span className="flex gap-1">
        <Badge>Tier {tier}</Badge>
        {detail?.capabilities.compression_fidelity === "reconstructed" && <Badge>Reconstructed history</Badge>}
      </span>
    </div>
    {error && <div className="border border-destructive text-destructive p-3 text-sm">{error}</div>}
    <div className="grid grid-cols-1 xl:grid-cols-[16rem_minmax(22rem,1fr)_minmax(24rem,1.2fr)] gap-3 min-h-[70vh]">
      <Card><CardHeader><CardTitle>Sessions</CardTitle></CardHeader><CardContent className="space-y-2">
        <div className="relative"><Search className="absolute left-2 top-2.5 h-4 w-4 text-text-secondary" /><Input className="pl-8" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search sessions" /></div>
        <Button outlined size="sm" onClick={() => void loadSessions()}><RefreshCw className="h-3 w-3 mr-1" />Refresh</Button>
        {loading ? <Spinner /> : <div className="space-y-1 max-h-[62vh] overflow-auto">{filtered.map((s) => <button key={s.id} onClick={() => setSelected(s.id)} className={`w-full text-left border p-2 ${selected === s.id ? "border-primary bg-primary/10" : "border-border"}`}>
          <div className="text-sm text-text-primary truncate">{s.title || s.preview || "Untitled"}</div>
          <div className="text-xs text-text-secondary">{s.context_vis.generated ? `${s.context_vis.unit_count} units` : "Not generated"}</div>
        </button>)}</div>}
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Semantic index</CardTitle></CardHeader><CardContent className="space-y-3 max-h-[72vh] overflow-auto">
        {!detail ? <p className="text-sm text-text-secondary">Select a session.</p> : <>
          {detail.model.legacy_transcript_warning && <div className="border border-warning text-warning p-2 text-xs">{detail.model.legacy_transcript_warning}</div>}
          <div className="flex flex-wrap gap-2">
            {!detail.model.units.length ? <Button disabled={working} onClick={() => void runJob({ action: "generate_units" })}><Sparkles className="h-4 w-4 mr-1" />Generate semantic view</Button> : <>
              <Button outlined disabled={working} onClick={() => void runJob({ action: "generate_units", incremental: true })}>Append new turns</Button>
              <Button outlined disabled={working} onClick={() => void runJob({ action: "detect_salient" })}>Detect salient info</Button>
              {detail.survival_stale && <Button outlined disabled={working} onClick={() => void runJob({ action: "refresh_survival" })} title="The context has changed since these statuses were computed">Refresh survival state</Button>}
              <Button outlined disabled title="Requires an agent with Tier 3 preserve support">Preserve original (unsupported)</Button>
            </>}
            {working && <Spinner />}
          </div>
          {!!detail.model.units.length && <>
            <div className="flex gap-2"><Button size="sm" outlined={mode !== "overview"} onClick={() => setMode("overview")}>Overview</Button><Button size="sm" outlined={mode !== "decision"} onClick={() => setMode("decision")}>Decision</Button></div>
            {mode === "decision" && <Input value={intent} onChange={(e) => setIntent(e.target.value)} placeholder="Continue, or turn toward…" />}
            <Button size="sm" outlined disabled={working || (mode === "decision" && !intent.trim())} onClick={() => void runJob({ action: "draft_aggregates", mode, intent })}>Draft aggregation</Button>
            {!!aggregates.length && <><AggregateEditor nodes={aggregates} units={detail.model.units} tier={tier} onChange={(nodes) => setDetail({ ...detail, model: { ...detail.model, [mode === "overview" ? "aggregates" : "decision_aggregates"]: nodes } })} /><Button size="sm" onClick={() => void saveEdits(mode === "overview" ? { aggregates } : { decision_aggregates: aggregates, decision_intent: detail.model.decision_intent })}>Save aggregation</Button></>}
            <div className="space-y-2">{detail.model.units.map((unit) => <div key={unit.unit_id} className={`border p-3 ${activeUnit === unit.unit_id ? "border-primary bg-primary/5" : "border-border"}`} onClick={() => { setActiveUnit(unit.unit_id); setActiveSpans([]); document.getElementById(`turn-${unit.covered_turns[0]}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); }}>
              <div className="flex flex-wrap justify-between gap-1"><strong className="text-sm text-text-primary">{unit.title}</strong><span className="flex gap-1"><Badge>Rules {unit.salient_infos.filter((i) => i.confidence === "reliable").length}</Badge><Badge>AI guesses {unit.salient_infos.filter((i) => i.confidence === "ai_guessed").length}</Badge>{(() => {
                const roll = summariseSurvival(unit.salient_infos, tier);
                return roll && (roll.reframed + roll.absent > 0) ? <Badge>{roll.reframed} reframed · {roll.absent} gone</Badge> : null;
              })()}<Badge>{unit.frozen ? "frozen" : "draft"}</Badge></span></div>
              {unit.summary_sentences.map((sentence: ContextVisSentence, i) => <p key={i} className="text-sm text-text-secondary mt-1 cursor-pointer" onMouseEnter={() => setActiveSpans(sentence.source_spans)} onMouseLeave={() => setActiveSpans([])}>{sentence.text}</p>)}
              {unit.salient_infos.map((info) => <div key={info.info_id} className="mt-2 border-l-2 border-warning pl-2 text-xs text-text-primary">
                <span className="flex flex-wrap items-center gap-1">
                  <Badge>{info.confidence === "reliable" ? "Rule match" : "AI guessed"}</Badge>
                  <SurvivalBadge info={info} tier={tier} onClick={() => setInspecting(inspecting === info.info_id ? null : info.info_id)} />
                </span>
                <span>{info.detected_text}</span>
                {inspecting === info.info_id && <SurvivalDetail
                  info={info} turn={turnById.get(info.span_in_B.turn_id)}
                  turnNumber={turnNumber(info.span_in_B.turn_id)}
                  onLocate={() => locateInTranscript(info.span_in_B)}
                />}
              </div>)}
            </div>)}</div>
            <div className="border-t border-border pt-3 space-y-2"><h3 className="font-mondwest text-display text-sm">Backtrack links</h3>
              {detail.model.backlinks.map((b, i) => <div key={`${b.from_unit_id}-${b.to_unit_id}-${i}`} className="flex items-center gap-1 border-l-2 border-t border-primary pl-2 pt-1 text-xs text-text-secondary">
                <Link2 className="h-3 w-3 shrink-0" />
                <Input value={b.note} onChange={(e) => setDetail({ ...detail, model: { ...detail.model, backlinks: detail.model.backlinks.map((link, idx) => idx === i ? { ...link, note: e.target.value } : link) } })} />
                <Button size="sm" outlined onClick={() => void saveEdits({ backlinks: detail.model.backlinks })}>Save</Button>
                <Button size="sm" destructive onClick={() => void saveEdits({ backlinks: detail.model.backlinks.filter((_, idx) => idx !== i) })}>Delete</Button>
              </div>)}
              <select className="w-full bg-background border border-border p-2 text-sm" value={backlinkFrom} onChange={(e) => setBacklinkFrom(e.target.value)}><option value="">From later unit</option>{detail.model.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}</select>
              <select className="w-full bg-background border border-border p-2 text-sm" value={backlinkTo} onChange={(e) => setBacklinkTo(e.target.value)}><option value="">To earlier unit</option>{detail.model.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}</select>
              <Input value={backlinkNote} onChange={(e) => setBacklinkNote(e.target.value)} placeholder="Why this thought was resumed" />
              <Button size="sm" disabled={!backlinkFrom || !backlinkTo || !backlinkNote.trim()} onClick={() => void saveEdits({ backlinks: [...detail.model.backlinks, { from_unit_id: backlinkFrom, to_unit_id: backlinkTo, note: backlinkNote.trim() }] }).then(() => setBacklinkNote(""))}>Add backlink</Button>
            </div>
          </>}
        </>}
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Original transcript — truth layer</CardTitle></CardHeader><CardContent className="space-y-3 max-h-[72vh] overflow-auto">
        {detail?.transcript.map((turn) => <article id={`turn-${turn.turn_id}`} key={turn.turn_id} onClick={() => setActiveUnit(unitByTurn.get(turn.turn_id) ?? null)} className={`border p-3 ${activeUnit && unitByTurn.get(turn.turn_id) === activeUnit ? "border-primary" : "border-border"}`}>
          <div className="text-xs text-text-secondary mb-2">{turn.role}{turn.tool_name ? ` · ${turn.tool_name}` : ""}</div>
          <pre className="whitespace-pre-wrap font-mono text-xs text-text-primary"><HighlightedText content={turn.content} spans={activeSpans} turnId={turn.turn_id} /></pre>
        </article>)}
      </CardContent></Card>
    </div>
  </div>;
}
