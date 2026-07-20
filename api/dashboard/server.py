"""HTTP API for external web dashboard integration."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp  # type: ignore
import discord  # type: ignore
from aiohttp import web  # type: ignore

from api.dashboard.auth import (
    authenticate,
    exchange_discord_oauth_code,
    require_guild_admin,
    _parse_bearer,
)
from core.config import (
    BOT_VERSION,
    BOT_WEBSITE,
    CONTACT_WEBHOOK_URL,
    DASHBOARD_API_ENABLED,
    DASHBOARD_API_PORT,
    DASHBOARD_API_SECRET,
    DASHBOARD_CORS_ORIGINS,
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
)
from core.dashboard_data import (
    create_guild_giveaway,
    end_guild_giveaway,
    fetch_bot_health,
    fetch_bot_stats,
    fetch_guild_analytics,
    fetch_guild_audit_log,
    fetch_guild_dashboard_overview,
    fetch_guild_features,
    fetch_guild_giveaways,
    fetch_guild_inbox_summary,
    fetch_guild_setup_health,
    fetch_warframe_snapshot,
    list_manageable_guilds,
    list_manageable_guilds_oauth,
    search_guild_dashboard,
    set_guild_feature,
    update_guild_setup_fields,
)

logger = logging.getLogger(__name__)

_runner: web.AppRunner | None = None
_contact_last: dict[str, float] = {}
_CONTACT_COOLDOWN_SEC = 60.0
_stats_cache: dict[str, Any] | None = None
_stats_cache_at: float = 0.0
_STATS_CACHE_SEC = 300.0


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
        resp.headers["Access-Control-Allow-Methods"] = "GET, PATCH, POST, OPTIONS"
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


async def handle_stats(request: web.Request) -> web.Response:
    """Lightweight public stats for the website (cached 5 min)."""
    global _stats_cache, _stats_cache_at
    bot: discord.Client = request.app["bot"]
    now = time.monotonic()
    if _stats_cache is None or now - _stats_cache_at >= _STATS_CACHE_SEC:
        _stats_cache = await fetch_bot_stats(bot)
        _stats_cache_at = now
    resp = _json(_stats_cache)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


async def handle_auth_info(request: web.Request) -> web.Response:
    """Describe how the website should authenticate (no secrets)."""
    return _json(
        {
            "oauth": {
                "authorize_url": "https://discord.com/api/oauth2/authorize",
                "token_url": "https://discord.com/api/oauth2/token",
                "exchange_path": "/api/auth/token",
                "user_me_path": "/api/me",
                "client_id": DISCORD_CLIENT_ID,
                "recommended_scopes": ["identify", "guilds"],
                "server_exchange_configured": bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET),
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


async def handle_auth_token(request: web.Request) -> web.Response:
    """Exchange a Discord OAuth code for an access token (keeps client secret server-side)."""
    if request.method == "OPTIONS":
        return web.Response(status=204)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text='{"error":"invalid_json"}',
            content_type="application/json",
        )
    code = str(body.get("code") or "").strip()
    redirect_uri = str(body.get("redirect_uri") or "").strip()
    code_verifier = str(body.get("code_verifier") or "").strip()
    if not code or not redirect_uri:
        raise web.HTTPBadRequest(
            text='{"error":"missing_fields","message":"code and redirect_uri are required"}',
            content_type="application/json",
        )
    payload = await exchange_discord_oauth_code(
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    return _json(
        {
            "access_token": payload.get("access_token"),
            "token_type": payload.get("token_type") or "Bearer",
            "expires_in": payload.get("expires_in"),
            "scope": payload.get("scope"),
        }
    )


async def handle_me(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    auth = await authenticate(request, bot)
    if auth.is_service:
        guilds = await list_manageable_guilds(bot, auth.user_id)
    else:
        token = _parse_bearer(request) or ""
        guilds = await list_manageable_guilds_oauth(bot, token)
        if not guilds:
            # Fallback when Discord guilds endpoint is unavailable.
            guilds = await list_manageable_guilds(bot, auth.user_id)
    return _json(
        {
            "user_id": str(auth.user_id),
            "username": auth.username,
            "display_name": auth.global_name or auth.username,
            "avatar_url": auth.avatar_url,
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


async def handle_guild_setup(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)

    if request.method == "PATCH":
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(
                text='{"error":"invalid_json"}',
                content_type="application/json",
            )
        updates = body.get("updates") or body.get("fields") or []
        if not isinstance(updates, list):
            raise web.HTTPBadRequest(
                text='{"error":"invalid_updates","message":"Body must include updates: []"}',
                content_type="application/json",
            )
        return _json(await update_guild_setup_fields(guild_id, bot, updates))

    return _json(await fetch_guild_setup_health(guild_id, bot))


async def handle_guild_giveaways(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)

    if request.method == "GET":
        return _json(await fetch_guild_giveaways(guild_id, bot))

    if request.method != "POST":
        raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST"])

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text='{"error":"invalid_json"}',
            content_type="application/json",
        )

    channel_id = body.get("channel_id")
    prize = str(body.get("prize") or "").strip()
    end_time_raw = body.get("end_time") or body.get("ends_at")
    if not channel_id or not prize or not end_time_raw:
        raise web.HTTPBadRequest(
            text='{"error":"missing_fields","message":"channel_id, prize, and end_time are required"}',
            content_type="application/json",
        )
    try:
        channel_id_int = int(channel_id)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(
            text='{"error":"invalid_channel_id"}',
            content_type="application/json",
        )

    try:
        end_time = datetime.fromisoformat(str(end_time_raw).replace("Z", "+00:00"))
    except ValueError:
        raise web.HTTPBadRequest(
            text='{"error":"invalid_end_time","message":"Use ISO8601 datetime"}',
            content_type="application/json",
        )

    winner_count = int(body.get("winner_count") or 1)
    title = body.get("title")
    description = body.get("description")
    required_role_id = body.get("required_role_id")
    min_level = body.get("min_level")
    role_id = int(required_role_id) if required_role_id not in (None, "", "null") else None
    min_lvl = int(min_level) if min_level not in (None, "", "null") else None

    result = await create_guild_giveaway(
        guild_id,
        bot,
        user_id=auth.user_id,
        channel_id=channel_id_int,
        prize=prize,
        end_time=end_time,
        winner_count=winner_count,
        title=str(title).strip() if title else None,
        description=str(description).strip() if description else None,
        required_role_id=role_id,
        min_level=min_lvl,
    )
    status = 200 if result.get("ok") else 400
    return _json(result, status=status)


async def handle_guild_giveaway_end(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    giveaway_id = int(request.match_info["giveaway_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    result = await end_guild_giveaway(guild_id, bot, giveaway_id)
    status = 200 if result.get("ok") else 400
    return _json(result, status=status)


async def handle_guild_warframe(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    return _json(await fetch_warframe_snapshot(guild_id, bot))


async def handle_guild_analytics(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    return _json(await fetch_guild_analytics(guild_id, bot))


async def handle_guild_audit(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    search = request.query.get("q") or request.query.get("search")
    try:
        limit = int(request.query.get("limit") or 50)
    except ValueError:
        limit = 50
    return _json(await fetch_guild_audit_log(guild_id, bot, search=search, limit=limit))


async def handle_guild_search(request: web.Request) -> web.Response:
    bot: discord.Client = request.app["bot"]
    guild_id = int(request.match_info["guild_id"])
    auth = await authenticate(request, bot)
    await require_guild_admin(request, bot, guild_id, auth)
    q = request.query.get("q") or ""
    try:
        limit = int(request.query.get("limit") or 25)
    except ValueError:
        limit = 25
    return _json(await search_guild_dashboard(guild_id, bot, q, limit=limit))


async def handle_contact(request: web.Request) -> web.Response:
    """Public contact form — forwards to CONTACT_WEBHOOK_URL (rate-limited)."""
    if request.method == "OPTIONS":
        return web.Response(status=204)

    ip = request.remote or "unknown"
    now = time.monotonic()
    last = _contact_last.get(ip, 0.0)
    if now - last < _CONTACT_COOLDOWN_SEC:
        raise web.HTTPTooManyRequests(
            text='{"error":"rate_limited","message":"Please wait before sending another message."}',
            content_type="application/json",
        )

    if not CONTACT_WEBHOOK_URL:
        return _json(
            {"error": "contact_disabled", "message": "Contact form is not configured on the bot."},
            status=503,
        )

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text='{"error":"invalid_json"}',
            content_type="application/json",
        )

    message = str(body.get("message") or "").strip()
    if not message:
        raise web.HTTPBadRequest(
            text='{"error":"missing_message"}',
            content_type="application/json",
        )
    if len(message) > 2000:
        raise web.HTTPBadRequest(
            text='{"error":"message_too_long"}',
            content_type="application/json",
        )

    name = str(body.get("name") or "").strip() or "—"
    email = str(body.get("email") or "").strip() or "—"
    preferred = str(body.get("preferred_response") or "Either").strip() or "Either"
    discord_username = str(body.get("discord_username") or "").strip() or "—"

    fields = [
        {"name": "From", "value": name[:256], "inline": True},
        {"name": "Email", "value": email[:256], "inline": True},
        {"name": "Preferred response", "value": preferred[:256], "inline": True},
        {"name": "Discord username", "value": discord_username[:256], "inline": True},
        {"name": "Message", "value": message[:1024], "inline": False},
    ]
    if len(message) > 1024:
        fields.append({"name": "(continued)", "value": message[1024:2048], "inline": False})

    payload = {
        "embeds": [
            {
                "title": "📩 New message from website",
                "color": 0x8B7CF8,
                "fields": fields,
                "footer": {"text": "Obsidian Overseer contact form"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(CONTACT_WEBHOOK_URL, json=payload) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.warning("[contact] webhook failed status=%s body=%s", resp.status, text[:200])
                return _json(
                    {"error": "webhook_failed", "message": "Could not deliver message."},
                    status=502,
                )

    _contact_last[ip] = now
    return _json({"ok": True})


def create_app(bot: discord.Client) -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app["bot"] = bot
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/auth/info", handle_auth_info)
    app.router.add_route("*", "/api/auth/token", handle_auth_token)
    app.router.add_get("/api/me", handle_me)
    app.router.add_get("/api/guilds", handle_guilds)
    app.router.add_get("/api/guilds/{guild_id}/inbox", handle_guild_inbox)
    app.router.add_get("/api/guilds/{guild_id}/overview", handle_guild_overview)
    app.router.add_get("/api/guilds/{guild_id}/features", handle_guild_features_get)
    app.router.add_patch("/api/guilds/{guild_id}/features", handle_guild_features_patch)
    app.router.add_get("/api/guilds/{guild_id}/setup", handle_guild_setup)
    app.router.add_patch("/api/guilds/{guild_id}/setup", handle_guild_setup)
    app.router.add_get("/api/guilds/{guild_id}/giveaways", handle_guild_giveaways)
    app.router.add_post("/api/guilds/{guild_id}/giveaways", handle_guild_giveaways)
    app.router.add_post(
        "/api/guilds/{guild_id}/giveaways/{giveaway_id}/end",
        handle_guild_giveaway_end,
    )
    app.router.add_get("/api/guilds/{guild_id}/warframe", handle_guild_warframe)
    app.router.add_get("/api/guilds/{guild_id}/analytics", handle_guild_analytics)
    app.router.add_get("/api/guilds/{guild_id}/audit", handle_guild_audit)
    app.router.add_get("/api/guilds/{guild_id}/search", handle_guild_search)
    app.router.add_route("*", "/api/contact", handle_contact)
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
    # CORS preflight + parallel dashboard fetches otherwise flood Railway logs.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
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
