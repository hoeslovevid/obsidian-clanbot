"""Purge command."""
import asyncio
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod


def setup(bot):
    """Register the purge command."""
    @bot.tree.command(name="purge", description="Clear messages from the current channel (mods only).")
    @app_commands.describe(
        amount="Number of messages to delete (1-100), or 'all' to delete all messages in channel"
    )
    async def purge(interaction: discord.Interaction, amount: str):
        # Check if user is a mod
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

        # Check if channel is a text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)

        # Parse amount
        if amount.lower() == "all":
            limit = None  # We'll use a high number for "all"
            delete_count = 9999  # Discord API limits to 100 per call, but we'll loop
        else:
            try:
                limit = int(amount)
                if limit < 1:
                    return await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
                if limit > 100:
                    return await interaction.response.send_message("Amount cannot exceed 100 per command. Use the command multiple times or use 'all'.", ephemeral=True)
                delete_count = limit
            except ValueError:
                return await interaction.response.send_message("Invalid amount. Use a number (1-100) or 'all'.", ephemeral=True)

        # Check bot permissions
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            return await interaction.response.send_message("I don't have permission to manage messages in this channel.", ephemeral=True)

        # Defer response since purge might take a moment
        await interaction.response.defer(ephemeral=True)

        deleted = 0
        try:
            if amount.lower() == "all":
                # Delete in batches of 100 (Discord API limit)
                while True:
                    deleted_messages = await interaction.channel.purge(limit=100, check=lambda m: not m.pinned)
                    if not deleted_messages:
                        break
                    deleted += len(deleted_messages)
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
            else:
                # Delete specified amount
                deleted_messages = await interaction.channel.purge(limit=limit, check=lambda m: not m.pinned)
                deleted = len(deleted_messages)

            if deleted == 0:
                await interaction.followup.send("No messages were deleted. (Note: Pinned messages are not deleted)", ephemeral=True)
            else:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "Messages Purged",
                        f"Successfully deleted **{deleted}** message(s) from {interaction.channel.mention}.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"An error occurred while deleting messages: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)
