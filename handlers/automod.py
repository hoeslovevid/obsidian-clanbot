"""Auto-moderation message checks (extracted from bot/app.py)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import discord  # type: ignore

from core.utils import obsidian_embed
from database import now_utc

logger = logging.getLogger(__name__)


def channel_mention_safe(channel: Any) -> str:
    if hasattr(channel, "mention"):
        return channel.mention
    return f"#unknown-channel"


async def check_auto_mod(bot: discord.Client, message: discord.Message) -> bool:
    """Check message for auto-moderation violations. Returns True if message was handled."""
    from database import (
        get_auto_mod_settings,
        get_spam_tracking,
        log_auto_mod_violation,
        reset_spam_tracking,
        update_spam_tracking,
    )
    from core.utils import is_mod

    if not message.guild or message.author.bot:
        return False

    if isinstance(message.author, discord.Member) and is_mod(message.author):
        return False

    settings = await get_auto_mod_settings(message.guild.id)
    if not settings or not settings["enabled"]:
        return False

    violation_type = None
    action_taken = "none"

    if settings["spam_enabled"]:
        now_iso = now_utc().isoformat()
        tracking = await get_spam_tracking(message.guild.id, message.author.id)

        if tracking:
            first_msg_time = datetime.fromisoformat(tracking["first_message_time"])
            time_diff = (now_utc() - first_msg_time).total_seconds()

            if time_diff <= settings["spam_interval"]:
                new_count = tracking["message_count"] + 1
                await update_spam_tracking(
                    message.guild.id,
                    message.author.id,
                    new_count,
                    tracking["first_message_time"],
                    now_iso,
                )
                if new_count >= settings["spam_threshold"]:
                    violation_type = "spam"
                    await reset_spam_tracking(message.guild.id, message.author.id)
            else:
                await update_spam_tracking(
                    message.guild.id,
                    message.author.id,
                    1,
                    now_iso,
                    now_iso,
                )
        else:
            await update_spam_tracking(
                message.guild.id,
                message.author.id,
                1,
                now_iso,
                now_iso,
            )

    if not violation_type and settings["caps_enabled"] and len(message.content) >= settings["caps_min_length"]:
        caps_count = sum(1 for c in message.content if c.isupper())
        caps_percent = (caps_count / len(message.content)) * 100 if message.content else 0
        if caps_percent >= settings["caps_threshold"]:
            violation_type = "caps"

    if not violation_type and settings["links_enabled"]:
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        if re.search(url_pattern, message.content):
            whitelist = settings["links_whitelist"].split(",") if settings["links_whitelist"] else []
            if whitelist:
                allowed = any(
                    domain.strip() in message.content.lower()
                    for domain in whitelist
                    if domain.strip()
                )
                if not allowed:
                    violation_type = "links"
            else:
                violation_type = "links"

    if not violation_type and settings["mention_enabled"]:
        mention_count = len(message.mentions) + len(message.role_mentions) + len(message.channel_mentions)
        if mention_count > settings["mention_limit"]:
            violation_type = "mention"

    if not violation_type:
        return False

    action = settings["punishment_action"]
    duration = settings["punishment_duration"]

    try:
        await message.delete()
        action_taken = "delete"

        if action == "warn":
            action_taken = "delete + warn"
            try:
                from core.safe_send import safe_dm

                await safe_dm(
                    message.author,
                    embed=obsidian_embed(
                        "⚠️ Auto-moderation warning",
                        f"Your message in {channel_mention_safe(message.channel)} was removed for **{violation_type}**.\n\n"
                        "Please follow the server rules.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                )
            except Exception:
                pass

        elif action == "timeout" and isinstance(message.author, discord.Member):
            if duration:
                timeout_until = now_utc() + timedelta(minutes=duration)
                await message.author.timeout(timeout_until, reason=f"Auto-mod: {violation_type}")
                action_taken = f"delete + timeout ({duration}m)"
            else:
                action_taken = "delete + timeout (no duration set)"

        elif action == "kick" and isinstance(message.author, discord.Member):
            try:
                await message.author.kick(reason=f"Auto-mod: {violation_type}")
                action_taken = "delete + kick"
            except discord.Forbidden:
                action_taken = "delete (kick failed - no permission)"

        await log_auto_mod_violation(
            message.guild.id,
            message.author.id,
            violation_type,
            message.content[:500],
            action_taken,
        )
        try:
            from core.audit import log_audit

            await log_audit(
                message.guild.id,
                f"automod_{violation_type}",
                0,
                target_id=message.author.id,
                target_type="user",
                details=action_taken[:200],
                bot=bot,
            )
        except Exception:
            pass

        log_ch_id = settings.get("log_channel_id")
        try:
            from views._core import AutoModAppealView
            from core.safe_send import safe_dm

            appeal = AutoModAppealView(
                guild_id=message.guild.id,
                user_id=message.author.id,
                violation_type=violation_type,
                preview=message.content[:300],
                log_channel_id=int(log_ch_id) if log_ch_id else None,
            )
            await safe_dm(
                message.author,
                embed=obsidian_embed(
                    "🛡️ Message removed",
                    f"Auto-mod removed your message in {channel_mention_safe(message.channel)} "
                    f"for **{violation_type}**.\n\n"
                    "If this was a mistake, tap **Report false positive** below.",
                    color=discord.Color.orange(),
                    client=bot,
                ),
                view=appeal,
            )
        except Exception:
            pass

        if settings["log_channel_id"]:
            log_channel = message.guild.get_channel(settings["log_channel_id"])
            if isinstance(log_channel, discord.TextChannel):
                embed = obsidian_embed(
                    f"🛡️ Auto-Moderation Action: {violation_type.upper()}",
                    f"**User:** {message.author.mention} ({message.author.id})\n"
                    f"**Channel:** {channel_mention_safe(message.channel)}\n"
                    f"**Action:** {action_taken}\n"
                    f"**Message:** {message.content[:200]}",
                    color=discord.Color.red(),
                    client=bot,
                )
                try:
                    await log_channel.send(embed=embed)
                except Exception:
                    pass

        return True

    except discord.NotFound:
        return True
    except discord.Forbidden:
        logger.warning(
            "[automod] No permission to punish %s in %s",
            message.author.id,
            message.guild.id,
        )
        return False
    except Exception as e:
        logger.error("[automod] Error handling violation: %s", e, exc_info=True)
        return False
