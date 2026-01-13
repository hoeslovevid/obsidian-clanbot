"""LFG list command to view active groups."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from bot import DB_PATH
import aiosqlite


def setup(bot):
    """Register the lfg_list command."""
    @bot.tree.command(name="lfg_list", description="View active Looking for Group posts.")
    @app_commands.describe(mission_type="Filter by mission type (optional)")
    async def lfg_list(interaction: discord.Interaction, mission_type: str = None):
        """Display active LFG posts."""
        async with aiosqlite.connect(DB_PATH) as db:
            if mission_type:
                cur = await db.execute("""
                    SELECT id, creator_id, mission_type, max_players, description, expires_at, created_at
                    FROM lfg_posts
                    WHERE guild_id=? AND channel_id=? AND status='OPEN' AND mission_type LIKE ?
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (interaction.guild.id, interaction.channel.id, f"%{mission_type}%"))
            else:
                cur = await db.execute("""
                    SELECT id, creator_id, mission_type, max_players, description, expires_at, created_at
                    FROM lfg_posts
                    WHERE guild_id=? AND channel_id=? AND status='OPEN'
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (interaction.guild.id, interaction.channel.id))
            
            posts = await cur.fetchall()
        
        if not posts:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "🔍 No Active Groups",
                    "There are no active LFG posts in this channel.\n\nUse `/lfg` to create one!",
                    color=discord.Color.orange(),
                ),
                ephemeral=True
            )
        
        desc = ""
        for lfg_id, creator_id, mission_type_val, max_players, description, expires_at, created_at in posts:
            # Get RSVP count
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN'",
                    (lfg_id,)
                )
                rsvp_count = (await cur.fetchone())[0]
            
            creator = interaction.guild.get_member(creator_id)
            creator_name = creator.display_name if creator else f"User {creator_id}"
            
            # Parse expiry time
            try:
                expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                time_remaining = expiry_dt - datetime.now(timezone.utc)
                if time_remaining.total_seconds() > 0:
                    hours = int(time_remaining.total_seconds() // 3600)
                    time_str = f"{hours}h remaining" if hours > 0 else "Expiring soon"
                else:
                    time_str = "Expired"
            except Exception:
                time_str = "Unknown"
            
            desc += f"**{mission_type_val}** - {rsvp_count}/{max_players} players\n"
            desc += f"Created by: {creator_name} • {time_str}\n"
            if description:
                desc += f"_{description[:50]}{'...' if len(description) > 50 else ''}_\n"
            desc += f"ID: {lfg_id}\n\n"
        
        embed = obsidian_embed(
            f"🔍 Active LFG Posts ({len(posts)})",
            desc,
            color=discord.Color.blue(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
