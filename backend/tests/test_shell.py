import os
import time

os.environ["JWT_SECRET"] = "test-secret"

import jwt
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def make_token(secret: str = "test-secret", exp_offset: int = 3600) -> str:
    return jwt.encode(
        {"sub": "user-1", "exp": int(time.time()) + exp_offset},
        secret,
        algorithm="HS256",
    )


def auth_header(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or make_token()}"}


PNG = {"file": ("test.png", b"fake-bytes", "image/png")}

# (method, path, kwargs for the request, expected status, expected message)
QUEUE_ENDPOINTS = [
    ("post", "/api/v1/wardrobe/upload", {"files": PNG}, "queued"),
    ("post", "/api/v1/user/upload-baseline", {"files": PNG}, "queued"),
    ("post", "/api/v1/outfits/recommend", {}, "queued"),
]
# Auth tests also cover VTON and jobs; VTON behavior is in test_vton.py
ENDPOINTS = QUEUE_ENDPOINTS + [
    ("post", "/api/v1/vton/generate", {"json": {"item_ids": ["a", "b"]}}, "queued"),
    ("get", "/api/v1/jobs/status/job-1234", {}, "completed"),
]


def test_health_is_public():
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("method,path,kwargs,_", ENDPOINTS)
def test_requires_token(method, path, kwargs, _):
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 401


@pytest.mark.parametrize("method,path,kwargs,_", ENDPOINTS)
def test_rejects_bad_signature(method, path, kwargs, _):
    headers = auth_header(make_token(secret="wrong-secret"))
    res = getattr(client, method)(path, headers=headers, **kwargs)
    assert res.status_code == 401


def test_rejects_expired_token():
    headers = auth_header(make_token(exp_offset=-10))
    res = client.post("/api/v1/outfits/recommend", headers=headers)
    assert res.status_code == 401


@pytest.mark.parametrize("method,path,kwargs,expected_status", QUEUE_ENDPOINTS)
def test_valid_token_returns_contract_shape(method, path, kwargs, expected_status):
    res = getattr(client, method)(path, headers=auth_header(), **kwargs)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == expected_status
    if expected_status == "queued":
        assert body["job_id"].startswith("job-")
        assert "message" in body
    else:
        assert "result_url" in body and "metadata" in body


def test_vton_requires_item_ids():
    res = client.post("/api/v1/vton/generate", headers=auth_header(), json={})
    assert res.status_code == 422


def test_cors_preflight_allows_local_frontend():
    res = client.options(
        "/api/v1/outfits/recommend",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5500"