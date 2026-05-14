"""Devstream notification setup command."""
import logging
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import dateparser  # type: ignore

from core.utils import obsidian_embed, setup_missing_embed, is_mod
from database import get_guild_setting, set_guild_setting, DB_PATH
import aiosqlite  # type: ignore

logger = logging.getLogger(__name__)

# Canonical key for the devstream notification channel. Older releases wrote to
# "devstream_channel_id"; _migrate_devstream_channel_key() copies legacy rows on
# startup so existing guilds keep their configured channel. Safe to remove the
# fallback + migration after one release cycle.
_DEVSTREAM_CHANNEL_KEY = "devstream_notify_channel_id"
_DEVSTREAM_CHANNEL_LEGACY_KEY = "devstream_channel_id"


async def _migrate_devstream_channel_key() -> None:
    """One-time migration: copy devstream_channel_id → devstream_notify_channel_id.

    Only copies when the new key is empty/missing so we never clobber a fresh
    value. The old key is left in place for one release cycle as a safety net.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT old.guild_id, old.value
                FROM guild_settings old
                LEFT JOIN guild_settings new
                  ON new.guild_id = old.guild_id AND new.key = ?
                WHERE old.key = ?
                  AND old.value IS NOT NULL AND old.value <> ''
                  AND (new.value IS NULL OR new.value = '')
                """,
                (_DEVSTREAM_CHANNEL_KEY, _DEVSTREAM_CHANNEL_LEGACY_KEY),
            )
            rows = await cur.fetchall()
            if not rows:
                return
            for guild_id, value in rows:
                await db.execute(
                    """
                    INSERT INTO guild_settings (guild_id, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value
                    """,
                    (guild_id, _DEVSTREAM_CHANNEL_KEY, value),
                )
            await db.commit()
            logger.info(
                f"[migration] Copied {len(rows)} devstream_channel_id row(s) to {_DEVSTREAM_CHANNEL_KEY}"
            )
    except Exception as e:
        logger.warning(f"[migration] devstream channel key migration failed: {e}")


def setup(bot, group=None):
    """Register the devstream_notify command."""
    
    command_decorator = group.command(name="devstream_notify", description="Configure devstream notifications (moderators only).") if group else bot.tree.command(name="devstream_notify", description="Configure devstream notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to send devstream notifications to"
    )
    async def devstream_notify(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure devstream notifications."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        if action.lower() == "setup":
            if not channel:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Channel",
                        "Please specify a channel for devstream notifications.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_guild_setting(interaction.guild.id, _DEVSTREAM_CHANNEL_KEY, str(channel.id))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Devstream Notifications Configured",
                    f"Devstream notifications will be sent to {channel.mention}.\n\n"
                    "Devstream dates are automatically detected. The bot will calculate the next devstream based on the typical schedule (every other Friday at 2pm ET).\n\n"
                    "You can manually override the date using `/devstream_set` if needed.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            await set_guild_setting(interaction.guild.id, _DEVSTREAM_CHANNEL_KEY, "")
            # Clear the legacy key too so a removed channel stays removed.
            await set_guild_setting(interaction.guild.id, _DEVSTREAM_CHANNEL_LEGACY_KEY, "")
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Devstream Notifications Disabled",
                    "Devstream notifications have been disabled.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            channel_id_str = await get_guild_setting(interaction.guild.id, _DEVSTREAM_CHANNEL_KEY)
            if not channel_id_str:
                # Fall back to the legacy key for guilds that haven't been
                # migrated yet (e.g. status check before the startup migration
                # ran).
                channel_id_str = await get_guild_setting(interaction.guild.id, _DEVSTREAM_CHANNEL_LEGACY_KEY)
            next_devstream = await get_guild_setting(interaction.guild.id, "next_devstream_date")
            
            if not channel_id_str:
                return await interaction.followup.send(
                    embed=setup_missing_embed(
                        "Devstream Notifications",
                        "/warframe devstream_notify",
                        "Use the 'set' action to choose a channel for devstream alerts.",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            
            try:
                channel_id = int(channel_id_str)
                channel_obj = interaction.guild.get_channel(channel_id)
                status_text = f"**Channel:** {channel_obj.mention if channel_obj else f'Channel ID: {channel_id}'}\n**Status:** Enabled\n"
                
                if next_devstream:
                    try:
                        devstream_date = dateparser.parse(next_devstream, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                        if devstream_date:
                            now = datetime.now(timezone.utc)
                            if devstream_date > now:
                                status_text += f"**Next Devstream:** <t:{int(devstream_date.timestamp())}:F>"
                            else:
                                status_text += f"**Next Devstream:** Past (needs update)"
                    except Exception:
                        status_text += f"**Next Devstream:** {next_devstream}"
                else:
                    status_text += "**Next Devstream:** Not set (use `/devstream_set`)"
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📺 Devstream Notifications Status",
                        status_text,
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except ValueError:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📺 Devstream Notifications Status",
                        "Devstream notifications are configured but channel ID is invalid.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `setup`, `remove`, `status`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
    
    command_decorator = group.command(name="devstream_set", description="Set the next devstream date (moderators only).") if group else bot.tree.command(name="devstream_set", description="Set the next devstream date (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        date="Date and time of the next devstream (e.g., 'Friday 2pm EST' or '2024-01-19 14:00')"
    )
    async def devstream_set(interaction: discord.Interaction, date: str):
        """Set the next devstream date."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Parse the date
        parsed_date = dateparser.parse(date, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not parsed_date:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Date",
                    f"Could not parse date: '{date}'\n\nTry formats like:\n• 'Friday 2pm EST'\n• '2024-01-19 14:00'\n• 'next Friday at 2pm'",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Store as ISO format
        await set_guild_setting(interaction.guild.id, "next_devstream_date", parsed_date.isoformat())
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Devstream Date Set",
                f"Next devstream scheduled for: <t:{int(parsed_date.timestamp())}:F>\n\n"
                "Notifications will be sent 24 hours and 1 hour before the devstream.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
