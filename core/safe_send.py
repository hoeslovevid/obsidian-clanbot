"""Resilient channel send with optional DM fallback.

When the bot lacks permission to post in a channel (or the channel is gone),
a normal ``channel.send`` raises and the notification is silently lost. These
helpers degrade gracefully: try the channel, then optionally DM the user, and
never raise.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import discord  # type: ignore

logger = logging.getLogger(__name__)


async def safe_channel_send(
    channel: Optional[discord.abc.Messageable],
    *,
    dm_user: Optional[discord.abc.User] = None,
    **send_kwargs: Any,
) -> Optional[discord.Message]:
    """Send to ``channel``; on permission/availability failure, DM ``dm_user``.

    Returns the sent message, or ``None`` if every delivery path failed.
    All exceptions are swallowed (logged at debug/warning) so callers in
    background loops never crash.
    """
    if channel is not None:
        try:
            return await channel.send(**send_kwargs)
        except (discord.Forbidden, discord.NotFound) as exc:
            logger.warning(
                "[safe_send] channel send failed (%s) in channel=%s; trying DM fallback",
                type(exc).__name__,
                getattr(channel, "id", None),
            )
        except discord.HTTPException as exc:
            logger.debug("[safe_send] channel send HTTP error: %s", exc)
            return None

    if dm_user is not None:
        try:
            return await dm_user.send(**send_kwargs)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.debug("[safe_send] DM fallback failed for %s: %s", dm_user, exc)

    return None
