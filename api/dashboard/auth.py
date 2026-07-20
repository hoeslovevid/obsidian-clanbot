"""Authentication for the web dashboard API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp  # type: ignore
import discord  # type: ignore
from aiohttp import web  # type: ignore

from core.config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DASHBOARD_API_SECRET,
)

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
_MANAGE_GUILD = 1 << 5
_ADMINISTRATOR = 1 << 3


@dataclass
class AuthContext:
    user_id: int
    is_service: bool
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    global_name: Optional[str] = None


def discord_avatar_url(user_id: int, avatar_hash: Optional[str]) -> str:
    if avatar_hash:
        ext = "gif" if str(avatar_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


def _parse_bearer(request: web.Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _has_manage_perms(permissions: int) -> bool:
    return bool(permissions & (_ADMINISTRATOR | _MANAGE_GUILD))


async def _fetch_discord_user(token: str) -> Optional[dict]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


async def fetch_user_guilds(user_token: str) -> list[dict[str, Any]]:
    """Guilds visible to the OAuth user (includes permissions with ``guilds`` scope)."""
    timeout = aiohttp.ClientTimeout(total=15)
    guilds: list[dict[str, Any]] = []
    url: Optional[str] = f"{DISCORD_API}/users/@me/guilds?limit=200"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while url:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {user_token}"},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(
                        "[dashboard-auth] guilds fetch failed status=%s body=%s",
                        resp.status,
                        text[:200],
                    )
                    break
                batch = await resp.json()
                if not isinstance(batch, list):
                    break
                guilds.extend(batch)
                if len(batch) < 200:
                    break
                url = f"{DISCORD_API}/users/@me/guilds?limit=200&after={batch[-1]['id']}"
    return guilds


async def _user_has_guild_admin(user_token: str, guild_id: int) -> bool:
    """Check Manage Server / Administrator via OAuth guild list (no extra scopes)."""
    for guild in await fetch_user_guilds(user_token):
        try:
            if int(guild.get("id") or 0) != guild_id:
                continue
        except (TypeError, ValueError):
            continue
        try:
            perms = int(guild.get("permissions") or 0)
        except (TypeError, ValueError):
            return False
        return _has_manage_perms(perms)
    return False


async def _bot_member_can_manage(bot: discord.Client, guild_id: int, user_id: int) -> bool:
    guild = bot.get_guild(guild_id)
    if not guild:
        return False
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    return bool(
        member.guild_permissions.administrator or member.guild_permissions.manage_guild
    )


async def authenticate(request: web.Request, bot: discord.Client) -> AuthContext:
    """Resolve caller from Bearer token (service secret or Discord OAuth)."""
    token = _parse_bearer(request)
    if not token:
        raise web.HTTPUnauthorized(
            text='{"error":"missing_token","message":"Authorization: Bearer required"}',
            content_type="application/json",
        )

    if DASHBOARD_API_SECRET and token == DASHBOARD_API_SECRET:
        raw_uid = request.headers.get("X-Discord-User-Id", "").strip()
        if not raw_uid.isdigit():
            raise web.HTTPBadRequest(
                text='{"error":"missing_user","message":"X-Discord-User-Id header required for service auth"}',
                content_type="application/json",
            )
        return AuthContext(user_id=int(raw_uid), is_service=True)

    user = await _fetch_discord_user(token)
    if not user:
        raise web.HTTPUnauthorized(
            text='{"error":"invalid_token","message":"Invalid or expired Discord access token"}',
            content_type="application/json",
        )
    return AuthContext(
        user_id=int(user["id"]),
        is_service=False,
        username=str(user.get("username") or ""),
        global_name=str(user.get("global_name") or user.get("username") or ""),
        avatar_url=discord_avatar_url(int(user["id"]), user.get("avatar")),
    )


async def require_guild_admin(
    request: web.Request,
    bot: discord.Client,
    guild_id: int,
    auth: AuthContext,
) -> None:
    """Ensure the caller can manage the guild."""
    if not bot.get_guild(guild_id):
        raise web.HTTPNotFound(
            text='{"error":"guild_not_found","message":"Bot is not in that server"}',
            content_type="application/json",
        )

    if auth.is_service:
        if not await _bot_member_can_manage(bot, guild_id, auth.user_id):
            raise web.HTTPForbidden(
                text='{"error":"forbidden","message":"User is not a server administrator"}',
                content_type="application/json",
            )
        return

    token = _parse_bearer(request)
    assert token
    if await _user_has_guild_admin(token, guild_id):
        return
    if await _bot_member_can_manage(bot, guild_id, auth.user_id):
        return

    raise web.HTTPForbidden(
        text='{"error":"forbidden","message":"Administrator or Manage Server permission required"}',
        content_type="application/json",
    )


async def exchange_discord_oauth_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str = "",
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for tokens (server-side)."""
    if not DISCORD_CLIENT_ID:
        raise web.HTTPServiceUnavailable(
            text='{"error":"oauth_unconfigured","message":"DISCORD_CLIENT_ID is not set on the bot."}',
            content_type="application/json",
        )
    if not DISCORD_CLIENT_SECRET:
        raise web.HTTPServiceUnavailable(
            text='{"error":"oauth_unconfigured","message":"DISCORD_CLIENT_SECRET is not set on Railway. Add it from the Discord Developer Portal."}',
            content_type="application/json",
        )

    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{DISCORD_API}/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            payload = await resp.json(content_type=None)
            if resp.status >= 400:
                logger.warning(
                    "[dashboard-auth] token exchange failed status=%s body=%s",
                    resp.status,
                    str(payload)[:300],
                )
                raise web.HTTPBadRequest(
                    text='{"error":"oauth_failed","message":"Discord login failed. Try again, and confirm the redirect URI matches the Developer Portal."}',
                    content_type="application/json",
                )
            return payload
