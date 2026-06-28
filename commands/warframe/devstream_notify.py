"""Devstream notification setup command."""
import logging

import discord
from discord import app_commands
import dateparser  # type: ignore

from core.utils import obsidian_embed, is_mod
from database import set_guild_setting, DB_PATH
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
    """Register devstream_set only; channel alerts use /wfnotify configure."""

    async def _ensure_migration():
        await _migrate_devstream_channel_key()

    command_decorator = (
        group.command(name="devstream_set", description="Set the next devstream date (moderators only).")
        if group
        else bot.tree.command(name="devstream_set", description="Set the next devstream date (moderators only).")
    )

    @command_decorator
    @app_commands.describe(
        date="Date and time of the next devstream (e.g., 'Friday 2pm EST' or '2024-01-19 14:00')"
    )
    async def devstream_set(interaction: discord.Interaction, date: str):
        """Set the next devstream date."""
        await _ensure_migration()
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

        await set_guild_setting(interaction.guild.id, "next_devstream_date", parsed_date.isoformat())

        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Devstream Date Set",
                f"Next devstream scheduled for: <t:{int(parsed_date.timestamp())}:F>\n\n"
                "Notifications will be sent 24 hours and 1 hour before the devstream.\n\n"
                "Configure the alert channel with **`/wfnotify configure`**.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
