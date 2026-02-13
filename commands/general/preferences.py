"""User and guild preferences (timezone, quieter mode)."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, success_embed, is_mod, EMBED_COLORS
from database import get_user_timezone, set_user_timezone, get_quieter_mode, set_quieter_mode

COMMON_TIMEZONES = [
    ("UTC", "UTC"),
    ("America/New_York", "Eastern"),
    ("America/Chicago", "Central"),
    ("America/Denver", "Mountain"),
    ("America/Los_Angeles", "Pacific"),
    ("Europe/London", "UK"),
    ("Europe/Paris", "Central Europe"),
    ("Asia/Tokyo", "Japan"),
    ("Australia/Sydney", "Australia East"),
]


def setup(bot, group=None):
    """Register preferences command."""
    command_decorator = group.command(name="preferences", description="Set your timezone or view server preferences.") if group else bot.tree.command(name="preferences", description="Set your timezone or view server preferences.")

    @command_decorator
    @app_commands.describe(
        timezone="Your timezone (used for reminders and event times)",
        quieter="Enable quieter mode: fewer pings in events/reminders (mods only)"
    )
    @app_commands.choices(timezone=[
        app_commands.Choice(name=label, value=tz) for tz, label in COMMON_TIMEZONES
    ])
    @app_commands.choices(quieter=[
        app_commands.Choice(name="On - fewer pings", value="1"),
        app_commands.Choice(name="Off - normal pings", value="0"),
        app_commands.Choice(name="(no change)", value="-"),
    ])
    async def preferences(
        interaction: discord.Interaction,
        timezone: Optional[app_commands.Choice[str]] = None,
        quieter: Optional[app_commands.Choice[str]] = None,
    ):
        """Set timezone or quieter mode."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True
            )

        lines = []
        updated = []

        if timezone:
            tz_val = timezone.value
            await set_user_timezone(interaction.guild.id, interaction.user.id, tz_val)
            updated.append(f"**Timezone:** {tz_val}")

        if quieter and quieter.value != "-":
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                lines.append("⚠️ Only moderators can change quieter mode.")
            else:
                enabled = quieter.value == "1"
                await set_quieter_mode(interaction.guild.id, enabled)
                updated.append(f"**Quieter mode:** {'On' if enabled else 'Off'}")

        if not lines and not updated:
            # Show current preferences
            current_tz = await get_user_timezone(interaction.guild.id, interaction.user.id)
            quieter_on = await get_quieter_mode(interaction.guild.id)
            lines.append(f"**Your timezone:** {current_tz or 'Not set (uses server default)'}")
            if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
                lines.append(f"**Quieter mode:** {'On' if quieter_on else 'Off'}")
            embed = obsidian_embed(
                "⚙️ Preferences",
                "\n".join(lines) or "Set timezone or quieter mode using the options above.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if updated:
            return await interaction.response.send_message(
                embed=success_embed("Preferences Updated", "\n".join(updated), client=interaction.client),
                ephemeral=True
            )

        await interaction.response.send_message(
            embed=obsidian_embed("⚙️ Preferences", "\n".join(lines), color=discord.Color.orange(), client=interaction.client),
            ephemeral=True
        )
