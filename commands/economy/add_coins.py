"""Add coins command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED, is_mod


def setup(bot):
    """Register the add_coins command."""
    @bot.tree.command(name="add_coins", description="Add coins to a user (moderators only).")
    @app_commands.describe(
        user="The user to give coins to",
        amount="The amount of coins to add (must be positive)"
    )
    async def add_coins_cmd(interaction: discord.Interaction, user: discord.Member, amount: int):
        """Add coins to a user's balance (moderators only)."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import add_coins, get_user_balance
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message("Economy system is disabled.", ephemeral=True)
        
        # Check if user is a moderator
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        # Validate amount
        if amount <= 0:
            return await interaction.response.send_message(
                "Amount must be greater than 0.",
                ephemeral=True
            )
        
        # Add coins
        await add_coins(
            interaction.guild.id,
            user.id,
            amount,
            "MOD_ADD",
            f"Added by {interaction.user.display_name} ({interaction.user.id})",
        )
        
        # Get new balance
        new_balance = await get_user_balance(interaction.guild.id, user.id)
        
        embed = obsidian_embed(
            "✅ Coins Added",
            f"Added **{amount:,}** coins to {user.mention}.\n\n"
            f"**New Balance:** {new_balance:,} coins",
            color=discord.Color.green(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
