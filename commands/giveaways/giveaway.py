"""Giveaway creation command."""
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils import obsidian_embed, is_mod, parse_time_natural
from database import DB_PATH
import aiosqlite


def setup(bot):
    """Register the giveaway command."""
    
    @bot.tree.command(name="giveaway", description="Create a new giveaway (mods only).")
    @app_commands.describe(
        prize="What is being given away",
        duration="How long the giveaway lasts (e.g., '1 hour', '2 days', 'tomorrow 8pm')",
        winners="Number of winners (default: 1)",
        title="Giveaway title (optional)",
        description="Additional description (optional)",
        required_role="Role required to enter (optional)",
        min_level="Minimum XP level required to enter (optional)"
    )
    async def giveaway(
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: int = 1,
        title: Optional[str] = None,
        description: Optional[str] = None,
        required_role: Optional[discord.Role] = None,
        min_level: Optional[int] = None
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can create giveaways.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Channel",
                    "Giveaways can only be created in text channels.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if winners < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Winners",
                    "Number of winners must be at least 1.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if winners > 20:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Too Many Winners",
                    "Maximum number of winners is 20.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Parse duration
        if duration.lower() in ["now", "immediately", "0"]:
            end_time = datetime.now(timezone.utc) + timedelta(seconds=10)
        else:
            # Try natural language parsing
            parsed_time = parse_time_natural(duration)
            if parsed_time:
                end_time = parsed_time
            else:
                # Try to parse as relative time (e.g., "1 hour", "2 days")
                try:
                    from dateparser import parse
                    now = datetime.now(timezone.utc)
                    parsed = parse(duration, settings={"RELATIVE_BASE": now, "TIMEZONE": "UTC"})
                    if parsed:
                        end_time = parsed.replace(tzinfo=timezone.utc)
                    else:
                        raise ValueError("Could not parse duration")
                except Exception:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Invalid Duration",
                            f"Could not parse duration: `{duration}`\n\n"
                            "Examples: '1 hour', '2 days', 'tomorrow 8pm', 'Jan 20 3pm'",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
        
        # Check if end time is in the future
        if end_time <= datetime.now(timezone.utc):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Duration",
                    "Giveaway end time must be in the future.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check if end time is too far in the future (max 1 year)
        max_end = datetime.now(timezone.utc) + timedelta(days=365)
        if end_time > max_end:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Duration Too Long",
                    "Giveaway duration cannot exceed 1 year.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Create giveaway embed
        giveaway_title = title or f"🎉 Giveaway: {prize}"
        time_remaining = end_time - datetime.now(timezone.utc)
        days = time_remaining.days
        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        time_str = ""
        if days > 0:
            time_str += f"{days} day{'s' if days != 1 else ''}, "
        if hours > 0:
            time_str += f"{hours} hour{'s' if hours != 1 else ''}, "
        if minutes > 0:
            time_str += f"{minutes} minute{'s' if minutes != 1 else ''}"
        if not time_str:
            time_str = "Less than a minute"
        
        desc = f"**Prize:** {prize}\n"
        desc += f"**Winners:** {winners}\n"
        desc += f"**Ends:** <t:{int(end_time.timestamp())}:R> (<t:{int(end_time.timestamp())}:F>)\n"
        
        if description:
            desc += f"\n{description}\n"
        
        requirements = []
        if required_role:
            requirements.append(f"Required Role: {required_role.mention}")
        if min_level:
            requirements.append(f"Minimum Level: {min_level}")
        
        if requirements:
            desc += f"\n**Requirements:**\n" + "\n".join(f"• {req}" for req in requirements)
        
        desc += f"\n\n**Entries:** 0"
        
        embed = obsidian_embed(
            giveaway_title,
            desc,
            color=discord.Color.gold(),
            client=interaction.client,
        )
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
        
        # Create view with enter button
        from views import GiveawayView
        view = GiveawayView()
        
        # Send giveaway message
        try:
            message = await interaction.channel.send(embed=embed, view=view)
            bot.add_view(view)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "I don't have permission to send messages in this channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Store in database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO giveaways (
                    guild_id, channel_id, message_id, title, description, prize,
                    winner_count, end_time, created_by, created_at, required_role_id, min_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                interaction.channel.id,
                message.id,
                giveaway_title,
                description or "",
                prize,
                winners,
                end_time.isoformat(),
                interaction.user.id,
                datetime.now(timezone.utc).isoformat(),
                required_role.id if required_role else None,
                min_level
            ))
            await db.commit()
            
            # Get the giveaway ID
            cur = await db.execute("""
                SELECT id FROM giveaways WHERE guild_id = ? AND message_id = ?
            """, (interaction.guild.id, message.id))
            giveaway_id = (await cur.fetchone())[0]
        
        # Create view with giveaway ID and update message
        from views import GiveawayView
        view = GiveawayView(giveaway_id)
        bot.add_view(view)
        
        # Update message with view
        try:
            await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding view to giveaway message: {e}")
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Giveaway Created",
                f"Giveaway created successfully!\n\n"
                f"[Jump to giveaway]({message.jump_url})",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
