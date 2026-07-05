"""JSON data for the external web dashboard API."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
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


def _parse_setup_block(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("✅"):
            status = "ok"
            body = line[1:].strip()
        elif line.startswith("⚠️"):
            status = "warn"
            body = line[1:].strip()
        elif line.startswith("❌"):
            status = "missing"
            body = line[1:].strip()
        else:
            status = "unknown"
            body = line
        items.append({"status": status, "text": body})
    return items


async def fetch_guild_setup_health(guild_id: int, bot: discord.Client) -> dict[str, Any]:
    """Structured setup status for the web dashboard."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return {"guild_id": guild_id, "error": "guild_not_found"}

    from commands.general.setup_status import compute_setup_health

    configured, total, core_block, wf_block, mod_block, extra_block = await compute_setup_health(guild)
    pct = int(100 * configured / total) if total else 0
    return {
        "guild_id": guild_id,
        "configured": configured,
        "total": total,
        "percent": pct,
        "sections": [
            {"id": "core", "title": "Core", "items": _parse_setup_block(core_block)},
            {"id": "warframe", "title": "Warframe feeds", "items": _parse_setup_block(wf_block)},
            {"id": "moderation", "title": "Moderation logs", "items": _parse_setup_block(mod_block)},
            {"id": "community", "title": "Community", "items": _parse_setup_block(extra_block)},
        ],
    }


def _parse_iso_ts(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return str(raw)


async def fetch_warframe_snapshot() -> dict[str, Any]:
    """Baro + open-world cycles for the dashboard Warframe tab."""
    from api.warframe_api import get_all_cycles, get_baro_status
    from commands.warframe.baro import _parse_baro_item_name

    is_active, baro_data = await get_baro_status()
    baro: dict[str, Any] = {"active": False, "available": baro_data is not None}
    if baro_data:
        inventory = baro_data.get("inventory") or []
        baro = {
            "active": bool(is_active),
            "available": True,
            "location": baro_data.get("location") or "Unknown",
            "activation": baro_data.get("activation"),
            "expiry": baro_data.get("expiry"),
            "inventory_pending": bool(baro_data.get("_inventory_pending")) and not inventory,
            "inventory_count": len(inventory),
            "inventory_preview": [
                {
                    "name": _parse_baro_item_name(item),
                    "ducats": int(item.get("ducats") or item.get("ducatPrice") or 0),
                    "credits": int(item.get("credits") or item.get("creditPrice") or 0),
                }
                for item in inventory[:8]
            ],
        }

    cycles_raw = await get_all_cycles()
    cycles: list[dict[str, Any]] = []
    labels = {"cetus": "Cetus (Plains)", "vallis": "Orb Vallis", "cambion": "Cambion Drift"}
    for key, label in labels.items():
        c = (cycles_raw or {}).get(key) if cycles_raw else None
        if not c:
            cycles.append({"id": key, "name": label, "state": "unknown"})
            continue
        is_day = c.get("isDay")
        cycles.append(
            {
                "id": key,
                "name": label,
                "state": "day" if is_day else "night",
                "label": "Day" if is_day else "Night",
                "expiry": c.get("expiry"),
            }
        )

    return {"baro": baro, "cycles": cycles}


async def fetch_guild_analytics(guild_id: int, bot: discord.Client) -> dict[str, Any]:
    """Guild activity and economy snapshot for charts."""
    guild = bot.get_guild(guild_id)
    since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    since_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT user_id, weekly_score, commands_used, events_attended, voice_minutes
            FROM activity_stats
            WHERE guild_id=? AND weekly_score > 0
            ORDER BY weekly_score DESC, commands_used DESC
            LIMIT 8
            """,
            (guild_id,),
        )
        top_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT COUNT(DISTINCT user_id) FROM activity_log
            WHERE guild_id=? AND activity_date >= ?
            """,
            (guild_id, since_7d),
        )
        active_users_7d = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM activity_log
            WHERE guild_id=? AND activity_type='command' AND activity_date >= ?
            """,
            (guild_id, since_7d),
        )
        commands_7d = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM economy_transactions
            WHERE guild_id=? AND created_at >= ? AND amount > 0
            """,
            (guild_id, since_7d),
        )
        economy_volume_7d = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT date(activity_date) AS d, COUNT(*) AS c
            FROM activity_log
            WHERE guild_id=? AND activity_type='command' AND activity_date >= ?
            GROUP BY date(activity_date)
            ORDER BY d ASC
            """,
            (guild_id, since_14d),
        )
        daily_rows = await cur.fetchall()

        cur = await db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'",
            (guild_id,),
        )
        open_tickets = int((await cur.fetchone())[0] or 0)
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

    top_members = [
        {
            "user_id": uid,
            "user_name": _member_label(guild, uid),
            "weekly_score": score,
            "commands_used": cmds,
            "events_attended": events,
            "voice_minutes": voice,
        }
        for uid, score, cmds, events, voice in top_rows
    ]

    daily_activity = [{"date": str(d), "commands": int(c)} for d, c in daily_rows if d]

    return {
        "guild_id": guild_id,
        "member_count": guild.member_count if guild else None,
        "active_users_7d": active_users_7d,
        "commands_7d": commands_7d,
        "economy_volume_7d": economy_volume_7d,
        "top_members": top_members,
        "daily_activity": daily_activity,
        "counts": {
            "open_tickets": open_tickets,
            "pending_apps": pending_apps,
            "open_lfg": open_lfg,
        },
    }


async def fetch_guild_audit_log(
    guild_id: int,
    bot: discord.Client,
    *,
    search: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Unified moderation audit timeline."""
    guild = bot.get_guild(guild_id)
    limit = max(1, min(limit, 100))
    entries: list[dict[str, Any]] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT user_id, reason, moderator_id, created_at FROM warnings
            WHERE guild_id=? ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        for uid, reason, mod_id, created in await cur.fetchall():
            entries.append(
                {
                    "id": f"warn-{uid}-{created}",
                    "type": "warning",
                    "timestamp": _parse_iso_ts(created),
                    "actor_id": mod_id,
                    "actor_name": _member_label(guild, mod_id),
                    "target_id": uid,
                    "target_name": _member_label(guild, uid),
                    "summary": reason or "Warning issued",
                }
            )

        cur = await db.execute(
            """
            SELECT case_id, actor_id, action, note, created_at FROM complaint_actions
            WHERE guild_id=? ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        for case_id, actor_id, action, note, created in await cur.fetchall():
            entries.append(
                {
                    "id": f"complaint-{case_id}-{created}",
                    "type": "complaint",
                    "timestamp": _parse_iso_ts(created),
                    "actor_id": actor_id,
                    "actor_name": _member_label(guild, actor_id),
                    "target_id": None,
                    "target_name": case_id,
                    "summary": f"{action}" + (f" — {note}" if note else ""),
                }
            )

        cur = await db.execute(
            """
            SELECT ticket_id, subject, user_id, closed_by, closed_at FROM tickets
            WHERE guild_id=? AND status='closed' AND closed_at IS NOT NULL
            ORDER BY closed_at DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        for ticket_id, subject, uid, closed_by, closed_at in await cur.fetchall():
            entries.append(
                {
                    "id": f"ticket-close-{ticket_id}-{closed_at}",
                    "type": "ticket_closed",
                    "timestamp": _parse_iso_ts(closed_at),
                    "actor_id": closed_by,
                    "actor_name": _member_label(guild, closed_by or 0),
                    "target_id": uid,
                    "target_name": _member_label(guild, uid),
                    "summary": f"Closed ticket {ticket_id}: {subject or '—'}",
                }
            )

    entries.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    if search:
        q = search.strip().lower()
        entries = [
            e
            for e in entries
            if q in (e.get("summary") or "").lower()
            or q in (e.get("actor_name") or "").lower()
            or q in (e.get("target_name") or "").lower()
            or q in str(e.get("type") or "").lower()
        ]

    return {"guild_id": guild_id, "entries": entries[:limit], "total": len(entries)}


async def search_guild_dashboard(
    guild_id: int,
    bot: discord.Client,
    query: str,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Search tickets, applications, and warnings."""
    guild = bot.get_guild(guild_id)
    q = (query or "").strip()
    if len(q) < 2:
        return {"query": q, "results": []}
    limit = max(1, min(limit, 50))
    like = f"%{q}%"
    results: list[dict[str, Any]] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT ticket_id, subject, user_id, channel_id, status FROM tickets
            WHERE guild_id=? AND status='open'
              AND (ticket_id LIKE ? OR subject LIKE ?)
            ORDER BY last_activity_at DESC LIMIT ?
            """,
            (guild_id, like, like, limit),
        )
        for ticket_id, subject, uid, channel_id, status in await cur.fetchall():
            results.append(
                {
                    "kind": "ticket",
                    "id": ticket_id,
                    "title": subject or ticket_id,
                    "subtitle": _member_label(guild, uid),
                    "status": status,
                    "jump_url": (
                        f"https://discord.com/channels/{guild_id}/{channel_id}" if channel_id else None
                    ),
                }
            )

        if q.isdigit():
            cur = await db.execute(
                """
                SELECT id, user_id, status FROM applications
                WHERE guild_id=? AND id=? LIMIT 1
                """,
                (guild_id, int(q)),
            )
        else:
            cur = await db.execute(
                """
                SELECT id, user_id, status FROM applications
                WHERE guild_id=? AND status='PENDING'
                ORDER BY created_at DESC LIMIT ?
                """,
                (guild_id, limit),
            )
        for app_id, uid, status in await cur.fetchall():
            name = _member_label(guild, uid)
            if q.isdigit() or q.lower() in name.lower():
                results.append(
                    {
                        "kind": "application",
                        "id": str(app_id),
                        "title": f"Application #{app_id}",
                        "subtitle": name,
                        "status": status,
                        "jump_url": None,
                    }
                )

        cur = await db.execute(
            """
            SELECT user_id, reason, created_at FROM warnings
            WHERE guild_id=? AND reason LIKE ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, like, limit),
        )
        for uid, reason, created in await cur.fetchall():
            results.append(
                {
                    "kind": "warning",
                    "id": f"{uid}-{created}",
                    "title": (reason or "Warning")[:80],
                    "subtitle": _member_label(guild, uid),
                    "status": "warning",
                    "jump_url": None,
                }
            )

    return {"query": q, "results": results[:limit]}
