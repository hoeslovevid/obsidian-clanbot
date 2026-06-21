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


def twitch_was_live(last_status: Any) -> bool:
    """Parse twitch_streamers.last_live_status reliably (handles int/str/NULL)."""
    if last_status is None:
        return False
    if isinstance(last_status, bool):
        return last_status
    if isinstance(last_status, str):
        return last_status.strip().lower() in ("1", "true", "yes")
    try:
        return int(last_status) != 0
    except (TypeError, ValueError):
        return bool(last_status)


async def ensure_twitch_streamer_schema() -> None:
    """Add columns used by go-live session tracking."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("PRAGMA table_info(twitch_streamers)")
        cols = {row[1] for row in await cur.fetchall()}
        if "last_stream_id" not in cols:
            await db.execute("ALTER TABLE twitch_streamers ADD COLUMN last_stream_id TEXT")
            await db.commit()


async def _fetch_streams_chunk(
    session: aiohttp.ClientSession,
    access_token: str,
    *,
    param_name: str,
    values: list[str],
) -> tuple[list[dict[str, Any]], bool]:
    """Returns (streams, unauthorized)."""
    if not values:
        return [], False
    params = [(param_name, value) for value in values]
    async with session.get(
        f"{_HELIX}/streams",
        params=params,
        headers=_helix_headers(access_token),
        timeout=aiohttp.ClientTimeout(total=20),
    ) as response:
        if response.status == 401:
            logger.warning("[twitch] streams %s unauthorized", param_name)
            return [], True
        if response.status != 200:
            body = await response.text()
            logger.warning(
                "[twitch] streams %s status=%s count=%s body=%s",
                param_name,
                response.status,
                len(values),
                body[:200],
            )
            return [], False
        data = await response.json()
        return list(data.get("data") or []), False


async def fetch_twitch_streams_batch(
    logins: list[str],
    access_token: str,
    *,
    user_ids: Optional[list[str]] = None,
    retry_on_unauthorized: bool = True,
) -> dict[str, dict[str, Any]]:
    """Map lowercase login -> stream payload for streamers currently live."""
    normalized = list(dict.fromkeys(ln.strip().lower() for ln in logins if ln and ln.strip()))
    uid_list = list(dict.fromkeys(str(uid).strip() for uid in (user_ids or []) if uid and str(uid).strip()))
    if (not normalized and not uid_list) or not twitch_client_id():
        return {}

    async def _run(token: str) -> tuple[dict[str, dict[str, Any]], bool]:
        live: dict[str, dict[str, Any]] = {}
        unauthorized = False
        try:
            async with aiohttp.ClientSession() as session:
                seen_ids: set[str] = set()
                for uid_chunk in [uid_list[i : i + _BATCH_SIZE] for i in range(0, len(uid_list), _BATCH_SIZE)]:
                    streams, auth_err = await _fetch_streams_chunk(
                        session, token, param_name="user_id", values=uid_chunk
                    )
                    unauthorized = unauthorized or auth_err
                    for stream in streams:
                        login = str(stream.get("user_login", "")).lower()
                        if login:
                            live[login] = stream
                            sid = str(stream.get("id") or "")
                            if sid:
                                seen_ids.add(sid)
                missing_logins = [ln for ln in normalized if ln not in live]
                for login_chunk in [
                    missing_logins[i : i + _BATCH_SIZE] for i in range(0, len(missing_logins), _BATCH_SIZE)
                ]:
                    streams, auth_err = await _fetch_streams_chunk(
                        session, token, param_name="user_login", values=login_chunk
                    )
                    unauthorized = unauthorized or auth_err
                    for stream in streams:
                        login = str(stream.get("user_login", "")).lower()
                        sid = str(stream.get("id") or "")
                        if login and sid not in seen_ids:
                            live[login] = stream
        except Exception as exc:
            logger.warning("[twitch] streams batch error: %s", exc)
        return live, unauthorized

    live, unauthorized = await _run(access_token)
    if unauthorized and retry_on_unauthorized:
        fresh = await get_twitch_access_token(force_refresh=True)
        if fresh and fresh != access_token:
            live, _ = await _run(fresh)
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
