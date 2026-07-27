import type {
  ContextVisCompression,
  ContextVisInfo,
  ContextVisIntentSegment,
  ContextVisSessionResponse,
  ContextVisSessionsResponse,
  ContextVisUnit,
} from "@/lib/api";

const unicodeTurn = "A😀𠜎é";
export const longUnbrokenTurn = `live-${"constraint".repeat(60)}`;

function salient(
  infoId: string,
  turnId: string,
  status: ContextVisInfo["status_in_A"],
  confidence: ContextVisInfo["confidence"],
): ContextVisInfo {
  return {
    info_id: infoId,
    kind: "user_stated_constraint",
    detected_text: turnId === "t1" ? unicodeTurn : "live",
    span_in_B: {
      turn_id: turnId,
      char_start: 0,
      char_end: turnId === "t1" ? 5 : 4,
    },
    status_in_A: status,
    reframed_text_in_A: status === "reframed" ? "Reframed constraint" : null,
    confidence,
  };
}

function contextUnit(
  unitId: string,
  title: string,
  coveredTurns: string[],
  infos: ContextVisInfo[],
): ContextVisUnit {
  return {
    unit_id: unitId,
    title,
    summary_sentences: [],
    covered_turns: coveredTurns,
    salient_infos: infos,
    frozen: true,
    created_at_turn: coveredTurns.at(-1) ?? "",
  };
}

export const observedCompression: ContextVisCompression = {
  fidelity: "observed",
  live_turn_ids: ["t3"],
  synthetic_entries: [
    { role: "user", content: "Merged synthetic summary of earlier work." },
  ],
  unlinked_live_count: 0,
  events: [
    {
      event_id: "event-1",
      timestamp: 100,
      sequence: 1,
      fidelity: "observed",
      kept_turn_ids: ["t3"],
      dropped_turn_ids: ["t1", "t2"],
      summary_text: "Earlier turns were compacted into this summary.",
      summary_truncated: false,
      note: null,
    },
  ],
};

export const reconstructedCompression: ContextVisCompression = {
  ...observedCompression,
  fidelity: "reconstructed",
  live_turn_ids: [],
  synthetic_entries: [],
  unlinked_live_count: 1,
  events: [],
};

const tierThreeUnits = [
  contextUnit(
    "u1",
    "Initial research direction",
    ["t1", "t2"],
    [salient("rule-absent", "t1", "absent", "reliable")],
  ),
  contextUnit(
    "u2",
    "Current research direction",
    ["t3"],
    [salient("guess-present", "t3", "present", "ai_guessed")],
  ),
];

export function intentSegment(
  segmentId: string,
  fromUnitId = "u1",
  toUnitId = "u1",
): ContextVisIntentSegment {
  return {
    segment_id: segmentId,
    label: "Existing direction",
    from_unit_id: fromUnitId,
    to_unit_id: toUnitId,
    trigger_span: null,
    note: "",
    origin: "user_edited",
  };
}

export function sessionDetail(
  sessionId: string,
  compression: ContextVisCompression | null,
  intentSegments: ContextVisIntentSegment[] = [],
): ContextVisSessionResponse {
  const tier = compression === null ? 1 : 3;
  return {
    session_id: sessionId,
    capabilities: {
      tier,
      compression_events: Boolean(compression?.events.length),
      compression_fidelity: compression?.fidelity ?? null,
      preserve: tier === 3,
    },
    survival_stale: false,
    model: {
      units: tier === 3 ? tierThreeUnits : [],
      aggregates: [],
      decision_aggregates: [],
      decision_intent: null,
      backlinks: [],
      intent_segments: intentSegments,
      tier,
      revision: 7,
      legacy_transcript_warning: null,
      survival: null,
      preserved: [],
    },
    transcript: tier === 3
      ? [
        { turn_id: "t1", role: "user", content: unicodeTurn, tool_name: null, timestamp: 1 },
        { turn_id: "t2", role: "assistant", content: "Earlier response", tool_name: null, timestamp: 2 },
        { turn_id: "t3", role: "user", content: longUnbrokenTurn, tool_name: null, timestamp: 3 },
      ]
      : [],
    compression,
  };
}

export const contextSessions: ContextVisSessionsResponse = {
  sessions: [
    {
      id: "tier3",
      source: "cli",
      model: "model",
      title: "Tier 3 observed",
      started_at: 1,
      ended_at: null,
      last_active: 3,
      is_active: false,
      message_count: 3,
      tool_call_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      preview: "observed",
      context_vis: { generated: true, revision: 7, unit_count: 2 },
    },
    {
      id: "tier1",
      source: "cli",
      model: "model",
      title: "Tier 1 sparse",
      started_at: 1,
      ended_at: null,
      last_active: 2,
      is_active: false,
      message_count: 0,
      tool_call_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      preview: "empty",
      context_vis: { generated: false, revision: 0, unit_count: 0 },
    },
  ],
};
