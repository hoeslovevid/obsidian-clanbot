"""Trading listing expiry loops (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def run_trading_expire_cycle(bot: discord.Client) -> None:
    """Expire stale trading posts and DM owners to renew."""
    from core.utils import obsidian_embed
    from database import get_guild_setting, set_guild_setting
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    soon = (now_dt + timedelta(hours=24)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id, guild_id, user_id, item_name, listing_type
            FROM trading_posts
            WHERE status='ACTIVE' AND expires_at IS NOT NULL
              AND expires_at > ? AND expires_at <= ?
            """,
            (now, soon),
        )
        expiring_soon = await cur.fetchall()
        for listing_id, guild_id, user_id, item_name, listing_type in expiring_soon:
            if await get_guild_setting(guild_id, f"trade_expiry_warned:{listing_id}"):
                continue
            guild = bot.get_guild(int(guild_id))
            member = guild.get_member(int(user_id)) if guild else None
            if member:
                try:
                    from core.quiet_hours import in_quiet_hours
                    if not await in_quiet_hours(guild_id, user_id):
                        await safe_dm(member,
                            embed=obsidian_embed(
                                "⏰ Listing expires soon",
                                f"Your **{listing_type}** for **{item_name}** expires within 24 hours.\n\n"
                                "Repost with `/trading trade` when it expires.",
                                color=discord.Color.orange(),
                                client=bot,
                            )
                        )
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await set_guild_setting(guild_id, f"trade_expiry_warned:{listing_id}", "1")

        cur = await db.execute("""
            SELECT id, guild_id, user_id, item_name, listing_type, message_id, channel_id
            FROM trading_posts
            WHERE status='ACTIVE' AND expires_at IS NOT NULL AND expires_at < ?
        """, (now,))
        expired = await cur.fetchall()

        for listing_id, guild_id, user_id, item_name, listing_type, message_id, channel_id in expired:
            try:
                guild = bot.get_guild(guild_id)
                if guild and message_id and channel_id:
                    channel = guild.get_channel(int(channel_id))
                    if isinstance(channel, discord.TextChannel):
                        try:
                            msg = await channel.fetch_message(int(message_id))
                            if msg.embeds:
                                embed = msg.embeds[0]
                                embed.color = discord.Color.greyple()
                                embed.set_footer(text="⏰ Listing expired — repost with /trading trade")
                                await msg.edit(embed=embed, view=None)
                        except discord.NotFound:
                            pass
                        except discord.HTTPException:
                            pass

                member = guild.get_member(int(user_id)) if guild else None
                if member:
                    try:
                        dm = obsidian_embed(
                            "⏰ Trading Listing Expired",
                            f"Your **{listing_type}** listing for **{item_name}** expired after 14 days.\n\n"
                            f"Run **`/trading trade`** in **{guild.name if guild else 'the server'}** "
                            f"to post a fresh listing.",
                            color=discord.Color.orange(),
                            client=bot,
                        )
                        await safe_dm(member,embed=dm)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                await db.execute(
                    "UPDATE trading_posts SET status='EXPIRED', updated_at=? WHERE id=?",
                    (now, listing_id),
                )
                await db.commit()
            except Exception as e:
                logger.error(f"Error expiring trading post {listing_id}: {e}", exc_info=True)

