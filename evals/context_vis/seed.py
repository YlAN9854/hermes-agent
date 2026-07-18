"""Seed synthetic cases into the HERMES_HOME state.db as real sessions.

Usage: HERMES_HOME=<isolated home> python -m evals.context_vis.seed [case_id ...]

Each case becomes a session `synth-<case_id>` with stable transcript_turn_ids
`synth-<case_id>-t<NNN>` so gold annotations align trivially with the
adapter's transcript. Re-seeding a case deletes and recreates its session.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_state import SessionDB

from .case_schema import Case, case_stats, validate_case

CASE_IDS = ["c1", "c2", "c3", "c4", "c5"]


def load_case(case_id: str) -> Case:
    module = importlib.import_module(f"evals.context_vis.cases.{case_id}")
    return module.CASE


def seed_case(db: SessionDB, case: Case) -> str:
    session_id = f"synth-{case.case_id}"
    def _wipe(conn):
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    db._execute_write(_wipe)
    db.create_session(session_id, source="synthetic-eval", model="synthetic")
    base = time.time() - 3600.0
    for i, turn in enumerate(case.turns):
        db.append_message(
            session_id,
            role=turn.role,
            content=turn.content,
            tool_name=turn.tool_name,
            timestamp=base + i * 30.0,
            transcript_turn_id=f"synth-{case.case_id}-t{i:03d}",
        )
    return session_id


def main() -> int:
    case_ids = sys.argv[1:] or CASE_IDS
    home = Path(get_hermes_home())
    db = SessionDB(db_path=home / "state.db")
    try:
        for case_id in case_ids:
            case = load_case(case_id)
            errors = validate_case(case)
            if errors:
                print(f"[{case_id}] INVALID:")
                for e in errors:
                    print(f"  - {e}")
                return 1
            session_id = seed_case(db, case)
            print(f"[{case_id}] seeded as {session_id}: {case_stats(case)}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
