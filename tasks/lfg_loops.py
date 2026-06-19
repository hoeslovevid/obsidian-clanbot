"""LFG post lifecycle loops (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def run_lfg_expire_cycle(bot: discord.Client) -> None:
    """Auto-expire LFG posts that have passed their expiry time."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(timezone.utc).isoformat()
    
        # Find expired posts
        cur = await db.execute("""
            SELECT id, guild_id, channel_id, message_id, thread_id
            FROM lfg_posts
            WHERE status='OPEN' AND expires_at < ?
        """, (now,))
    
        expired = await cur.fetchall()
    
        for lfg_id, guild_id, channel_id, message_id, thread_id in expired:
            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
            
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
            
                try:
                    message = await channel.fetch_message(message_id)
                
                    # Update embed
                    embed = message.embeds[0] if message.embeds else None
                    if embed:
                        embed.color = discord.Color.grey()
                        embed.set_footer(text="⏰ Expired")
                    
                        # Disable buttons
                        view = discord.ui.View()
                        for item in message.components[0].children if message.components else []:
                            if hasattr(item, 'disabled'):
                                item.disabled = True
                                view.add_item(item)
                    
                        await message.edit(embed=embed, view=view)
                except discord.NotFound:
                    pass
            
                # Mark as expired in database
                await db.execute(
                    "UPDATE lfg_posts SET status='EXPIRED' WHERE id=?",
                    (lfg_id,)
                )
                await db.commit()

                try:
                    from core.lfg_extras import post_lfg_thread_summary
                    await post_lfg_thread_summary(
                        bot, guild_id, lfg_id, thread_id, reason="expired",
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error expiring LFG post {lfg_id}: {e}", exc_info=True)
                continue


async def run_lfg_scheduled_reminder_cycle(bot: discord.Client) -> None:
    """DM creators ~15 minutes before scheduled LFG start time."""
    import dateparser
    from core.embed_templates import embed_template
    from core.embed_footers import footer_for
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, guild_id, creator_id, mission_type, scheduled_at
            FROM lfg_posts
            WHERE status='OPEN' AND scheduled_at IS NOT NULL AND scheduled_at != ''
              AND COALESCE(reminder_sent, 0) = 0
        """)
        rows = await cur.fetchall()
    now = now_utc()
    for lfg_id, guild_id, creator_id, mission, sched_raw in rows:
        try:
            sched_dt = dateparser.parse(
                sched_raw,
                settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if not sched_dt:
                continue
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=timezone.utc)
            delta = (sched_dt - now).total_seconds()
            if not (0 < delta <= 15 * 60):
                continue
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            member = guild.get_member(creator_id)
            if member:
                await safe_dm(member,
                    embed=embed_template(
                        "showcase",
                        "⏰ LFG starting soon",
                        f"Your **{mission}** squad is scheduled for <t:{int(sched_dt.timestamp())}:R>.\n"
                        f"Head to your LFG post to rally your squad.",
                        category="community",
                        footer=footer_for("community_lfg"),
                        client=bot,
                    ),
                )
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE lfg_posts SET reminder_sent=1 WHERE id=?",
                    (lfg_id,),
                )
                await db.commit()
        except Exception as e:
            logger.debug("[lfg_reminder] %s: %s", lfg_id, e)


async def run_lfg_bump_cycle(bot: discord.Client) -> None:
    """Bump stale LFG posts with no replies after 30+ minutes."""
    if not bot.is_ready():
        return
    from database import get_guild_setting, set_guild_setting

    cutoff = (now_utc() - timedelta(minutes=30)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id, guild_id, channel_id, message_id
            FROM lfg_posts
            WHERE status='OPEN' AND datetime(created_at) <= datetime(?)
            """,
            (cutoff,),
        )
        rows = await cur.fetchall()
    for lfg_id, guild_id, channel_id, message_id in rows:
        try:
            if await get_guild_setting(int(guild_id), f"lfg_bumped:{lfg_id}"):
                continue
            guild = bot.get_guild(int(guild_id))
            if not guild:
                continue
            ch = guild.get_channel(int(channel_id))
            if not isinstance(ch, discord.TextChannel):
                continue
            msg = await ch.fetch_message(int(message_id))
            if msg.thread and getattr(msg.thread, "message_count", 0) > 1:
                continue
            from core.safe_send import safe_channel_send
            await safe_channel_send(
                ch,
                content=f"👋 Still looking for squad — {msg.jump_url}",
                delete_after=3600,
            )
            await set_guild_setting(int(guild_id), f"lfg_bumped:{lfg_id}", "1")
        except Exception as exc:
            logger.debug("[lfg_bump] %s: %s", lfg_id, exc)


async def run_lfg_poster_nudge_cycle(bot: discord.Client) -> None:
    """DM LFG creators after ~2h with no thread replies."""
    if not bot.is_ready():
        return
    from database import get_guild_setting, set_guild_setting

    cutoff = (now_utc() - timedelta(hours=2)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id, guild_id, creator_id, message_id, channel_id, mission_type
            FROM lfg_posts
            WHERE status='OPEN' AND datetime(created_at) <= datetime(?)
            """,
            (cutoff,),
        )
        rows = await cur.fetchall()
    for lfg_id, guild_id, creator_id, message_id, channel_id, mission in rows:
        try:
            if await get_guild_setting(int(guild_id), f"lfg_creator_nudged:{lfg_id}"):
                continue
            guild = bot.get_guild(int(guild_id))
            if not guild:
                continue
            ch = guild.get_channel(int(channel_id))
            if not isinstance(ch, discord.TextChannel):
                continue
            msg = await ch.fetch_message(int(message_id))
            if msg.thread and getattr(msg.thread, "message_count", 0) > 1:
                continue
            user = guild.get_member(int(creator_id)) or bot.get_user(int(creator_id))
            if not user:
                continue
            from core.quiet_hours import in_quiet_hours
            if await in_quiet_hours(int(guild_id), int(creator_id)):
                continue
            await safe_dm(user,
                embed=obsidian_embed(
                    "👋 Still looking for squad?",
                    f"Your **{mission}** LFG has had no replies for 2+ hours.\n\n"
                    f"[Jump to post]({msg.jump_url}) — bump in chat or mark filled when done.",
                    client=bot,
                )
            )
            await set_guild_setting(int(guild_id), f"lfg_creator_nudged:{lfg_id}", "1")
        except Exception as exc:
            logger.debug("[lfg_nudge] %s: %s", lfg_id, exc)

