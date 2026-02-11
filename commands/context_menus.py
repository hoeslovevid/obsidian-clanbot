"""Context menu commands - right-click on users/messages for quick actions."""
import discord
from discord import app_commands

from utils import obsidian_embed, error_embed, ECONOMY_ENABLED, is_mod


def setup(bot, group=None):
    """Register context menu commands."""

    @bot.tree.context_menu(name="View Profile")
    async def view_profile_context(interaction: discord.Interaction, member: discord.Member):
        """View a user's profile from context menu."""
        from commands.general.profile import get_user_profile_data
        from database import xp_for_level, xp_for_next_level
        from utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT, now_utc

        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True
            )
        profile_data = await get_user_profile_data(interaction.guild.id, member.id)
        target_user = member
        current_level = profile_data["level"]
        current_xp = profile_data["xp"]
        xp_for_current = xp_for_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if current_level > 0 else 0
        xp_for_next = xp_for_next_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        xp_progress = current_xp - xp_for_current
        xp_range = xp_for_next - xp_for_current
        progress_percent = int((xp_progress / xp_range * 100)) if xp_range > 0 else 0
        voice_hours = profile_data["voice_minutes"] // 60
        voice_mins = profile_data["voice_minutes"] % 60
        voice_time = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"
        fields = []
        if profile_data["balance"] > 0 or profile_data["total_earned"] > 0:
            fields.append(("Economy", f"Balance: {profile_data['balance']:,} | Total: {profile_data['total_earned']:,}", True))
        if profile_data["level"] > 0 or profile_data["xp"] > 0:
            bar = "█" * (progress_percent // 5) + "░" * (20 - progress_percent // 5)
            fields.append(("Leveling", f"Level {current_level} | {bar} {progress_percent}%", True))
        fields.append(("Activity", f"Messages: {profile_data['messages_sent']:,} | Voice: {voice_time}", True))
        desc = f"Profile for {target_user.mention}"
        embed = obsidian_embed(
            f"{target_user.display_name}'s Profile",
            desc,
            color=target_user.color if target_user.color.value != 0 else discord.Color.blurple(),
            author=target_user,
            fields=fields,
            client=interaction.client,
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="View Balance")
    async def view_balance_context(interaction: discord.Interaction, member: discord.Member):
        """View a user's balance from context menu."""
        from database import get_user_balance
        from utils import COINS_PER_MESSAGE, COINS_DAILY_REWARD

        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=error_embed("Economy Disabled", "The economy system is currently disabled.", client=interaction.client),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True
            )
        is_mod = interaction.user.guild_permissions.administrator if isinstance(interaction.user, discord.Member) else False
        if member.id != interaction.user.id and not is_mod:
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "You can only view your own balance.", client=interaction.client),
                ephemeral=True
            )
        balance = await get_user_balance(interaction.guild.id, member.id)
        fields = [
            ("Balance", f"**{balance:,}** coins", True),
            ("Earning", f"Daily: {COINS_DAILY_REWARD:,} | Messages: {COINS_PER_MESSAGE}", False),
        ]
        embed = obsidian_embed(
            f"{member.display_name}'s Balance",
            "",
            color=discord.Color.gold(),
            author=member,
            thumbnail=member.display_avatar.url,
            fields=fields,
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="Transfer Coins")
    async def transfer_coins_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → Transfer Coins (opens modal for amount)."""
        from modals import TransferCoinsModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=error_embed("Economy Disabled", "The economy system is currently disabled.", client=interaction.client),
                ephemeral=True,
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Recipient", "You cannot transfer coins to bots.", client=interaction.client),
                ephemeral=True,
            )
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Recipient", "You cannot transfer coins to yourself.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(TransferCoinsModal(member))

    @bot.tree.context_menu(name="Warn User")
    async def warn_user_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → Warn (mod only, opens modal for reason)."""
        from modals import WarnUserModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only administrators can warn users.", client=interaction.client),
                ephemeral=True,
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot warn bots.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(WarnUserModal(member))

    @bot.tree.context_menu(name="Give Reputation")
    async def give_rep_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → Give Reputation (opens modal for optional reason)."""
        from modals import GiveRepModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot give reputation to bots.", client=interaction.client),
                ephemeral=True,
            )
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot give reputation to yourself.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(GiveRepModal(member))

    @bot.tree.context_menu(name="Check Price")
    async def check_price_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → Check Warframe Market price for text in message."""
        from warframe_api import search_warframe_market_item, get_warframe_market_price
        from commands.trading.trade_price import _build_trade_embed
        content = (message.content or "").strip()
        # Try to extract item-like text: words with potential item names (e.g. "Mesa Prime Set", "Primed Continuity")
        import re
        # Look for quoted text first, then camel-case/space-separated phrases
        quoted = re.findall(r'"([^"]+)"', content)
        if quoted:
            search_term = quoted[0][:80]
        else:
            # Take first line or first 60 chars
            first_line = content.split("\n")[0].strip()[:80]
            search_term = first_line if len(first_line) >= 2 else None
        if not search_term or len(search_term) < 2:
            return await interaction.response.send_message(
                embed=error_embed("No Search Term", "Message has no usable text for price check. Try right-clicking a message that mentions an item (e.g. 'Mesa Prime Set').", client=interaction.client),
                ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        item_data = await search_warframe_market_item(search_term, "pc")
        if not item_data:
            return await interaction.followup.send(
                embed=error_embed("Item Not Found", f"Could not find '{search_term[:50]}' on Warframe Market.", client=interaction.client),
                ephemeral=True
            )
        price_data = await get_warframe_market_price(item_data.get("url_name", ""), "pc")
        if not price_data:
            return await interaction.followup.send(
                embed=error_embed("Price Unavailable", f"Could not fetch prices for {item_data.get('item_name', search_term)}.", client=interaction.client),
                ephemeral=True
            )
        embed = _build_trade_embed(item_data, price_data, "pc", interaction.client, author=interaction.user)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="Create LFG")
    async def create_lfg_context(interaction: discord.Interaction, message: discord.Message):
        """Quick LFG: create an LFG post in this channel with default settings."""
        from commands.warframe.lfg import create_lfg_post

        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        await create_lfg_post(bot, interaction, "Other", 4, 24, "", None)
