"""Schedule message command - send a message at a future time."""
import dateparser  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore
from datetime import datetime, timezone

from config import TIMEZONE
from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the schedule command."""
    command_decorator = (
        group.command(name="schedule", description="Schedule a message to be sent at a future time.")
        if group
        else bot.tree.command(name="schedule", description="Schedule a message to be sent at a future time.")
    )

    @command_decorator
    @app_commands.describe(
        channel="Channel to send the message in",
        when="When to send (e.g. 'tomorrow 8pm', 'in 2 hours')",
        message="The message content to send",
    )
    async def schedule(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        when: str,
        message: str,
    ):
        """Schedule a message to be sent later."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True,
            )

        if len(message) < 1 or len(message) > 2000:
            return await interaction.response.send_message(
                "Message must be 1–2000 characters.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        send_time = dateparser.parse(
            when,
            settings={"TIMEZONE": TIMEZONE, "RETURN_AS_TIMEZONE_AWARE": True, "TO_TIMEZONE": "UTC"},
            relative_base=datetime.now(timezone.utc),
        )

        if not send_time:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Time",
                    f"Could not parse '{when}'. Try: 'in 2 hours', 'tomorrow 8pm', 'Jan 15 3:00pm'.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if send_time <= datetime.now(timezone.utc):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Time",
                    "The scheduled time must be in the future.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO scheduled_messages (guild_id, channel_id, user_id, message_content, send_at, created_at, sent)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    interaction.guild.id,
                    channel.id,
                    interaction.user.id,
                    message,
                    send_time.isoformat(),
                    now_utc().isoformat(),
                ),
            )
            await db.commit()

        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Message Scheduled",
                f"**Channel:** {channel.mention}\n"
                f"**When:** <t:{int(send_time.timestamp())}:F> (<t:{int(send_time.timestamp())}:R>)\n"
                f"**Preview:** {message[:100]}{'…' if len(message) > 100 else ''}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
