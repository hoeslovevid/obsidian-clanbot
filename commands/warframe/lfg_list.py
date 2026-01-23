"""LFG list command to view active groups."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite


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
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build fields for each LFG post
        fields = []
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
            
            value = f"👥 {rsvp_count}/{max_players} players\n"
            value += f"👤 {creator_name}\n"
            value += f"⏰ {time_str}\n"
            if description:
                value += f"📝 _{description[:60]}{'...' if len(description) > 60 else ''}_\n"
            value += f"`ID: {lfg_id}`"
            
            fields.append((f"🎯 {mission_type_val}", value, True))
        
        embed = obsidian_embed(
            f"🔍 Active LFG Posts",
            f"**{len(posts)}** active group{'s' if len(posts) != 1 else ''} in this channel",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
