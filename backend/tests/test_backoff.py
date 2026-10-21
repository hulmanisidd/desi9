import asyncio
import time

import pytest

from services import gemini_service as gs


class Fake429(Exception):
    code = 429


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []

    async def fake_sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(gs.asyncio, "sleep", fake_sleep)
    return recorded


def fast_limiter():
    return gs.RateLimiter(max_calls=1000, period=60)


def test_retries_then_succeeds(sleeps):
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Fake429("rate limited")
        return "ok"

    result = asyncio.run(gs.call_with_backoff(flaky, limiter=fast_limiter()))
    assert result == "ok"
    assert attempts["n"] == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]  # delays grow exponentially


def test_gives_up_after_max_retries(sleeps):
    attempts = {"n": 0}

    async def always_429():
        attempts["n"] += 1
        raise Fake429("rate limited")

    with pytest.raises(Fake429):
        asyncio.run(gs.call_with_backoff(always_429, max_retries=2, limiter=fast_limiter()))
    assert attempts["n"] == 3


def test_does_not_retry_other_errors(sleeps):
    attempts = {"n": 0}

    async def bad_input():
        attempts["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        asyncio.run(gs.call_with_backoff(bad_input, limiter=fast_limiter()))
    assert attempts["n"] == 1
    assert sleeps == []


def test_rate_limiter_delays_excess_calls():
    limiter = gs.RateLimiter(max_calls=2, period=0.3)

    async def burst():
        for _ in range(3):
            await limiter.acquire()

    start = time.monotonic()
    asyncio.run(burst())
    assert time.monotonic() - start >= 0.25