import hashlib
import threading
from datetime import datetime, timezone
from uuid import uuid4

# In-memory stores. Step 3 swaps these for PostgreSQL; keep the signatures.
_jobs: dict[str, dict] = {}
_wardrobe: dict[str, dict[str, dict]] = {}  # user_id -> item_id -> item
_outfit_cache: dict[str, dict] = {}  # user_id -> {"version", "outfits"}
_lock = threading.Lock()
_users: dict[str, dict] = {}  # user_id -> {"user_id", "baseline_url", "pose_maps"}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Jobs ----------

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

def fail_stale_jobs() -> int:
    """Mirrors the Postgres version. In memory, jobs never outlive the server,
    so there is nothing to clean up at startup."""
    return 0
# ---------- Wardrobe ----------

def add_wardrobe_item(user_id: str, item: dict) -> None:
    with _lock:
        _wardrobe.setdefault(user_id, {})[item["item_id"]] = item


def list_wardrobe_items(user_id: str) -> list[dict]:
    with _lock:
        return [dict(i) for i in _wardrobe.get(user_id, {}).values()]

def get_wardrobe_item(user_id: str, item_id: str) -> dict | None:
    with _lock:
        item = _wardrobe.get(user_id, {}).get(item_id)
        return dict(item) if item else None


def set_baseline(user_id: str, baseline_url: str, pose_maps: dict) -> None:
    with _lock:
        _users[user_id] = {
            "user_id": user_id, "baseline_url": baseline_url, "pose_maps": pose_maps,
        }


def get_user(user_id: str) -> dict | None:
    with _lock:
        user = _users.get(user_id)
        return dict(user) if user else None

def version_of(items: list[dict]) -> str:
    """Fingerprint of a wardrobe: changes whenever an item is added or removed."""
    ids = ",".join(sorted(i["item_id"] for i in items))
    return hashlib.sha256(ids.encode()).hexdigest()


# ---------- Outfit cache ----------

def get_cached_outfits(user_id: str) -> list[dict] | None:
    """Returns cached outfits only if the wardrobe hasn't changed since."""
    items = list_wardrobe_items(user_id)
    with _lock:
        cached = _outfit_cache.get(user_id)
    if cached and cached["version"] == version_of(items):
        return cached["outfits"]
    return None


def set_cached_outfits(user_id: str, outfits: list[dict], version: str) -> None:
    with _lock:
        _outfit_cache[user_id] = {"version": version, "outfits": outfits}


def reset_all() -> None:
    """For tests."""
    with _lock:
        _jobs.clear()
        _wardrobe.clear()
        _outfit_cache.clear()
        _users.clear()