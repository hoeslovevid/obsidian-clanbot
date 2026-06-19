"""Miscellaneous lightweight background ticks."""
from __future__ import annotations

import logging

import discord  # type: ignore

logger = logging.getLogger(__name__)


async def run_music_auto_leave_cycle(bot: discord.Client) -> None:
    if not bot.is_ready():
        return
    from core.music_player import music_auto_leave_tick

    await music_auto_leave_tick(bot)


async def run_price_watch_cycle(bot: discord.Client) -> None:
    if not bot.is_ready():
        return
    from core.price_watchlist import check_price_watches

    await check_price_watches(bot)
