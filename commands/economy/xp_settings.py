"""XP settings command - configure level-up announcements and XP multiplier events."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.utils import obsidian_embed, is_mod, XP_LEVELUP_CHANNEL_KEY
from database import get_guild_setting, set_guild_setting

XP_EVENT_KEY = "xp_multiplier_event"  # stored as "multiplier:iso_expires_at"


async def get_active_xp_event(guild_id: int) -> tuple[float, datetime | None]:
    """Return (multiplier, expires_at) for the active XP event, or (1.0, None) if none."""
    raw = await get_guild_setting(guild_id, XP_EVENT_KEY)
    if not raw or ":" not in raw:
        return 1.0, None
    try:
        mult_str, exp_str = raw.split(":", 1)
        mult = float(mult_str)
        exp_dt = datetime.fromisoformat(exp_str)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= exp_dt:
            return 1.0, None  # expired
        return mult, exp_dt
    except Exception:
        return 1.0, None


def setup(bot, group=None):
    """Register the xp_settings and xp_event commands."""
    command_decorator = (
        group.command(name="settings", description="Configure XP level-up announcements (moderators only).")
        if group
        else bot.tree.command(name="settings", description="Configure XP level-up announcements (moderators only).")
    )

    @command_decorator
    @app_commands.describe(
        channel="Channel to send level-up announcements to (leave empty to view current setting)",
        disable="Set to True to disable level-up announcements"
    )
    async def xp_settings_cmd(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        disable: Optional[bool] = None,
    ):
        """Configure where level-up announcements are sent."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure XP settings.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        current = await get_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY)
        current_channel_id = int(current) if current and current.isdigit() else None

        if disable:
            await set_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY, "")
            msg = "Level-up announcements have been disabled."
        elif channel:
            await set_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY, str(channel.id))
            msg = f"Level-up announcements will be sent to {channel.mention}."
        elif current_channel_id:
            ch = interaction.guild.get_channel(current_channel_id)
            msg = f"**Current:** Level-up announcements are sent to {ch.mention if ch else f'<#{current_channel_id}>'}.\n\nUse `channel` to change, or `disable` to turn off."
        else:
            msg = "Level-up announcements are not configured. Provide a `channel` to enable them."

        await interaction.response.send_message(
            embed=obsidian_embed(
                "⚙️ XP Settings",
                msg,
                color=discord.Color.blue(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # XP multiplier event command
    event_decorator = (
        group.command(name="xp_event", description="Start or stop a server-wide XP boost event (mods only).")
        if group
        else bot.tree.command(name="xp_event", description="Start or stop a server-wide XP boost event (mods only).")
    )

    @event_decorator
    @app_commands.describe(
        multiplier="XP multiplier (e.g. 2 = double XP). Leave blank to view/cancel current event.",
        duration_hours="How many hours the event lasts (1–168). Default: 24.",
        cancel="Set to True to end the active XP event early.",
    )
    async def xp_event_cmd(
        interaction: discord.Interaction,
        multiplier: Optional[float] = None,
        duration_hours: int = 24,
        cancel: bool = False,
    ):
        """Start, view, or cancel a server-wide XP multiplier event."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Permission Denied", "Only moderators can manage XP events.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)

        if cancel:
            await set_guild_setting(interaction.guild.id, XP_EVENT_KEY, "")
            return await interaction.followup.send(
                embed=obsidian_embed("✅ XP Event Cancelled", "The XP multiplier event has been ended.", color=discord.Color.orange(), client=interaction.client),
                ephemeral=True,
            )

        # Show current event if no multiplier given
        active_mult, active_exp = await get_active_xp_event(interaction.guild.id)
        if multiplier is None:
            if active_exp:
                exp_ts = int(active_exp.timestamp())
                msg = f"**Active XP Event:** `{active_mult}x` — ends <t:{exp_ts}:R> (<t:{exp_ts}:F>)\n\nUse `cancel:True` to end it early."
            else:
                msg = "No active XP event. Provide a `multiplier` to start one."
            return await interaction.followup.send(
                embed=obsidian_embed("⚡ XP Event Status", msg, color=discord.Color.gold(), client=interaction.client),
                ephemeral=True,
            )

        if multiplier < 1.0 or multiplier > 10.0:
            return await interaction.followup.send(
                embed=obsidian_embed("❌ Invalid Multiplier", "Multiplier must be between 1 and 10.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        duration_hours = max(1, min(168, duration_hours))
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        await set_guild_setting(interaction.guild.id, XP_EVENT_KEY, f"{multiplier}:{expires_at.isoformat()}")

        exp_ts = int(expires_at.timestamp())
        embed = obsidian_embed(
            "⚡ XP Multiplier Event Started!",
            f"All members now earn **{multiplier}× XP** from messages and voice.\n\n"
            f"**Duration:** {duration_hours}h — ends <t:{exp_ts}:R>",
            color=discord.Color.gold(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Announce in the configured level-up channel if set
        ch_id_str = await get_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY)
        if ch_id_str and ch_id_str.isdigit():
            ch = interaction.guild.get_channel(int(ch_id_str))
            if isinstance(ch, discord.TextChannel):
                try:
                    announce = obsidian_embed(
                        "⚡ XP Multiplier Event!",
                        f"A **{multiplier}× XP event** is now active! Earn more XP from messages and voice.\n\nEnds <t:{exp_ts}:R>",
                        color=discord.Color.gold(),
                        client=interaction.client,
                    )
                    await ch.send(embed=announce)
                except Exception:
                    pass
