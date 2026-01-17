"""Manage coins command (moderators only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED, is_mod


def setup(bot):
    """Register the manage_coins command."""
    @bot.tree.command(name="manage_coins", description="Add or remove coins from a user (moderators only).")
    @app_commands.describe(
        action="Whether to add or remove coins",
        user="The user to modify coins for",
        amount="The amount of coins (must be positive)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add Coins", value="add"),
        app_commands.Choice(name="Remove Coins", value="remove"),
    ])
    async def manage_coins_cmd(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        user: discord.Member,
        amount: int
    ):
        """Add or remove coins from a user's balance (moderators only)."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import add_coins, remove_coins, get_user_balance
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message("Economy system is disabled.", ephemeral=True)
        
        # Check if user is a moderator
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        # Validate amount
        if amount <= 0:
            return await interaction.response.send_message(
                "Amount must be greater than 0.",
                ephemeral=True
            )
        
        action_value = action.value if isinstance(action.value, str) else action
        is_add = action_value == "add"
        
        # Get current balance before modification
        current_balance = await get_user_balance(interaction.guild.id, user.id)
        
        if is_add:
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
            
            fields = [
                ("💰 Coins Added", f"**+{amount:,}** coins", True),
                ("💵 Previous Balance", f"{current_balance:,} coins", True),
                ("💵 New Balance", f"{new_balance:,} coins", True),
            ]
            
            embed = obsidian_embed(
                "✅ Coins Added",
                f"Added **{amount:,}** coins to {user.mention}.",
                color=discord.Color.green(),
                fields=fields,
                client=interaction.client,
            )
        else:
            # Remove coins
            success = await remove_coins(
                interaction.guild.id,
                user.id,
                amount,
                "MOD_REMOVE",
                f"Removed by {interaction.user.display_name} ({interaction.user.id})",
            )
            
            if not success:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Insufficient Balance",
                        f"{user.mention} only has **{current_balance:,}** coins.\n"
                        f"Cannot remove **{amount:,}** coins.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Get new balance
            new_balance = await get_user_balance(interaction.guild.id, user.id)
            
            fields = [
                ("💰 Coins Removed", f"**-{amount:,}** coins", True),
                ("💵 Previous Balance", f"{current_balance:,} coins", True),
                ("💵 New Balance", f"{new_balance:,} coins", True),
            ]
            
            embed = obsidian_embed(
                "✅ Coins Removed",
                f"Removed **{amount:,}** coins from {user.mention}.",
                color=discord.Color.orange(),
                fields=fields,
                client=interaction.client,
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
