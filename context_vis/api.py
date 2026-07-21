from __future__ import annotations

import concurrent.futures
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_constants import get_hermes_home
from hermes_state import SessionDB

from .hermes_adapter import HermesContextAdapter
from .repository import ContextVisRepository
from .service import ContextVisService

router = APIRouter(prefix="/api/context-vis", tags=["context-vis"])
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="context-vis")
_RECOVERY_LOCK = threading.Lock()
_RECOVERED_HOMES: set[Path] = set()


def _home(profile: str | None) -> Path:
    requested = (profile or "").strip()
    if not requested or requested.lower() == "current":
        return Path(get_hermes_home())
    from hermes_cli import profiles
    try:
        name = profiles.normalize_profile_name(requested)
        profiles.validate_profile_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not profiles.profile_exists(name):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' does not exist")
    return profiles.get_profile_dir(name)


def _ensure_recovered(home: Path) -> None:
    """Recover stale jobs once per profile home for this Dashboard process."""
    resolved = home.resolve()
    with _RECOVERY_LOCK:
        if resolved in _RECOVERED_HOMES:
            return
        repo = ContextVisRepository(resolved)
        try:
            repo.recover_interrupted_jobs()
        finally:
            repo.close()
        _RECOVERED_HOMES.add(resolved)


def _resources(profile: str | None, session_id: str):
    home = _home(profile)
    _ensure_recovered(home)
    db = SessionDB(db_path=home / "state.db")
    sid = db.resolve_session_id(session_id)
    if not sid:
        db.close()
        raise HTTPException(status_code=404, detail="Session not found")
    sid = db.resolve_resume_session_id(sid)
    repo = ContextVisRepository(home)
    adapter = HermesContextAdapter(db, sid, home)
    return home, sid, db, repo, adapter


class JobRequest(BaseModel):
    action: str
    incremental: bool = False
    mode: str | None = None
    intent: str | None = None


class EditRequest(BaseModel):
    revision: int
    aggregates: list[dict[str, Any]] | None = None
    decision_aggregates: list[dict[str, Any]] | None = None
    decision_intent: str | None = None
    backlinks: list[dict[str, Any]] | None = None


@router.get("/sessions")
def list_context_sessions(profile: str | None = None, limit: int = 50):
    home = _home(profile)
    _ensure_recovered(home)
    db = SessionDB(db_path=home / "state.db")
    repo = ContextVisRepository(home)
    try:
        sessions = db.list_sessions_rich(limit=min(max(limit, 1), 100), order_by_last_active=True)
        for session in sessions:
            model, _ = repo.load(session["id"])
            session["context_vis"] = {
                "generated": bool(model and model.get("units")),
                "revision": int((model or {}).get("revision", 0)),
                "unit_count": len((model or {}).get("units", [])),
            }
        return {"sessions": sessions}
    finally:
        repo.close(); db.close()


@router.get("/sessions/{session_id}")
def get_context_session(session_id: str, profile: str | None = None):
    _, sid, db, repo, adapter = _resources(profile, session_id)
    try:
        service = ContextVisService(adapter, repo)
        model, transcript, _ = service.load()
        active = adapter.get_active_context()
        events = adapter.get_compression_events()
        return {
            "session_id": sid,
            "survival_stale": service.survival_is_stale(model),
            "capabilities": {
                "tier": adapter.tier,
                "compression_events": bool(events),
                "compression_fidelity": (
                    events[-1].fidelity if events else (active.fidelity if active else None)
                ),
                "preserve": bool(getattr(adapter, "preserve_supported", False)),
            },
            "model": model.to_dict(),
            "transcript": [t.__dict__ for t in transcript],
        }
    finally:
        repo.close(); db.close()


def _run_job(home: Path, session_id: str, job_id: str, request: dict[str, Any]) -> None:
    repo = ContextVisRepository(home)
    db = SessionDB(db_path=home / "state.db")
    try:
        repo.update_job(job_id, "running")
        service = ContextVisService(HermesContextAdapter(db, session_id, home), repo)
        action = request["action"]
        if action == "generate_units":
            result = service.generate_units(bool(request.get("incremental")))
        elif action == "detect_salient":
            result = service.detect_salient()
        elif action == "draft_aggregates":
            result = service.draft_aggregates(request.get("mode") or "overview", request.get("intent"))
        elif action == "refresh_survival":
            result = service.refresh_survival()
        else:
            raise ValueError(f"Unsupported action: {action}")
        repo.update_job(job_id, "succeeded", result={"model": result})
    except Exception as exc:
        repo.update_job(job_id, "failed", error=str(exc))
    finally:
        db.close(); repo.close()


@router.post("/sessions/{session_id}/jobs", status_code=202)
def create_context_job(session_id: str, body: JobRequest, profile: str | None = None):
    if body.action not in {"generate_units", "detect_salient", "draft_aggregates", "refresh_survival"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
    home, sid, db, repo, _ = _resources(profile, session_id)
    job_id = f"cvjob-{uuid.uuid4().hex}"
    request = body.model_dump()
    try:
        repo.create_job(job_id, sid, body.action, request)
    except RuntimeError as exc:
        if str(exc) == "job_conflict":
            raise HTTPException(status_code=409, detail="An equivalent job is already running")
        raise
    finally:
        repo.close(); db.close()
    _EXECUTOR.submit(_run_job, home, sid, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
def get_context_job(job_id: str, profile: str | None = None):
    home = _home(profile)
    _ensure_recovered(home)
    repo = ContextVisRepository(home)
    try:
        job = repo.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    finally:
        repo.close()


@router.put("/sessions/{session_id}/model")
def edit_context_model(session_id: str, body: EditRequest, profile: str | None = None):
    _, _, db, repo, adapter = _resources(profile, session_id)
    try:
        payload = body.model_dump(exclude_none=True)
        payload.pop("revision", None)
        try:
            model = ContextVisService(adapter, repo).save_edits(payload, body.revision)
        except RuntimeError as exc:
            if str(exc) == "revision_conflict":
                raise HTTPException(status_code=409, detail="Model was edited elsewhere; reload and retry")
            raise
        return {"model": model}
    finally:
        repo.close(); db.close()
