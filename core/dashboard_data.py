"""JSON data for the external web dashboard API."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.mod_inbox import get_oldest_open_ticket, _ticket_sla_stats
from core.utils import TOGGLEABLE_FEATURES, feature_enabled
from database import DB_PATH, get_auto_mod_settings, get_guild_setting


async def fetch_guild_inbox_summary(guild_id: int) -> dict[str, Any]:
    """Staff inbox counts (mirrors ``core.mod_inbox``)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'",
            (guild_id,),
        )
        open_tickets = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'
            AND (first_response_at IS NULL OR first_response_at='')
            """,
            (guild_id,),
        )
        awaiting_reply = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE guild_id=? AND status='PENDING'",
            (guild_id,),
        )
        pending_apps = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild_id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM suggestions WHERE guild_id=? AND status IN ('PENDING','UNDER_REVIEW')
            """,
            (guild_id,),
        )
        open_suggestions = int((await cur.fetchone())[0] or 0)

    sla_breaches, sla_hours = await _ticket_sla_stats(guild_id)
    oldest = await get_oldest_open_ticket(guild_id)
    oldest_ticket = None
    if oldest:
        tid, subject, ch_id = oldest
        oldest_ticket = {
            "ticket_id": tid,
            "subject": subject,
            "channel_id": ch_id,
            "jump_url": f"https://discord.com/channels/{guild_id}/{ch_id}",
        }

    return {
        "guild_id": guild_id,
        "tickets": {
            "open": open_tickets,
            "awaiting_first_reply": awaiting_reply,
            "sla_breaches": sla_breaches,
            "sla_hours": sla_hours,
            "oldest": oldest_ticket,
        },
        "applications_pending": pending_apps,
        "suggestions_open": open_suggestions,
        "lfg_open": open_lfg,
    }


def _member_label(guild: discord.Guild | None, user_id: int) -> str:
    if guild:
        member = guild.get_member(user_id)
        if member:
            return member.display_name
    return f"User {user_id}"


async def fetch_guild_dashboard_overview(
    guild_id: int,
    bot: discord.Client,
) -> dict[str, Any]:
    """Mod dashboard snapshot as structured JSON."""
    guild = bot.get_guild(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT ticket_id, subject, user_id, created_at, last_activity_at, tag, priority, escalated,
                   first_response_at, channel_id
            FROM tickets
            WHERE guild_id=? AND status='open'
            ORDER BY CASE WHEN COALESCE(priority,'normal')='urgent' THEN 0 ELSE 1 END,
                     COALESCE(escalated,0) DESC, last_activity_at ASC
            LIMIT 10
            """,
            (guild_id,),
        )
        ticket_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND status='open'
              AND (first_response_at IS NULL OR first_response_at='')
            """,
            (guild_id,),
        )
        awaiting_first_response = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT id, user_id, created_at FROM applications
            WHERE guild_id=? AND status='PENDING'
            ORDER BY created_at DESC LIMIT 10
            """,
            (guild_id,),
        )
        app_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT user_id, reason, moderator_id, created_at FROM warnings
            WHERE guild_id=? ORDER BY created_at DESC LIMIT 5
            """,
            (guild_id,),
        )
        warn_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM complaints
            WHERE guild_id=? AND status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')
            """,
            (guild_id,),
        )
        open_incidents = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild_id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)

        today_iso = date.today().isoformat()
        cur = await db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND date(created_at) = ?",
            (guild_id, today_iso),
        )
        warns_today = int((await cur.fetchone())[0] or 0)

    automod = await get_auto_mod_settings(guild_id)
    incident_raw = await get_guild_setting(guild_id, "incident_mode")
    incident_on = bool(incident_raw and incident_raw.lower() in ("1", "true", "on", "yes"))

    tickets = []
    for row in ticket_rows:
        ticket_id, subject, uid = row[0], row[1], row[2]
        channel_id = row[9] if len(row) > 9 else None
        tickets.append(
            {
                "ticket_id": ticket_id,
                "subject": subject,
                "user_id": uid,
                "user_name": _member_label(guild, uid),
                "tag": row[5] if len(row) > 5 else None,
                "priority": row[6] if len(row) > 6 else None,
                "escalated": bool(row[7]) if len(row) > 7 else False,
                "awaiting_first_reply": not (row[8] if len(row) > 8 else None),
                "channel_id": channel_id,
                "jump_url": (
                    f"https://discord.com/channels/{guild_id}/{channel_id}" if channel_id else None
                ),
            }
        )

    applications = [
        {
            "id": app_id,
            "user_id": uid,
            "user_name": _member_label(guild, uid),
            "created_at": created,
        }
        for app_id, uid, created in app_rows
    ]

    warnings = [
        {
            "user_id": uid,
            "user_name": _member_label(guild, uid),
            "moderator_id": mod_id,
            "moderator_name": _member_label(guild, mod_id),
            "reason": reason,
            "created_at": created,
        }
        for uid, reason, mod_id, created in warn_rows
    ]

    sla_raw = await get_guild_setting(guild_id, "ticket_sla_hours")
    sla_hours = int(sla_raw) if sla_raw and str(sla_raw).isdigit() else 4

    return {
        "guild_id": guild_id,
        "guild_name": guild.name if guild else None,
        "guild_icon": guild.icon.url if guild and guild.icon else None,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "open_incidents": open_incidents,
            "open_lfg": open_lfg,
            "warns_today": warns_today,
            "incident_mode": incident_on,
            "automod_enabled": bool(automod and automod.get("enabled")),
            "tickets_awaiting_reply": awaiting_first_response,
            "ticket_sla_hours": sla_hours,
        },
        "tickets": tickets,
        "applications": applications,
        "warnings": warnings,
    }


async def fetch_guild_features(guild_id: int) -> dict[str, Any]:
    """Feature toggle states for a guild."""
    features = {}
    for name in TOGGLEABLE_FEATURES:
        features[name] = await feature_enabled(guild_id, name)
    return {"guild_id": guild_id, "features": features}


async def set_guild_feature(guild_id: int, feature: str, enabled: bool) -> bool:
    """Toggle a feature on/off. Returns False if feature name is invalid."""
    if feature not in TOGGLEABLE_FEATURES:
        return False
    from database import set_guild_setting

    await set_guild_setting(guild_id, f"feature:{feature}", "on" if enabled else "off")
    return True


async def fetch_bot_health(bot: discord.Client, guild_id: Optional[int] = None) -> dict[str, Any]:
    """Bot health metrics (subset of ``/admin health``)."""
    from core.config import BOT_VERSION, COMMAND_SYNC_GUILD_ONLY, GUILD_ID
    from core.command_tree_stats import collect_command_tree_stats
    from core.error_handling import RECENT_ERRORS

    db_ok = False
    db_ms: float | None = None
    try:
        t0 = time.perf_counter()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
        db_ms = round((time.perf_counter() - t0) * 1000, 1)
        db_ok = True
    except Exception as exc:
        db_ms = None
        db_err = str(exc)[:120]
    else:
        db_err = None

    latency_ms = round(bot.latency * 1000) if bot.latency >= 0 else None
    cmd_stats = getattr(bot, "_command_tree_stats", None) or collect_command_tree_stats(bot)
    if isinstance(cmd_stats, dict):
        cmd_groups = int(cmd_stats.get("groups", 0))
        cmd_subcommands = int(cmd_stats.get("subcommands", 0))
    else:
        cmd_groups = cmd_stats.groups
        cmd_subcommands = cmd_stats.grouped_subcommands
    tasks_info = getattr(bot, "_background_tasks", {}) or {}
    running_tasks = sum(
        1 for t in tasks_info.values() if getattr(t, "is_running", lambda: False)()
    )

    last_sync = getattr(bot, "_last_command_sync", None)
    if isinstance(last_sync, datetime):
        last_sync_iso = last_sync.isoformat()
    else:
        last_sync_iso = None

    sync_scope = f"guild {GUILD_ID}" if COMMAND_SYNC_GUILD_ONLY and GUILD_ID else "global"

    payload: dict[str, Any] = {
        "version": BOT_VERSION,
        "discord_ready": bot.is_ready(),
        "latency_ms": latency_ms,
        "guild_count": len(bot.guilds),
        "database": {"ok": db_ok, "latency_ms": db_ms, "error": db_err},
        "commands": {
            "groups": cmd_groups,
            "subcommands": cmd_subcommands,
            "sync_scope": sync_scope,
            "guild_only_sync": COMMAND_SYNC_GUILD_ONLY,
            "dev_guild_id": GUILD_ID or None,
            "last_sync_at": last_sync_iso,
        },
        "background_tasks": {"total": len(tasks_info), "running": running_tasks},
        "recent_errors": len(RECENT_ERRORS),
    }

    if guild_id and bot.get_guild(guild_id):
        payload["guild"] = await fetch_guild_inbox_summary(guild_id)

    return payload


async def list_manageable_guilds(
    bot: discord.Client,
    user_id: int,
) -> list[dict[str, Any]]:
    """Guilds where the user has administrator permission and the bot is present."""
    out: list[dict[str, Any]] = []
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        if not member.guild_permissions.administrator:
            continue
        out.append(
            {
                "id": str(guild.id),
                "name": guild.name,
                "icon": guild.icon.url if guild.icon else None,
                "member_count": guild.member_count,
            }
        )
    out.sort(key=lambda g: g["name"].lower())
    return out
