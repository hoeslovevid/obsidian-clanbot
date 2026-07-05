"""HTTP API for external web dashboard integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import discord  # type: ignore
from aiohttp import web  # type: ignore

from api.dashboard.auth import authenticate, require_guild_admin
from core.config import (
    BOT_VERSION,
    BOT_WEBSITE,
    DASHBOARD_API_ENABLED,
    DASHBOARD_API_PORT,
    DASHBOARD_API_SECRET,
    DASHBOARD_CORS_ORIGINS,
    DISCORD_CLIENT_ID,
)
from core.dashboard_data import (
    fetch_bot_health,
    fetch_guild_dashboard_overview,
    fetch_guild_features,
    fetch_guild_inbox_summary,
    list_manageable_guilds,
    set_guild_feature,
)

logger = logging.getLogger(__name__)

_runner: web.AppRunner | None = None


def _json(data: Any, *, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, default=str),
        content_type="application/json",
        status=status,
    )


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    origin = request.headers.get("Origin")
    if origin and DASHBOARD_CORS_ORIGINS and origin.rstrip("/") in {
        o.rstrip("/") for o in DASHBOARD_CORS_ORIGINS
    }:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET, PATCH, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, X-Discord-User-Id"
        )
        resp.headers["Vary"] = "Origin"
    return resp


async def handle_health(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = request.query.get("guild_id")
    gid = int(guild_id) if guild_id and guild_id.isdigit() else None
    return _json(await fetch_bot_health(bot, gid))


async def handle_auth_info(request: web.Request) -> web.Response:
    """Describe how the website should authenticate (no secrets)."""
    return _json(
        {
            "oauth": {
                "authorize_url": "https://discord.com/api/oauth2/authorize",
                "token_url": "https://discord.com/api/oauth2/token",
                "user_me_path": "/api/me",
                "client_id": DISCORD_CLIENT_ID,
                "recommended_scopes": ["identify", "guilds"],
            },
            "service_auth": {
                "header": "Authorization: Bearer <DASHBOARD_API_SECRET>",
                "act_as_user": "X-Discord-User-Id: <discord_user_id>",
                "note": "Use server-side only. Never expose the API secret in browser JavaScript.",
                "configured": bool(DASHBOARD_API_SECRET),
            },
            "website": BOT_WEBSITE,
            "version": BOT_VERSION,
        }
    )


async def handle_me(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    auth = await authenticate(request, bot)
    guilds = await list_manageable_guilds(bot, auth.user_id)
    return _json(
        {
            "user_id": str(auth.user_id),
            "username": auth.username,
            "guilds": guilds,
        }
    )


async def handle_guilds(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    auth = await authenticate(request, bot)
    guilds = await list_manageable_guilds(bot, auth.user_id)
    return _json({"guilds": guilds})


async def handle_guild_inbox(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    return _json(await fetch_guild_inbox_summary(guild_id))


async def handle_guild_overview(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    return _json(await fetch_guild_dashboard_overview(guild_id, bot))


async def handle_guild_features_get(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    return _json(await fetch_guild_features(guild_id))


async def handle_guild_features_patch(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text='{"error":"invalid_json"}',
            content_type="application/json",
        )
    feature = str(body.get("feature") or "").strip()
    if "enabled" not in body:
        raise web.HTTPBadRequest(
            text='{"error":"missing_enabled","message":"Body must include enabled: true|false"}',
            content_type="application/json",
        )
    enabled = bool(body["enabled"])
    if not await set_guild_feature(guild_id, feature, enabled):
        raise web.HTTPBadRequest(
            text='{"error":"invalid_feature","message":"Unknown feature name"}',
            content_type="application/json",
        )
    return _json(await fetch_guild_features(guild_id))


def create_app(bot: discord.Client) -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app["bot"] = bot
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/auth/info", handle_auth_info)
    app.router.add_get("/api/me", handle_me)
    app.router.add_get("/api/guilds", handle_guilds)
    app.router.add_get("/api/guilds/{guild_id}/inbox", handle_guild_inbox)
    app.router.add_get("/api/guilds/{guild_id}/overview", handle_guild_overview)
    app.router.add_get("/api/guilds/{guild_id}/features", handle_guild_features_get)
    app.router.add_patch("/api/guilds/{guild_id}/features", handle_guild_features_patch)
    return app


async def start_dashboard_server(bot: discord.Client) -> web.AppRunner | None:
    global _runner
    if not DASHBOARD_API_ENABLED:
        logger.info("[dashboard-api] Disabled (set DASHBOARD_API_ENABLED=true to enable)")
        return None
    if not DASHBOARD_API_SECRET:
        logger.warning(
            "[dashboard-api] DASHBOARD_API_SECRET is not set — only Discord OAuth tokens will work"
        )
    app = create_app(bot)
    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", DASHBOARD_API_PORT)
    await site.start()
    logger.info("[dashboard-api] Listening on 0.0.0.0:%s", DASHBOARD_API_PORT)
    return _runner


async def stop_dashboard_server(runner: web.AppRunner | None) -> None:
    global _runner
    if runner:
        await runner.cleanup()
    _runner = None
