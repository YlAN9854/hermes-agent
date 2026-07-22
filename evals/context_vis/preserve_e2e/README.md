# Tier 3 preserve — end-to-end tests

Two complementary e2e checks for the pin/preserve feature (pin a transcript
turn → compaction keeps it verbatim instead of summarizing it away).

## 1. Fast deterministic e2e — `tests/test_tier3_preserve_e2e.py`

The primary, CI-friendly proof. Runs the whole pin path through its real public
surfaces with only the summary LLM stubbed:

```
adapter.request_preserve  →  writes the real pin file
_load_pinned_turn_ids     →  the loader compress_context uses
ContextCompressor.compress →  honours the pin set
archive_and_compact        →  persists the new active context A
get_active_context         →  observable: pinned turn is byte-for-byte verbatim in A
```

A control test compacts the identical session with **no** pin and confirms the
same middle constraint is dropped — so survival is caused by the pin, not the
turn's position. Assertions are mechanical; no agent judgement needed.

```
uv run --extra dev python -m pytest tests/test_tier3_preserve_e2e.py -q
```

Its validity was independently audited with a false-pass experiment: breaking
the pin mechanism (filter no-op / loader returns empty) makes the main test
fail, so it genuinely catches regressions.

## 2. Live real-threshold e2e — `run_live.py` (on-demand)

The slow confirmation through a **real** agent session that crosses the real
compaction threshold and runs the full `compress_context` orchestration. Needs
a real LLM (~10 min) and its verdict is an independent sub-agent judgement, so
it is not a pytest test.

### Run it

```bash
# 1. Isolated home with a small enough context window that a real audit fills it.
E=/tmp/preserve-home; rm -rf "$E"; mkdir -p "$E"
cp ~/.hermes/config.yaml ~/.hermes/auth.json ~/.hermes/.env "$E/"
python - "$E" <<'PY'
import sys, yaml; from pathlib import Path
p = Path(sys.argv[1])/"config.yaml"; c = yaml.safe_load(p.read_text()) or {}
c.setdefault("model", {})["context_length"] = 64000          # Hermes floor
c.setdefault("compression", {}).update({"enabled": True, "threshold": 0.75,
                                        "protect_last_n": 6, "in_place": True})
p.write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False))
PY

# 2. A realistic project big enough to push context past the threshold.
uv run --extra dev python evals/context_vis/preserve_e2e/make_project.py /tmp/logpipe-project

# 3. Drive the session (pins a substantive early-middle user turn mid-run).
HERMES_HOME=$E E2E_PROJECT=/tmp/logpipe-project \
  uv run --extra dev python evals/context_vis/preserve_e2e/run_live.py
```

It writes `preserve_e2e_result.json`, `preserve_e2e_active.json`,
`preserve_e2e_transcript.json`, and the pin file under `$E`. The result json
records the compaction's dropped set, the pinned turn, whether it was kept vs
its neighbours dropped, and `verbatim_B_equals_A`.

### Judge it with a sub-agent (not the main agent)

Hand those artifacts to an **independent** sub-agent to verify, from the
artifacts + DB, that: a real compaction occurred; the pinned turn was genuinely
at risk (mid-dropped-region, neighbours dropped); it survived byte-for-byte in
A as a real non-synthetic entry; and B is intact. Do not self-certify.

### Gotchas learned building this

- `-z` oneshot is **stateless** and the chat REPL swallows piped stdin as one
  prompt — neither builds a long conversation. The driver keeps ONE agent and
  threads `result["messages"]` back as the next `conversation_history`, or the
  context never accumulates and compaction never fires.
- Pin a substantive **user text** turn. An assistant turn whose only payload is
  a tool call cannot be preserved verbatim (its paired tool result may be
  dropped, orphaning the call) — `request_preserve` now rejects such turns.
