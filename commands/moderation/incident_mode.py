"""Incident mode controls (moderators only)."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting, get_log_channel_id, now_utc


async def get_incident_mode(guild_id: int) -> bool:
    """Return True when incident mode is currently enabled for ``guild_id``."""
    return (await get_guild_setting(guild_id, "incident_mode_enabled") or "0") == "1"


async def _resolve_incident_banner_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Prefer mod audit log channel, then system channel."""
    for log_type in ("audit", "bot_error"):
        ch_id = await get_log_channel_id(guild.id, log_type)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
    if isinstance(guild.system_channel, discord.TextChannel):
        return guild.system_channel
    return None


async def sync_incident_banner(
    guild: discord.Guild,
    client: discord.Client,
    *,
    enabled: bool,
    message: str = "",
    until_ts: int = 0,
) -> None:
    """Pin or update the incident banner in the mod log / system channel."""
    ch = await _resolve_incident_banner_channel(guild)
    if ch is None:
        return

    banner_id_s = await get_guild_setting(guild.id, "incident_banner_msg")
    banner_id = int(banner_id_s) if banner_id_s and banner_id_s.isdigit() else 0

    if not enabled:
        if banner_id:
            try:
                msg = await ch.fetch_message(banner_id)
                from_ts = await get_guild_setting(guild.id, "incident_mode_until_ts")
                started = await get_guild_setting(guild.id, "incident_mode_started_at")
                summary = "Normal operations restored."
                if started:
                    summary += f"\n\n**Incident window:** {started[:16]} → cleared <t:{int(now_utc().timestamp())}:R>"
                await msg.edit(
                    embed=obsidian_embed(
                        "✅ Incident Mode Cleared",
                        summary,
                        color=discord.Color.green(),
                        client=client,
                    ),
                    content=None,
                )
                try:
                    await msg.unpin()
                except Exception:
                    pass
            except Exception:
                pass
        await set_guild_setting(guild.id, "incident_banner_msg", "0")
        return

    until_line = f"<t:{until_ts}:R>" if until_ts else "—"
    body = message.strip() or "Non-critical bot commands are limited for non-moderators during this incident."
    embed = obsidian_embed(
        "🚨 Incident Mode Active",
        f"{body}\n\n**Auto-disable:** {until_line}\n\n_Moderators retain full access._",
        color=discord.Color.orange(),
        category="moderation",
        client=client,
    )

    msg: Optional[discord.Message] = None
    if banner_id:
        try:
            msg = await ch.fetch_message(banner_id)
            await msg.edit(embed=embed, content="@everyone" if ch.permissions_for(guild.me).mention_everyone else None)
        except Exception:
            msg = None

    if msg is None:
        try:
            content = "@everyone" if ch.permissions_for(guild.me).mention_everyone else None
            msg = await ch.send(content=content, embed=embed)
            try:
                await msg.pin()
            except Exception:
                pass
        except Exception:
            return

    if msg:
        await set_guild_setting(guild.id, "incident_banner_msg", str(msg.id))


async def toggle_incident_mode(
    guild_id: int,
    *,
    duration_minutes: int = 60,
    guild: Optional[discord.Guild] = None,
    client: Optional[discord.Client] = None,
    message: str = "",
) -> bool:
    """Flip incident mode on/off for ``guild_id``. Returns the new state."""
    new_state = not await get_incident_mode(guild_id)
    if new_state:
        until = int((now_utc() + timedelta(minutes=max(5, min(duration_minutes, 24 * 60)))).timestamp())
        await set_guild_setting(guild_id, "incident_mode_enabled", "1")
        await set_guild_setting(guild_id, "incident_mode_until_ts", str(until))
        await set_guild_setting(guild_id, "incident_mode_started_at", now_utc().isoformat())
        if message:
            await set_guild_setting(guild_id, "incident_mode_message", message)
        if guild and client:
            msg = await get_guild_setting(guild_id, "incident_mode_message")
            await sync_incident_banner(
                guild,
                client,
                enabled=True,
                message=msg or message or "",
                until_ts=until,
            )
    else:
        await set_guild_setting(guild_id, "incident_mode_enabled", "0")
        await set_guild_setting(guild_id, "incident_mode_until_ts", "0")
        await set_guild_setting(guild_id, "incident_mode_message", "")
        await set_guild_setting(guild_id, "incident_mode_started_at", "")
        if guild and client:
            await sync_incident_banner(guild, client, enabled=False)
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
            await sync_incident_banner(interaction.guild, interaction.client, enabled=False)
            try:
                from core.audit import log_audit
                bot_ref = getattr(interaction.client, "bot", interaction.client)
                await log_audit(
                    interaction.guild.id,
                    "incident_disable",
                    interaction.user.id,
                    details="Incident mode disabled",
                    bot=bot_ref,
                )
            except Exception:
                pass
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
        await set_guild_setting(interaction.guild.id, "incident_mode_started_at", now_utc().isoformat())
        await set_guild_setting(interaction.guild.id, "incident_mode_message", message or "")
        await sync_incident_banner(
            interaction.guild,
            interaction.client,
            enabled=True,
            message=message or "",
            until_ts=until,
        )
        try:
            from core.audit import log_audit
            bot_ref = getattr(interaction.client, "bot", interaction.client)
            await log_audit(
                interaction.guild.id,
                "incident_enable",
                interaction.user.id,
                details=f"{minutes}m — {(message or 'default')[:120]}",
                bot=bot_ref,
            )
        except Exception:
            pass

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
