"""Manage XP command (moderators only)."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, XP_ENABLED, is_mod


def setup(bot, group=None):
    """Register the manage_xp command."""
    command_decorator = group.command(name="manage", description="Add or remove XP from a user (moderators only).") if group else bot.tree.command(name="manage", description="Add or remove XP from a user (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Whether to add or remove XP",
        user="The user to modify XP for",
        amount="The amount of XP (must be positive)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add XP", value="add"),
        app_commands.Choice(name="Remove XP", value="remove"),
    ])
    async def manage_xp_cmd(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        user: discord.Member,
        amount: int
    ):
        """Add or remove XP from a user (moderators only)."""
        # Import bot-specific functions inside to avoid circular imports
        from database import add_xp, remove_xp, get_user_xp, calculate_level
        from core.utils import XP_LEVEL_MULTIPLIER
        
        if not XP_ENABLED:
            return await interaction.response.send_message("XP system is disabled.", ephemeral=True)
        
        # Check if user is a moderator
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This can only be used in a server.",
                ephemeral=True,
            )

        # Validate amount
        if amount <= 0:
            return await interaction.response.send_message(
                "Amount must be greater than 0.",
                ephemeral=True
            )
        
        action_value = action.value if isinstance(action.value, str) else action
        is_add = action_value == "add"
        
        # Get current XP before modification
        current_xp, current_level, total_xp = await get_user_xp(interaction.guild.id, user.id)
        
        if is_add:
            # Add XP
            leveled_up = await add_xp(
                interaction.guild.id,
                user.id,
                amount,
                "MOD_ADD",
            )
            
            # Get new XP
            new_xp, new_level, new_total_xp = await get_user_xp(interaction.guild.id, user.id)
            
            fields = [
                ("💎 XP Added", f"**+{amount:,}** XP", True),
                ("⭐ Previous", f"{current_xp:,} XP (Level {current_level})", True),
                ("⭐ New", f"{new_xp:,} XP (Level {new_level})", True),
            ]
            
            desc = f"Added **{amount:,}** XP to {user.mention}."
            if leveled_up:
                desc += f"\n\n🎉 **Level Up!** {user.mention} reached level **{new_level}**!"
                from core.utils import send_levelup_announcement
                await send_levelup_announcement(
                    interaction.guild,
                    user,
                    new_level,
                    new_xp,
                    new_total_xp,
                )

            embed = obsidian_embed(
                "✅ XP Added",
                desc,
                color=discord.Color.green(),
                author=user,
                thumbnail=user.display_avatar.url if user.display_avatar else None,
                fields=fields,
                footer=f"Level {current_level} → {new_level}",
                client=interaction.client,
            )
        else:
            # Remove XP
            success = await remove_xp(
                interaction.guild.id,
                user.id,
                amount,
            )
            
            if not success:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Insufficient XP",
                        f"{user.mention} only has **{current_xp:,}** XP.\n"
                        f"Cannot remove **{amount:,}** XP.",
                        color=discord.Color.red(),
                        author=user,
                        thumbnail=user.display_avatar.url if user.display_avatar else None,
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Get new XP
            new_xp, new_level, new_total_xp = await get_user_xp(interaction.guild.id, user.id)
            
            fields = [
                ("💎 XP Removed", f"**-{amount:,}** XP", True),
                ("⭐ Previous", f"{current_xp:,} XP (Level {current_level})", True),
                ("⭐ New", f"{new_xp:,} XP (Level {new_level})", True),
            ]
            
            desc = f"Removed **{amount:,}** XP from {user.mention}."
            if new_level < current_level:
                desc += f"\n\n⚠️ {user.mention} dropped to level **{new_level}**."
            
            embed = obsidian_embed(
                "✅ XP Removed",
                desc,
                color=discord.Color.orange(),
                author=user,
                thumbnail=user.display_avatar.url if user.display_avatar else None,
                fields=fields,
                footer=f"Level {current_level} → {new_level}",
                client=interaction.client,
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
