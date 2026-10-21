import threading
from datetime import datetime, timezone
from uuid import uuid4

# In-memory job store. Swap for PostgreSQL in the database step;
# keep these function signatures and the routes won't need to change.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_type: str, user_id: str) -> str:
    job_id = f"job-{uuid4().hex[:8]}"
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "job_type": job_type,
            "user_id": user_id,
            "status": "queued",
            "result_url": None,
            "metadata": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
    return job_id


def update_job(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)
            _jobs[job_id]["updated_at"] = _now()


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None