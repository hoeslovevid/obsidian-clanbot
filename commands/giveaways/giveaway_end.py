"""End giveaway early command."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite
import random


async def end_giveaway(giveaway_id: int, bot, force: bool = False) -> tuple[bool, str, list]:
    """End a giveaway and select winners. Returns (success, message, winners)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, guild_id, channel_id, message_id, title, prize, winner_count, end_time, ended
            FROM giveaways WHERE id = ?
        """, (giveaway_id,))
        row = await cur.fetchone()
    
    if not row:
        return False, "Giveaway not found.", []
    
    giveaway_id, guild_id, channel_id, message_id, title, prize, winner_count, end_time_str, ended = row
    
    if ended and not force:
        return False, "This giveaway has already ended.", []
    
    # Get entries
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?
        """, (giveaway_id,))
        entries = await cur.fetchall()
    
    if not entries:
        # Mark as ended
        from database import now_utc
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE giveaways SET ended = 1, ended_at = ? WHERE id = ?
            """, (now_utc().isoformat(), giveaway_id))
            await db.commit()
        
        return True, "Giveaway ended, but there were no entries.", []
    
    # Select winners
    entry_user_ids = [entry[0] for entry in entries]
    
    # If more winners than entries, just use all entries
    if winner_count >= len(entry_user_ids):
        winners = entry_user_ids
    else:
        winners = random.sample(entry_user_ids, winner_count)
    
    # Mark as ended
    from database import now_utc
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE giveaways SET ended = 1, ended_at = ? WHERE id = ?
        """, (now_utc().isoformat(), giveaway_id))
        await db.commit()
    
    # Update the giveaway message
    try:
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(message_id)
                    if message:
                        # Update embed
                        embed = message.embeds[0] if message.embeds else None
                        if embed:
                            embed.color = discord.Color.dark_grey()
                            embed.description = embed.description.replace("**Ends:**", "**Ended:**")
                            
                            # Add winners
                            winner_mentions = []
                            for winner_id in winners:
                                member = guild.get_member(winner_id)
                                if member:
                                    winner_mentions.append(member.mention)
                                else:
                                    winner_mentions.append(f"<@{winner_id}>")
                            
                            embed.description += f"\n\n**🎉 Winner{'s' if len(winners) > 1 else ''}:**\n" + "\n".join(winner_mentions)
                            
                            await message.edit(embed=embed, view=None)  # Remove buttons
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.error(f"Error updating giveaway message: {e}")
    except Exception as e:
        logger.error(f"Error ending giveaway: {e}")
    
    return True, f"Giveaway ended! {len(winners)} winner(s) selected.", winners


def setup(bot, group=None):
    """Register the giveaway_end command."""
    
    command_decorator = group.command(name="giveaway_end", description="End a giveaway early and select winners (mods only).") if group else bot.tree.command(name="giveaway_end", description="End a giveaway early and select winners (mods only).")
    
    @command_decorator
    @app_commands.describe(
        message="The giveaway message ID or link"
    )
    async def giveaway_end(interaction: discord.Interaction, message: str):
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
        
        # Find giveaway by message ID
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id FROM giveaways WHERE guild_id = ? AND message_id = ?
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
        
        giveaway_id = row[0]
        
        # End giveaway
        success, result_message, winners = await end_giveaway(giveaway_id, interaction.client)
        
        if not success:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    result_message,
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build winner list
        winner_mentions = []
        for winner_id in winners:
            member = interaction.guild.get_member(winner_id)
            if member:
                winner_mentions.append(member.mention)
            else:
                winner_mentions.append(f"<@{winner_id}>")
        
        embed = obsidian_embed(
            "✅ Giveaway Ended",
            f"{result_message}\n\n"
            f"**Winner{'s' if len(winners) > 1 else ''}:**\n" + "\n".join(winner_mentions),
            color=discord.Color.green(),
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{len(winners)} winner(s) selected",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
