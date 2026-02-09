"""Context menu commands - right-click on users for quick actions."""
import discord
from discord import app_commands

from utils import obsidian_embed, error_embed, ECONOMY_ENABLED


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
