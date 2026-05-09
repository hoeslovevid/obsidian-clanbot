"""Transfer command - available via context menu (right-click user → Transfer Coins)."""
import discord

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, BUTTON_ONLY_RUNNER_MSG
from views import ConfirmView


async def get_transfer_confirm_threshold(guild_id: int) -> int:
    """Get configurable transfer confirmation threshold (default 1000)."""
    from database import get_guild_setting
    val = await get_guild_setting(guild_id, "transfer_confirm_threshold")
    if val and str(val).isdigit():
        return max(0, int(val))
    return 1000


async def run_transfer_with_modal(interaction: discord.Interaction, user: discord.Member, amount: int):
    """Execute transfer logic (called from context menu modal)."""
    from bot import transfer_coins, get_user_balance

    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
            ephemeral=True,
        )
    if not interaction.guild:
        return await interaction.response.send_message(
            embed=obsidian_embed(
                "❌ Invalid Context",
                "Transfers can only be used in a server.",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
    if user.bot:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid Recipient", "You cannot transfer coins to bots.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    if user.id == interaction.user.id:
        return await interaction.response.send_message(
            embed=obsidian_embed(
                "Pick someone else",
                "You can't transfer coins to yourself. Choose another member.",
                color=discord.Color.orange(),
                client=interaction.client,
            ),
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
                "Transfer complete",
                f"**{amount:,}** coins went to {user.mention}. Balances below are up to date. _(Only you see this.)_",
                color=discord.Color.green(),
                thumbnail=user.display_avatar.url if user.display_avatar else None,
                fields=fields,
                footer=f"Bank transfer • Ref: {interaction.id & 0xFFFF:04X}",
                client=interaction.client,
            )
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        return obsidian_embed(
            "Not enough coins",
            f"You have **{balance:,}** coins but tried to send **{amount:,}**. Earn more with **`/daily`** or chatting in voice.",
            color=discord.Color.orange(),
            client=interaction.client,
        )

    threshold = await get_transfer_confirm_threshold(interaction.guild.id)
    if amount >= threshold:
        embed = obsidian_embed(
            "⚠️ Confirm Transfer",
            f"Send **{amount:,}** coins to {user.mention}?\n\nThis can't be undone. _(Only you can confirm.)_",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.followup.send(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            if not confirmed:
                return await btn_interaction.followup.send("Transfer cancelled — nothing was sent. _(Only you see this.)_", ephemeral=True)
            result = await do_transfer()
            await btn_interaction.followup.send(embed=result, ephemeral=True)
        view = ConfirmView(on_confirm)
        return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    result = await do_transfer()
    await interaction.response.send_message(embed=result, ephemeral=True)


def setup(bot, group=None):
    """Context menu only - no slash command. Transfer is registered in context_menus."""
    pass
