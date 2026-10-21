import os
from pathlib import Path
from uuid import uuid4


def upload_dir() -> Path:
    default = Path(__file__).resolve().parent.parent / "uploads"
    path = Path(os.getenv("UPLOAD_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_url(filename: str) -> str:
    base = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    return f"{base}/uploads/{filename}"


def save_upload(data: bytes, mime_type: str, label: str = "item") -> tuple[str, str]:
    """Save bytes under a UUID name (e.g. <uuid>_item.png). Returns (item_id, url).
    Local-disk stand-in; Step 3 swaps this for S3/Supabase with the same signature."""
    ext = ".png" if mime_type == "image/png" else ".jpg"
    item_id = str(uuid4())
    filename = f"{item_id}_{label}{ext}"
    (upload_dir() / filename).write_bytes(data)
    return item_id, public_url(filename)