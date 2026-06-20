"""Twitch Helix API helpers — token cache, user lookup, batch stream checks."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import aiohttp  # type: ignore
import aiosqlite  # type: ignore

from database import DB_PATH

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}
_HELIX = "https://api.twitch.tv/helix"
_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_BATCH_SIZE = 100


def twitch_credentials_configured() -> bool:
    return bool(os.getenv("TWITCH_CLIENT_ID", "").strip() and os.getenv("TWITCH_CLIENT_SECRET", "").strip())


def twitch_client_id() -> str:
    return os.getenv("TWITCH_CLIENT_ID", "").strip()


async def get_twitch_access_token(*, force_refresh: bool = False) -> Optional[str]:
    """App access token with in-memory cache (~50 min TTL)."""
    if not twitch_credentials_configured():
        return None

    now = time.time()
    if not force_refresh and _token_cache["token"] and now < float(_token_cache["expires_at"]):
        return str(_token_cache["token"])

    client_id = twitch_client_id()
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _TOKEN_URL,
                params={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning("[twitch] token request failed status=%s body=%s", response.status, body[:200])
                    return None
                data = await response.json()
                token = data.get("access_token")
                if not token:
                    logger.warning("[twitch] token response missing access_token")
                    return None
                expires_in = int(data.get("expires_in", 3600))
                _token_cache["token"] = token
                _token_cache["expires_at"] = now + max(expires_in - 300, 60)
                return str(token)
    except Exception as exc:
        logger.warning("[twitch] token request error: %s", exc)
        return None


def _helix_headers(access_token: str) -> dict[str, str]:
    return {
        "Client-ID": twitch_client_id(),
        "Authorization": f"Bearer {access_token}",
    }


async def resolve_twitch_user(login: str, access_token: str) -> Optional[dict[str, Any]]:
    """Resolve a Twitch login to a user record, or None if not found."""
    login = login.strip().lower()
    if not login:
        return None
    client_id = twitch_client_id()
    if not client_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_HELIX}/users",
                params={"login": login},
                headers=_helix_headers(access_token),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 401:
                    logger.warning("[twitch] users lookup unauthorized for %s", login)
                    return None
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "[twitch] users lookup status=%s login=%s body=%s",
                        response.status,
                        login,
                        body[:200],
                    )
                    return None
                data = await response.json()
                users = data.get("data") or []
                return users[0] if users else None
    except Exception as exc:
        logger.warning("[twitch] users lookup error login=%s: %s", login, exc)
        return None


async def check_twitch_stream(streamer_name: str, access_token: str) -> Optional[dict[str, Any]]:
    """Check if one streamer is live."""
    results = await fetch_twitch_streams_batch([streamer_name], access_token)
    return results.get(streamer_name.strip().lower())


async def fetch_twitch_streams_batch(
    logins: list[str],
    access_token: str,
) -> dict[str, dict[str, Any]]:
    """Map lowercase login -> stream payload for streamers currently live."""
    normalized = list(dict.fromkeys(ln.strip().lower() for ln in logins if ln and ln.strip()))
    if not normalized or not twitch_client_id():
        return {}

    live: dict[str, dict[str, Any]] = {}
    try:
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(normalized), _BATCH_SIZE):
                chunk = normalized[i : i + _BATCH_SIZE]
                params = [("user_login", login) for login in chunk]
                async with session.get(
                    f"{_HELIX}/streams",
                    params=params,
                    headers=_helix_headers(access_token),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status == 401:
                        logger.warning("[twitch] streams batch unauthorized")
                        return live
                    if response.status != 200:
                        body = await response.text()
                        logger.warning(
                            "[twitch] streams batch status=%s count=%s body=%s",
                            response.status,
                            len(chunk),
                            body[:200],
                        )
                        continue
                    data = await response.json()
                    for stream in data.get("data") or []:
                        login = str(stream.get("user_login", "")).lower()
                        if login:
                            live[login] = stream
    except Exception as exc:
        logger.warning("[twitch] streams batch error: %s", exc)
    return live


async def get_guild_twitch_settings(guild_id: int) -> Optional[dict[str, Any]]:
    """Return guild twitch_settings row or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id, enabled, ping_role_id FROM twitch_settings WHERE guild_id=?",
            (guild_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "channel_id": row[0],
        "enabled": bool(row[1]),
        "ping_role_id": row[2],
    }


async def guild_twitch_setup_status(guild_id: int) -> tuple[bool, str]:
    """Whether this guild can receive live alerts, plus a short reason."""
    settings = await get_guild_twitch_settings(guild_id)
    if not settings:
        return False, "No notify channel — run `/community twitch_setup` first."
    if not settings["enabled"]:
        return False, "Twitch alerts are disabled — re-run `/community twitch_setup` with **enabled: True**."
    if not settings.get("channel_id"):
        return False, "Notify channel not set — run `/community twitch_setup`."
    return True, "Configured"


def format_twitch_diagnostics() -> str:
    """One-line bot-side Twitch API readiness."""
    if not twitch_credentials_configured():
        return "❌ **API:** `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` not set on the bot host."
    cached = "cached token" if _token_cache.get("token") else "no token yet"
    return f"✅ **API:** credentials present ({cached})."
