"""Run Context Vis semantic-unit generation for seeded synthetic sessions.

Usage: HERMES_HOME=<isolated home> python -m evals.context_vis.run_generate [case_id ...]

Calls ContextVisService.generate_units directly (same code path the Dashboard
job runner uses) and dumps model + transcript JSON under evals/context_vis/runs/.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from context_vis.hermes_adapter import HermesContextAdapter
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from hermes_constants import get_hermes_home
from hermes_state import SessionDB

from .seed import CASE_IDS

RUNS_DIR = Path(__file__).parent / "runs"

# detect_salient sends the WHOLE transcript in one llm_complete call (no
# batching), so we only run it for the constraint-focused cases; c4 (>135k
# chars) would blow the prompt budget — that limitation itself is an eval
# finding, not something to hide here.
SALIENT_CASE_IDS = {"c3", "c5"}


def run_case(home: Path, case_id: str) -> dict:
    session_id = f"synth-{case_id}"
    db = SessionDB(db_path=home / "state.db")
    repo = ContextVisRepository(home)
    out_dir = RUNS_DIR / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        adapter = HermesContextAdapter(db, session_id)
        service = ContextVisService(adapter, repo)
        transcript = adapter.get_full_transcript()
        (out_dir / "transcript.json").write_text(
            json.dumps([t.__dict__ for t in transcript], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        model = service.generate_units(incremental=False)
        (out_dir / "model_units.json").write_text(
            json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if case_id in SALIENT_CASE_IDS:
            model = service.detect_salient()
        (out_dir / "model.json").write_text(
            json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        elapsed = time.monotonic() - started
        summary = {
            "case_id": case_id,
            "status": "ok",
            "seconds": round(elapsed, 1),
            "turns": len(transcript),
            "units": len(model.get("units", [])),
        }
    except Exception as exc:
        elapsed = time.monotonic() - started
        (out_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        summary = {
            "case_id": case_id,
            "status": "failed",
            "seconds": round(elapsed, 1),
            "error": str(exc)[:500],
        }
    finally:
        repo.close()
        db.close()
    return summary


def main() -> int:
    case_ids = sys.argv[1:] or CASE_IDS
    home = Path(get_hermes_home())
    summaries = []
    for case_id in case_ids:
        print(f"[{case_id}] generating…", flush=True)
        summary = run_case(home, case_id)
        print(f"[{case_id}] {summary}", flush=True)
        summaries.append(summary)
    (RUNS_DIR / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0 if all(s["status"] == "ok" for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
