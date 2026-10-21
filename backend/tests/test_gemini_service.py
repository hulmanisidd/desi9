import asyncio
from types import SimpleNamespace

import pytest

from services import gemini_service as gs
from services.gemini_service import (
    extract_clothing_metadata as real_extract,
    recommend_outfits as real_recommend,
)  # imported at module load, before the autouse fixture patches the module


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(parsed=item)


def install_fake_client(monkeypatch, responses):
    models = FakeModels(responses)
    monkeypatch.setattr(
        gs, "_get_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=models))
    )
    return models


class Fake429(Exception):
    code = 429


def test_extract_returns_plain_dict(monkeypatch):
    parsed = gs.ClothingMetadata(
        category="top", sub_category="polo", color="navy", fabric="cotton"
    )
    install_fake_client(monkeypatch, [parsed])
    result = asyncio.run(real_extract(b"img", "image/png"))
    assert result == {
        "category": "top", "sub_category": "polo", "color": "navy", "fabric": "cotton",
    }


def test_extract_raises_when_unparsable(monkeypatch):
    install_fake_client(monkeypatch, [None])
    with pytest.raises(ValueError):
        asyncio.run(real_extract(b"img", "image/png"))


def test_extract_retries_on_429(monkeypatch):
    async def fake_sleep(_):
        pass

    monkeypatch.setattr(gs.asyncio, "sleep", fake_sleep)
    parsed = gs.ClothingMetadata(
        category="bottom", sub_category="jeans", color="blue", fabric="denim"
    )
    models = install_fake_client(monkeypatch, [Fake429("slow down"), parsed])
    result = asyncio.run(real_extract(b"img", "image/png"))
    assert result["sub_category"] == "jeans"
    assert models.calls == 2


def test_recommend_drops_outfits_with_invented_ids(monkeypatch):
    parsed = gs.OutfitList(
        outfits=[
            gs.Outfit(name="Good", item_ids=["a", "b"], occasion="work", reasoning="ok"),
            gs.Outfit(name="Bad", item_ids=["a", "ghost"], occasion="work", reasoning="no"),
        ]
    )
    install_fake_client(monkeypatch, [parsed])
    items = [
        {"item_id": i, "category": "top", "sub_category": "x", "color": "red", "fabric": "y"}
        for i in ("a", "b")
    ]
    outfits = asyncio.run(real_recommend(items))
    assert [o["name"] for o in outfits] == ["Good"]