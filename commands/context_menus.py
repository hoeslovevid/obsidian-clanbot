"""Context menu commands - right-click on users/messages for quick actions."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, error_embed, feature_off_embed, ECONOMY_ENABLED, is_mod, format_timestamp_readable, EMBED_FOOTER_DEFAULT


def setup(bot, group=None):
    """Register context menu commands."""

    @bot.tree.context_menu(name="View Profile")
    async def view_profile_context(interaction: discord.Interaction, member: discord.Member):
        """View a user's profile from context menu."""
        from commands.general.profile import get_user_profile_data
        from database import xp_for_level, xp_for_next_level
        from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT, now_utc

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
        desc_parts = [f"Profile for {target_user.mention}"]
        if target_user.joined_at:
            desc_parts.append(f"\n**Member since:** {format_timestamp_readable(target_user.joined_at, include_relative=True)}")
        if profile_data.get("title"):
            desc_parts.append(f"\n**Title:** {profile_data['title']}")
        if profile_data.get("equipped_badge"):
            e, n = profile_data["equipped_badge"]
            desc_parts.append(f"\n**Badge:** {(e or '🏆')} {n or 'Badge'}")
        if profile_data.get("showcase_badges"):
            parts = [f"{(x or '🏆')} {y or 'Badge'}" for _, x, y in profile_data["showcase_badges"][:3]]
            desc_parts.append(f"\n**Showcase:** {' '.join(parts)}")
        desc = "".join(desc_parts)
        embed = obsidian_embed(
            f"👤 {target_user.display_name}'s Profile",
            desc,
            color=target_user.color if target_user.color.value != 0 else discord.Color.blurple(),
            author=target_user,
            fields=fields,
            client=interaction.client,
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.set_footer(text=EMBED_FOOTER_DEFAULT)
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

    @bot.tree.context_menu(name="Warn User")
    async def warn_user_context(interaction: discord.Interaction, member: discord.Member):
        """Right-click user → Warn (mod only, opens modal for reason)."""
        from core.modals import WarnUserModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Only administrators can warn users.", client=interaction.client),
                ephemeral=True,
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot warn bots.", client=interaction.client),
                ephemeral=True,
            )
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User", "You cannot warn yourself.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(WarnUserModal(member))

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

    @bot.tree.context_menu(name="Add to Suggestions")
    async def add_to_suggestions_context(interaction: discord.Interaction, message: discord.Message):
        """Right-click message → Add to Suggestions (turns message content into a suggestion)."""
        from core.modals import AddToSuggestionModal
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        content = (message.content or "").strip()
        if not content or len(content) < 3:
            return await interaction.response.send_message(
                embed=error_embed("No Content", "This message has no usable text. Try a message with more content.", action_hint="Use /community suggest to submit a suggestion manually.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(AddToSuggestionModal(message))

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

    # Create Ticket for User removed: Discord allows max 5 user context menus. Use /community ticket instead.
