"""Database connection pooling and caching utilities for performance optimization."""
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import aiosqlite
from database import DB_PATH

logger = None
try:
    import logging
    logger = logging.getLogger(__name__)
except:
    pass

# Connection pool (simple approach - reuse connections)
_db_pool: Optional[aiosqlite.Connection] = None
_pool_lock = asyncio.Lock()

# Cache for frequently accessed data
_settings_cache: Dict[int, Dict[str, Any]] = {}
_cache_timestamps: Dict[str, datetime] = {}
CACHE_TTL = timedelta(minutes=5)  # Cache for 5 minutes


async def get_db_connection() -> aiosqlite.Connection:
    """Get a database connection (reuse if available, otherwise create new)."""
    global _db_pool
    
    async with _pool_lock:
        if _db_pool is None:
            _db_pool = await aiosqlite.connect(DB_PATH)
            _db_pool.row_factory = aiosqlite.Row
        return _db_pool


async def close_db_pool():
    """Close the database connection pool."""
    global _db_pool
    async with _pool_lock:
        if _db_pool:
            await _db_pool.close()
            _db_pool = None


def _is_cache_valid(cache_key: str) -> bool:
    """Check if cache entry is still valid."""
    if cache_key not in _cache_timestamps:
        return False
    return datetime.now() - _cache_timestamps[cache_key] < CACHE_TTL


def _invalidate_cache(cache_key: Optional[str] = None):
    """Invalidate cache entry or all cache if key is None."""
    if cache_key:
        _settings_cache.pop(cache_key, None)
        _cache_timestamps.pop(cache_key, None)
    else:
        _settings_cache.clear()
        _cache_timestamps.clear()


async def get_cached_setting(guild_id: int, key: str) -> Optional[Any]:
    """Get a cached guild setting."""
    cache_key = f"{guild_id}:{key}"
    
    if _is_cache_valid(cache_key):
        return _settings_cache.get(cache_key)
    
    # Fetch from database
    from database import get_guild_setting
    value = await get_guild_setting(guild_id, key)
    
    # Cache it
    _settings_cache[cache_key] = value
    _cache_timestamps[cache_key] = datetime.now()
    
    return value


async def set_cached_setting(guild_id: int, key: str, value: Any):
    """Set a guild setting and update cache."""
    from database import set_guild_setting
    await set_guild_setting(guild_id, key, value)
    
    # Update cache
    cache_key = f"{guild_id}:{key}"
    _settings_cache[cache_key] = value
    _cache_timestamps[cache_key] = datetime.now()
