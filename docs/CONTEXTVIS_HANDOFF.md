# ContextVis — handoff (2026-07-24)

Working state of the ContextVis project, written so work can resume on a new
device without re-deriving context. This file lives inside `hermes-agent/` so
it travels with `git pull`. Everything outside `hermes-agent/` (the parent
`vis-demo/` folder — `docs/contextVis-spec.md`, `.agents`, `.codex`, `.claude`)
is being synced manually by the user; this doc doesn't restate that content,
just points at it.

## What ContextVis is

A semantic-layer + compression-visualization view over long AI-agent
conversations, built as a fork of the Hermes agent. The governing spec is
`../../docs/contextVis-spec.md` (one level above this repo, in `vis-demo/`).

**Iron laws** (do not violate these):
1. All `SpanRef`s point only to the immutable transcript **B** (raw turns),
   never to mutable working context **A**.
2. Core/UI layers contain zero Hermes-specific names — this is meant to be a
   portable layer over any agent transcript.
3. Degradation hides features; it never fabricates data. Every UI element that
   depends on a tier gates itself off below that tier (see `SURVIVAL`/pin
   gating in `ContextVisPage.tsx`) rather than showing a fake/zero value.
4. Frozen units are never mutated after the fact — corrections happen via new
   backtrack links/notes, not silent edits.

**Constraint (user-set, durable):** never reference or consult
`origin/feat/contextvis-occupancy-panel` — it's a deprecated test branch (v2),
unrelated to this work. Ignore it if it surfaces in `git branch -a` etc.

## Repo / branch state

- Repo: `hermes-agent/` (this directory), branch **`vis-demo`**.
- **Fully pushed** — `origin/vis-demo` is up to date, 32 commits ahead of
  `main`, 0 ahead/behind its own origin ref. Clone/pull `vis-demo` on the new
  device and you have everything committed.
- Nothing uncommitted was left behind (`git status` clean as of last session).

## Architecture (three tiers, all complete — backend + frontend)

| Tier | Capability | Backend | Frontend |
|---|---|---|---|
| 1 | Semantic units (topic segmentation over the transcript) | `context_vis/{domain,service,api,hermes_adapter,repository,codec}.py` | unit list / spine in `ContextVisPage.tsx` |
| 2 | Survival probe — does a stated constraint stay **present** / get **reframed** / go **absent** after compaction | `agent/conversation_compression.py` compaction probe hook, `context_vis/survival.py` | `SURVIVAL` encoding, `SalientRow` B-vs-A comparison |
| 3 | Preserve/pin — pin specific turns so compaction can't drop them | `context_vis/hermes_adapter.py` (`request_preserve`, writes `<HERMES_HOME>/context-vis/pins/<session_id>.json`), `agent/conversation_compression.py::_load_pinned_turn_ids`, `agent/context_compressor.py` (filters + re-inserts pinned turns) | pin button per unit → `POST /context-vis/sessions/{id}/preserve` |

Key backend files:
- `context_vis/domain.py` — `ContextVisModel`, `PreserveResult`, tier logic.
- `context_vis/hermes_adapter.py` — the Hermes-specific adapter (session data,
  pin storage, MAX_PINNED_CHARS cap, rejects tool-only/text-less turns).
- `context_vis/service.py` / `context_vis/api.py` — service layer + FastAPI
  routes (`/api/context-vis/sessions`, `/sessions/{id}`, `/preserve`, jobs for
  generate/detect-salient/draft-aggregates).
- `agent/context_compressor.py`, `agent/conversation_compression.py` — the
  actual Hermes compaction pipeline, patched to read pins and (Tier 2) emit a
  compaction probe event so ContextVis can tell what survived.

Key frontend files:
- `web/src/pages/ContextVisPage.tsx` — the entire page (~470 lines): top bar,
  conversation panel (Transcript/Live toggle), semantic spine, unit detail,
  backtrack section, Tier-3 pin controls, `SpineLegend`.
- `web/src/lib/context-vis.ts` — pure helpers: `buildHighlightSegments`,
  `summariseSurvival`, `dominantSurvival`, `unitIsPinned` (all unit-tested).
- `web/src/lib/api.ts` — `ContextVisModel`/`ContextVisUnit`/`ContextVisInfo`
  types, `getContextVisSessions`, `getContextVisSession`, `preserveContextVisTurns`.
- `web/src/context-vis-theme.css` — scoped `[data-contextvis-shell]` theme
  (see below).
- `web/src/App.tsx` — `/context-vis` is a **standalone full-bleed route**,
  rendered outside the normal sidebar/header app shell (search
  `isContextVisRoute` in `App.tsx`).
- `web/src/pages/ContextVisPage.test.ts` — 9 vitest unit tests, all passing.

## Frontend redesign (completed this cycle)

Starting point was a plain 3-column read-only dashboard reusing Hermes's teal
theme, embedded in the normal app shell. Redesigned per user direction into a
standalone "cockpit":

- **Full-bleed shell**: `/context-vis` renders outside the sidebar/header,
  own scoped visual identity via `data-contextvis-shell`.
- **Left ~35% conversation panel**, dual-mode: default rich transcript
  (message bubbles, tool calls, `id="cv-turn-<id>"` anchors for linkage) or
  switch to a live terminal (`navigate('/chat?resume=<id>')` — reuses the
  existing persistent PTY-backed ChatPage rather than spawning a second PTY).
- **Right ~65% vertical "semantic spine"**: one block per unit, color-coded by
  dominant survival status, salient count, pin state; expandable per-unit
  detail (summary sentences, salient rows with survival badges, B-vs-A
  comparison, "show me in the transcript" jump, Tier-3 pin toggle).
- Toolbar actions: Append turns (incremental generate), Detect salient,
  Overview/Decision aggregation draft + editor, refresh survival.
- Backtrack section: linear before/after unit links + notes (not a graph —
  iron law 4).
- Notice vs. error separation: a partial pin rejection (e.g. pinning a
  tool-only turn that can't be preserved verbatim) surfaces as a dismissable
  amber **notice**, not a red error — this was a bug found via self-QA
  screenshot and fixed in `280035fd0`.

### Theme: dark → light (most recent change, `acdf2415c`)

The user's explicit ask: make it look like an **academic vis system**, and
switch from dark to **light** (most vis systems are light-toned). Done via
`web/src/context-vis-theme.css`, fully rewritten:

- Near-white canvas (`--cv-bg: #f6f7f9`), white panels, near-black ink,
  hairline borders — Tufte-style restrained surface.
- One academic-blue accent (`#2a78d6`), a distinct violet pin accent
  (`#7c3aed`).
- Status triad grounded in the **dataviz skill's validated light-mode
  palette**: present `#0f8a12` / reframed `#b45309` / absent `#d03b3b`. The
  validator (`validate_palette.js`) flags red↔amber as a close hue pair —
  accepted because status colors always ship with a glyph (`●`/`◐`/`○`) *and*
  a text label (never color alone), which is the skill's prescribed
  mitigation for that case.
- Added `SpineLegend` component (`ContextVisPage.tsx`) — previously the
  survival glyphs/rail colors/pin icon were unlabeled; now there's a small
  recessive legend strip under the spine toolbar, gated the same way the
  marks are (survival ≥ Tier 2, pin ≥ Tier 3).
- One residual hardcoded dark value (`SegToggle` active-state text color,
  `#0b1120`) was replaced with a proper `--cv-on-accent` token.

Verified via: `tsc --noEmit`, `vite build`, `vitest run` (9/9 pass), and
headless-Chromium screenshots (see below) read back and inspected for
console errors and visual correctness — including the B-vs-A comparison
detail view and the pin round-trip.

## How to run / re-verify on a new device

```bash
cd hermes-agent
# backend venv is expected at ~/.hermes/hermes-agent/venv (adjust if different
# on the new machine)
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main dashboard --no-open
# then open http://127.0.0.1:<port>/context-vis in a browser
```

Frontend build/test loop:
```bash
cd hermes-agent/web
npx tsc --noEmit -p tsconfig.app.json
npx vite build          # writes hermes_cli/web_dist/ — dashboard serves this,
                         # so rebuild + reload browser to see frontend changes
npx vitest run src/pages/ContextVisPage.test.ts
```

Self-screenshot workflow used throughout (dashboard MCP's Playwright wasn't
usable — its default `chrome` channel binary was missing and needed root; the
bundled Chromium works without root):
```js
const { chromium } = require("playwright-core");
const EXE = "<user-cache-dir>/ms-playwright/chromium-<rev>/chrome-linux64/chrome";
const b = await chromium.launch({ executablePath: EXE, args: ["--no-sandbox"] });
// navigate to http://127.0.0.1:<port>/context-vis, screenshot, Read the PNG
```
(`npx playwright install chromium` — no root needed — if the cache is missing
on the new machine.)

Eval harness: `evals/context_vis/` — synthetic long-task cases (`cases/c1..c6.py`),
`run_generate.py` / `run_incremental.py` / `run_survival.py` drivers,
`REPORT.md` / `E2E_ACCEPTANCE.md` write-ups of prior evaluation rounds
(sub-agent blind eval was used for Tier 1 unit-quality judgment per user's
explicit requirement — judgment must come from a sub-agent, not the main
agent, to avoid self-grading bias). `preserve_e2e/` holds the live Tier 3
pin round-trip harness (`run_live.py`, `make_project.py`).

## Pending / not yet done

1. **In-page embedded live terminal** (deferred "Phase 3" from the original
   redesign plan) — currently Live mode just navigates to `/chat?resume=`
   rather than embedding the terminal inline.
2. **Scroll-sync** between the left transcript and the right spine
   (IntersectionObserver-driven alignment) — noted as the trickiest polish
   item, not started.
3. Compression-events panel — backend data exists, no dedicated UI section
   yet (right column has some unused space earmarked for this).
4. Backtrack panel could collapse when empty (minor polish, not done).
5. No further tier work is planned — Tiers 1–3 are functionally complete.

## Where a fresh session should start

If asked to continue, re-read this file plus:
- `../../docs/contextVis-spec.md` for the governing spec.
- `evals/context_vis/REPORT.md` and `E2E_ACCEPTANCE.md` for eval history.
- The full plan that drove the redesign is saved as a Claude plan-mode file
  (not part of this repo) titled *"/context-vis 界面重构"* — if unavailable
  on the new device, this handoff doc plus the "Frontend redesign" section
  above supersedes it (the plan has been executed through Phase 2; Phase 3
  is the pending embedded-terminal item above).
