"""
Simple TTL cache for expensive API calls (Warframe, leaderboards).

Supports stale-while-revalidate and singleflight so slash commands return
cached data immediately while a background refresh runs.
"""
import asyncio
import logging
import time
from typing import Any, Callable, Awaitable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

# key -> (value, expiry_monotonic)
_cache: dict[str, tuple[Any, float]] = {}
# key -> monotonic time when value was last fetched successfully
_fetched_at: dict[str, float] = {}
# key -> in-flight fetch task (singleflight)
_inflight: dict[str, asyncio.Task[Any]] = {}
_lock = asyncio.Lock()


async def _store(key: str, val: Any, ttl_seconds: float) -> None:
    now = time.monotonic()
    async with _lock:
        _cache[key] = (val, now + ttl_seconds)
        _fetched_at[key] = now


async def _run_fetch(key: str, ttl_seconds: float, fetch: Callable[[], Awaitable[T]]) -> T:
    try:
        val = await fetch()
        await _store(key, val, ttl_seconds)
        return val
    finally:
        async with _lock:
            _inflight.pop(key, None)


def _start_fetch_task(key: str, ttl_seconds: float, fetch: Callable[[], Awaitable[Any]]) -> asyncio.Task[Any]:
    task = asyncio.create_task(_run_fetch(key, ttl_seconds, fetch))
    _inflight[key] = task
    return task


async def get_cached(
    key: str,
    ttl_seconds: float,
    fetch: Callable[[], Awaitable[T]],
    *,
    stale_seconds: float = 0,
) -> T:
    """Get value from cache or fetch and cache it.

    When ``stale_seconds`` > 0, return the last good value immediately if it is
    younger than ``stale_seconds`` even after TTL expiry, and refresh in the
    background. Concurrent callers coalesce on a single in-flight fetch.
    """
    task_to_await: asyncio.Task[Any] | None = None

    async with _lock:
        now = time.monotonic()
        if key in _cache:
            val, expiry = _cache[key]
            if now < expiry:
                return val
            fetched = _fetched_at.get(key, 0)
            if stale_seconds > 0 and (now - fetched) < stale_seconds:
                if key not in _inflight or _inflight[key].done():
                    _start_fetch_task(key, ttl_seconds, fetch)
                # #region agent log
                if key.startswith("warframe:"):
                    try:
                        import json
                        from pathlib import Path

                        _p = Path(__file__).resolve().parent.parent / "debug-42c590.log"
                        with _p.open("a", encoding="utf-8") as _f:
                            _f.write(
                                json.dumps(
                                    {
                                        "sessionId": "42c590",
                                        "runId": "cache",
                                        "hypothesisId": "H-cache-stale",
                                        "location": "core/cache_utils.py:get_cached",
                                        "message": "stale-while-revalidate hit",
                                        "data": {"key": key, "age_s": round(now - fetched, 1)},
                                        "timestamp": int(time.time() * 1000),
                                    }
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                # #endregion
                return val
            del _cache[key]

        if key in _inflight:
            task_to_await = _inflight[key]
        else:
            task_to_await = _start_fetch_task(key, ttl_seconds, fetch)

    return await task_to_await


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
        _fetched_at.clear()
        for task in _inflight.values():
            if not task.done():
                task.cancel()
        _inflight.clear()
        return n
    to_remove = [k for k in _cache if k.startswith(key_prefix)]
    for k in to_remove:
        del _cache[k]
        _fetched_at.pop(k, None)
        task = _inflight.pop(k, None)
        if task and not task.done():
            task.cancel()
    return len(to_remove)
