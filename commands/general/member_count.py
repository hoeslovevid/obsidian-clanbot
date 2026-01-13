"""Server member count command."""
import discord
from discord import app_commands

from utils import obsidian_embed


def setup(bot):
    """Register the member_count command."""
    @bot.tree.command(name="member_count", description="View the current server member count.")
    async def member_count(interaction: discord.Interaction):
        """Display the current server member count."""
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )
        
        # Get member count
        member_count = interaction.guild.member_count
        
        # Get online/offline status counts if available
        # Note: This requires the members intent and may not be 100% accurate for large servers
        online_count = 0
        idle_count = 0
        dnd_count = 0
        offline_count = 0
        
        # Only calculate status counts for smaller servers (to avoid performance issues)
        # For larger servers, we'll just show the total count
        show_status_breakdown = member_count <= 1000
        
        if show_status_breakdown:
            try:
                for member in interaction.guild.members:
                    if member.bot:
                        continue  # Skip bots for status counts
                    
                    status = member.status
                    if status == discord.Status.online:
                        online_count += 1
                    elif status == discord.Status.idle:
                        idle_count += 1
                    elif status == discord.Status.dnd:
                        dnd_count += 1
                    else:
                        offline_count += 1
            except Exception:
                # If we can't iterate members, just show total count
                show_status_breakdown = False
        
        # Build description
        desc = f"**Total Members:** {member_count:,}\n\n"
        
        # Get bot count (more efficient approach)
        bot_count = 0
        try:
            # Try to get accurate bot count
            bot_count = sum(1 for member in interaction.guild.members if member.bot)
        except Exception:
            # Fallback: estimate bots as ~5% of total (rough estimate)
            bot_count = int(member_count * 0.05)
        
        human_count = member_count - bot_count
        
        # Add status breakdown if we have data and server isn't too large
        if show_status_breakdown and (online_count + idle_count + dnd_count + offline_count > 0):
            desc += "**Member Status:**\n"
            desc += f"🟢 Online: {online_count:,}\n"
            desc += f"🟡 Idle: {idle_count:,}\n"
            desc += f"🔴 Do Not Disturb: {dnd_count:,}\n"
            desc += f"⚫ Offline: {offline_count:,}\n"
        
        desc += "\n**Breakdown:**\n"
        desc += f"👥 Humans: {human_count:,}\n"
        desc += f"🤖 Bots: {bot_count:,}"
        
        embed = obsidian_embed(
            "👥 Server Member Count",
            desc,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
