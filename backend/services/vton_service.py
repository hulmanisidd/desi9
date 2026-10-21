import io
import os

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

def extract_pose_maps(image_bytes: bytes) -> dict:
    if _provider() == "mock":
        return {"provider": "mock"}
    raise NotImplementedError("Remote pose extraction is not built yet (Module 2.4b)")


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


def render_garment(baseline: bytes, garment: bytes, category: str) -> bytes:
    """Renders one garment onto the baseline and returns PNG bytes.
    Module 2.4b adds a remote OOTDiffusion provider here."""
    if _provider() == "mock":
        return _mock_render(baseline, garment, category)
    raise NotImplementedError("Remote VTON provider is not built yet (Module 2.4b)")