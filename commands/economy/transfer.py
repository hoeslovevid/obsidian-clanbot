"""Transfer command - available via context menu (right-click user → Transfer Coins)."""
import discord

from utils import obsidian_embed, ECONOMY_ENABLED
from views import ConfirmView

TRANSFER_CONFIRM_THRESHOLD = 1000


async def run_transfer_with_modal(interaction: discord.Interaction, user: discord.Member, amount: int):
    """Execute transfer logic (called from context menu modal)."""
    from bot import transfer_coins, get_user_balance

    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Economy Disabled", "The economy system is currently disabled.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    if not interaction.guild:
        return
    if user.bot:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid Recipient", "You cannot transfer coins to bots.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    if user.id == interaction.user.id:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid Recipient", "You cannot transfer coins to yourself.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )

    async def do_transfer():
        success = await transfer_coins(interaction.guild.id, interaction.user.id, user.id, amount)
        if success:
            try:
                from database import check_and_unlock_achievement, get_user_balance
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "first_transfer", getattr(interaction.client, "bot", interaction.client))
                # Check first_million for receiver
                recv_bal = await get_user_balance(interaction.guild.id, user.id)
                if recv_bal >= 1_000_000:
                    await check_and_unlock_achievement(interaction.guild.id, user.id, "first_million", getattr(interaction.client, "bot", interaction.client))
            except Exception:
                pass
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
                thumbnail=user.display_avatar.url if user.display_avatar else None,
                fields=fields,
                footer=f"Bank transfer • Ref: {interaction.id & 0xFFFF:04X}",
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
                return await btn_interaction.followup.send("Only the sender can confirm.", ephemeral=True)
            if not confirmed:
                return await btn_interaction.followup.send("Transfer cancelled.", ephemeral=True)
            result = await do_transfer()
            await btn_interaction.followup.send(embed=result, ephemeral=True)
        view = ConfirmView(on_confirm)
        return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    result = await do_transfer()
    await interaction.response.send_message(embed=result, ephemeral=True)


def setup(bot, group=None):
    """Context menu only - no slash command. Transfer is registered in context_menus."""
    pass
