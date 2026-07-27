# ContextVis Design System

ContextVis is an existing route in the Hermes web workspace. This document is
an extraction of the language already implemented in
`src/context-vis-theme.css`, `src/index.css`, `src/pages/ContextVisPage.tsx`,
and the ContextVis route shell in `src/App.tsx`. It is an implementation
contract for the academic visualization surface, not a visual redesign.

## 1. Atmosphere & Identity

ContextVis is a quiet, scholarly instrument for people returning to a long,
exploratory agent session. It is dense but calm: near-white paper, near-black
ink, hairline structure, and a single academic blue for interaction. The
semantic spine and the transcript remain visibly related without turning the
screen into a dashboard of competing cards. The signature is provenance made
visible: a linear semantic spine, a linked transcript, subtle dominant-status
rails, and explicit glyph-plus-label survival states.

The locked product dials are `DESIGN_VARIANCE: 4`, `MOTION_INTENSITY: 2`, and
`VISUAL_DENSITY: 7`. These values describe the current operational surface and
must not be increased as part of ordinary ContextVis feature work.

## 2. Color

### Palette

All ContextVis tokens are scoped below `[data-contextvis-shell]`. They do not
replace the global Hermes theme. The route intentionally has a light-only
academic presentation; no dark values are implied by this extraction.

| Role | Token | Value | Usage |
| --- | --- | --- | --- |
| Canvas | `--cv-bg` | `#f6f7f9` | Route canvas and spine background |
| Alternate canvas | `--cv-bg-2` | `#eef1f5` | Gutters, headers, notices, metadata rows |
| Surface | `--cv-surface` | `#ffffff` | Panels, transcript turns, controls |
| Raised surface | `--cv-surface-2` | `#f4f6f9` | Hover and selected-control backing |
| Border | `--cv-border` | `#e4e8ee` | Hairline separators and panel borders |
| Strong border | `--cv-border-strong` | `#cdd4de` | Rails and scrollbar thumbs |
| Text | `--cv-text` | `#1a1f29` | Primary copy and ink |
| Dim text | `--cv-text-dim` | `#59626f` | Secondary copy and labels |
| Faint text | `--cv-text-faint` | `#98a1af` | Tertiary metadata and quiet affordances |
| Accent | `--cv-accent` | `#2a78d6` | Links, selected outlines, action fills |
| Accent strong | `--cv-accent-2` | `#1f5fae` | Available for stronger academic-blue emphasis |
| Accent tint | `--cv-accent-dim` | `#dce9f8` | Available for light accent backing |
| On accent | `--cv-on-accent` | `#ffffff` | Text and icons on accent fills |
| Preserve pin | `--cv-pin` | `#7c3aed` | Pinned or preserved context |
| Pin tint | `--cv-pin-dim` | `#efe7fd` | Available for light pin backing |
| Present | `--cv-present` | `#0f8a12` | Still visible after compaction |
| Reframed | `--cv-reframed` | `#b45309` | Still represented with changed wording |
| Absent | `--cv-absent` | `#d03b3b` | No longer visible |
| Unknown | `--cv-unknown` | `#98a1af` | No compression visibility available |
| Present tint | `--cv-present-dim` | `#e3f3e3` | Available for present-state backing |
| Reframed tint | `--cv-reframed-dim` | `#f8ecdb` | Available for reframed-state backing |
| Absent tint | `--cv-absent-dim` | `#f9e4e4` | Available for absent-state backing |
| Reliable salient | `--cv-salient-reliable` | `#475569` | Monochrome reliable salient count |
| Guessed salient | `--cv-salient-guessed` | `#94a3b8` | Monochrome AI-guessed salient count |

The inherited shadcn-compatible slots are remapped inside the same scope:
`--background`, `--background-base`, `--foreground`, `--foreground-base`,
`--midground`, `--midground-base`, `--theme-font-sans`, and
`--theme-font-mono` resolve to the `--cv-*` tokens above. New UI must use
semantic `--cv-*` tokens or the existing scoped utility classes. Do not add a
second accent family or a global color override.

Survival states are always redundant encodings. The current legend and rows
pair each status color with a glyph and text label: present `●`, reframed `◐`,
absent `○`. Pinning also has a violet icon and a text label. Hue alone never
communicates a state.

## 3. Typography

### Font stacks

- Sans: `"Fira Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` via `--cv-font-sans`.
- Mono: `"Fira Code", ui-monospace, "JetBrains Mono", "SF Mono", "Cascadia Code", Menlo, Consolas, monospace` via `--cv-font-mono`.
- `ContextVis` headings, turn roles, counts, IDs, and dense status metadata use the mono stack where the current JSX applies `font-mono`. Body and explanatory copy use the scoped sans stack.
- Fira is a preferred stack, not a new font download. The existing page falls back to the listed system fonts when Fira is unavailable; do not claim an unshipped font asset.

### Existing scale and intent

| Intent | Existing expression | Use |
| --- | --- | --- |
| UI title | `text-sm` with `font-semibold` | ContextVis wordmark, unit titles |
| Body and summaries | `text-sm` or `text-xs` | Transcript prose, summary sentences, controls |
| Dense metadata | `text-[11px]` | Turn counts, helper copy, notices |
| Encoding and compact labels | `text-[10px] font-mono uppercase tracking-wide` | Legend, role labels, pills, aggregate headings |
| Terminal or source text | `font-mono text-xs leading-relaxed` | Transcript `pre`, IDs, detected text |

The 10px and 11px sizes are existing metadata treatments only. They must not
be used for paragraphs, instructions, error explanations, or other content a
person must read continuously. Preserve the current academic-blue/ink contrast
and do not introduce a display serif or a second display family.

## 4. Spacing & Layout

### Base unit and intent

The global Tailwind v4 spacing variable is `calc(0.25rem *
var(--theme-spacing-mul, 1))`, so ContextVis spacing follows a 4px base unit.
Existing utility values map as follows:

| Intent | Existing utility examples | Base-unit value |
| --- | --- | ---: |
| Hairline separation | `gap-1`, `p-1.5`, `mt-1` | 4px, 6px, 4px |
| Compact control rhythm | `gap-2`, `px-2`, `py-2` | 8px |
| Standard panel rhythm | `px-3`, `py-3`, `gap-3` | 12px |
| Page/header inset | `px-4` | 16px |
| Empty-state breathing room | `p-6` | 24px |

Values such as `35%`, `65%`, `h-dvh`, `max-h-[70vh]`, and `max-h-[58vh]`
are layout mechanics, not spacing tokens. Keep intrinsic sizing and viewport
units raw when they express a constraint. Do not introduce arbitrary spacing
steps without adding the intent here first.

### Shell and scroll ownership

The ContextVis route is a bounded application shell:

1. `App.tsx` mounts `[data-contextvis-shell]` as `h-dvh max-h-dvh w-screen overflow-hidden`.
2. `ContextVisPage` is a `flex h-full flex-col` column. The header, notices,
   toolbars, and legend are `shrink-0` fixed regions.
3. The body is `flex min-h-0 flex-1`. It contains a 35% conversation pane and
   a 65% semantic-spine pane.
4. The conversation pane's toolbar stays fixed; `TranscriptView` owns its
   vertical scroll with `h-full overflow-auto`. Each transcript `pre` may own a
   subordinate bounded scroll when a single turn is very long.
5. The semantic-spine pane's action toolbar and legend stay fixed; its content
   region owns vertical scroll with `min-h-0 flex-1 overflow-auto`. The session
   dropdown and its result list have their own named bounded scroll regions.

Every additional scrollbar must have one of those explicit jobs. Do not move
scroll ownership to the document, remove `min-h-0`, or add an unnamed nested
scroll container. The shell uses dynamic viewport units so browser chrome does
not make the fixed regions jump.

### Responsive rules

These are the current extraction rules at the required observation widths:

- **1280px:** preserve the two-pane composition at 35% conversation and 65%
  spine. Both panes remain independently scrollable; action controls fit on a
  single toolbar row where content permits.
- **768px:** the global app media rule releases document overflow for the
  mobile dashboard, while the ContextVis shell remains bounded. Keep the
  two-pane ratio, allow toolbars and status rows to wrap, and keep the named
  pane scroll owners. `sm:grid-cols-2` detail comparisons are available from
  640px upward.
- **375px:** preserve the existing operational split-pane surface rather than
  inventing a stacked redesign. Controls wrap via `flex-wrap`; transcript
  content uses `whitespace-pre-wrap break-words`; labels and IDs must wrap or
  truncate rather than force horizontal scrolling. The session picker keeps
  its existing bounded dropdown behavior and must be checked against the
  viewport before any future width change.

At every width, content stress cases include empty sessions, no generated
semantic view, long labels, long paragraphs, unbroken IDs/URLs, emoji and
non-BMP trigger text, and CJK strings. Reflow and wrapping are preferred over
shrinking readable copy.

## 5. Components

The following primitives are already shared by two or more ContextVis states
or are the route's named structural primitives. Keep their anatomy and state
language stable.

### ContextVis shell

- **Structure:** bounded route container, fixed header/notices, dual-pane body.
- **Variants:** loading, selected session, no selected session, stale survival,
  inline error, inline notice.
- **Spacing:** `px-4`, `py-2.5`, `gap-3`, 4px-derived utility rhythm.
- **States:** loading uses the existing `Spinner`; errors and notices are
  dismissible inline rows; no-data states use `Empty` or the generated-view
  prompt; working controls disable through the existing `Button` contract.
- **Accessibility:** preserve landmarks, semantic sections, text alternatives,
  keyboard reachability, and visible focus. Status rows must not rely on color.
- **Motion:** only existing color/opacity affordances and bounded smooth
  locate behavior; reduced motion removes non-essential transitions.
- **Layout:** `scroll-body-shell` plus a `list-detail`-like 35/65 split. The
  conversation and spine bodies are the two primary scroll owners.

### SessionSwitcher

- **Structure:** button with current title/preview, search `Input`, bounded
  result list, selected-session row.
- **Variants:** selected, no selection, filtered results, no matches.
- **Spacing:** compact `gap-2`, `px-3`, `py-1.5`, dropdown `p-2`.
- **States:** default, open, selected, hover, keyboard focus, empty results,
  and loading/disabled when the route is working.
- **Accessibility:** button and input remain native controls; search autofocus
  is preserved; each result is a keyboard-activatable button with a readable
  title and message count.
- **Motion:** opening and filtering do not introduce decorative animation.
- **Layout:** anchored overlay with a named bounded result-list scroll owner.

### SegToggle and Button/Input primitives

- **Structure:** grouped native buttons for `transcript/live` and
  `overview/decision`, plus Nous UI `Button` and `Input` primitives.
- **Variants:** selected/unselected, outlined/filled, disabled, working.
- **Spacing:** `p-0.5`, `px-2`, `py-1`, and existing DS component spacing.
- **States:** default, hover, active, focus-visible, disabled, and working.
  Selected state is the academic-blue fill with on-accent text.
- **Accessibility:** use button semantics, readable labels, visible focus,
  and no icon-only action without an accessible name or title.
- **Motion:** `transition-colors` only; no layout movement.

### TranscriptView and transcript turn

- **Structure:** scrollable list of semantic `article` turns, role/tool label,
  wrapped `pre`, and linked highlight marks.
- **Variants:** user, assistant, tool, active coverage, highlighted span.
- **Spacing:** `space-y-2`, `px-3`, `py-3`, turn `px-3 py-2`.
- **States:** default, covered/linked, selected by spine, hover, keyboard
  focus when made focusable, empty transcript, and long-content stress.
- **Accessibility:** role labels and tool names remain text; highlight is
  supplementary; the turn's selection action is a keyboard-reachability
  target. The current click-only `article` surface is recorded under Accepted
  Debt rather than silently treated as compliant.
- **Motion:** locate actions may scroll the existing turn into view. The
  current calls request smooth scrolling unconditionally; the missing reduced-
  motion fallback is recorded under Accepted Debt.
- **Layout:** primary conversation scroll owner; turn `pre` is a subordinate
  scroll only for exceptionally long content.

### SpineLegend and Pill

- **Structure:** compact legend or inline label with optional status glyph.
- **Variants:** capability tier, reconstructed warning, confidence (`rule` or
  `ai`), survival, pin, draft.
- **Spacing:** `gap-1`, `gap-x-3`, `gap-y-1`, `px-1.5`, `py-0.5`.
- **States:** visible only when the capability exists; never represent an
  unsupported tier as zero; selected/hover/focus behavior belongs to the
  containing control.
- **Accessibility:** glyph, label, and title together carry meaning. Do not
  hide the text label behind color.
- **Motion:** static. A legend is explanatory, not decorative.

### SpineUnit and SalientRow

- **Structure:** unit title and metadata, dominant-status inset rail, optional
  expanded detail, salient confidence/status rows, transcript locate action,
  and tier-gated preserve action.
- **Variants:** collapsed/active, pinned/unpinned, draft/frozen, reliable or
  AI-guessed salient, present/reframed/absent/unknown survival.
- **Spacing:** unit `px-3 py-2`; detail and preserve rows use `px-3 py-2`;
  salient rows use `px-2 py-1.5`.
- **States:** default, hover, active, focus-visible, expanded, disabled when
  status is non-actionable, working, error, and saved notice. Unsupported
  status or tier controls are hidden rather than rendered as fake zeroes.
- **Accessibility:** unit selection, status disclosure, locate, and preserve
  are explicit buttons. Original and reframed text are presented as labeled
  columns; pinned state has icon plus text.
- **Motion:** color transition and disclosure only; preserve/reframed feedback
  uses the existing notice/error rows.

### AggregateEditor, BacktrackSection, and Empty

- **Structure:** bordered aggregate nodes with title input and move/split/merge
  actions; backlink list and add form; shared centered empty-state copy.
- **Variants:** overview/decision aggregate, no aggregates, invalid/incomplete
  form, saved, working, error, and no semantic model.
- **Spacing:** panel `p-2`, node `p-2`, form `gap-1`, empty state `p-6`.
- **States:** preserve native input/select focus, disabled save when required
  values are absent, and route-level working/error feedback.
- **Accessibility:** action buttons have text or an explicit accessible name;
  selects have meaningful option labels; empty state explains the next action.
- **Motion:** none beyond the existing control transitions.

## 6. Motion & Interaction

ContextVis is intentionally low-motion (`MOTION_INTENSITY: 2`). Motion exists
only to confirm a state change or help a user trace provenance:

- `transition-colors` marks hover/selected changes on turns, units, and toggles.
- `scrollIntoView({ behavior: "smooth" })` links a semantic item to its source
  transcript turn. It must fall back to instant scrolling when
  `prefers-reduced-motion: reduce` is active.
- The scoped stylesheet disables all transitions and animations under
  `[data-contextvis-shell]` for reduced-motion users.
- No autoplay, parallax, perpetual pulse, scroll hijack, layout animation, or
  animation of width/height/top/left is part of this system.

Interaction feedback is explicit: selected controls use the academic-blue
fill, active units use an accent outline and status rail, pinned units use the
violet pin encoding, and async work uses the existing spinner plus disabled
controls. Errors and notices stay inline and dismissible.

## 7. Depth & Surface

The surface strategy is **mixed, led by tonal shift and hairline borders**.

- `--cv-bg` is the paper-like canvas; `--cv-bg-2` separates gutters,
  headers, and notices; `--cv-surface` is the white reading surface;
  `--cv-surface-2` is the quiet raised/hover tone.
- `.cv-panel` uses a 1px `--cv-border` and a `0.625rem` radius. Existing
  utility `rounded-md`, `rounded-lg`, and compact `rounded` variants remain
  as component-level anatomy; do not create a new radius family.
- `.cv-rail` and the inline `box-shadow: inset 3px 0` on units provide a
  narrow semantic status rail. Salient rows use an inset 2px rail.
- The session picker may use the existing dropdown `shadow-2xl` to clear the
  reading surface. This is an overlay exception, not a general card-shadow
  language.
- Scrollbars are scoped to the shell: 10px tracks, strong-border thumbs, and
  a 2px canvas-colored thumb border. Keep them quiet and secondary. The
  existing hover color is a raw value rather than a semantic token; that
  tokenization gap is recorded under Accepted Debt.

Do not flatten status rails into fills, add decorative gradients, or apply
global shadows. Depth should continue to come from tonal separation, borders,
and provenance rails.

## 8. Accessibility Constraints & Accepted Debt

### Constraints

- **Target:** WCAG 2.2 AA, with at least 4.5:1 contrast for normal body copy
  and 3:1 for large text or meaningful graphical marks.
- **Keyboard:** every session, toggle, input, select, unit, disclosure,
  transcript locate action, preserve action, and save/delete action must be
  reachable in DOM order with visible focus. Do not replace native controls
  with click-only containers.
- **Zoom and reflow:** at 200% browser zoom, preserve a readable primary
  column and do not require two-dimensional scrolling for ordinary content.
  Keep `min-h-0`, `min-w-0`, wrapping, and bounded pane ownership intact.
- **Content stress:** empty state, long labels, long paragraphs, unbroken
  identifiers, emoji/non-BMP trigger text, and CJK text must remain legible.
  Use `whitespace-pre-wrap`, `break-words`, and equivalent overflow-safe rules
  for source text; never silently clip the evidence a user is inspecting.
- **Status clarity:** survival and confidence state always includes text and a
  glyph. Reliable rule matches and AI guesses remain distinct labels.
- **Reduced motion:** honor `prefers-reduced-motion: reduce` by disabling
  non-essential CSS transitions/animations and using instant source-location
  scrolling.
- **Theme boundary:** keep the light ContextVis theme scoped to
  `[data-contextvis-shell]`; do not regress the rest of the Hermes dashboard.
- **Language:** labels remain plain, operational, and locale-safe. CJK text,
  long translations, and bidirectional or unbroken content must wrap without
  changing semantic order.

### Accepted Debt

| Item | Location | Why accepted | Owner / Exit |
| --- | --- | --- | --- |
| Click-only transcript turns | `src/pages/ContextVisPage.tsx:125-139` | Each transcript turn is an `<article onClick>` with no `tabIndex` or keyboard handler, so the exposed selection surface is not keyboard-reachable today. | Future accessibility pass: provide a native or fully keyboard-equivalent selection control while preserving the current turn anatomy. |
| Missing reduced-motion scroll fallback | `src/pages/ContextVisPage.tsx:327-337` | Locate helpers call `scrollIntoView({ behavior: "smooth" })` unconditionally; the stylesheet only disables transitions/animations and does not change this scroll behavior. | Future motion pass: route source-location scrolling through a reduced-motion-aware instant fallback. |
| Untokenized scrollbar-hover color | `src/context-vis-theme.css:104` | `::-webkit-scrollbar-thumb:hover` uses raw `#aab3c0` instead of a scoped semantic token, so the hover state is outside the palette contract. | Future token pass: add or map a scoped scrollbar-hover token without changing the route's color language. |

The three rows above are existing debt documented by this extraction, not new
UI work. The absence of a dark ContextVis palette, a bundled Fira font file,
or a stacked mobile redesign is intentional scope, not an unreported defect.
Any future change to those decisions or to the debt rows requires a
design-system update before code.
