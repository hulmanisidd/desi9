import io
import os
import time
import httpx
from PIL import Image

_rembg_session = None


def _provider() -> str:
    return os.getenv("VTON_PROVIDER", "mock")


# ---------- Background removal (real, CPU) ----------

def remove_background(data: bytes) -> bytes:
    """Returns a transparent PNG. Blocking; call via asyncio.to_thread."""
    global _rembg_session
    from rembg import new_session, remove

    if _rembg_session is None:
        _rembg_session = new_session(os.getenv("REMBG_MODEL", "u2net"))
    return remove(data, session=_rembg_session)


# ---------- Pose extraction ----------
# ---------- Remote GPU provider ----------

# OOTDiffusion supports upper body, lower body and full dresses only
OOTD_CATEGORY = {
    "top": "upperbody",
    "outerwear": "upperbody",
    "bottom": "lowerbody",
    "dress": "dress",
}
RETRY_STATUSES = {502, 503, 504}


def _make_client() -> httpx.Client:
    timeout = httpx.Timeout(float(os.getenv("VTON_REMOTE_TIMEOUT", "300")), connect=10.0)
    return httpx.Client(timeout=timeout)


def _remote_render(baseline: bytes, garment: bytes, category: str, retries: int = 2) -> bytes:
    mapped = OOTD_CATEGORY.get(category)
    if mapped is None:
        return baseline  # unsupported by OOTDiffusion: skip, keep the image as is

    base_url = os.getenv("VTON_REMOTE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("VTON_REMOTE_URL is not set")

    headers = {
        "X-API-Key": os.getenv("VTON_REMOTE_KEY", ""),
        "ngrok-skip-browser-warning": "true",  # free ngrok tunnels otherwise return an HTML page
    }
    files = {
        "baseline": ("baseline.png", baseline, "image/png"),
        "garment": ("garment.png", garment, "image/png"),
    }

    last_error = "unknown error"
    with _make_client() as client:
        for attempt in range(retries + 1):
            try:
                res = client.post(
                    f"{base_url}/tryon", headers=headers, files=files, data={"category": mapped}
                )
            except (httpx.ConnectError, httpx.ConnectTimeout):
                last_error = "could not reach the GPU server (is it running?)"
            except httpx.ReadTimeout:
                # Not retried: the render may still be running and a retry would double the wait
                raise RuntimeError("GPU server took too long to respond")
            else:
                if res.status_code in (401, 403):
                    raise RuntimeError("GPU server rejected the API key (check VTON_REMOTE_KEY)")
                if res.status_code in RETRY_STATUSES:
                    last_error = f"GPU server unavailable (HTTP {res.status_code})"
                elif res.status_code != 200:
                    raise RuntimeError(
                        f"GPU server error (HTTP {res.status_code}): {res.text[:200]}"
                    )
                elif not res.content.startswith(b"\x89PNG"):
                    raise RuntimeError("GPU server did not return a PNG image")
                else:
                    return res.content

            if attempt < retries:
                time.sleep(2**attempt)  # 1s, then 2s

    raise RuntimeError(f"Remote try-on failed after {retries + 1} attempts: {last_error}")


# ---------- Pose extraction ----------

def extract_pose_maps(image_bytes: bytes) -> dict:
    provider = _provider()
    if provider == "mock":
        return {"provider": "mock"}
    if provider == "remote":
        # The GPU server computes pose/parsing per request, so there is nothing to store yet
        return {"provider": "remote"}
    raise ValueError(f"Unknown VTON_PROVIDER: {provider}")


# ---------- Garment rendering ----------

def render_garment(baseline: bytes, garment: bytes, category: str) -> bytes:
    """Renders one garment onto the baseline and returns PNG bytes."""
    provider = _provider()
    if provider == "mock":
        return _mock_render(baseline, garment, category)
    if provider == "remote":
        return _remote_render(baseline, garment, category)
    raise ValueError(f"Unknown VTON_PROVIDER: {provider}")


# ---------- Garment rendering ----------

# Where each category lands on the baseline: (left, top, right, bottom) as fractions
REGIONS = {
    "top": (0.22, 0.17, 0.78, 0.55),
    "outerwear": (0.18, 0.17, 0.82, 0.62),
    "dress": (0.22, 0.17, 0.78, 0.80),
    "bottom": (0.28, 0.50, 0.72, 0.95),
    "footwear": (0.28, 0.90, 0.72, 1.00),
    "accessory": (0.40, 0.05, 0.60, 0.15),
}


def _mock_render(baseline: bytes, garment: bytes, category: str) -> bytes:
    """Pastes the cut-out garment onto the baseline. Not a real try-on."""
    base = Image.open(io.BytesIO(baseline)).convert("RGBA")
    g = Image.open(io.BytesIO(garment)).convert("RGBA")
    bbox = g.getbbox()
    if bbox:
        g = g.crop(bbox)

    left, top, right, bottom = REGIONS.get(category, REGIONS["top"])
    w, h = base.size
    box_w, box_h = max(1, int((right - left) * w)), max(1, int((bottom - top) * h))
    scale = min(box_w / g.width, box_h / g.height)
    g = g.resize((max(1, int(g.width * scale)), max(1, int(g.height * scale))))

    x = int(left * w) + (box_w - g.width) // 2
    y = int(top * h)
    base.alpha_composite(g, (x, y))

    out = io.BytesIO()
    base.save(out, "PNG")
    return out.getvalue()


