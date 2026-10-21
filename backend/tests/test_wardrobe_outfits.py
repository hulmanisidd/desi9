import time

import jwt
from fastapi.testclient import TestClient

from main import app
from services import db_service, gemini_service

client = TestClient(app)
PNG = ("test.png", b"fake-bytes", "image/png")


def headers(sub="user-1"):
    token = jwt.encode(
        {"sub": sub, "exp": int(time.time()) + 3600}, "test-secret", algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


def job_result(job_id, sub="user-1"):
    return client.get(f"/api/v1/jobs/status/{job_id}", headers=headers(sub)).json()


def upload_item(sub="user-1"):
    res = client.post("/api/v1/wardrobe/upload", headers=headers(sub), files={"file": PNG})
    assert res.status_code == 200
    return job_result(res.json()["job_id"], sub)


def recommend(sub="user-1"):
    res = client.post("/api/v1/outfits/recommend", headers=headers(sub))
    assert res.status_code == 200
    return job_result(res.json()["job_id"], sub)


def test_upload_tags_and_stores_item():
    job = upload_item()
    assert job["status"] == "completed"
    assert job["metadata"]["category"] == "top"
    assert job["metadata"]["item_id"] in job["result_url"]
    assert len(db_service.list_wardrobe_items("user-1")) == 1


def test_upload_rejects_non_image():
    res = client.post(
        "/api/v1/wardrobe/upload", headers=headers(),
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 415


def test_upload_rejects_empty_file():
    res = client.post(
        "/api/v1/wardrobe/upload", headers=headers(),
        files={"file": ("a.png", b"", "image/png")},
    )
    assert res.status_code == 400


def test_failed_tagging_marks_job_failed_and_stores_nothing(monkeypatch):
    async def boom(image_bytes, mime_type):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(gemini_service, "extract_clothing_metadata", boom)
    job = upload_item()
    assert job["status"] == "failed"
    assert "gemini down" in job["error"]
    assert db_service.list_wardrobe_items("user-1") == []


def test_recommend_needs_two_items():
    upload_item()
    job = recommend()
    assert job["status"] == "failed"
    assert "at least 2" in job["error"]


def test_recommend_returns_outfits_with_item_details():
    upload_item()
    upload_item()
    job = recommend()
    assert job["status"] == "completed"
    outfit = job["metadata"]["outfits"][0]
    assert outfit["name"] == "Test look"
    assert all("image_url" in i for i in outfit["items"])


def test_recommend_caches_until_wardrobe_changes(monkeypatch):
    calls = {"n": 0}

    async def counting(items):
        calls["n"] += 1
        return [{"name": "L", "item_ids": [items[0]["item_id"]],
                 "occasion": "x", "reasoning": "y"}]

    monkeypatch.setattr(gemini_service, "recommend_outfits", counting)
    upload_item()
    upload_item()

    assert recommend()["metadata"]["cached"] is False
    assert recommend()["metadata"]["cached"] is True
    assert calls["n"] == 1

    upload_item()  # wardrobe changed
    assert recommend()["metadata"]["cached"] is False
    assert calls["n"] == 2


def test_wardrobes_are_per_user():
    upload_item("user-1")
    assert db_service.list_wardrobe_items("user-2") == []
    assert recommend("user-2")["status"] == "failed"