"""Opt-in "notify me when the Warframe API is back" helper.

Watches persist across bot restarts until expiry (~15 minutes from opt-in).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import aiosqlite
import discord  # type: ignore

from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)

_pending: set[int] = set()
_POLL_SECONDS = 30
_MAX_MINUTES = 15

_PROBE_FETCHERS: dict[str, Callable[[], Awaitable]] = {}


def _register_probes() -> None:
    if _PROBE_FETCHERS:
        return

    async def _default():
        from api.warframe_api import get_all_cycles

        return await get_all_cycles()

    _PROBE_FETCHERS["default"] = _default


async def _ensure_watch_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS wf_recovery_watches (
                user_id INTEGER PRIMARY KEY,
                probe TEXT NOT NULL DEFAULT 'default',
                expires_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def _save_watch(user_id: int, probe: str, expires_at: datetime) -> None:
    await _ensure_watch_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO wf_recovery_watches (user_id, probe, expires_at) VALUES (?,?,?)",
            (user_id, probe, expires_at.isoformat()),
        )
        await db.commit()


async def _clear_watch(user_id: int) -> None:
    await _ensure_watch_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM wf_recovery_watches WHERE user_id=?", (user_id,))
        await db.commit()


async def _watch(user: discord.abc.User, probe: str = "default") -> None:
    _register_probes()
    fetch_fn = _PROBE_FETCHERS.get(probe, _PROBE_FETCHERS["default"])
    elapsed = 0
    deadline = _MAX_MINUTES * 60
    try:
        while elapsed < deadline:
            await asyncio.sleep(_POLL_SECONDS)
            elapsed += _POLL_SECONDS
            try:
                data = await fetch_fn()
            except Exception:
                data = None
            ok = bool(data)
            if isinstance(data, dict):
                ok = any(v is not None for v in data.values())
            if ok:
                try:
                    from core.safe_send import safe_dm
                    await safe_dm(
                        user,
                        embed=discord.Embed(
                            title="✅ Warframe data is back",
                            description="The Warframe API is responding again — re-run your command to see fresh data.",
                            color=discord.Color.green(),
                        )
                    )
                except Exception:
                    logger.debug("[wf_recovery] could not DM %s", getattr(user, "id", "?"))
                return
    finally:
        _pending.discard(user.id)
        await _clear_watch(user.id)


def watch_for_recovery(
    user: discord.abc.User,
    fetch_fn: Callable[[], Awaitable] | None = None,
    *,
    probe: str = "default",
) -> bool:
    """Start watching for API recovery. Returns False if already watching."""
    if user.id in _pending:
        return False
    _pending.add(user.id)
    if fetch_fn is not None:
        _register_probes()
        _PROBE_FETCHERS[probe] = fetch_fn
    expires = now_utc() + timedelta(minutes=_MAX_MINUTES)
    asyncio.create_task(_save_watch(user.id, probe, expires))
    asyncio.create_task(_watch(user, probe))
    return True


def is_watching(user_id: int) -> bool:
    return user_id in _pending


async def resume_persisted_watches(bot: discord.Client) -> int:
    """Re-start watches saved before a restart. Returns count resumed."""
    await _ensure_watch_table()
    _register_probes()
    now_iso = now_utc().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, probe FROM wf_recovery_watches WHERE expires_at > ?",
            (now_iso,),
        )
        rows = await cur.fetchall()
    count = 0
    for user_id, probe in rows:
        if int(user_id) in _pending:
            continue
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        if user:
            _pending.add(int(user_id))
            asyncio.create_task(_watch(user, str(probe or "default")))
            count += 1
    return count


def attach_notify_when_back(view: discord.ui.View, fetch_fn: Callable[[], Awaitable] | None = None):
    """Append a "Notify me when back" button to an existing view."""
    probe = "default"
    button = discord.ui.Button(
        label="Notify me when back",
        emoji="🔔",
        style=discord.ButtonStyle.secondary,
    )

    async def _callback(interaction: discord.Interaction):
        started = watch_for_recovery(interaction.user, fetch_fn, probe=probe)
        if started:
            await interaction.response.send_message(
                "🔔 I'll DM you when the Warframe API is back (checking for ~15 min, even across restarts).",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "You're already on the list — I'll DM you as soon as it's back.",
                ephemeral=True,
            )

    button.callback = _callback
    view.add_item(button)
    return view
