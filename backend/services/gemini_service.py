import asyncio
import json
import os
import random
import time
from collections import deque
from enum import Enum

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()


# ---------- Rate limiting and backoff (from Module 2.2) ----------

class RateLimitError(Exception):
    """Raise this to force a retry with backoff."""


class RateLimiter:
    """Sliding-window limiter. Free tier is ~10 requests per minute."""

    def __init__(self, max_calls: int = 10, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                await asyncio.sleep(self.period - (now - self._calls[0]))


gemini_limiter = RateLimiter(max_calls=10, period=60.0)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 503):
        return True
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "UNAVAILABLE" in text


async def call_with_backoff(
    fn,
    *args,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    limiter: RateLimiter | None = None,
    **kwargs,
):
    """Call an async fn, waiting for the rate limiter and retrying 429/503 errors
    with exponential backoff (1s, 2s, 4s, ... plus jitter)."""
    limiter = limiter or gemini_limiter
    for attempt in range(max_retries + 1):
        await limiter.acquire()
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if not _is_retryable(exc) or attempt == max_retries:
                raise
            delay = min(max_delay, base_delay * 2**attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)


# ---------- Gemini client ----------

_client = None


def _model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


# ---------- Structured output schemas ----------

class Category(str, Enum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    outerwear = "outerwear"
    footwear = "footwear"
    accessory = "accessory"


class ClothingMetadata(BaseModel):
    category: Category
    sub_category: str
    color: str
    fabric: str


class Outfit(BaseModel):
    name: str
    item_ids: list[str]
    occasion: str
    reasoning: str


class OutfitList(BaseModel):
    outfits: list[Outfit]


# ---------- Gemini calls ----------

METADATA_PROMPT = (
    "You are a fashion cataloguing assistant. Look at this photo of a single "
    "clothing item and return: category (top, bottom, dress, outerwear, footwear "
    "or accessory), sub_category (specific, e.g. 't-shirt', 'chinos', 'kurta'), "
    "color (the dominant color as a simple lowercase name, e.g. 'navy'), and "
    "fabric (your best guess, e.g. 'cotton', 'denim', 'wool')."
)


async def extract_clothing_metadata(image_bytes: bytes, mime_type: str) -> dict:
    async def _call():
        return await _get_client().aio.models.generate_content(
            model=_model(),
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                METADATA_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClothingMetadata,
                temperature=0.2,
            ),
        )

    response = await call_with_backoff(_call)
    if response.parsed is None:
        raise ValueError("Gemini returned no parsable clothing metadata")
    return response.parsed.model_dump(mode="json")


async def recommend_outfits(items: list[dict]) -> list[dict]:
    """items: [{"item_id", "category", "sub_category", "color", "fabric", ...}]"""
    catalogue = [
        {k: item[k] for k in ("item_id", "category", "sub_category", "color", "fabric")}
        for item in items
    ]
    prompt = (
        "You are a personal stylist. From ONLY the wardrobe items below, create up "
        "to 5 distinct outfits. Each outfit is either one top plus one bottom, or "
        "one dress, optionally with outerwear and footwear. Use each item's exact "
        "item_id, never invent ids, and give each outfit a short name, an occasion, "
        "and one or two sentences of reasoning about colors and style.\n\n"
        f"Wardrobe:\n{json.dumps(catalogue)}"
    )

    async def _call():
        return await _get_client().aio.models.generate_content(
            model=_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=OutfitList,
                temperature=0.8,
            ),
        )

    response = await call_with_backoff(_call)
    if response.parsed is None:
        raise ValueError("Gemini returned no parsable outfit recommendations")

    valid_ids = {item["item_id"] for item in items}
    outfits = []
    for outfit in response.parsed.outfits:
        # Drop outfits that reference ids Gemini made up
        if outfit.item_ids and all(i in valid_ids for i in outfit.item_ids):
            outfits.append(outfit.model_dump())
    return outfits