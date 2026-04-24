"""Small async TTL cache for external service health checks."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

HealthResult = dict[str, Any]

_TTL_SECONDS = 5.0
_cache: dict[str, tuple[float, HealthResult]] = {}
_locks: dict[tuple[str, int], asyncio.Lock] = {}


async def cached_health(name: str, probe: Callable[[], Awaitable[HealthResult]]) -> HealthResult:
    """Return cached health result for a short TTL to avoid probe storms."""
    now = time.monotonic()
    cached = _cache.get(name)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]

    loop = asyncio.get_running_loop()
    lock = _locks.setdefault((name, id(loop)), asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _cache.get(name)
        if cached and now - cached[0] < _TTL_SECONDS:
            return cached[1]

        result = await probe()
        _cache[name] = (time.monotonic(), result)
        return result
