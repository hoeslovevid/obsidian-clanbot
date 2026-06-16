"""Opt-in "notify me when the Warframe API is back" helper.

Self-contained: when a user opts in, we spawn a short-lived background task that
polls a cheap fetch function and DMs the user once it succeeds. No global loop,
no persistence — interest is dropped on bot restart or after the watch window.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import discord  # type: ignore

logger = logging.getLogger(__name__)

# user_ids currently being watched (dedupe so we don't spawn duplicate watchers)
_pending: set[int] = set()

_POLL_SECONDS = 30
_MAX_MINUTES = 15


async def _watch(user: discord.abc.User, fetch_fn: Callable[[], Awaitable]) -> None:
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
                    await user.send(
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


def watch_for_recovery(user: discord.abc.User, fetch_fn: Callable[[], Awaitable]) -> bool:
    """Start watching for API recovery for ``user``. Returns False if already watching."""
    if user.id in _pending:
        return False
    _pending.add(user.id)
    asyncio.create_task(_watch(user, fetch_fn))
    return True


def is_watching(user_id: int) -> bool:
    return user_id in _pending


def attach_notify_when_back(view: discord.ui.View, fetch_fn: Callable[[], Awaitable]) -> None:
    """Append a "Notify me when back" button to an existing view."""
    button = discord.ui.Button(
        label="Notify me when back",
        emoji="🔔",
        style=discord.ButtonStyle.secondary,
    )

    async def _callback(interaction: discord.Interaction):
        started = watch_for_recovery(interaction.user, fetch_fn)
        if started:
            await interaction.response.send_message(
                "🔔 I'll DM you when the Warframe API is back (checking for ~15 min).",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "You're already on the list — I'll DM you as soon as it's back.",
                ephemeral=True,
            )

    button.callback = _callback
    view.add_item(button)
