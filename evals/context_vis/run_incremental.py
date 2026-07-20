"""Milestone acceptance: incremental generation must only append.

The Step 0–2 milestone requires that appending new conversation turns and
re-running generation leaves every existing unit (id, title, boundaries) and
every user-edited aggregate untouched (spec 铁律 3). The unit tests cover this
with a fake adapter; this script proves it end-to-end on synth-c1 through the
real service + LLM path.

Usage: python -m evals.context_vis.run_incremental
Requires: synth-c1 seeded and runs/c1/model.json present (full generation).
Re-runnable: it restores the committed baseline model and re-appends the
continuation turns on every invocation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from context_vis.hermes_adapter import HermesContextAdapter
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from hermes_constants import get_hermes_home
from hermes_state import SessionDB

from .case_schema import T

RUNS_DIR = Path(__file__).parent / "runs"
SESSION_ID = "synth-c1"
BASE_TURNS = 40  # c1's committed transcript: synth-c1-t000..t039

# A genuinely new topic appended after c1's "文档与部署" ending: metrics/monitoring.
INC_TURNS = [
    T("user",
      "服务已经部署好了，接下来我想给它加 Prometheus 指标：至少要有请求计数、"
      "缓存命中率和上游 OpenWeather 调用延迟三个指标，暴露在 /metrics 路径。"),
    T("assistant",
      "好的，用 prometheus-fastapi-instrumentator 加自定义 Counter/Histogram：\n"
      "- weather_requests_total{city}: 请求计数；\n"
      "- weather_cache_hits_total / weather_cache_misses_total: 算命中率；\n"
      "- openweather_latency_seconds: 上游调用延迟直方图。\n"
      "我先加依赖再改 app/main.py 与 app/weather.py。"),
    T("tool",
      "$ uv add prometheus-fastapi-instrumentator\n"
      "Resolved 34 packages in 412ms\n"
      "Installed 2 packages in 18ms\n"
      " + prometheus-client==0.20.0\n"
      " + prometheus-fastapi-instrumentator==7.0.0",
      tool_name="bash"),
    T("tool",
      "$ curl -s http://127.0.0.1:8000/metrics | grep -E 'weather_|openweather_' | head -6\n"
      "weather_requests_total{city=\"Shanghai\"} 3.0\n"
      "weather_cache_hits_total 2.0\n"
      "weather_cache_misses_total 1.0\n"
      "openweather_latency_seconds_bucket{le=\"0.25\"} 1.0\n"
      "openweather_latency_seconds_count 1.0\n"
      "openweather_latency_seconds_sum 0.183",
      tool_name="bash"),
    T("assistant",
      "指标已经生效：/metrics 能看到请求计数、缓存命中/未命中计数和上游延迟直方图，"
      "缓存命中率可由 hits/(hits+misses) 推出。监控接入完成。"),
]


def main() -> int:
    home = Path(get_hermes_home())
    db = SessionDB(db_path=home / "state.db")
    repo = ContextVisRepository(home)
    out_path = RUNS_DIR / "c1" / "incremental_check.json"
    try:
        baseline = json.loads((RUNS_DIR / "c1" / "model.json").read_text(encoding="utf-8"))

        # Restore a deterministic starting state: baseline model, no leftover
        # continuation turns from a previous invocation.
        def _wipe_inc(conn):
            conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND transcript_turn_id LIKE 'synth-c1-inc-%'",
                (SESSION_ID,),
            )
        db._execute_write(_wipe_inc)
        repo.delete_model(SESSION_ID)
        repo.save(SESSION_ID, baseline, f"synth-c1-t{BASE_TURNS - 1:03d}")

        service = ContextVisService(HermesContextAdapter(db, SESSION_ID), repo)
        model_before, transcript_before, _ = service.load()
        assert len(transcript_before) == BASE_TURNS, f"expected {BASE_TURNS} base turns, got {len(transcript_before)}"

        # A user-edited aggregate over all existing units must survive the update.
        user_aggregates = [{
            "node_id": "agg-user-1",
            "title": "用户裁定的总览",
            "child_unit_ids": [u.unit_id for u in model_before.units],
            "origin": "user_edited",
            "intent_tag": None,
        }]
        saved = service.save_edits({"aggregates": user_aggregates}, model_before.revision)

        base = time.time()
        for i, turn in enumerate(INC_TURNS):
            db.append_message(
                SESSION_ID,
                role=turn.role,
                content=turn.content,
                tool_name=turn.tool_name,
                timestamp=base + i,
                transcript_turn_id=f"synth-c1-inc-{i:03d}",
            )

        units_before = saved["units"]
        started = time.monotonic()
        updated = service.generate_units(incremental=True)
        elapsed = round(time.monotonic() - started, 1)

        old = updated["units"][:len(units_before)]
        new = updated["units"][len(units_before):]
        inc_ids = [f"synth-c1-inc-{i:03d}" for i in range(len(INC_TURNS))]
        checks = {
            "old_units_byte_identical": old == units_before,
            "new_units_appended": len(new) >= 1,
            "new_units_cover_exactly_inc_turns": [t for u in new for t in u["covered_turns"]] == inc_ids,
            "user_aggregate_untouched": updated["aggregates"][0] == user_aggregates[0],
            "draft_node_appended_for_new_units": (
                len(updated["aggregates"]) == 2
                and updated["aggregates"][1]["origin"] == "llm_draft"
                and updated["aggregates"][1]["child_unit_ids"] == [u["unit_id"] for u in new]
            ),
        }
        result = {
            "status": "pass" if all(checks.values()) else "fail",
            "seconds": elapsed,
            "checks": checks,
            "units_before": len(units_before),
            "units_after": len(updated["units"]),
            "new_unit_titles": [u["title"] for u in new],
        }
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["status"] == "pass" else 1
    finally:
        repo.close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
