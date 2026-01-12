"""Transfer command."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED


def setup(bot):
    """Register the transfer command."""
    @bot.tree.command(name="transfer", description="Transfer coins to another user.")
    @app_commands.describe(
        user="The user to transfer coins to",
        amount="Amount of coins to transfer"
    )
    async def transfer(interaction: discord.Interaction, user: discord.Member, amount: int):
        """Transfer coins to another user."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import transfer_coins, get_user_balance
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message("Economy system is disabled.", ephemeral=True)
        
        if amount <= 0:
            return await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        
        if user.bot:
            return await interaction.response.send_message("You cannot transfer coins to bots.", ephemeral=True)
        
        if user.id == interaction.user.id:
            return await interaction.response.send_message("You cannot transfer coins to yourself.", ephemeral=True)
        
        success = await transfer_coins(interaction.guild.id, interaction.user.id, user.id, amount)
        
        if success:
            embed = obsidian_embed(
                "✅ Transfer Complete",
                f"You transferred **{amount:,}** coins to {user.mention}.",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            await interaction.response.send_message(
                f"Insufficient balance. You have {balance:,} coins.",
                ephemeral=True,
            )
