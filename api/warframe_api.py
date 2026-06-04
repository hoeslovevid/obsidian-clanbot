"""
Warframe API functions for fetching game data.
This module handles all Warframe World State API calls.
"""
import asyncio
import logging
import os
import time
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urlencode

import aiohttp  # type: ignore

# Timeout and retries for api.warframestat.us (can be slow or unreachable from some networks/proxy)
def _wf_stat_timeout() -> int:
    v = os.environ.get("WARFRAME_STAT_TIMEOUT", "")
    if not v.isdigit():
        return 12  # Sensible default: 12s per attempt (was 60s — too slow when proxy is dead)
    n = int(v)
    return n if n >= 1 else 12
WARFRAME_STAT_TIMEOUT = _wf_stat_timeout()

def _wf_stat_retries() -> int:
    v = os.environ.get("WARFRAME_STAT_RETRIES", "")
    return int(v) if v.isdigit() and int(v) >= 1 else 2  # 2 retries default (was 4)
WARFRAME_STAT_RETRIES = _wf_stat_retries()

# Optional proxy for Warframe APIs (e.g. when datacenter IP gets 404)
def _market_proxy() -> Optional[str]:
    return os.environ.get("WARFRAME_MARKET_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None


def _api_proxy() -> Optional[str]:
    """Proxy for api.warframestat.us - reuse same env vars as Warframe Market."""
    return os.environ.get("WARFRAME_STAT_PROXY") or _market_proxy()


def _wf_stat_base_url() -> str:
    """Base URL for Warframe World State API. Override via WARFRAME_STAT_BASE_URL to use a mirror or proxy."""
    return (os.environ.get("WARFRAME_STAT_BASE_URL") or "https://api.warframestat.us").rstrip("/")


def _wf_stat_url(path: str) -> str:
    """Full URL for a warframestat.us path (e.g. 'pc/cetusCycle' or 'pc/archonHunt?language=en')."""
    return f"{_wf_stat_base_url()}/{path.lstrip('/')}"


import re as _re
import dateparser  # type: ignore
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# Cloudflare/origin errors worth retrying (404 = often "blocked" from some IPs, 522/523 = timeout/unreachable, 502/503 = Bad Gateway)
_WF_STAT_RETRY_STATUSES = (404, 502, 503, 522, 523)

# When API fails, serve last successful response for up to this many seconds (configurable via env)
def _wf_stat_fallback_max_age() -> float:
    v = os.environ.get("WARFRAME_STAT_FALLBACK_MAX_AGE_SECONDS", "").strip()
    if not v:
        return 7200.0
    try:
        return float(v)
    except ValueError:
        return 7200.0


_wf_stat_fallback: Dict[str, Tuple[Any, float]] = {}  # url -> (data, monotonic_timestamp)
_wf_stat_failure_logged: Dict[str, float] = {}  # url -> monotonic time of last "failure" log (throttle spam)
_WF_STAT_FAILURE_LOG_INTERVAL = 3600.0  # log each URL failure at most once per hour
_wf_stat_proxy_logged = False
_wf_stat_base_url_logged = False
_wf_stat_success_logged = False


def _wf_stat_fallback_get(url: str) -> Optional[Any]:
    """Return last known good data for url if still within fallback max age."""
    entry = _wf_stat_fallback.get(url)
    if not entry:
        return None
    data, ts = entry
    age = time.monotonic() - ts
    if age > _wf_stat_fallback_max_age():
        return None
    logger.debug("Warframe API unavailable for %s; using last known good data (%.0f min old)", url, age / 60)
    return data


async def _wf_stat_get(url: str, proxy: Optional[str]) -> Optional[Any]:
    """GET api.warframestat.us with timeout and retries. Returns parsed JSON or None. Uses fallback cache on failure."""
    global _wf_stat_proxy_logged, _wf_stat_base_url_logged, _wf_stat_success_logged
    base = _wf_stat_base_url()
    if base != "https://api.warframestat.us" and not _wf_stat_base_url_logged:
        _wf_stat_base_url_logged = True
        logger.info("Warframe API using custom base URL: %s", base)
    if proxy and not _wf_stat_proxy_logged:
        _wf_stat_proxy_logged = True
        _host = proxy.split("@")[-1].split("/")[0] if "@" in proxy else proxy.split("/")[-1]
        logger.info("Warframe API proxy enabled: %s", _host)
    timeout = aiohttp.ClientTimeout(total=WARFRAME_STAT_TIMEOUT)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_exc = None
    for attempt in range(WARFRAME_STAT_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, proxy=proxy, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _wf_stat_fallback[url] = (data, time.monotonic())
                        if not _wf_stat_success_logged:
                            _wf_stat_success_logged = True
                            logger.info("Warframe API connected successfully")
                        return data
                    if resp.status in _WF_STAT_RETRY_STATUSES and attempt < WARFRAME_STAT_RETRIES - 1:
                        delay = 2 * (attempt + 1)  # 2s, 4s, 6s...
                        logger.debug(
                            "Warframe API returned %s for %s, retrying in %ss...",
                            resp.status, url, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    now = time.monotonic()
                    if now - _wf_stat_failure_logged.get(url, 0) >= _WF_STAT_FAILURE_LOG_INTERVAL:
                        _wf_stat_failure_logged[url] = now
                        logger.debug(
                            "Warframe API returned %s for %s (after retries), falling back to world state",
                            resp.status, url,
                        )
                    return _wf_stat_fallback_get(url) or None
        except (asyncio.TimeoutError, TimeoutError) as e:
            last_exc = e
            if attempt < WARFRAME_STAT_RETRIES - 1:
                logger.debug("Warframe API timeout for %s, retry %s/%s in 3s", url, attempt + 1, WARFRAME_STAT_RETRIES)
                await asyncio.sleep(3)
            else:
                now = time.monotonic()
                if now - _wf_stat_failure_logged.get(url, 0) >= _WF_STAT_FAILURE_LOG_INTERVAL:
                    _wf_stat_failure_logged[url] = now
                    logger.debug(
                        "Warframe API timeout for %s after %s attempt(s), falling back to world state",
                        url, WARFRAME_STAT_RETRIES,
                    )
                return _wf_stat_fallback_get(url) or None
        except (aiohttp.ClientHttpProxyError, aiohttp.ClientConnectorError) as e:
            # Proxy/connection failure — expected when running on datacenter IPs (Cloudflare blocks).
            # The world-state fallback handles data for all callers; no action needed from operators.
            last_exc = e
            if attempt < WARFRAME_STAT_RETRIES - 1:
                logger.debug("Warframe API proxy/connection error for %s, retry %s/%s in 3s", url, attempt + 1, WARFRAME_STAT_RETRIES)
                await asyncio.sleep(3)
            else:
                now = time.monotonic()
                if now - _wf_stat_failure_logged.get(url, 0) >= _WF_STAT_FAILURE_LOG_INTERVAL:
                    _wf_stat_failure_logged[url] = now
                    logger.debug(
                        "Warframe API unreachable for %s — using content.warframe.com fallback (normal on datacenter IPs)",
                        url,
                    )
                return _wf_stat_fallback_get(url) or None
    if last_exc:
        raise last_exc
    return None


# ---------------------------------------------------------------------------
# Official world-state fallback (content.warframe.com)
# Used when api.warframestat.us is unreachable (common on datacenter IPs).
# ---------------------------------------------------------------------------

# Relay node → human-readable name (used by Baro Ki'Teer)
# The world state uses short hub codes (EarthHUB, PlutoHUB, …) rather than SolNodeXX
_BARO_RELAY_MAP: Dict[str, str] = {
    # Short hub codes (current world state format)
    "EarthHUB":   "Strata Relay (Earth)",
    "PlutoHUB":   "Orcus Relay (Pluto)",
    "SaturnHUB":  "Kronia Relay (Saturn)",
    "MercuryHUB": "Larunda Relay (Mercury)",
    "EuropaHUB":  "Leonov Relay (Europa)",
    "VenusHUB":   "Vesper Relay (Venus)",
    # SolNode codes (older format, kept for compatibility)
    "SolNode36": "Maroo's Bazaar (Mars)",
    "SolNode39": "Strata Relay (Earth)",
    "SolNode40": "Orcus Relay (Pluto)",
    "SolNode41": "Kronia Relay (Saturn)",
    "SolNode43": "Larunda Relay (Mercury)",
    "SolNode44": "Leonov Relay (Europa)",
    "SolNode45": "Vesper Relay (Venus)",
}

# World-state in-memory cache
_ws_cache_data: Optional[Dict[str, Any]] = None
_ws_cache_ts: float = 0.0
_WS_CACHE_TTL = 90.0

# Suppress repeated "fallback active" log spam
_ws_fallback_logged = False


def _parse_ws_date(val: Any) -> Optional[str]:
    """Convert a world-state date object to an ISO UTC string.

    World state uses MongoDB Extended JSON: ``{"$date": {"$numberLong": "ms"}}``
    or occasionally the old .NET ``/Date(ms)/`` format.
    """
    if val is None:
        return None
    if isinstance(val, dict):
        d = val.get("$date")
        if isinstance(d, dict):
            ms = d.get("$numberLong")
            if ms:
                try:
                    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    pass
        elif isinstance(d, (int, float)):
            try:
                return datetime.fromtimestamp(int(d) / 1000, tz=timezone.utc).isoformat()
            except Exception:
                pass
    if isinstance(val, str):
        m = _re.match(r"/Date\((\d+)", val)
        if m:
            try:
                return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def _ws_is_active(activation_iso: Optional[str], expiry_iso: Optional[str]) -> bool:
    """Return True if the time window [activation, expiry] contains now."""
    if not activation_iso or not expiry_iso:
        return False
    try:
        now = datetime.now(timezone.utc)
        act = datetime.fromisoformat(activation_iso)
        exp = datetime.fromisoformat(expiry_iso)
        return act <= now < exp
    except Exception:
        return False


async def _fetch_official_world_state() -> Optional[Dict[str, Any]]:
    """Fetch the raw Warframe world state from DE's official content endpoint.

    This endpoint (content.warframe.com) is the source that api.warframestat.us
    parses. It is not subject to the same Cloudflare bot-protection that blocks
    most datacenter IPs from warframestat.us.
    """
    global _ws_cache_data, _ws_cache_ts, _ws_fallback_logged
    now = time.monotonic()
    if _ws_cache_data is not None and (now - _ws_cache_ts) < _WS_CACHE_TTL:
        return _ws_cache_data
    url = "https://content.warframe.com/dynamic/worldState.php"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=12),
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    _ws_cache_data = data
                    _ws_cache_ts = time.monotonic()
                    if not _ws_fallback_logged:
                        _ws_fallback_logged = True
                        logger.info(
                            "Warframe world state: using content.warframe.com fallback "
                            "(api.warframestat.us unreachable from this IP). "
                            "Set WARFRAME_STAT_PROXY in .env to restore full API access."
                        )
                    return data
    except Exception as e:
        logger.debug("content.warframe.com world state unavailable: %s", e)
    return None


def _ws_to_baro(ws: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert world-state VoidTraders[0] to warframestat.us voidTrader shape."""
    traders = ws.get("VoidTraders", [])
    if not traders:
        return None
    t = traders[0]
    activation = _parse_ws_date(t.get("Activation"))
    expiry = _parse_ws_date(t.get("Expiry"))
    node = t.get("Node", "")
    location = _BARO_RELAY_MAP.get(node, node or "Unknown Relay")
    inventory = []
    for item in t.get("Manifest", []):
        raw = item.get("ItemType", "")
        name_part = raw.strip("/").split("/")[-1] if raw else "Unknown Item"
        # CamelCase → spaced
        name_part = _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name_part)
        inventory.append({
            "item": name_part,
            "ducats": int(item.get("PrimePrice", 0)),
            "credits": int(item.get("RegularPrice", 0)),
        })
    return {
        "character": "Baro Ki'Teer",
        "location": location,
        "activation": activation or "",
        "expiry": expiry or "",
        "inventory": inventory,
    }


# Cycle epochs and constants (from warframe-worldstate-parser community research).
# All durations in seconds.
_CETUS_EPOCH   = 1509826800   # Unix ts of a known Cetus day start
_CETUS_DAY     = 6000         # 100 min
_CETUS_NIGHT   = 3000         # 50 min
_CETUS_TOTAL   = _CETUS_DAY + _CETUS_NIGHT

_VALLIS_EPOCH  = 1543027200   # Unix ts of a known Fortuna warm start
_VALLIS_WARM   = 1600          # ~26.6 min
_VALLIS_COLD   = 3200          # ~53.3 min
_VALLIS_TOTAL  = _VALLIS_WARM + _VALLIS_COLD


def _ws_to_cycles(_ws: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    """Compute cycle states from epoch maths (no lookup tables required)."""
    now_ts = datetime.now(timezone.utc).timestamp()

    # Cetus
    cetus: Optional[Dict[str, Any]] = None
    try:
        elapsed_c = (now_ts - _CETUS_EPOCH) % _CETUS_TOTAL
        if elapsed_c < _CETUS_DAY:
            left_c = _CETUS_DAY - elapsed_c
            cetus = {"state": "day", "isDay": True,
                     "expiry": datetime.fromtimestamp(now_ts + left_c, tz=timezone.utc).isoformat()}
        else:
            left_c = _CETUS_TOTAL - elapsed_c
            cetus = {"state": "night", "isDay": False,
                     "expiry": datetime.fromtimestamp(now_ts + left_c, tz=timezone.utc).isoformat()}
    except Exception:
        pass

    # Fortuna (Venus Proxima)
    vallis: Optional[Dict[str, Any]] = None
    try:
        elapsed_v = (now_ts - _VALLIS_EPOCH) % _VALLIS_TOTAL
        if elapsed_v < _VALLIS_WARM:
            left_v = _VALLIS_WARM - elapsed_v
            vallis = {"state": "warm", "isWarm": True,
                      "expiry": datetime.fromtimestamp(now_ts + left_v, tz=timezone.utc).isoformat()}
        else:
            left_v = _VALLIS_TOTAL - elapsed_v
            vallis = {"state": "cold", "isWarm": False,
                      "expiry": datetime.fromtimestamp(now_ts + left_v, tz=timezone.utc).isoformat()}
    except Exception:
        pass

    # Cambion Drift — world state has a direct CambionCycle object
    cambion: Optional[Dict[str, Any]] = None
    try:
        cc = _ws.get("CambionCycle") or {}
        if cc:
            exp = _parse_ws_date(cc.get("Expiry"))
            state = cc.get("State", "fass").lower()
            cambion = {"state": state, "expiry": exp or ""}
    except Exception:
        pass

    return {"cetus": cetus, "vallis": vallis, "cambion": cambion}


def _ws_to_alerts(ws: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert world-state Alerts to warframestat.us-compatible list."""
    now = datetime.now(timezone.utc)
    result = []
    for a in ws.get("Alerts", []):
        expiry = _parse_ws_date(a.get("Expiry"))
        if not expiry:
            continue
        try:
            if datetime.fromisoformat(expiry) < now:
                continue
        except Exception:
            pass
        mi = a.get("MissionInfo", {})
        node_raw = mi.get("location") or mi.get("missionType", "")
        node = node_raw.strip("/").split("/")[-1] if node_raw else "?"
        reward = mi.get("missionReward", {})
        counted = [i.get("ItemType", "").strip("/").split("/")[-1]
                   for i in reward.get("countedItems", [])]
        result.append({
            "active": True,
            "expired": False,
            "expiry": expiry,
            "mission": {"node": node, "type": mi.get("missionType", "").split("/")[-1]},
            "rewardTypes": counted,
        })
    return result


def _ws_to_invasions(ws: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert world-state Invasions to warframestat.us-compatible list."""
    result = []
    for inv in ws.get("Invasions", []):
        if inv.get("Completed", False):
            continue
        node_raw = inv.get("Node", "")
        node = node_raw.strip("/").split("/")[-1] if node_raw else "?"

        def _extract_items(reward: Any) -> List[Dict[str, Any]]:
            """Handle reward as a dict-with-countedItems or as a plain list."""
            if isinstance(reward, dict):
                items = reward.get("countedItems", [])
            elif isinstance(reward, list):
                items = reward
            else:
                return []
            return [{"type": i.get("ItemType", "").strip("/").split("/")[-1]}
                    for i in items if isinstance(i, dict)]

        result.append({
            "completed": False,
            "node": node,
            "desc": inv.get("Desc", ""),
            "attackerReward": {"countedItems": _extract_items(inv.get("AttackerReward", {}))},
            "defenderReward": {"countedItems": _extract_items(inv.get("DefenderReward", {}))},
        })
    return result


# Map world-state Region integer → (planet_name, primary_faction)
# Based on Warframe's solar chart region numbering.
_WS_REGION_INFO: Dict[int, tuple] = {
    1:  ("Mercury",       "Grineer"),
    2:  ("Venus",         "Corpus"),
    3:  ("Earth",         "Grineer"),
    4:  ("Mars",          "Grineer"),
    5:  ("Phobos",        "Grineer"),
    6:  ("Ceres",         "Grineer"),
    7:  ("Jupiter",       "Corpus"),
    8:  ("Europa",        "Corpus"),
    9:  ("Saturn",        "Grineer"),
    10: ("Uranus",        "Grineer"),
    11: ("Neptune",       "Corpus"),
    12: ("Pluto",         "Corpus"),
    13: ("Sedna",         "Grineer"),
    14: ("Eris",          "Infested"),
    15: ("Void",          "Corrupted"),
    16: ("Kuva Fortress", "Grineer"),
    17: ("Deimos",        "Infested"),
    18: ("Zariman",       "Corrupted"),
    19: ("Duviri",        "Grineer"),
}

_WS_MT_MAP: Dict[str, str] = {
    "MT_EXTERMINATION":  "Exterminate",
    "MT_CAPTURE":        "Capture",
    "MT_TERRITORY":      "Interception",
    "MT_RESCUE":         "Rescue",
    "MT_SABOTAGE":       "Sabotage",
    "MT_ARTIFACT":       "Sabotage",
    "MT_SURVIVAL":       "Survival",
    "MT_DEFENSE":        "Defense",
    "MT_MOBILE_DEFENSE": "Mobile Defense",
    "MT_EXCAVATE":       "Excavation",
    "MT_HIVE":           "Hive",
    "MT_ASSASSINATION":  "Assassination",
    "MT_SPY":            "Spy",
    "MT_INTEL":          "Spy",
    "MT_DISRUPTION":     "Disruption",
    "MT_PURSUIT":        "Pursuit",
    "MT_RUSH":           "Rush",
    "MT_LANDSCAPE":      "Free Roam",
    "MT_JUNCTION":       "Junction",
}

_WS_VOID_TIER: Dict[str, str] = {
    "VoidT1": "Lith",
    "VoidT2": "Meso",
    "VoidT3": "Neo",
    "VoidT4": "Axi",
}
_WS_TIER_NUM: Dict[str, int] = {"Lith": 1, "Meso": 2, "Neo": 3, "Axi": 4}


def _ws_to_fissures(ws: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert world-state ActiveMissions + VoidStorms to warframestat.us fissure shape.

    The world state does not carry human-readable node names, so we derive
    planet and faction from the ``Region`` integer field and translate the
    ``MissionType`` code (``MT_SURVIVAL`` → ``Survival``, etc.).  The display
    will read e.g. "Saturn • Survival (Grineer)" instead of "Piscinas (Saturn)".
    """
    now = datetime.now(timezone.utc)
    result: List[Dict[str, Any]] = []

    for m in ws.get("ActiveMissions", []):
        expiry = _parse_ws_date(m.get("Expiry"))
        if not expiry:
            continue
        try:
            if datetime.fromisoformat(expiry) < now:
                continue
        except Exception:
            pass

        modifier = m.get("Modifier", "")
        tier = _WS_VOID_TIER.get(modifier)
        if not tier:
            continue  # Not a fissure mission

        region = m.get("Region", 0)
        planet, faction = _WS_REGION_INFO.get(region, ("Unknown", "Unknown"))

        mt_raw = m.get("MissionType", "")
        mission = _WS_MT_MAP.get(mt_raw, mt_raw.replace("MT_", "").title() if mt_raw else "?")

        is_hard = bool(m.get("Hard", False))

        result.append({
            "node": f"{planet}",
            "tier": tier,
            "tierNum": _WS_TIER_NUM.get(tier, 0),
            "missionType": mission,
            "enemy": faction,
            "expiry": expiry,
            "expired": False,
            "isHard": is_hard,
            "isStorm": False,
        })

    # VoidStorms (Railjack fissures — use ActiveMissionTier not Modifier)
    for m in ws.get("VoidStorms", []):
        expiry = _parse_ws_date(m.get("Expiry"))
        if not expiry:
            continue
        try:
            if datetime.fromisoformat(expiry) < now:
                continue
        except Exception:
            pass
        tier = _WS_VOID_TIER.get(m.get("ActiveMissionTier", ""))
        if not tier:
            continue
        result.append({
            "node": "Railjack",
            "tier": tier,
            "tierNum": _WS_TIER_NUM.get(tier, 0),
            "missionType": "Void Storm",
            "enemy": "Grineer/Corpus",
            "expiry": expiry,
            "expired": False,
            "isHard": False,
            "isStorm": True,
        })

    # Sort: normal first, then Steel Path; within each group sort by tier
    result.sort(key=lambda f: (1 if f.get("isHard") else 0, f.get("tierNum", 99)))
    return result


def _ws_to_sortie(ws: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert world-state Sorties[0] to warframestat.us shape."""
    sorties = ws.get("Sorties", [])
    if not sorties:
        return None
    s = sorties[0]
    expiry = _parse_ws_date(s.get("Expiry"))
    variants = []
    for v in s.get("Variants", []):
        variants.append({
            "missionType": v.get("missionType", "").split("/")[-1],
            "modifier": v.get("modifierType", ""),
            "node": v.get("node", "").split("/")[-1],
        })
    return {"expiry": expiry or "", "variants": variants}


async def fetch_baro_data() -> Optional[Dict[str, Any]]:
    """Fetch Baro Ki'Teer data. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached

    async def _fetch():
        try:
            result = await _wf_stat_get(_wf_stat_url("pc/voidTrader"), _api_proxy())
            if result is not None:
                return result
        except Exception as e:
            logger.error("Error fetching Baro data: %s: %s", type(e).__name__, e, exc_info=True)
        ws = await _fetch_official_world_state()
        return _ws_to_baro(ws) if ws else None

    return await get_cached("warframe:baro", 60, _fetch)


async def fetch_cycle_data(cycle_type: str) -> Optional[Dict[str, Any]]:
    """Fetch cycle data from Warframe World State API.
    
    Args:
        cycle_type: One of 'cetus', 'vallis', or 'cambion'
    
    Returns:
        Cycle data dict or None if error
    """
    endpoints = {
        'cetus': _wf_stat_url('pc/cetusCycle'),
        'vallis': _wf_stat_url('pc/vallisCycle'),
        'cambion': _wf_stat_url('pc/cambionCycle'),
    }
    
    if cycle_type not in endpoints:
        return None
    
    try:
        return await _wf_stat_get(endpoints[cycle_type], _api_proxy())
    except Exception as e:
        logger.error("Error fetching %s cycle data: %s: %s", cycle_type, type(e).__name__, e, exc_info=True)
        return None


async def get_all_cycles() -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch all cycle data (Cetus, Fortuna, Deimos). Falls back to epoch calculation."""
    from core.cache_utils import get_cached

    async def _fetch():
        import asyncio as _asyncio
        cetus, vallis, cambion = await _asyncio.gather(
            fetch_cycle_data('cetus'),
            fetch_cycle_data('vallis'),
            fetch_cycle_data('cambion'),
        )
        if cetus is not None or vallis is not None or cambion is not None:
            return {'cetus': cetus, 'vallis': vallis, 'cambion': cambion}
        # Primary API unreachable — fall back to epoch calculation + world state for Cambion
        ws = await _fetch_official_world_state()
        return _ws_to_cycles(ws or {})

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
    """Fetch active Void Fissure missions. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached
    async def _fetch():
        try:
            data = await _wf_stat_get(_wf_stat_url("pc/fissures"), _api_proxy())
            if data is not None:
                return [f for f in data if not f.get("expired", False)]
        except Exception as e:
            logger.error("Error fetching fissures: %s: %s", type(e).__name__, e, exc_info=True)
        # Fallback: parse ActiveMissions from official world state
        ws = await _fetch_official_world_state()
        return _ws_to_fissures(ws) if ws else None
    return await get_cached("warframe:fissures", 60, _fetch)


async def fetch_sortie() -> Optional[Dict[str, Any]]:
    """Fetch today's Sortie. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached
    async def _fetch():
        try:
            result = await _wf_stat_get(_wf_stat_url("pc/sortie"), _api_proxy())
            if result is not None:
                return result
        except Exception as e:
            logger.error("Error fetching sortie: %s: %s", type(e).__name__, e, exc_info=True)
        ws = await _fetch_official_world_state()
        return _ws_to_sortie(ws) if ws else None
    return await get_cached("warframe:sortie", 60, _fetch)


async def fetch_steel_path() -> Optional[Dict[str, Any]]:
    """Fetch Steel Path data (current missions). Cached 60s."""
    from core.cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get(_wf_stat_url("pc/steelPath"), _api_proxy())
        except Exception as e:
            logger.error("Error fetching steel path: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:steelPath", 60, _fetch)


async def fetch_arbitration() -> Optional[Dict[str, Any]]:
    """Fetch current Arbitration. Cached 60s."""
    from core.cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get(_wf_stat_url("pc/arbitration"), _api_proxy())
        except Exception as e:
            logger.error("Error fetching arbitration: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:arbitration", 60, _fetch)


async def fetch_nightwave() -> Optional[Dict[str, Any]]:
    """Fetch Nightwave challenges. Cached 300s (updates daily)."""
    from core.cache_utils import get_cached
    async def _fetch():
        try:
            return await _wf_stat_get(_wf_stat_url("pc/nightwave"), _api_proxy())
        except Exception as e:
            logger.error("Error fetching nightwave: %s: %s", type(e).__name__, e, exc_info=True)
            return None
    return await get_cached("warframe:nightwave", 300, _fetch)


async def fetch_invasions() -> Optional[list]:
    """Fetch invasion data. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached

    async def _fetch():
        try:
            data = await _wf_stat_get(_wf_stat_url("pc/invasions"), _api_proxy())
            if data is not None:
                return [inv for inv in data if not inv.get("completed", False)]
        except Exception as e:
            logger.error("Error fetching invasion data: %s: %s", type(e).__name__, e, exc_info=True)
        ws = await _fetch_official_world_state()
        return _ws_to_invasions(ws) if ws else None

    return await get_cached("warframe:invasions", 60, _fetch)


async def fetch_archon_hunt_data() -> Optional[Dict[str, Any]]:
    """Fetch Archon Hunt data. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached

    async def _fetch():
        try:
            result = await _wf_stat_get(_wf_stat_url("pc/archonHunt?language=en"), _api_proxy())
            if result is not None:
                return result
        except Exception as e:
            logger.error("Error fetching archon hunt data: %s: %s", type(e).__name__, e, exc_info=True)
        # World state archon hunt: look for "ArchwingMission" with SortieTag or
        # the dedicated ArchonMissions list
        ws = await _fetch_official_world_state()
        if not ws:
            return None
        archon = ws.get("ArchwingMission") or ws.get("ArchonMissions")
        if archon and isinstance(archon, list) and archon:
            a = archon[0]
            expiry = _parse_ws_date(a.get("Expiry"))
            variants = []
            for v in a.get("Variants", []):
                variants.append({
                    "missionType": v.get("missionType", "").split("/")[-1],
                    "node": v.get("node", "").split("/")[-1],
                    "boss": v.get("boss", ""),
                })
            return {"expiry": expiry or "", "variants": variants, "boss": a.get("boss", "Archon Hunt")}
        return None

    return await get_cached("warframe:archon", 60, _fetch)


async def fetch_events_data() -> Optional[List[Dict[str, Any]]]:
    """Fetch active events data from Warframe World State API."""
    try:
        data = await _wf_stat_get(_wf_stat_url("pc/events"), _api_proxy())
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
    from core.cache_utils import get_cached

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
    from core.cache_utils import get_cached

    async def _fetch():
        try:
            return await _wf_stat_get(_wf_stat_url("pc/duviriCycle"), _api_proxy())
        except Exception as e:
            logger.error("Error fetching Duviri Circuit data: %s: %s", type(e).__name__, e, exc_info=True)
            return None

    return await get_cached("warframe:duviri", 60, _fetch)


async def fetch_alerts() -> Optional[List[Dict[str, Any]]]:
    """Fetch active alerts. Falls back to content.warframe.com world state."""
    from core.cache_utils import get_cached

    async def _fetch():
        try:
            data = await _wf_stat_get(_wf_stat_url("pc/alerts"), _api_proxy())
            if data is not None:
                return [a for a in data if not a.get("expired", False)]
        except Exception as e:
            logger.error("Error fetching alerts data: %s: %s", type(e).__name__, e, exc_info=True)
        ws = await _fetch_official_world_state()
        return _ws_to_alerts(ws) if ws else None

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
            # urlencode prevents vanity names with & or ? from breaking the query or injecting params
            q = urlencode({"key": key, "vanityurl": vanity})
            url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?{q}"
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
    sid = (steam_id_64 or "").strip()
    if not sid.isdigit() or len(sid) < 15:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            q = urlencode(
                {"key": key, "steamid": sid, "include_played_free_games": "1"}
            )
            url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?{q}"
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
    from core.cache_utils import get_cached

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


def wf_cache_age_seconds(url: str) -> Optional[float]:
    """Seconds since last successful fetch for this API URL (None if unknown)."""
    entry = _wf_stat_fallback.get(url)
    if not entry:
        return None
    _, ts = entry
    return max(0.0, time.monotonic() - ts)


def wf_cache_datetime(url: str) -> Optional[datetime]:
    """Approximate UTC time when cached data was last refreshed."""
    age = wf_cache_age_seconds(url)
    if age is None:
        return None
    return datetime.now(timezone.utc) - timedelta(seconds=age)


def wf_staleness_for_path(path: str) -> Optional[datetime]:
    """Cached-at timestamp for a warframestat.us path (e.g. pc/voidTrader)."""
    return wf_cache_datetime(_wf_stat_url(path))

