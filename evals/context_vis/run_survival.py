"""Run the Tier 2 survival pass for seeded cases that carry a compaction.

Usage: python -m evals.context_vis.run_survival [case_id ...]

Goes through the real service + Hermes adapter, so it exercises the same path
the Dashboard uses. Requires the case to have been seeded (seed.py replays its
compaction) and its units generated.
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


def run_case(home: Path, case_id: str) -> dict:
    session_id = f"synth-{case_id}"
    db = SessionDB(db_path=home / "state.db")
    repo = ContextVisRepository(home)
    out_dir = RUNS_DIR / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        adapter = HermesContextAdapter(db, session_id, home)
        service = ContextVisService(adapter, repo)
        active = adapter.get_active_context()
        events = adapter.get_compression_events()
        (out_dir / "active_context.json").write_text(
            json.dumps({
                "fidelity": active.fidelity if active else None,
                "entries": [e.__dict__ for e in active.entries] if active else [],
                "events": [e.__dict__ for e in events],
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        model = service.refresh_survival()
        (out_dir / "model_survival.json").write_text(
            json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        statuses = [i["status_in_A"] for u in model["units"] for i in u["salient_infos"]]
        summary = {
            "case_id": case_id, "status": "ok", "seconds": round(time.monotonic() - started, 1),
            "tier": adapter.tier, "events": len(events),
            "salient": len(statuses),
            "by_status": {s: statuses.count(s) for s in sorted(set(statuses))},
        }
    except Exception as exc:
        (out_dir / "error_survival.txt").write_text(traceback.format_exc(), encoding="utf-8")
        summary = {"case_id": case_id, "status": "failed", "error": str(exc)[:500]}
    finally:
        repo.close()
        db.close()
    return summary


def main() -> int:
    case_ids = sys.argv[1:] or CASE_IDS
    home = Path(get_hermes_home())
    summaries = []
    for case_id in case_ids:
        summary = run_case(home, case_id)
        print(f"[{case_id}] {summary}", flush=True)
        summaries.append(summary)
    (RUNS_DIR / "survival_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0 if all(s["status"] == "ok" for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
