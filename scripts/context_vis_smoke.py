#!/usr/bin/env python3
"""Run Context Vis semantic-unit generation through the backend API, without the UI."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9119")
    parser.add_argument("--session", help="Session ID; defaults to the latest session")
    parser.add_argument("--profile", help="Optional Hermes profile")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    query = "?" + urllib.parse.urlencode({"profile": args.profile}) if args.profile else ""
    base = args.base_url.rstrip("/")
    session_id = args.session
    if not session_id:
        sessions = request_json(f"{base}/api/context-vis/sessions{query}").get("sessions", [])
        if not sessions:
            raise RuntimeError("No Hermes sessions found")
        session_id = sessions[0]["id"]

    encoded_session = urllib.parse.quote(session_id, safe="")
    job = request_json(
        f"{base}/api/context-vis/sessions/{encoded_session}/jobs{query}",
        "POST",
        {"action": "generate_units", "incremental": args.incremental},
    )
    job_id = job["job_id"]
    print(f"session={session_id} job={job_id}", flush=True)

    deadline = time.monotonic() + args.timeout
    encoded_job = urllib.parse.quote(job_id, safe="")
    while time.monotonic() < deadline:
        status = request_json(f"{base}/api/context-vis/jobs/{encoded_job}{query}")
        state = status["status"]
        print(f"status={state}", flush=True)
        if state == "succeeded":
            model = status.get("result", {}).get("model", {})
            print(f"semantic_units={len(model.get('units', []))}")
            return 0
        if state == "failed":
            raise RuntimeError(status.get("error") or "Context Vis job failed")
        time.sleep(1)
    raise TimeoutError(f"Job did not finish within {args.timeout}s")


if __name__ == "__main__":
    raise SystemExit(main())
