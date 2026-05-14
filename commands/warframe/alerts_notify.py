"""Alert notification setup command."""
import logging
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, setup_missing_embed, is_mod
from database import get_guild_setting, set_guild_setting, DB_PATH
import aiosqlite  # type: ignore

logger = logging.getLogger(__name__)

# Canonical key for the alerts notification channel. Older releases wrote to
# "alerts_channel_id"; _migrate_alerts_channel_key() copies legacy rows on
# startup so existing guilds keep their configured channel. Safe to remove the
# fallback + migration after one release cycle.
_ALERTS_CHANNEL_KEY = "alerts_notify_channel_id"
_ALERTS_CHANNEL_LEGACY_KEY = "alerts_channel_id"


async def _migrate_alerts_channel_key() -> None:
    """One-time migration: copy alerts_channel_id → alerts_notify_channel_id.

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
                (_ALERTS_CHANNEL_KEY, _ALERTS_CHANNEL_LEGACY_KEY),
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
                    (guild_id, _ALERTS_CHANNEL_KEY, value),
                )
            await db.commit()
            logger.info(
                f"[migration] Copied {len(rows)} alerts_channel_id row(s) to {_ALERTS_CHANNEL_KEY}"
            )
    except Exception as e:
        logger.warning(f"[migration] alerts channel key migration failed: {e}")


def setup(bot, group=None):
    """Register the alerts_notify command."""
    
    command_decorator = group.command(name="alerts_notify", description="Configure alert notifications (moderators only).") if group else bot.tree.command(name="alerts_notify", description="Configure alert notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to send alert notifications to"
    )
    async def alerts_notify(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure alert notifications."""
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
                        "Please specify a channel for alert notifications.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_guild_setting(interaction.guild.id, _ALERTS_CHANNEL_KEY, str(channel.id))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Alert Notifications Configured",
                    f"Alert notifications will be sent to {channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            await set_guild_setting(interaction.guild.id, _ALERTS_CHANNEL_KEY, "")
            # Clear the legacy key too so a removed channel stays removed.
            await set_guild_setting(interaction.guild.id, _ALERTS_CHANNEL_LEGACY_KEY, "")
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Alert Notifications Disabled",
                    "Alert notifications have been disabled.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            channel_id_str = await get_guild_setting(interaction.guild.id, _ALERTS_CHANNEL_KEY)
            if not channel_id_str:
                # Fall back to the legacy key for guilds that haven't been
                # migrated yet (e.g. status check before the startup migration
                # ran).
                channel_id_str = await get_guild_setting(interaction.guild.id, _ALERTS_CHANNEL_LEGACY_KEY)
            
            if not channel_id_str:
                return await interaction.followup.send(
                    embed=setup_missing_embed(
                        "Alert Notifications",
                        "/warframe alerts_notify",
                        "Use the 'set' action to choose a channel for Warframe alert pings.",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            
            try:
                channel_id = int(channel_id_str)
                channel_obj = interaction.guild.get_channel(channel_id)
                if channel_obj:
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "📢 Alert Notifications Status",
                            f"**Channel:** {channel_obj.mention}\n**Status:** Enabled",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "📢 Alert Notifications Status",
                            f"**Channel ID:** {channel_id}\n**Status:** Channel not found (may have been deleted)",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
            except ValueError:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📢 Alert Notifications Status",
                        "Alert notifications are configured but channel ID is invalid.",
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
