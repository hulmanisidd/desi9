import os
import tempfile
os.environ["DATABASE_URL"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret"
os.environ["STUB_TASK_DELAY"] = "0"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()

import pytest

from services import db_service, gemini_service


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    db_service.reset_all()

    async def fake_extract(image_bytes, mime_type):
        return {
            "category": "top",
            "sub_category": "t-shirt",
            "color": "navy",
            "fabric": "cotton",
        }

    async def fake_recommend(items):
        ids = [i["item_id"] for i in items]
        return [
            {
                "name": "Test look",
                "item_ids": ids[:2],
                "occasion": "casual",
                "reasoning": "Looks good together.",
            }
        ]

    monkeypatch.setattr(gemini_service, "extract_clothing_metadata", fake_extract)
    monkeypatch.setattr(gemini_service, "recommend_outfits", fake_recommend)