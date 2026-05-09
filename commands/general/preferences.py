"""User and guild preferences (timezone, quieter mode)."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, success_embed, is_mod, EMBED_COLORS
from database import get_user_timezone, set_user_timezone, get_user_platform, set_user_platform, get_quieter_mode, set_quieter_mode

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
    ("America/Toronto", "Toronto"),
    ("America/Sao_Paulo", "São Paulo"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Moscow", "Moscow"),
    ("Asia/Shanghai", "China"),
    ("Asia/Seoul", "Korea"),
    ("Asia/Kolkata", "India"),
]

PLATFORM_CHOICES = [
    app_commands.Choice(name="PC", value="pc"),
    app_commands.Choice(name="Xbox", value="xbox"),
    app_commands.Choice(name="PlayStation", value="ps4"),
    app_commands.Choice(name="Switch", value="switch"),
    app_commands.Choice(name="(clear)", value="-"),
]


def setup(bot, group=None):
    """Register preferences command."""
    command_decorator = group.command(name="preferences", description="Set your timezone or view server preferences.") if group else bot.tree.command(name="preferences", description="Set your timezone or view server preferences.")

    @command_decorator
    @app_commands.describe(
        timezone="Your timezone (used for reminders and event times)",
        platform="Trading platform (used by /trading trade_price when not specified)",
        quieter="Enable quieter mode: fewer pings in events/reminders (mods only)",
        daily_reminder="Get a DM ~1 hour before your daily streak resets",
        levelup_dm="Get a DM (instead of a public post) when you level up",
    )
    @app_commands.choices(timezone=[
        app_commands.Choice(name=label, value=tz) for tz, label in COMMON_TIMEZONES
    ])
    @app_commands.choices(platform=PLATFORM_CHOICES)
    @app_commands.choices(quieter=[
        app_commands.Choice(name="On - fewer pings", value="1"),
        app_commands.Choice(name="Off - normal pings", value="0"),
        app_commands.Choice(name="(no change)", value="-"),
    ])
    @app_commands.choices(daily_reminder=[
        app_commands.Choice(name="On - DM me before my streak resets", value="1"),
        app_commands.Choice(name="Off - no reminder", value="0"),
        app_commands.Choice(name="(no change)", value="-"),
    ])
    @app_commands.choices(levelup_dm=[
        app_commands.Choice(name="On - DM me when I level up (private)", value="1"),
        app_commands.Choice(name="Off - post in level-up channel (public)", value="0"),
        app_commands.Choice(name="(no change)", value="-"),
    ])
    async def preferences(
        interaction: discord.Interaction,
        timezone: Optional[app_commands.Choice[str]] = None,
        platform: Optional[app_commands.Choice[str]] = None,
        quieter: Optional[app_commands.Choice[str]] = None,
        daily_reminder: Optional[app_commands.Choice[str]] = None,
        levelup_dm: Optional[app_commands.Choice[str]] = None,
    ):
        """Set timezone or quieter mode."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        lines = []
        updated = []

        if timezone:
            tz_val = timezone.value
            await set_user_timezone(interaction.guild.id, interaction.user.id, tz_val)
            updated.append(f"**Timezone:** {tz_val}")

        if platform and platform.value != "-":
            await set_user_platform(interaction.guild.id, interaction.user.id, platform.value)
            updated.append(f"**Trading platform:** {platform.value.upper()}")
        elif platform and platform.value == "-":
            await set_user_platform(interaction.guild.id, interaction.user.id, "")
            updated.append("**Trading platform:** cleared (defaults to PC)")

        if quieter and quieter.value != "-":
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                lines.append("⚠️ Only moderators can change quieter mode.")
            else:
                enabled = quieter.value == "1"
                await set_quieter_mode(interaction.guild.id, enabled)
                updated.append(f"**Quieter mode:** {'On' if enabled else 'Off'}")

        if daily_reminder and daily_reminder.value != "-":
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_daily_reminder:{interaction.user.id}", daily_reminder.value)
            state = "On" if daily_reminder.value == "1" else "Off"
            updated.append(f"**Daily streak reminder:** {state}")

        if levelup_dm and levelup_dm.value != "-":
            from database import set_guild_setting
            await set_guild_setting(interaction.guild.id, f"user_levelup_dm:{interaction.user.id}", levelup_dm.value)
            state = "On (DM)" if levelup_dm.value == "1" else "Off (public)"
            updated.append(f"**Level-up notification:** {state}")

        if not lines and not updated:
            # Show current preferences
            current_tz = await get_user_timezone(interaction.guild.id, interaction.user.id)
            current_platform = await get_user_platform(interaction.guild.id, interaction.user.id)
            quieter_on = await get_quieter_mode(interaction.guild.id)
            from database import get_guild_setting
            dr_val = await get_guild_setting(interaction.guild.id, f"user_daily_reminder:{interaction.user.id}")
            dr_on = dr_val == "1"
            lu_val = await get_guild_setting(interaction.guild.id, f"user_levelup_dm:{interaction.user.id}")
            lu_dm = lu_val == "1"
            lines.append(f"**Your timezone:** {current_tz or 'Not set (uses server default)'}")
            lines.append(f"**Trading platform:** {current_platform.upper() if current_platform else 'Not set (defaults to PC)'}")
            lines.append(f"**Daily streak reminder:** {'On 🔔' if dr_on else 'Off'}")
            lines.append(f"**Level-up notification:** {'DM (private) 📬' if lu_dm else 'Public channel'}")
            if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
                lines.append(f"**Quieter mode:** {'On' if quieter_on else 'Off'}")
            embed = obsidian_embed(
                "⚙️ Preferences",
                "\n".join(lines) or "Set timezone or quieter mode using the options above.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        if updated:
            return await interaction.followup.send(
                embed=success_embed("Preferences Updated", "\n".join(updated), client=interaction.client),
                ephemeral=True
            )

        await interaction.followup.send(
            embed=obsidian_embed("⚙️ Preferences", "\n".join(lines), color=discord.Color.orange(), client=interaction.client),
            ephemeral=True
        )
