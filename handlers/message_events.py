"""Primary on_message pipeline: mentions, tickets, automod, economy, AFK."""
from __future__ import annotations

import logging

import discord  # type: ignore

from core.config import ECONOMY_ENABLED, OPENAI_API_KEY
from core.db import is_db_locked_error, open_db
from core.utils import is_mod, obsidian_embed
from database import get_afk_status, now_utc, remove_afk
from handlers.automod import check_auto_mod
from handlers.message_economy import award_message_economy

logger = logging.getLogger(__name__)


async def handle_on_message(bot: discord.Client, message: discord.Message) -> None:
    """Check auto-moderation violations and award coins for text messages."""
    if message.author.bot or not message.guild:
        return

    if message.guild.me in message.mentions:
        try:
            from core.mention_chat import get_mention_reply
            from core.embed_footers import footer_for
            from core.embed_templates import embed_template

            reply = await get_mention_reply(
                message.content,
                message.guild.me.id,
                OPENAI_API_KEY,
                bot=bot,
            )
            embed = embed_template(
                "showcase",
                "💬 Obsidian Bot",
                reply,
                category="general",
                footer=footer_for("mention"),
                client=bot,
            )
            await message.reply(embed=embed, mention_author=False)
            return
        except discord.Forbidden:
            pass

    try:
        if (
            isinstance(message.channel, discord.TextChannel)
            and message.channel.category
            and message.channel.category.name == "Tickets"
        ):
            now_iso = now_utc().isoformat()
            is_staff = isinstance(message.author, discord.Member) and is_mod(message.author)
            new_status = None
            async with open_db() as db:
                cur = await db.execute(
                    "SELECT user_id FROM tickets WHERE guild_id=? AND channel_id=? AND status!='closed'",
                    (message.guild.id, message.channel.id),
                )
                owner_row = await cur.fetchone()
                if owner_row:
                    owner_id = int(owner_row[0])
                    if is_staff:
                        new_status = "awaiting_member"
                    elif message.author.id == owner_id:
                        new_status = "awaiting_staff"
                await db.execute(
                    """
                    UPDATE tickets
                    SET last_activity_at=?,
                        status=COALESCE(?, status),
                        first_response_at=CASE
                            WHEN ?=1 AND (first_response_at IS NULL OR first_response_at='') THEN ?
                            ELSE first_response_at
                        END
                    WHERE guild_id=? AND channel_id=? AND status!='closed'
                    """,
                    (
                        now_iso,
                        new_status,
                        1 if is_staff else 0,
                        now_iso,
                        message.guild.id,
                        message.channel.id,
                    ),
                )
                await db.commit()
            if new_status:
                from commands.tickets.ticket import sync_ticket_status_for_channel

                await sync_ticket_status_for_channel(message.guild, message.channel.id, new_status)
    except Exception:
        pass

    violation_handled = await check_auto_mod(bot, message)
    if violation_handled:
        return

    try:
        from core.typo_helper import maybe_suggest_command

        await maybe_suggest_command(message, bot)
    except Exception as typo_err:
        logger.debug(f"[typo_helper] error: {typo_err}")

    if not ECONOMY_ENABLED:
        return

    try:
        from core.utils import feature_enabled

        if not await feature_enabled(message.guild.id, "economy_passive"):
            return
    except Exception:
        pass

    if message.content.startswith("!"):
        return

    try:
        await award_message_economy(bot, message)
    except Exception as econ_err:
        if is_db_locked_error(econ_err):
            logger.warning(
                "Message economy skipped (database locked): guild=%s user=%s",
                message.guild.id,
                message.author.id,
            )
            return
        logger.error("Message economy error: %s", econ_err, exc_info=True)
        return

    if isinstance(message.author, discord.Member):
        try:
            from commands.moderation.inactive_role import maybe_clear_inactive_role

            await maybe_clear_inactive_role(message.author)
        except Exception:
            pass

    if message.mentions:
        for mentioned_user in message.mentions:
            if mentioned_user.id != message.author.id and not mentioned_user.bot:
                afk_status = await get_afk_status(message.guild.id, mentioned_user.id)
                if afk_status:
                    reason_text = f" - {afk_status['reason']}" if afk_status["reason"] else ""
                    try:
                        await message.channel.send(
                            embed=obsidian_embed(
                                "💤 User is AFK",
                                f"{mentioned_user.mention} is currently AFK{reason_text}",
                                color=discord.Color.orange(),
                                client=bot,
                            )
                        )
                    except Exception:
                        pass

    if not message.author.bot:
        afk_status = await get_afk_status(message.guild.id, message.author.id)
        if afk_status:
            await remove_afk(message.guild.id, message.author.id)
            if isinstance(message.author, discord.Member):
                try:
                    if message.author.display_name.startswith("[AFK]"):
                        new_nick = (
                            message.author.display_name.replace("[AFK] ", "")
                            .replace("[AFK]", "")
                            .strip()
                        )
                        if not new_nick:
                            new_nick = None
                        await message.author.edit(nick=new_nick)
                except Exception:
                    pass
