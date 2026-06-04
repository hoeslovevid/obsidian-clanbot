"""Pace Discord message edits per channel to reduce 429 rate limits."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import discord  # type: ignore

logger = logging.getLogger(__name__)

CHANNEL_EDIT_MIN_INTERVAL = float(os.getenv("CHANNEL_EDIT_MIN_INTERVAL", "1.25"))

_channel_last_edit: dict[int, float] = {}
_channel_locks: dict[int, asyncio.Lock] = {}


async def safe_message_edit(message: discord.Message, **kwargs: Any) -> bool:
    """Edit a message with minimum spacing between edits in the same channel."""
    ch_id = message.channel.id
    lock = _channel_locks.setdefault(ch_id, asyncio.Lock())
    async with lock:
        last = _channel_last_edit.get(ch_id, 0.0)
        wait = CHANNEL_EDIT_MIN_INTERVAL - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await message.edit(**kwargs)
            _channel_last_edit[ch_id] = time.monotonic()
            return True
        except discord.HTTPException as exc:
            if exc.status == 429:
                logger.debug(
                    "[safe_edit] rate limited channel=%s message=%s",
                    ch_id,
                    message.id,
                )
            raise
