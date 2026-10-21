import asyncio
import random
import time
from collections import deque


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