"""Server milestones tracking and celebration."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def check_and_celebrate_milestone(guild: discord.Guild, milestone_type: str, milestone_value: int) -> bool:
    """Check if a milestone should be celebrated and celebrate it. Returns True if celebrated."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if already celebrated
        cur = await db.execute("""
            SELECT 1 FROM server_milestones
            WHERE guild_id=? AND milestone_type=? AND milestone_value=?
        """, (guild.id, milestone_type, milestone_value))
        if await cur.fetchone():
            return False  # Already celebrated
        
        # Record milestone
        await db.execute("""
            INSERT INTO server_milestones (guild_id, milestone_type, milestone_value, achieved_at, announced)
            VALUES (?, ?, ?, ?, 0)
        """, (guild.id, milestone_type, milestone_value, now_utc().isoformat()))
        await db.commit()
        
        # Get announcement settings
        cur = await db.execute("""
            SELECT announcement_channel_id FROM server_milestone_settings
            WHERE guild_id=?
        """, (guild.id,))
        row = await cur.fetchone()
        announcement_channel_id = row[0] if row else None
        
        # Celebrate milestone
        if announcement_channel_id:
            channel = guild.get_channel(announcement_channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    if milestone_type == "member_count":
                        embed = obsidian_embed(
                            "🎉 Server Milestone Achieved!",
                            f"**{guild.name}** has reached **{milestone_value:,} members**!\n\n"
                            f"Thank you to everyone who has joined our community! 🎊",
                            color=discord.Color.gold(),
                            client=None,
                        )
                    elif milestone_type == "anniversary":
                        embed = obsidian_embed(
                            "🎂 Server Anniversary!",
                            f"**{guild.name}** is celebrating **{milestone_value} year(s)** of existence!\n\n"
                            f"Thank you to all members for being part of this amazing community! 🎊",
                            color=discord.Color.gold(),
                            client=None,
                        )
                    else:
                        embed = obsidian_embed(
                            "🎉 Milestone Achieved!",
                            f"**{guild.name}** has reached a new milestone!\n\n"
                            f"**Type:** {milestone_type}\n"
                            f"**Value:** {milestone_value:,}",
                            color=discord.Color.gold(),
                            client=None,
                        )
                    
                    await channel.send(embed=embed)
                    
                    # Mark as announced
                    await db.execute("""
                        UPDATE server_milestones SET announced = 1
                        WHERE guild_id=? AND milestone_type=? AND milestone_value=?
                    """, (guild.id, milestone_type, milestone_value))
                    await db.commit()
                    
                    return True
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Error celebrating milestone: {e}")
        
        return True  # Recorded even if not announced


def setup(bot, group=None):
    """Register milestone commands."""
    # Milestone settings command
    settings_decorator = group.command(name="milestone_settings", description="Configure server milestone announcements (moderators only).") if group else bot.tree.command(name="milestone_settings", description="Configure server milestone announcements (moderators only).")
    
    @settings_decorator
    @app_commands.describe(
        channel="Channel to send milestone announcements to",
        member_count_enabled="Enable member count milestones",
        anniversary_enabled="Enable server anniversary milestones"
    )
    async def milestone_settings(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        member_count_enabled: Optional[bool] = None,
        anniversary_enabled: Optional[bool] = None
    ):
        """Configure milestone settings."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure milestone settings.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Get current settings
            cur = await db.execute("""
                SELECT announcement_channel_id, member_count_enabled, anniversary_enabled
                FROM server_milestone_settings WHERE guild_id=?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
            
            current_channel_id = row[0] if row else None
            current_member_enabled = row[1] if row else 1
            current_anniversary_enabled = row[2] if row else 1
            
            # Update settings
            new_channel_id = channel.id if channel else current_channel_id
            new_member_enabled = member_count_enabled if member_count_enabled is not None else current_member_enabled
            new_anniversary_enabled = anniversary_enabled if anniversary_enabled is not None else current_anniversary_enabled
            
            await db.execute("""
                INSERT INTO server_milestone_settings
                (guild_id, announcement_channel_id, member_count_enabled, anniversary_enabled)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    announcement_channel_id = excluded.announcement_channel_id,
                    member_count_enabled = excluded.member_count_enabled,
                    anniversary_enabled = excluded.anniversary_enabled
            """, (interaction.guild.id, new_channel_id, new_member_enabled, new_anniversary_enabled))
            await db.commit()
        
        channel_text = channel.mention if channel else (f"<#{current_channel_id}>" if current_channel_id else "Not set")
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Milestone Settings Updated",
                f"**Announcement Channel:** {channel_text}\n"
                f"**Member Count Milestones:** {'Enabled' if new_member_enabled else 'Disabled'}\n"
                f"**Anniversary Milestones:** {'Enabled' if new_anniversary_enabled else 'Disabled'}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
