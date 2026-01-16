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
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        if amount <= 0:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Amount",
                    "Amount must be greater than 0.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if user.bot:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Recipient",
                    "You cannot transfer coins to bots.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if user.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Recipient",
                    "You cannot transfer coins to yourself.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        success = await transfer_coins(interaction.guild.id, interaction.user.id, user.id, amount)
        
        if success:
            # Get new balances
            sender_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            receiver_balance = await get_user_balance(interaction.guild.id, user.id)
            
            fields = [
                ("💰 Amount", f"**{amount:,}** coins", True),
                ("👤 Recipient", user.mention, True),
                ("💵 Your Balance", f"{sender_balance:,} coins", True),
                ("💵 Their Balance", f"{receiver_balance:,} coins", True),
            ]
            
            embed = obsidian_embed(
                "✅ Transfer Complete",
                f"You transferred **{amount:,}** coins to {user.mention}.",
                color=discord.Color.green(),
                fields=fields,
                client=interaction.client,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Insufficient Balance",
                    f"You have **{balance:,}** coins, but tried to transfer **{amount:,}** coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
