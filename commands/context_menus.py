"""Context menu commands - right-click on users/messages for quick actions."""
import discord
from discord import app_commands

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import error_embed, feature_off_embed, ECONOMY_ENABLED, is_mod


def setup(bot, group=None):
    """Register context menu commands."""

    @bot.tree.context_menu(name="View Profile")
    async def view_profile_context(interaction: discord.Interaction, member: discord.Member):
        """View a user's profile from context menu (matches /profile template)."""
        from commands.general.profile import build_profile_embed, get_user_profile_data

        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        profile_data = await get_user_profile_data(interaction.guild.id, member.id)
        embed = await build_profile_embed(
            interaction.guild,
            member,
            profile_data,
            viewer=interaction.user,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="View Balance")
    async def view_balance_context(interaction: discord.Interaction, member: discord.Member):
        """View a user's balance from context menu."""
        from database import get_user_balance
        from core.utils import COINS_PER_MESSAGE, COINS_DAILY_REWARD

        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True
            )
        is_admin = interaction.user.guild_permissions.administrator if isinstance(interaction.user, discord.Member) else False
        if member.id != interaction.user.id and not is_admin:
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "You can only view your own balance.", client=interaction.client),
                ephemeral=True
            )
        balance = await get_user_balance(interaction.guild.id, member.id)
        fields = [
            ("Balance", f"**{balance:,}** coins", True),
            ("Earning", f"Daily: {COINS_DAILY_REWARD:,} | Messages: {COINS_PER_MESSAGE}", True),
        ]
        embed = embed_template(
            "showcase",
            f"💰 {member.display_name}'s Balance",
            f"> {member.mention}",
            category="economy",
            author=member,
            thumbnail=member.display_avatar.url,
            fields=fields,
            footer=footer_for("economy_wallet"),
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="Transfer Coins")
    async def transfer_coins_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → Transfer Coins (opens modal for amount)."""
        from core.modals import TransferCoinsModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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

    @bot.tree.context_menu(name="Mod Context")
    async def mod_context_menu(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → unified mod dashboard (warn / DM / kick / ban / notes / warnings)."""
        from commands.moderation.mod_context_view import build_mod_context

        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Only administrators can use Mod Context.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        embed, view = await build_mod_context(interaction, member)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @bot.tree.context_menu(name="Open Ticket About User")
    async def ticket_about_user_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → open a support ticket regarding this member."""
        from core.modals import TicketAboutUserModal

        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot open a ticket about bots.", client=interaction.client),
                ephemeral=True,
            )
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Use /ticket", "For your own issues, run **`/ticket`** directly.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(TicketAboutUserModal(member))

    # Warn User removed — use Mod Context → Warn (Discord 5 user context menu cap).

    @bot.tree.context_menu(name="Look up market price")
    async def market_lookup_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → look up Warframe Market price from message text."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        text = (message.content or "").strip()
        if message.embeds:
            emb = message.embeds[0]
            if emb.title:
                text = text or emb.title
        item = text.split(":")[-1].strip() if ":" in text else text
        item = item.replace("WTS", "").replace("WTB", "").strip()[:120]
        if not item:
            return await interaction.response.send_message(
                embed=error_embed(
                    "No item found",
                    "Couldn't find an item name in that message.",
                    action_hint="Try a trade message like `WTS Vitrica 80p` or use `/trade_price`.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        from database import get_user_platform
        from api.warframe_api import search_warframe_market_item, get_warframe_market_price

        platform = await get_user_platform(interaction.guild.id, interaction.user.id) or "pc"
        found = await search_warframe_market_item(item, platform)
        if not found:
            return await interaction.followup.send(
                embed=error_embed(
                    "Not on market",
                    f"No listing for **{item}** on {platform.upper()}.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        price_data = await get_warframe_market_price(found.get("url_name", ""), platform)
        lowest = price_data.get("lowest_sell") if price_data else None
        highest = price_data.get("highest_buy") if price_data else None
        fields = []
        if lowest is not None:
            fields.append(("Lowest sell", f"**{lowest}p**", True))
        if highest is not None:
            fields.append(("Highest buy", f"**{highest}p**", True))
        embed = embed_template(
            "showcase",
            f"💎 {found.get('item_name', item)}",
            f"Warframe Market · **{platform.upper()}**",
            category="trading",
            fields=fields or None,
            footer="Use /price_watch for price-drop DMs",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.context_menu(name="Create LFG")
    async def create_lfg_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → Create LFG post in this channel, pre-filled with message content."""
        from commands.warframe.lfg import create_lfg_post

        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        content = (message.content or "").strip()
        description_parts = []
        if content:
            description_parts.append(content[:1024])
        try:
            description_parts.append(f"Source: {message.jump_url}")
        except Exception:
            pass
        description = "\n\n".join(description_parts)
        await create_lfg_post(bot, interaction, "Other", 4, 24, description, None)

    @bot.tree.context_menu(name="Explain command")
    async def explain_command_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click a bot message → describe which command produced it (Item 63)."""
        from commands.context_menus_explain import build_explanation

        embed, view = await build_explanation(interaction, message)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # Report User removed: Discord allows max 5 user context menus. Use /community submit_complaint or complaint panel.

    @bot.tree.context_menu(name="Report Message")
    async def report_message_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → Report (opens complaint modal pre-filled with message link)."""
        from core.modals import ReportMessageModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(ReportMessageModal(message))

    # Add to Suggestions removed — use /community suggest (Discord 5 message context menu cap).

    @bot.tree.context_menu(name="Add as Event")
    async def add_as_event_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → Create event from message content (pre-filled)."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        content = (message.content or "").strip()
        if not content or len(content) < 3:
            return await interaction.response.send_message(
                embed=error_embed("No Content", "Message has no usable text. Try a message with a title or description.", action_hint="Use /events event_create to create an event manually.", client=interaction.client),
                ephemeral=True,
            )
        from core.modals import AddAsEventModal
        await interaction.response.send_modal(AddAsEventModal(message))

    # User context menus (5): View Profile, View Balance, Transfer Coins, Mod Context, Open Ticket About User.
