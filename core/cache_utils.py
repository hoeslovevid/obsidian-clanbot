"""
Simple TTL cache for expensive API calls (Warframe, leaderboards).
"""
import asyncio
import time
from typing import Any, Optional, Callable, Awaitable, TypeVar

T = TypeVar("T")

# In-memory cache: key -> (value, expiry_timestamp)
_cache: dict[str, tuple[Any, float]] = {}
_lock = asyncio.Lock()


async def get_cached(key: str, ttl_seconds: float, fetch: Callable[[], Awaitable[T]]) -> T:
    """Get value from cache or fetch and cache it. Thread-safe."""
    async with _lock:
        now = time.monotonic()
        if key in _cache:
            val, expiry = _cache[key]
            if now < expiry:
                return val
            del _cache[key]
    val = await fetch()
    async with _lock:
        _cache[key] = (val, time.monotonic() + ttl_seconds)
    return val


def cache_stats() -> str:
    """Short summary for /admin health."""
    return f"{len(_cache)} API entries"


def warframe_health_line() -> tuple[str, bool]:
    """User-facing Warframe API status for ``/status``. Returns (line, is_degraded)."""
    try:
        from api.warframe_api import warframe_api_health
        return warframe_api_health()
    except Exception:
        return "Warframe API: **operational** (health probe unavailable)", False


def invalidate(key_prefix: str = "") -> int:
    """Invalidate cache entries matching prefix. Returns count removed."""
    global _cache
    if not key_prefix:
        n = len(_cache)
        _cache.clear()
        return n
    to_remove = [k for k in _cache if k.startswith(key_prefix)]
    for k in to_remove:
        del _cache[k]
    return len(to_remove)
