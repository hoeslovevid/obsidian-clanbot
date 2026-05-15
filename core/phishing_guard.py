"""
Runtime hook for phishing heuristics: react, optional DM, optional mod log.

Never deletes messages or applies moderation actions.
"""
from __future__ import annotations

import json
import logging
import re

import discord  # type: ignore

from core.phishing_scanner import message_looks_phishy, normalize_domain
from core.utils import obsidian_embed
from database import get_guild_setting

logger = logging.getLogger(__name__)

_MENTION_SPAM_RE = re.compile(r"<@[!&]?\d+>")


async def maybe_flag_phishing_message(message: discord.Message, bot: discord.Client) -> None:
    """If enabled for the guild and content matches heuristics, flag without punishing."""
    if not message.guild or message.author.bot:
        return
    content = (message.content or "").strip()
    if not content:
        return
    if await get_guild_setting(message.guild.id, "phishing_enabled") != "1":
        return

    raw_list = await get_guild_setting(message.guild.id, "phishing_allowlist") or ""
    allow: set[str] = set()
    if raw_list:
        try:
            data = json.loads(raw_list)
            if isinstance(data, list):
                allow = {normalize_domain(str(x)) for x in data}
        except json.JSONDecodeError:
            allow = {normalize_domain(p) for p in raw_list.split(",")}
    allow = {x for x in allow if x}

    if not message_looks_phishy(message.content or "", frozenset(allow)):
        return

    try:
        await message.add_reaction("\u26a0\ufe0f")
    except Exception:
        pass

    try:
        await message.author.send(
            "Your message in **{g}** may contain a suspicious link — please verify URLs before clicking.".format(
                g=message.guild.name
            )
        )
    except Exception:
        pass

    log_raw = await get_guild_setting(message.guild.id, "phishing_log_channel_id")
    if log_raw and str(log_raw).isdigit():
        ch = message.guild.get_channel(int(log_raw))
        if ch and isinstance(ch, discord.TextChannel):
            safe = _MENTION_SPAM_RE.sub("[mention]", content)
            preview = safe[:800] + ("..." if len(safe) > 800 else "")
            loc = message.channel.mention if isinstance(message.channel, discord.TextChannel) else f"#{getattr(message.channel, 'name', '?')}"
            embed = obsidian_embed(
                "\u26a0\ufe0f Phishing heuristic hit",
                f"**Author:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Channel:** {loc}\n"
                f"**Message:** [jump]({message.jump_url})\n\n**Content (trimmed):** {preview}",
                category="moderation",
                client=bot,
            )
            try:
                await ch.send(embed=embed)
            except Exception as e:
                logger.debug("[phishing] log channel send failed: %s", e)
