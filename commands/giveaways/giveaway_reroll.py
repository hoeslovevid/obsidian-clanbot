"""Reroll giveaway winners command."""
import discord
from discord import app_commands
import random

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot):
    """Register the giveaway_reroll command."""
    
    @bot.tree.command(name="giveaway_reroll", description="Reroll winners for an ended giveaway (mods only).")
    @app_commands.describe(
        message="The giveaway message ID or link",
        winner_count="Number of winners to select (default: original winner count)"
    )
    async def giveaway_reroll(interaction: discord.Interaction, message: str, winner_count: int = None):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can reroll giveaways.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Parse message ID
        message_id = None
        try:
            if "/" in message:
                message_id = int(message.split("/")[-1])
            else:
                message_id = int(message)
        except ValueError:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Input",
                    "Invalid message ID or link. Please provide a valid message ID or message link.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Find giveaway
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, winner_count, ended FROM giveaways
                WHERE guild_id = ? AND message_id = ?
            """, (interaction.guild.id, message_id))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Giveaway Not Found",
                    "No giveaway found with that message ID in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        giveaway_id, original_winner_count, ended = row
        
        if not ended:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Giveaway Not Ended",
                    "This giveaway has not ended yet. Use `/giveaway_end` to end it first.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get entries
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?
            """, (giveaway_id,))
            entries = await cur.fetchall()
        
        if not entries:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ No Entries",
                    "This giveaway had no entries.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Use provided winner count or original
        num_winners = winner_count if winner_count else original_winner_count
        
        if num_winners < 1:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Winners",
                    "Number of winners must be at least 1.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if num_winners > len(entries):
            num_winners = len(entries)
        
        # Select new winners
        entry_user_ids = [entry[0] for entry in entries]
        winners = random.sample(entry_user_ids, num_winners)
        
        # Update message
        try:
            channel = interaction.channel
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    giveaway_message = await channel.fetch_message(message_id)
                    if giveaway_message and giveaway_message.embeds:
                        embed = giveaway_message.embeds[0]
                        
                        # Update winners section
                        winner_mentions = []
                        for winner_id in winners:
                            member = interaction.guild.get_member(winner_id)
                            if member:
                                winner_mentions.append(member.mention)
                            else:
                                winner_mentions.append(f"<@{winner_id}>")
                        
                        # Remove old winners section and add new one
                        desc = embed.description
                        if "**🎉 Winner" in desc:
                            desc = desc.rsplit("**🎉 Winner", 1)[0]
                        
                        desc += f"\n\n**🎉 Winner{'s' if len(winners) > 1 else ''} (Rerolled):**\n" + "\n".join(winner_mentions)
                        embed.description = desc
                        
                        await giveaway_message.edit(embed=embed)
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.error(f"Error updating rerolled giveaway message: {e}")
        except Exception as e:
            logger.error(f"Error rerolling giveaway: {e}")
        
        winner_mentions = []
        for winner_id in winners:
            member = interaction.guild.get_member(winner_id)
            if member:
                winner_mentions.append(member.mention)
            else:
                winner_mentions.append(f"<@{winner_id}>")
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Winners Rerolled",
                f"New winner{'s' if len(winners) > 1 else ''} selected:\n\n" + "\n".join(winner_mentions),
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
