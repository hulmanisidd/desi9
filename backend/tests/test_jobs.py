import asyncio
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from main import app
from services import db_service, task_queue

client = TestClient(app)


def headers(sub: str = "user-1") -> dict:
    token = jwt.encode(
        {"sub": sub, "exp": int(time.time()) + 3600}, "test-secret", algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


PNG = {"file": ("test.png", b"fake-bytes", "image/png")}

QUEUE_ENDPOINTS = [
    ("/api/v1/wardrobe/upload", {"files": PNG}),
    ("/api/v1/user/upload-baseline", {"files": PNG}),
    ("/api/v1/outfits/recommend", {}),
    ("/api/v1/vton/generate", {"json": {"item_ids": ["a"]}}),
]
PLACEHOLDER_ENDPOINTS = [
    ("/api/v1/user/upload-baseline", {"files": PNG}),
    ("/api/v1/vton/generate", {"json": {"item_ids": ["a"]}}),
]

@pytest.mark.parametrize("path,kwargs", PLACEHOLDER_ENDPOINTS)
def test_endpoint_queues_job_that_completes(path, kwargs):
    res = client.post(path, headers=headers(), **kwargs)
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # TestClient runs background tasks before returning, so the job is done
    status = client.get(f"/api/v1/jobs/status/{job_id}", headers=headers())
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "completed"
    assert body["result_url"].startswith("https://")
    assert body["metadata"] is not None


def test_status_reflects_lifecycle():
    job_id = db_service.create_job("test", "user-1")
    get = lambda: client.get(f"/api/v1/jobs/status/{job_id}", headers=headers()).json()

    assert get()["status"] == "queued"
    db_service.update_job(job_id, status="processing")
    assert get()["status"] == "processing"


def test_unknown_job_returns_404():
    res = client.get("/api/v1/jobs/status/job-nope", headers=headers())
    assert res.status_code == 404


def test_cannot_read_another_users_job():
    job_id = db_service.create_job("test", "user-1")
    res = client.get(f"/api/v1/jobs/status/{job_id}", headers=headers("user-2"))
    assert res.status_code == 404


def test_failed_task_is_recorded():
    async def boom():
        raise RuntimeError("boom")

    job_id = db_service.create_job("test", "user-1")
    asyncio.run(task_queue.run_job(job_id, boom))

    body = client.get(f"/api/v1/jobs/status/{job_id}", headers=headers()).json()
    assert body["status"] == "failed"
    assert body["error"] == "boom"


def test_blocking_function_is_supported():
    def blocking():
        return {"result_url": "https://x/y.png", "metadata": {"a": 1}}

    job_id = db_service.create_job("test", "user-1")
    asyncio.run(task_queue.run_job(job_id, blocking))

    body = client.get(f"/api/v1/jobs/status/{job_id}", headers=headers()).json()
    assert body["status"] == "completed"
    assert body["metadata"] == {"a": 1}