"""XP command."""
import discord
from discord import app_commands

from utils import obsidian_embed, XP_ENABLED, XP_LEVEL_MULTIPLIER


def setup(bot):
    """Register the xp command."""
    @bot.tree.command(name="xp", description="Check your XP and level.")
    @app_commands.describe(user="User to check (default: yourself)")
    async def xp(interaction: discord.Interaction, user: discord.Member = None):
        """Display the user's current XP and level."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import get_user_xp
        
        if not XP_ENABLED:
            return await interaction.response.send_message("XP system is disabled.", ephemeral=True)
        
        target_user = user or interaction.user
        xp, level, total_xp = await get_user_xp(interaction.guild.id, target_user.id)
        
        # Calculate XP needed for next level
        xp_for_current_level = int(level ** 2 * XP_LEVEL_MULTIPLIER)
        xp_for_next = int((level + 1) ** 2 * XP_LEVEL_MULTIPLIER)
        xp_needed = xp_for_next - xp
        progress = xp - xp_for_current_level
        progress_needed = xp_for_next - xp_for_current_level
        progress_percent = int((progress / progress_needed * 100)) if progress_needed > 0 else 100
        
        # Create progress bar
        bar_length = 15
        filled = int(bar_length * progress / progress_needed) if progress_needed > 0 else bar_length
        progress_bar = "█" * filled + "░" * (bar_length - filled)
        
        fields = [
            ("⭐ Level", f"**{level}**", True),
            ("💎 Current XP", f"{xp:,} / {xp_for_next:,}", True),
            ("📊 Total XP", f"{total_xp:,}", True),
            ("📈 Progress to Level {level + 1}", f"`{progress_bar}` **{progress_percent}%**\n{xp_needed:,} XP needed", False)
        ]
        
        embed = obsidian_embed(
            f"⭐ {target_user.display_name}'s XP",
            "",
            color=discord.Color.blue(),
            author=target_user,
            thumbnail=target_user.display_avatar.url if hasattr(target_user, 'display_avatar') else target_user.avatar.url if target_user.avatar else None,
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=(target_user != interaction.user))
