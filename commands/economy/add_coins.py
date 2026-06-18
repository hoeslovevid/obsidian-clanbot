"""Manage coins command (moderators only)."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, is_mod

# Above this amount, require an explicit confirmation (fat-finger protection).
_CONFIRM_THRESHOLD = 100_000


def setup(bot, group=None):
    """Register the manage_coins command."""
    command_decorator = group.command(name="manage_coins", description="Add or remove coins from a user (moderators only).") if group else bot.tree.command(name="manage_coins", description="Add or remove coins from a user (moderators only).")
    
    @command_decorator
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
            return await interaction.response.send_message(embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client), ephemeral=True)
        
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

        # Get current balance before modification
        current_balance = await get_user_balance(interaction.guild.id, user.id)

        async def apply_and_report(src: discord.Interaction, *, followup: bool):
            sender = src.followup.send if followup else src.response.send_message
            if is_add:
                await add_coins(
                    interaction.guild.id,
                    user.id,
                    amount,
                    "MOD_ADD",
                    f"Added by {interaction.user.display_name} ({interaction.user.id})",
                )
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
                await sender(embed=embed, ephemeral=False)
            else:
                success = await remove_coins(
                    interaction.guild.id,
                    user.id,
                    amount,
                    "MOD_REMOVE",
                    f"Removed by {interaction.user.display_name} ({interaction.user.id})",
                )
                if not success:
                    return await sender(
                        embed=obsidian_embed(
                            "❌ Insufficient Balance",
                            f"{user.mention} only has **{current_balance:,}** coins.\n"
                            f"Cannot remove **{amount:,}** coins.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True,
                    )
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
                await sender(embed=embed, ephemeral=False)

        # Large changes require explicit confirmation (fat-finger protection).
        if amount >= _CONFIRM_THRESHOLD:
            from views import ConfirmView
            from core.embed_templates import confirm_embed

            verb = "add" if is_add else "remove"
            prep = "to" if is_add else "from"
            confirm = confirm_embed(
                "⚠️ Confirm Large Coin Change",
                f"{verb.capitalize()} **{amount:,}** coins {prep} {user.mention}?\n"
                f"Their current balance is **{current_balance:,}** coins.",
                client=interaction.client,
            )

            async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
                if not confirmed:
                    return await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.followup.send(
                        "Only the person who started this can confirm.", ephemeral=True
                    )
                await apply_and_report(btn_interaction, followup=True)

            view = ConfirmView(on_confirm)
            await interaction.response.send_message(embed=confirm, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        await apply_and_report(interaction, followup=False)
