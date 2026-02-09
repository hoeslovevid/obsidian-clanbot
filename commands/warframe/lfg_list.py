"""LFG list command to view active groups."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH
from views import EmbedPaginator
import aiosqlite

ITEMS_PER_PAGE = 5


def setup(bot, group=None):
    """Register the lfg_list command."""
    command_decorator = group.command(name="lfg_list", description="View active Looking for Group posts.") if group else bot.tree.command(name="lfg_list", description="View active Looking for Group posts.")
    
    @command_decorator
    @app_commands.describe(mission_type="Filter by mission type (optional)")
    async def lfg_list(interaction: discord.Interaction, mission_type: str = None):
        """Display active LFG posts."""
        async with aiosqlite.connect(DB_PATH) as db:
            if mission_type:
                cur = await db.execute("""
                    SELECT id, creator_id, mission_type, max_players, description, expires_at, created_at, message_id
                    FROM lfg_posts
                    WHERE guild_id=? AND channel_id=? AND status='OPEN' AND mission_type LIKE ?
                    ORDER BY created_at DESC
                    LIMIT 50
                """, (interaction.guild.id, interaction.channel.id, f"%{mission_type}%"))
            else:
                cur = await db.execute("""
                    SELECT id, creator_id, mission_type, max_players, description, expires_at, created_at, message_id
                    FROM lfg_posts
                    WHERE guild_id=? AND channel_id=? AND status='OPEN'
                    ORDER BY created_at DESC
                    LIMIT 50
                """, (interaction.guild.id, interaction.channel.id))
            
            posts = await cur.fetchall()

            # Fetch RSVP counts for all posts in one query
            counts_by_id = {}
            if posts:
                ids = [p[0] for p in posts]
                placeholders = ",".join(["?"] * len(ids))
                cur = await db.execute(
                    f"SELECT lfg_id, COUNT(*) FROM lfg_rsvps WHERE response='JOIN' AND lfg_id IN ({placeholders}) GROUP BY lfg_id",
                    tuple(ids),
                )
                for lfg_id, cnt in await cur.fetchall():
                    counts_by_id[int(lfg_id)] = int(cnt)
        
        if not posts:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "🔍 No Active Groups",
                    "There are no active LFG posts in this channel.\n\nUse `/lfg` to create one!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build pages (5 posts per page)
        pages = []
        for i in range(0, len(posts), ITEMS_PER_PAGE):
            page_posts = posts[i : i + ITEMS_PER_PAGE]
            fields = []
            for lfg_id, creator_id, mission_type_val, max_players, description, expires_at, created_at, message_id in page_posts:
                rsvp_count = counts_by_id.get(int(lfg_id), 0)

                creator = interaction.guild.get_member(creator_id)
                creator_name = creator.display_name if creator else f"User {creator_id}"

                try:
                    expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    time_remaining = expiry_dt - datetime.now(timezone.utc)
                    if time_remaining.total_seconds() > 0:
                        hours = int(time_remaining.total_seconds() // 3600)
                        time_str = f"Expires in {hours}h" if hours > 0 else "Expiring soon"
                    else:
                        time_str = "Expired"
                except Exception:
                    time_str = "Unknown"

                value = f"👥 {rsvp_count}/{max_players} players\n"
                value += f"👤 {creator_name}\n"
                value += f"⏰ {time_str}\n"
                if description:
                    value += f"📝 _{description[:60]}{'...' if len(description) > 60 else ''}_\n"
                jump_link = ""
                if message_id and interaction.channel.id:
                    jump_link = f"\n[Jump to post](https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{message_id})"
                value += f"`ID: {lfg_id}`{jump_link}"

                fields.append((f"🎯 {mission_type_val}", value, True))

            desc = f"**{len(posts)}** active group{'s' if len(posts) != 1 else ''} in this channel"
            pages.append({"description": desc, "fields": fields})

        if len(pages) == 1:
            embed = obsidian_embed(
                "🔍 Active LFG Posts",
                pages[0]["description"],
                color=discord.Color.blue(),
                fields=pages[0]["fields"],
                client=interaction.client,
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            view = EmbedPaginator("🔍 Active LFG Posts", pages, color=discord.Color.blue(), client=interaction.client)
            await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=False)
