"""
Warframe API functions for fetching game data.
This module handles all Warframe World State API calls.
"""
import asyncio
import logging
import os
import time
from typing import Optional, Dict, Any, Tuple, List
import aiohttp  # type: ignore

# Timeout and retries for api.warframestat.us (can be slow or unreachable from some networks)
WARFRAME_STAT_TIMEOUT = 25
WARFRAME_STAT_RETRIES = 3

# Optional proxy for Warframe APIs (e.g. when datacenter IP gets 404)
def _market_proxy() -> Optional[str]:
    return os.environ.get("WARFRAME_MARKET_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None


def _api_proxy() -> Optional[str]:
    """Proxy for api.warframestat.us - reuse same env vars as Warframe Market."""
    return os.environ.get("WARFRAME_STAT_PROXY") or _market_proxy()


import dateparser  # type: ignore
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# Cloudflare/origin errors worth retrying once (523 = Origin Unreachable, 502/503 = Bad Gateway / Unavailable)
_WF_STAT_RETRY_STATUSES = (502, 503, 523)

# When API fails, serve last successful response for up to this many seconds (1 hour)
_WF_STAT_FALLBACK_MAX_AGE = 3600
_wf_stat_fallback: Dict[str, Tuple[Any, float]] = {}  # url -> (data, monotonic_timestamp)
_wf_stat_proxy_logged = False


def _wf_stat_fallback_get(url: str) -> Optional[Any]:
    """Return last known good data for url if still within fallback max age."""
    entry = _wf_stat_fallback.get(url)
    if not entry:
        return None
    data, ts = entry
    age = time.monotonic() - ts
    if age > _WF_STAT_FALLBACK_MAX_AGE:
        return None
    logger.info("Warframe API unavailable for %s; using last known good data (%.0f min old)", url, age / 60)
    return data


async def _wf_stat_get(url: str, proxy: Optional[str]) -> Optional[Any]:
    """GET api.warframestat.us with timeout and retries. Returns parsed JSON or None. Uses fallback cache on failure."""
    if proxy and not _wf_stat_proxy_logged:
        global _wf_stat_proxy_logged
        _wf_stat_proxy_logged = True
        _host = proxy.split("@")[-1].split("/")[0] if "@" in proxy else proxy.split("/")[-1]
        logger.info("Warframe API proxy enabled: %s", _host)
    timeout = aiohttp.ClientTimeout(total=WARFRAME_STAT_TIMEOUT)
    last_exc = None
    for attempt in range(WARFRAME_STAT_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, proxy=proxy) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _wf_stat_fallback[url] = (data, time.monotonic())
                        return data
                    if resp.status in _WF_STAT_RETRY_STATUSES and attempt < WARFRAME_STAT_RETRIES - 1:
                        logger.warning(
                            "Warframe API returned %s (%s) for %s, retrying in 2s...",
                            resp.status,
                            "Origin Unreachable" if resp.status == 523 else "server error",
                            url,
                        )
                        await asyncio.sleep(2)
                        continue
                    logger.info("Warframe API returned status %s for %s (after retries), skipping", resp.status, url)
                    return _wf_stat_fallback_get(url) or None
        except (asyncio.TimeoutError, TimeoutError) as e:
            last_exc = e
            if attempt < WARFRAME_STAT_RETRIES - 1:
                logger.debug("Warframe API timeout for %s, retry %s/%s", url, attempt + 1, WARFRAME_STAT_RETRIES)
                await asyncio.sleep(1)
            else:
                logger.info(
                    "Warframe API timeout for %s after %s attempt(s), skipping",
                    url,
                    WARFRAME_STAT_RETRIES,
                )
                return _wf_stat_fallback_get(url) or None
    if last_exc:
        raise last_exc
    return None


async def fetch_baro_data() -> Optional[Dict[str, Any]]:
    """Fetch Baro Ki'Teer data from Warframe World State API. Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/voidTrader", _api_proxy())
        except Exception as e:
            logger.error("Error fetching Baro data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:baro", 60, _fetch)


async def fetch_cycle_data(cycle_type: str) -> Optional[Dict[str, Any]]:
    """Fetch cycle data from Warframe World State API.
    
    Args:
        cycle_type: One of 'cetus', 'vallis', or 'cambion'
    
    Returns:
        Cycle data dict or None if error
    """
    endpoints = {
        'cetus': 'https://api.warframestat.us/pc/cetusCycle',
        'vallis': 'https://api.warframestat.us/pc/vallisCycle',
        'cambion': 'https://api.warframestat.us/pc/cambionCycle',
    }
    
    if cycle_type not in endpoints:
        return None
    
    try:
        return await _wf_stat_get(endpoints[cycle_type], _api_proxy())
    except Exception as e:
        logger.error("Error fetching %s cycle data: %s: %s", cycle_type, type(e).__name__, e, exc_info=True)
        return None


async def get_all_cycles() -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch all cycle data (Cetus, Fortuna, Deimos). Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        import asyncio
        cetus, vallis, cambion = await asyncio.gather(
            fetch_cycle_data('cetus'),
            fetch_cycle_data('vallis'),
            fetch_cycle_data('cambion'),
        )
        return {'cetus': cetus, 'vallis': vallis, 'cambion': cambion}

    return await get_cached("warframe:cycles", 60, _fetch)


async def get_baro_status() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get current Baro Ki'Teer status.
    Returns (is_active, baro_data)
    """
    data = await fetch_baro_data()
    if not data:
        return (False, None)
    
    # Check if Baro is active
    activation = data.get("activation", "")
    expiry = data.get("expiry", "")
    
    # If we don't have both activation and expiry, Baro is not active
    if not activation or not expiry:
        return (False, data)
    
    try:
        # Parse ISO format timestamps
        activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not activation_time or not expiry_time:
            return (False, data)
        
        now = datetime.now(timezone.utc)
        
        # Baro is active only if:
        # 1. Current time is after activation
        # 2. Current time is before expiry
        # 3. Activation is before expiry (to avoid weird API responses)
        is_active = activation_time <= now < expiry_time and activation_time < expiry_time
        
        return (is_active, data)
    except Exception as e:
        logger.error(f"Error parsing Baro timestamps: {e}")
        return (False, data)


async def fetch_fissures() -> Optional[List[Dict[str, Any]]]:
    """Fetch active Void Fissure missions. Cached 60s."""
    from cache_utils import get_cached
    async def _fetch():
        try:
            data = await _wf_stat_get("https://api.warframestat.us/pc/fissures", _api_proxy())
            return [f for f in data if not f.get("expired", False)] if data else None
        except Exception as e:
            logger.error("Error fetching fissures: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:fissures", 60, _fetch)


async def fetch_sortie() -> Optional[Dict[str, Any]]:
    """Fetch today's Sortie. Cached 60s."""
    from cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/sortie", _api_proxy())
        except Exception as e:
            logger.error("Error fetching sortie: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:sortie", 60, _fetch)


async def fetch_steel_path() -> Optional[Dict[str, Any]]:
    """Fetch Steel Path data (current missions). Cached 60s."""
    from cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/steelPath", _api_proxy())
        except Exception as e:
            logger.error("Error fetching steel path: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:steelPath", 60, _fetch)


async def fetch_arbitration() -> Optional[Dict[str, Any]]:
    """Fetch current Arbitration. Cached 60s."""
    from cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/arbitration", _api_proxy())
        except Exception as e:
            logger.error("Error fetching arbitration: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:arbitration", 60, _fetch)


async def fetch_nightwave() -> Optional[Dict[str, Any]]:
    """Fetch Nightwave challenges. Cached 300s (updates daily)."""
    from cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/nightwave", _api_proxy())
        except Exception as e:
            logger.error("Error fetching nightwave: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:nightwave", 300, _fetch)


async def fetch_invasions() -> Optional[list]:
    """Fetch invasion data from Warframe World State API. Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        try:
            data = await _wf_stat_get("https://api.warframestat.us/pc/invasions", _api_proxy())
            if not data:
                return None
            return [inv for inv in data if inv.get("completed", False) == False]
        except Exception as e:
            logger.error("Error fetching invasion data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:invasions", 60, _fetch)


async def fetch_archon_hunt_data() -> Optional[Dict[str, Any]]:
    """Fetch Archon Hunt data from Warframe World State API. Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/archonHunt?language=en", _api_proxy())
        except Exception as e:
            logger.error("Error fetching archon hunt data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:archon", 60, _fetch)


async def fetch_events_data() -> Optional[List[Dict[str, Any]]]:
    """Fetch active events data from Warframe World State API."""
    try:
        data = await _wf_stat_get("https://api.warframestat.us/pc/events", _api_proxy())
        if not data:
            return None
        return [event for event in data if event.get("expired", False) == False]
    except Exception as e:
        logger.error("Error fetching events data: %s: %s", type(e).__name__, e, exc_info=True)
        return None


def _normalize_item_payload(raw: Dict[str, Any], fallback_url_name: str) -> Optional[Dict[str, Any]]:
    """Extract item_name and url_name from API payload.item (handles different response shapes)."""
    if not raw:
        return None
    # Direct fields (list-style response)
    item_name = raw.get("item_name")
    url_name = raw.get("url_name") or fallback_url_name
    # Nested en (single-item response sometimes has item_name under en)
    if not item_name and isinstance(raw.get("en"), dict):
        item_name = raw["en"].get("item_name")
    # items_in_set: use first entry for display name
    if not item_name and raw.get("items_in_set"):
        first = raw["items_in_set"][0] if raw["items_in_set"] else {}
        item_name = first.get("en", {}).get("item_name") if isinstance(first.get("en"), dict) else first.get("item_name")
    if not item_name:
        item_name = url_name.replace("_", " ").title()
    return {"item_name": item_name, "url_name": url_name, **raw}


def _extract_items_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get items array from payload; handle payload.items as list or dict keyed by language."""
    items = payload.get("items")
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return items.get("en", []) or []
    return []


async def _fetch_warframe_market_items_list() -> List[Dict[str, Any]]:
    """Fetch full Warframe Market items list. Cached for 5 minutes."""
    from cache_utils import get_cached

    async def _fetch():
        headers = {
            "Language": "en",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://warframe.market",
            "Referer": "https://warframe.market/",
        }
        proxy = _market_proxy()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.warframe.market/v1/items",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
                proxy=proxy,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                payload = data.get("payload") or data
                return _extract_items_list(payload) if isinstance(payload, dict) else []

    return await get_cached("warframe_market:items_list", 300, _fetch)


async def search_warframe_market_item(item_name: str, platform: str = "pc") -> Optional[Dict[str, Any]]:
    """
    Search for an item on Warframe Market. Uses cached items list, then fuzzy-matches.
    """
    try:
        stripped = item_name.strip()
        if not stripped:
            return None
        search_name = stripped.lower().replace(" ", "_")
        item_lower = stripped.lower()

        all_items = await _fetch_warframe_market_items_list()

        def score(it: Dict[str, Any]) -> int:
            iname = (it.get("item_name") or "").lower()
            uname = (it.get("url_name") or "").lower()
            if uname == search_name or uname == item_lower.replace(" ", "_"):
                return 100
            if iname == item_lower or iname == stripped:
                return 95
            if iname.startswith(item_lower) or item_lower in iname:
                return 80
            if search_name in uname or item_lower.replace(" ", "_") in uname:
                return 60
            if item_lower in iname:
                return 50
            return 0

        if all_items:
            scored = [(score(it), it) for it in all_items]
            scored = [(s, it) for s, it in scored if s > 0]
            scored.sort(key=lambda x: (-x[0], len(x[1].get("item_name", ""))))
            if scored:
                _, best = scored[0]
                return _normalize_item_payload(best, best.get("url_name", search_name))

        # Fallback: direct GET by url_name variants
        headers = {
            "Language": "en",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://warframe.market",
            "Referer": "https://warframe.market/",
        }
        timeout = aiohttp.ClientTimeout(total=20)
        proxy = _market_proxy()

        async with aiohttp.ClientSession() as session:
            def _url_variants() -> List[str]:
                seen: set = set()
                out: List[str] = []
                candidates = [search_name]
                if not search_name.endswith("_set"):
                    candidates.append(search_name + "_set")
                replaced = search_name.replace("_set", "").rstrip("_")
                if replaced:
                    candidates.append(replaced)
                for s in ("_blueprint", "_receiver", "_barrel", "_chassis", "_neuroptics", "_systems"):
                    if not search_name.endswith(s):
                        candidates.append(search_name + s)
                for cand in candidates:
                    if cand not in seen:
                        seen.add(cand)
                        out.append(cand)
                return out

            for url_name in _url_variants():
                if not url_name:
                    continue
                try:
                    async with session.get(
                        f"https://api.warframe.market/v1/items/{url_name}",
                        headers=headers,
                        timeout=timeout,
                        proxy=proxy
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            payload = data.get("payload", {})
                            item = payload.get("item")
                            if item:
                                out = _normalize_item_payload(item, url_name)
                                if out:
                                    return out
                except Exception:
                    continue
            return None
    except Exception as e:
        logger.error(f"Error searching Warframe Market for {item_name}: {e}")
        return None


async def fetch_duviri_circuit() -> Optional[Dict[str, Any]]:
    """Fetch Duviri Circuit data from Warframe World State API. Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        try:
            return await _wf_stat_get("https://api.warframestat.us/pc/duviriCycle", _api_proxy())
        except Exception as e:
            logger.error("Error fetching Duviri Circuit data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:duviri", 60, _fetch)


async def fetch_alerts() -> Optional[List[Dict[str, Any]]]:
    """Fetch active alerts from Warframe World State API. Cached for 60s."""
    from cache_utils import get_cached

    async def _fetch():
        try:
            data = await _wf_stat_get("https://api.warframestat.us/pc/alerts", _api_proxy())
            if not data:
                return None
            return [alert for alert in data if alert.get("expired", False) == False]
        except Exception as e:
            logger.error("Error fetching alerts data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:alerts", 60, _fetch)


# Warframe Steam App ID (for playtime lookup)
WARFRAME_STEAM_APP_ID = 230410


async def resolve_steam_id(vanity_url_or_id: str) -> Optional[str]:
    """
    Resolve Steam profile URL or vanity name to 64-bit Steam ID.
    Returns Steam ID string or None if not found/invalid.
    """
    key = os.environ.get("STEAM_API_KEY", "")
    if not key:
        logger.warning("STEAM_API_KEY not set - cannot resolve Steam IDs")
        return None
    stripped = (vanity_url_or_id or "").strip()
    if not stripped:
        return None
    # Extract vanity name from URL: steamcommunity.com/id/USERNAME
    vanity = None
    if "steamcommunity.com/id/" in stripped:
        parts = stripped.split("steamcommunity.com/id/")[-1].split("/")[0].split("?")[0]
        if parts:
            vanity = parts
    elif "steamcommunity.com/profiles/" in stripped:
        # Already a numeric ID
        parts = stripped.split("steamcommunity.com/profiles/")[-1].split("/")[0].split("?")[0]
        if parts.isdigit():
            return parts
    elif stripped.isdigit() and len(stripped) >= 17:
        return stripped  # Already 64-bit ID
    else:
        vanity = stripped  # Assume vanity name
    if not vanity:
        return None
    if vanity.isdigit():
        return vanity
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={key}&vanityurl={vanity}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                r = data.get("response", {})
                if r.get("success") == 1 and r.get("steamid"):
                    return r["steamid"]
    except Exception as e:
        logger.error(f"Error resolving Steam ID: {e}")
    return None


async def fetch_steam_warframe_playtime(steam_id_64: str) -> Optional[int]:
    """
    Fetch Warframe playtime in hours from Steam API.
    Requires STEAM_API_KEY. Returns hours or None if unavailable.
    Note: User must have Steam profile/game details set to public.
    """
    key = os.environ.get("STEAM_API_KEY", "")
    if not key:
        logger.warning("STEAM_API_KEY not set - cannot fetch Warframe playtime")
        return None
    try:
        async with aiohttp.ClientSession() as session:
            url = (
                f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
                f"?key={key}&steamid={steam_id_64}&include_played_free_games=1"
            )
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                games = data.get("response", {}).get("games", [])
                for g in games:
                    if str(g.get("appid")) == str(WARFRAME_STEAM_APP_ID):
                        minutes = int(g.get("playtime_forever", 0) or 0)
                        return minutes // 60  # Convert to hours
    except Exception as e:
        logger.error("Error fetching Steam Warframe playtime: %s: %s", type(e).__name__, e, exc_info=True)
    return None


async def fetch_twitch_stream_status(channel_name: str = "playwarframe") -> Optional[Dict[str, Any]]:
    """
    Check if a Twitch channel is live using Twitch API.
    This checks if Warframe's official channel is streaming.
    
    Args:
        channel_name: Twitch channel name (default: "playwarframe")
    
    Returns:
        Stream data dict if live, None if offline or error
    """
    try:
        # Get app access token (no user auth needed for public stream status)
        async with aiohttp.ClientSession() as session:
            # First get an app access token
            # Note: For production, you'd want to cache this token and refresh it
            # For now, we'll use a simpler approach - checking via unofficial API or scraping
            # Actually, let's use the public Helix API endpoint that doesn't require auth for basic checks
            # But we still need client-id - let's make it optional via env var
            import os
            twitch_client_id = os.getenv("TWITCH_CLIENT_ID", "")
            
            if not twitch_client_id:
                # Fallback: Try to check via alternative method or return None
                # For now, we'll skip Twitch API and use pattern-based detection instead
                return None
            
            # Get app access token
            token_url = "https://id.twitch.tv/oauth2/token"
            async with session.post(token_url, params={
                "client_id": twitch_client_id,
                "client_secret": os.getenv("TWITCH_CLIENT_SECRET", ""),
                "grant_type": "client_credentials"
            }) as token_resp:
                if token_resp.status != 200:
                    return None
                token_data = await token_resp.json()
                access_token = token_data.get("access_token")
            
            if not access_token:
                return None
            
            # Get stream status
            url = f"https://api.twitch.tv/helix/streams?user_login={channel_name}"
            headers = {
                "Client-ID": twitch_client_id,
                "Authorization": f"Bearer {access_token}"
            }
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    streams = data.get("data", [])
                    if streams and len(streams) > 0:
                        return streams[0]  # Return first stream
                    return None
                else:
                    logger.warning(f"Twitch API returned status {response.status}")
                    return None
    except Exception as e:
        logger.error("Error fetching Twitch stream status: %s: %s", type(e).__name__, e, exc_info=True)
        return None


async def calculate_next_devstream_date() -> Optional[datetime]:
    """
    Calculate the next likely devstream date.
    Warframe devstreams are typically every other Friday at 2pm ET/EDT.
    This is a fallback if Twitch API is not available.
    """
    try:
        now = datetime.now(timezone.utc)
        
        # Convert to ET/EDT (rough approximation - this is UTC-5/UTC-4)
        # For simplicity, we'll use UTC-5 (EST) and calculate next Friday
        # Devstreams are typically at 2pm ET = 7pm UTC (EST) or 6pm UTC (EDT)
        # But we'll just use the pattern: every other Friday
        
        # Find next Friday
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0:
            # Today is Friday, check if it's past 2pm ET (7pm UTC)
            et_hour = (now.hour - 5) % 24  # Rough EST conversion
            if et_hour < 14:  # Before 2pm ET
                next_friday = now
            else:
                next_friday = now + timedelta(days=14)  # Next devstream cycle (2 weeks)
        else:
            next_friday = now + timedelta(days=days_until_friday)
        
        # Check if this is a devstream week (every other week)
        # Simple heuristic: if week number is even, it's a devstream week
        week_number = next_friday.isocalendar()[1]
        if week_number % 2 == 0:
            # This is a devstream week
            # Set time to 2pm ET (7pm UTC EST, 6pm UTC EDT)
            # For simplicity, use 7pm UTC
            next_devstream = next_friday.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            # Next week is devstream week (add 1 week)
            next_devstream = (next_friday + timedelta(days=7)).replace(hour=19, minute=0, second=0, microsecond=0)
        
        return next_devstream
    except Exception as e:
        logger.error(f"Error calculating next devstream date: {e}")
        return None


async def get_warframe_market_price(item_url_name: str, platform: str = "pc") -> Optional[Dict[str, Any]]:
    """
    Get price statistics for an item from Warframe Market. Cached for 90 seconds per item/platform.
    
    Args:
        item_url_name: The item's URL name (from search_warframe_market_item)
        platform: Platform (pc, xbox, ps4, switch)
    
    Returns:
        Price statistics dict with orders and stats, or None if error
    """
    from cache_utils import get_cached

    async def _fetch():
        try:
            proxy = _market_proxy()
            async with aiohttp.ClientSession() as session:
                wfm_headers = {
                    "Language": "en",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Origin": "https://warframe.market",
                    "Referer": "https://warframe.market/",
                }
                async with session.get(
                    f"https://api.warframe.market/v1/items/{item_url_name}/orders",
                    params={"platform": platform, "status": "ingame"},
                    headers=wfm_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                    proxy=proxy
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        orders = data.get("payload", {}).get("orders", [])
                        async with session.get(
                            f"https://api.warframe.market/v1/items/{item_url_name}/statistics",
                            params={"platform": platform},
                            headers=wfm_headers,
                            timeout=aiohttp.ClientTimeout(total=10),
                            proxy=proxy
                        ) as stats_response:
                            stats_data = None
                            if stats_response.status == 200:
                                stats_data = await stats_response.json()
                            sell_orders = [o for o in orders if o.get("order_type") == "sell" and o.get("user", {}).get("status") == "ingame"]
                            buy_orders = [o for o in orders if o.get("order_type") == "buy" and o.get("user", {}).get("status") == "ingame"]
                            sell_prices = sorted([o.get("platinum", 0) for o in sell_orders if o.get("platinum")])
                            buy_prices = sorted([o.get("platinum", 0) for o in buy_orders if o.get("platinum")], reverse=True)
                            result = {
                                "item_url_name": item_url_name,
                                "platform": platform,
                                "sell_orders": sell_orders[:5],
                                "buy_orders": buy_orders[:5],
                                "lowest_sell": sell_prices[0] if sell_prices else None,
                                "highest_buy": buy_prices[0] if buy_prices else None,
                                "stats": stats_data.get("payload", {}).get("statistics_closed", {}).get("90days", [])[-1] if stats_data else None,
                            }
                            return result
                    else:
                        logger.warning(f"Warframe Market API returned status {response.status} for {item_url_name}")
                        return None
        except Exception as e:
            logger.error("Error fetching Warframe Market price for %s: %s: %s", item_url_name, type(e).__name__, e, exc_info=True)
            return None

    return await get_cached(f"warframe_market:price:{item_url_name}:{platform}", 90, _fetch)
