"""Transfer command."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED
from views import ConfirmView

TRANSFER_CONFIRM_THRESHOLD = 1000


def setup(bot, group=None):
    """Register the transfer command."""
    command_decorator = group.command(name="transfer", description="Transfer coins to another user.") if group else bot.tree.command(name="transfer", description="Transfer coins to another user.")
    
    @command_decorator
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

        async def do_transfer():
            success = await transfer_coins(interaction.guild.id, interaction.user.id, user.id, amount)
            if success:
                sender_balance = await get_user_balance(interaction.guild.id, interaction.user.id)
                receiver_balance = await get_user_balance(interaction.guild.id, user.id)
                fields = [
                    ("💰 Amount", f"**{amount:,}** coins", True),
                    ("👤 Recipient", user.mention, True),
                    ("💵 Your Balance", f"{sender_balance:,} coins", True),
                    ("💵 Their Balance", f"{receiver_balance:,} coins", True),
                ]
                return obsidian_embed(
                    "✅ Transfer Complete",
                    f"You transferred **{amount:,}** coins to {user.mention}.",
                    color=discord.Color.green(),
                    fields=fields,
                    client=interaction.client,
                )
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            return obsidian_embed(
                "❌ Insufficient Balance",
                f"You have **{balance:,}** coins, but tried to transfer **{amount:,}** coins.",
                color=discord.Color.red(),
                client=interaction.client,
            )

        if amount >= TRANSFER_CONFIRM_THRESHOLD:
            embed = obsidian_embed(
                "⚠️ Confirm Transfer",
                f"Transfer **{amount:,}** coins to {user.mention}?\n\nThis cannot be undone.",
                color=discord.Color.orange(),
                client=interaction.client,
            )
            async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message("Only the sender can confirm.", ephemeral=True)
                if not confirmed:
                    return await btn_interaction.response.send_message("Transfer cancelled.", ephemeral=True)
                # ConfirmView already sent response.edit_message; use followup for result
                result = await do_transfer()
                await btn_interaction.followup.send(embed=result, ephemeral=True)
            view = ConfirmView(on_confirm)
            return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
