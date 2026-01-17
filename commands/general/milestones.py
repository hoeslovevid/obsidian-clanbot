"""Member milestones command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the milestones command."""
    
    @bot.tree.command(name="milestones", description="View your server milestones and achievements.")
    async def milestones(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """View milestones."""
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
        
        target = user or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if not target:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid User",
                    "Could not determine target user.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=(user is None))
        
        # Get milestones
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT milestone_type, milestone_value, achieved_at
                FROM member_milestones
                WHERE guild_id=? AND user_id=?
                ORDER BY achieved_at DESC
            """, (interaction.guild.id, target.id))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🎯 No Milestones",
                    f"{target.mention} hasn't achieved any milestones yet.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=(user is None)
            )
        
        # Group by type
        milestones_by_type = {}
        for milestone_type, milestone_value, achieved_at in rows:
            if milestone_type not in milestones_by_type:
                milestones_by_type[milestone_type] = []
            milestones_by_type[milestone_type].append((milestone_value, achieved_at))
        
        # Build description
        desc = ""
        milestone_names = {
            "join_anniversary": "Join Anniversaries",
            "message_count": "Message Milestones",
            "voice_hours": "Voice Activity",
            "level": "Level Milestones",
        }
        
        for milestone_type, milestones_list in milestones_by_type.items():
            type_name = milestone_names.get(milestone_type, milestone_type.replace("_", " ").title())
            desc += f"**{type_name}:**\n"
            for value, achieved_at in sorted(milestones_list, reverse=True)[:5]:  # Show top 5 per type
                if milestone_type == "join_anniversary":
                    desc += f"• {value} year{'s' if value != 1 else ''} anniversary\n"
                elif milestone_type == "message_count":
                    desc += f"• {value:,} messages\n"
                elif milestone_type == "voice_hours":
                    desc += f"• {value} hours\n"
                elif milestone_type == "level":
                    desc += f"• Level {value}\n"
                else:
                    desc += f"• {value}\n"
            desc += "\n"
        
        embed = obsidian_embed(
            f"🎯 Milestones - {target.display_name}",
            desc,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else None)
        
        await interaction.followup.send(embed=embed, ephemeral=(user is None))
