import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

_supabase = None


def _use_supabase() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


def _bucket() -> str:
    return os.getenv("SUPABASE_BUCKET", "desi9-images")


def _client():
    global _supabase
    if _supabase is None:
        from supabase import create_client

        _supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _supabase


def upload_dir() -> Path:
    default = Path(__file__).resolve().parent.parent / "uploads"
    path = Path(os.getenv("UPLOAD_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_url(filename: str) -> str:
    base = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    return f"{base}/uploads/{filename}"


def save_upload(data: bytes, mime_type: str, label: str = "item") -> tuple[str, str]:
    """Save bytes under a UUID name (e.g. <uuid>_item.png). Returns (item_id, url).
    Uses Supabase Storage when configured, local disk otherwise."""
    ext = ".png" if mime_type == "image/png" else ".jpg"
    item_id = str(uuid4())
    filename = f"{item_id}_{label}{ext}"

    if _use_supabase():
        bucket = _client().storage.from_(_bucket())
        bucket.upload(path=filename, file=data, file_options={"content-type": mime_type})
        return item_id, bucket.get_public_url(filename).rstrip("?")

    (upload_dir() / filename).write_bytes(data)
    return item_id, _local_url(filename)