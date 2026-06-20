"""Force version update command for moderators to manually trigger version updates."""
import discord

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the force_version_update command."""
    command_decorator = group.command(name="force_version_update", description="Force post the most recent bot update to Discord (moderators only).") if group else bot.tree.command(name="force_version_update", description="Force post the most recent bot update to Discord (moderators only).")
    
    @command_decorator
    async def force_version_update(interaction: discord.Interaction):
        """Force post the current release changelog to the update log channel."""
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
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        from core.config import BOT_VERSION
        from core.changelog import get_release_announce_changes
        from core.release_announce import post_release_to_channel, _resolve_changelog_channel_id

        bullets = get_release_announce_changes()
        if not bullets:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ No Release Notes",
                    "No bullets in `CURRENT_RELEASE_CHANGES` for this version. Update `core/changelog.py` first.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        channel_id = await _resolve_changelog_channel_id(interaction.guild.id)
        if not channel_id:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT channel_id FROM update_log_settings WHERE guild_id = ?",
                    (interaction.guild.id,),
                )
                row = await cur.fetchone()
            channel_id = row[0] if row and row[0] else None

        if not channel_id:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Update Log Channel Not Set",
                    "Configure a changelog channel with `/updates update_log_setup` or `/admin branding`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Channel Not Found",
                    "The configured update log channel no longer exists. Please reconfigure.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        try:
            await post_release_to_channel(
                interaction.client,
                interaction.guild,
                channel,
                version=BOT_VERSION,
                mark_posted=True,
            )
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Update Posted",
                    f"Release notes for **v{BOT_VERSION}** ({len(bullets)} bullet(s)) posted to {channel.mention}.\n"
                    f"-# Only the current release is announced — older versions stay in `/whatsnew` history.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    f"I don't have permission to send messages in {channel.mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error posting version update: {e}")
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    f"Failed to post version update: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
