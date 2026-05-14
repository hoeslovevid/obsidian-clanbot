"""Incident mode controls (moderators only)."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting, now_utc


async def get_incident_mode(guild_id: int) -> bool:
    """Return True when incident mode is currently enabled for ``guild_id``."""
    return (await get_guild_setting(guild_id, "incident_mode_enabled") or "0") == "1"


async def toggle_incident_mode(guild_id: int, *, duration_minutes: int = 60) -> bool:
    """Flip incident mode on/off for ``guild_id``. Returns the new state."""
    new_state = not await get_incident_mode(guild_id)
    if new_state:
        until = int((now_utc() + timedelta(minutes=max(5, min(duration_minutes, 24 * 60)))).timestamp())
        await set_guild_setting(guild_id, "incident_mode_enabled", "1")
        await set_guild_setting(guild_id, "incident_mode_until_ts", str(until))
    else:
        await set_guild_setting(guild_id, "incident_mode_enabled", "0")
        await set_guild_setting(guild_id, "incident_mode_until_ts", "0")
        await set_guild_setting(guild_id, "incident_mode_message", "")
    return new_state


def setup(bot, group=None):
    """Register incident mode command."""
    command_decorator = group.command(
        name="incident",
        description="Toggle incident mode (limits bot commands during incidents).",
    ) if group else bot.tree.command(
        name="incident",
        description="Toggle incident mode (limits bot commands during incidents).",
    )

    @command_decorator
    @app_commands.describe(
        action="Enable/disable/status",
        duration_minutes="Auto-disable after N minutes (enable only)",
        message="Optional incident message shown to users when blocked",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Status", value="status"),
    ])
    async def incident(
        interaction: discord.Interaction,
        action: str,
        duration_minutes: Optional[int] = 60,
        message: Optional[str] = None,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can manage incident mode.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        if action == "status":
            enabled = await get_guild_setting(interaction.guild.id, "incident_mode_enabled")
            until_ts = await get_guild_setting(interaction.guild.id, "incident_mode_until_ts")
            msg = await get_guild_setting(interaction.guild.id, "incident_mode_message")

            is_on = (enabled or "0") == "1"
            until = int(until_ts) if until_ts and until_ts.isdigit() else 0
            until_text = f"<t:{until}:R>" if until else "—"

            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🚨 Incident Mode Status",
                    f"**Enabled:** {is_on}\n"
                    f"**Auto-disable:** {until_text}\n"
                    f"**Message:** {msg or 'Default'}",
                    color=discord.Color.orange() if is_on else discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if action == "disable":
            await set_guild_setting(interaction.guild.id, "incident_mode_enabled", "0")
            await set_guild_setting(interaction.guild.id, "incident_mode_until_ts", "0")
            await set_guild_setting(interaction.guild.id, "incident_mode_message", "")
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Incident Mode Disabled",
                    "Normal command usage restored.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # enable
        minutes = duration_minutes or 60
        if minutes < 5:
            minutes = 5
        if minutes > 24 * 60:
            minutes = 24 * 60

        until = int((now_utc() + timedelta(minutes=minutes)).timestamp())
        await set_guild_setting(interaction.guild.id, "incident_mode_enabled", "1")
        await set_guild_setting(interaction.guild.id, "incident_mode_until_ts", str(until))
        await set_guild_setting(interaction.guild.id, "incident_mode_message", message or "")

        return await interaction.followup.send(
            embed=obsidian_embed(
                "🚨 Incident Mode Enabled",
                f"Non-critical bot commands will be blocked for non-mods.\n\n"
                f"**Auto-disable:** <t:{until}:R>\n"
                f"**Message:** {(message or 'Default')}",
                color=discord.Color.orange(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

