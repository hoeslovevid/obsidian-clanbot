"""Authentication for the web dashboard API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp  # type: ignore
import discord  # type: ignore
from aiohttp import web  # type: ignore

from core.config import DASHBOARD_API_SECRET

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
_MANAGE_GUILD = 1 << 5
_ADMINISTRATOR = 1 << 3


@dataclass
class AuthContext:
    user_id: int
    is_service: bool
    username: Optional[str] = None


def _parse_bearer(request: web.Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


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


async def _user_has_guild_admin(user_token: str, guild_id: int) -> bool:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{DISCORD_API}/users/@me/guilds/{guild_id}/member",
            headers={"Authorization": f"Bearer {user_token}"},
        ) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
            perms = int(data.get("permissions") or 0)
            return bool(perms & (_ADMINISTRATOR | _MANAGE_GUILD))


async def _bot_member_is_admin(bot: discord.Client, guild_id: int, user_id: int) -> bool:
    guild = bot.get_guild(guild_id)
    if not guild:
        return False
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    return member.guild_permissions.administrator


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
        if not await _bot_member_is_admin(bot, guild_id, auth.user_id):
            raise web.HTTPForbidden(
                text='{"error":"forbidden","message":"User is not a server administrator"}',
                content_type="application/json",
            )
        return

    token = _parse_bearer(request)
    assert token
    if await _user_has_guild_admin(token, guild_id):
        return
    if await _bot_member_is_admin(bot, guild_id, auth.user_id):
        return

    raise web.HTTPForbidden(
        text='{"error":"forbidden","message":"Administrator permission required"}',
        content_type="application/json",
    )
