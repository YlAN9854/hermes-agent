from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS context_models (
  session_id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL DEFAULT 0,
  model_json TEXT NOT NULL,
  last_processed_turn TEXT,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS context_jobs (
  job_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_jobs_session ON context_jobs(session_id, created_at DESC);
"""


class ContextVisRepository:
    def __init__(self, hermes_home: Path):
        self.path = hermes_home / "context-vis.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def recover_interrupted_jobs(self) -> int:
        """Fail jobs left active by a previous Dashboard process.

        This is an explicit process-start operation, not repository setup:
        request handlers and workers open repositories routinely while jobs
        are live and must never reinterpret those jobs as restart leftovers.
        """
        with self._lock:
            cursor = self._db.execute(
                "UPDATE context_jobs SET status='failed', error='Dashboard restarted; retry this job', updated_at=? WHERE status IN ('queued','running')",
                (time.time(),),
            )
            self._db.commit()
            return cursor.rowcount

    def load(self, session_id: str) -> tuple[dict[str, Any] | None, str | None]:
        with self._lock:
            row = self._db.execute("SELECT * FROM context_models WHERE session_id=?", (session_id,)).fetchone()
        return (json.loads(row["model_json"]), row["last_processed_turn"]) if row else (None, None)

    def save(self, session_id: str, model: dict[str, Any], last_turn: str | None, expected_revision: int | None = None) -> int:
        with self._lock:
            row = self._db.execute("SELECT revision FROM context_models WHERE session_id=?", (session_id,)).fetchone()
            current = int(row[0]) if row else 0
            if expected_revision is not None and current != expected_revision:
                raise RuntimeError("revision_conflict")
            revision = current + 1
            model = {**model, "revision": revision}
            self._db.execute(
                "INSERT INTO context_models(session_id,revision,model_json,last_processed_turn,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,model_json=excluded.model_json,last_processed_turn=excluded.last_processed_turn,updated_at=excluded.updated_at",
                (session_id, revision, json.dumps(model, ensure_ascii=False), last_turn, time.time()),
            )
            self._db.commit()
        return revision

    def create_job(self, job_id: str, session_id: str, action: str, request: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            active = self._db.execute(
                "SELECT 1 FROM context_jobs WHERE session_id=? AND action=? AND status IN ('queued','running')",
                (session_id, action),
            ).fetchone()
            if active:
                raise RuntimeError("job_conflict")
            self._db.execute(
                "INSERT INTO context_jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, session_id, action, "queued", json.dumps(request), None, None, now, now),
            )
            self._db.commit()

    def update_job(self, job_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE context_jobs SET status=?,result_json=?,error=?,updated_at=? WHERE job_id=?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, time.time(), job_id),
            )
            self._db.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM context_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["request"] = json.loads(data.pop("request_json"))
        data["result"] = json.loads(data.pop("result_json")) if data.get("result_json") else None
        data.pop("result_json", None)
        return data
