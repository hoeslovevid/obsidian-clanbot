"""List active giveaways command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH
from views import EmbedPaginator
import aiosqlite

ITEMS_PER_PAGE = 15


def setup(bot, group=None):
    """Register the giveaway_list and my_entries commands."""

    my_entries_decorator = group.command(name="my_entries", description="List giveaways you've entered.") if group else None
    if my_entries_decorator:
        @my_entries_decorator
        async def my_entries(interaction: discord.Interaction):
            """List giveaways the user has entered."""
            if not interaction.guild:
                return await interaction.response.send_message(
                    embed=obsidian_embed("❌ Invalid Context", "Use in a server.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT g.id, g.title, g.prize, g.winner_count, g.end_time, g.channel_id, g.message_id
                    FROM giveaways g
                    JOIN giveaway_entries e ON g.id = e.giveaway_id
                    WHERE g.guild_id = ? AND e.user_id = ? AND g.ended = 0
                    ORDER BY g.end_time ASC
                    LIMIT 15
                """, (interaction.guild.id, interaction.user.id))
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "🎉 No Giveaway Entries",
                        "You haven't entered any active giveaways. Use `/giveaways giveaway_list` to see open giveaways.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            lines = []
            for gid, title, prize, winner_count, end_time_str, ch_id, msg_id in rows:
                try:
                    end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                    ts = int(end_time.timestamp())
                    jump = f" [Jump](https://discord.com/channels/{interaction.guild.id}/{ch_id}/{msg_id})" if ch_id and msg_id else ""
                    lines.append(f"**{title}** — {prize}\nEnds <t:{ts}:R>{jump}")
                except Exception:
                    lines.append(f"**{title}** — {prize}")
            await interaction.followup.send(
                embed=obsidian_embed("🎉 My Giveaway Entries", "\n\n".join(lines), color=discord.Color.gold(), client=interaction.client),
                ephemeral=True,
            )

    command_decorator = group.command(name="giveaway_list", description="List all active giveaways.") if group else bot.tree.command(name="giveaway_list", description="List all active giveaways.")
    
    @command_decorator
    async def giveaway_list(interaction: discord.Interaction):
        """List all active giveaways in the server."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, channel_id, message_id, title, prize, winner_count, end_time, ended
                FROM giveaways
                WHERE guild_id = ? AND ended = 0
                ORDER BY end_time ASC
            """, (interaction.guild.id,))
            rows = await cur.fetchall()

            # Get all entry counts in one query (same connection)
            entry_counts = {row[0]: 0 for row in rows}
            if rows:
                placeholders = ",".join("?" * len(rows))
                giveaway_ids = [row[0] for row in rows]
                cur = await db.execute(
                    f"SELECT giveaway_id, COUNT(*) FROM giveaway_entries WHERE giveaway_id IN ({placeholders}) GROUP BY giveaway_id",
                    giveaway_ids,
                )
                for gid, count in await cur.fetchall():
                    entry_counts[gid] = count

        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 No Active Giveaways",
                    "There are currently no active giveaways in this server.\n\nUse `/giveaways giveaway` to create one!",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        pages = []
        for i in range(0, len(rows), ITEMS_PER_PAGE):
            page_rows = rows[i : i + ITEMS_PER_PAGE]
            description = ""
            for row in page_rows:
                giveaway_id, channel_id, message_id, title, prize, winner_count, end_time_str, ended = row
                channel = interaction.guild.get_channel(channel_id)
                channel_name = f"#{channel.name}" if channel else f"Channel {channel_id}"
                entry_count = entry_counts.get(giveaway_id, 0)

                try:
                    end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                    time_remaining = end_time - datetime.now(timezone.utc)
                    ts = int(end_time.replace(tzinfo=timezone.utc).timestamp())

                    if time_remaining.total_seconds() <= 0:
                        time_str = f"Ended (<t:{ts}:R>)"
                    else:
                        days = time_remaining.days
                        hours, remainder = divmod(time_remaining.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        countdown = ""
                        if days > 0:
                            countdown += f"{days}d "
                        if hours > 0:
                            countdown += f"{hours}h "
                        if minutes > 0:
                            countdown += f"{minutes}m"
                        if not countdown:
                            countdown = "Less than 1m"
                        time_str = f"<t:{ts}:R> ({countdown.strip()})"
                except Exception:
                    time_str = "Unknown"

                description += f"**{title}**\n"
                description += f"Prize: {prize}\n"
                description += f"Winners: {winner_count} | Entries: {entry_count}\n"
                description += f"Ends: {time_str} | {channel_name}\n"
                description += f"[Jump](https://discord.com/channels/{interaction.guild.id}/{channel_id}/{message_id})\n\n"

            pages.append({"description": description.strip()})

        if len(pages) == 1:
            embed = obsidian_embed(
                "🎉 Active Giveaways",
                pages[0]["description"],
                color=discord.Color.gold(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer=f"{len(rows)} active giveaway(s)",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            view = EmbedPaginator(
                "🎉 Active Giveaways", pages, color=discord.Color.gold(), client=interaction.client,
                total_items=len(rows), per_page=ITEMS_PER_PAGE
            )
            await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)
