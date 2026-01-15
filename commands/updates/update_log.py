"""Update log command for moderators to post bot updates."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the update_log command."""
    @bot.tree.command(name="update_log", description="Post a bot update log (moderators only).")
    @app_commands.describe(
        title="Title of the update (e.g., 'New Command Added')",
        description="Description of the update (what was added/changed)",
        version="Optional version number or date"
    )
    async def update_log(
        interaction: discord.Interaction,
        title: str,
        description: str,
        version: str = None
    ):
        """Post an update log to the configured channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Get update log channel
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT channel_id FROM update_log_settings WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
        
        if not row or not row[0]:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Update Log Channel Not Set",
                    "Please configure an update log channel first using `/update_log_setup`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        channel_id = row[0]
        channel = interaction.guild.get_channel(channel_id)
        
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Channel Not Found",
                    "The configured update log channel no longer exists. Please reconfigure using `/update_log_setup`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Create update log embed
        fields = [
            ("Update", description, False),
        ]
        
        if version:
            fields.append(("Version", version, True))
        
        fields.append(("Posted By", interaction.user.mention, True))
        fields.append(("Date", f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", True))
        
        embed = obsidian_embed(
            f"🔔 Bot Update: {title}",
            "",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        # Set timestamp
        embed.timestamp = datetime.now(timezone.utc)
        
        try:
            await channel.send(embed=embed)
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Log Posted",
                    f"Update log has been posted to {channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    f"I don't have permission to send messages in {channel.mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error posting update log: {e}")
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    f"Failed to post update log: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
