"""List active giveaways command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH
from views import EmbedPaginator
import aiosqlite

ITEMS_PER_PAGE = 5


def setup(bot, group=None):
    """Register the giveaway_list command."""
    
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, channel_id, message_id, title, prize, winner_count, end_time, ended
                FROM giveaways
                WHERE guild_id = ? AND ended = 0
                ORDER BY end_time ASC
            """, (interaction.guild.id,))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "📋 No Active Giveaways",
                    "There are currently no active giveaways in this server.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        # Get all entry counts in one query
        entry_counts = {}
        async with aiosqlite.connect(DB_PATH) as db2:
            for row in rows:
                gid = row[0]
                cur2 = await db2.execute(
                    "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (gid,)
                )
                entry_counts[gid] = (await cur2.fetchone())[0]

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

                    if time_remaining.total_seconds() <= 0:
                        time_str = "Ended"
                    else:
                        days = time_remaining.days
                        hours, remainder = divmod(time_remaining.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        time_str = ""
                        if days > 0:
                            time_str += f"{days}d "
                        if hours > 0:
                            time_str += f"{hours}h "
                        if minutes > 0:
                            time_str += f"{minutes}m"
                        if not time_str:
                            time_str = "Less than 1m"
                except Exception:
                    time_str = "Unknown"

                description += f"**{title}**\n"
                description += f"Prize: {prize}\n"
                description += f"Winners: {winner_count} | Entries: {entry_count}\n"
                description += f"Ends: {time_str} | {channel_name}\n"
                description += f"[Jump](https://discord.com/channels/{interaction.guild.id}/{channel_id}/{message_id})\n\n"

            pages.append({"description": description.strip()})

        if len(pages) == 1:
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "🎉 Active Giveaways",
                    pages[0]["description"],
                    color=discord.Color.gold(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        else:
            view = EmbedPaginator("🎉 Active Giveaways", pages, color=discord.Color.gold(), client=interaction.client)
            await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)
