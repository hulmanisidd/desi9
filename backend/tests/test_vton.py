import io
import time

import jwt
from fastapi.testclient import TestClient
from PIL import Image

from main import app
from services import db_service, gemini_service, vton_service

client = TestClient(app)


def headers(sub="user-1"):
    token = jwt.encode(
        {"sub": sub, "exp": int(time.time()) + 3600}, "test-secret", algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


def png(color=(200, 30, 30), size=(200, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def job(job_id, sub="user-1"):
    return client.get(f"/api/v1/jobs/status/{job_id}", headers=headers(sub)).json()


def upload_baseline(sub="user-1"):
    res = client.post(
        "/api/v1/user/upload-baseline", headers=headers(sub),
        files={"file": ("me.png", png((120, 120, 120), (400, 800)), "image/png")},
    )
    assert res.status_code == 200
    return job(res.json()["job_id"], sub)


def upload_item(monkeypatch, category, sub="user-1") -> str:
    async def fake(image_bytes, mime_type):
        return {"category": category, "sub_category": "x", "color": "red", "fabric": "cotton"}

    monkeypatch.setattr(gemini_service, "extract_clothing_metadata", fake)
    res = client.post(
        "/api/v1/wardrobe/upload", headers=headers(sub),
        files={"file": ("a.png", png(), "image/png")},
    )
    return job(res.json()["job_id"], sub)["metadata"]["item_id"]


def generate(item_ids, sub="user-1"):
    return client.post(
        "/api/v1/vton/generate", headers=headers(sub), json={"item_ids": item_ids}
    )


def test_baseline_is_saved_for_user():
    result = upload_baseline()
    assert result["status"] == "completed"
    user = db_service.get_user("user-1")
    assert user["baseline_url"] == result["result_url"]


def test_baseline_rejects_non_image():
    res = client.post(
        "/api/v1/user/upload-baseline", headers=headers(),
        files={"file": ("a.txt", b"hi", "text/plain")},
    )
    assert res.status_code == 415


def test_generate_requires_baseline(monkeypatch):
    item_id = upload_item(monkeypatch, "top")
    assert generate([item_id]).status_code == 400


def test_generate_unknown_item_is_404():
    upload_baseline()
    assert generate(["nope"]).status_code == 404


def test_generate_cannot_use_another_users_item(monkeypatch):
    item_id = upload_item(monkeypatch, "top", sub="user-1")
    upload_baseline("user-2")
    assert generate([item_id], sub="user-2").status_code == 404


def test_renders_top_first_then_bottom(monkeypatch):
    bottom_id = upload_item(monkeypatch, "bottom")
    top_id = upload_item(monkeypatch, "top")
    upload_baseline()

    res = generate([bottom_id, top_id])  # sent in the "wrong" order on purpose
    assert res.status_code == 200
    result = job(res.json()["job_id"])

    assert result["status"] == "completed"
    steps = result["metadata"]["steps"]
    assert [s["category"] for s in steps] == ["top", "bottom"]
    assert steps[0]["image_url"] != steps[1]["image_url"]
    assert result["result_url"] == steps[-1]["image_url"]


def test_duplicate_item_ids_render_once(monkeypatch):
    top_id = upload_item(monkeypatch, "top")
    upload_baseline()
    result = job(generate([top_id, top_id]).json()["job_id"])
    assert len(result["metadata"]["steps"]) == 1


def test_render_failure_marks_job_failed(monkeypatch):
    top_id = upload_item(monkeypatch, "top")
    upload_baseline()

    def boom(*args):
        raise RuntimeError("gpu on fire")

    monkeypatch.setattr(vton_service, "render_garment", boom)
    result = job(generate([top_id]).json()["job_id"])
    assert result["status"] == "failed"
    assert "gpu on fire" in result["error"]


def test_mock_render_keeps_baseline_size():
    baseline = png((120, 120, 120), (400, 800))
    out = vton_service.render_garment(baseline, png(), "top")
    assert Image.open(io.BytesIO(out)).size == (400, 800)