"""Server member count channel command."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore


def format_member_count_name(member_count: int, bot_count: int, human_count: int) -> str:
    """Format the channel name with member counts."""
    # Discord channel names have a 100 character limit
    # Format: "👥 Members: 1,234 | 🤖 Bots: 56 | 👤 Humans: 1,178"
    name = f"👥 Members: {member_count:,} | 🤖 Bots: {bot_count:,} | 👤 Humans: {human_count:,}"
    
    # Truncate if too long (shouldn't happen with reasonable numbers, but safety check)
    if len(name) > 100:
        # Fallback to simpler format
        name = f"👥 {member_count:,} | 🤖 {bot_count:,} | 👤 {human_count:,}"
        if len(name) > 100:
            # Last resort: just total
            name = f"👥 Members: {member_count:,}"
            if len(name) > 100:
                name = f"Members: {member_count:,}"[:100]
    
    return name


async def update_member_count_channel(guild: discord.Guild, channel_id: int) -> bool:
    """Update the member count channel name. Returns True if successful."""
    try:
        channel = guild.get_channel(channel_id)
        if not channel:
            return False
        
        # Get counts
        member_count = guild.member_count
        bot_count = sum(1 for member in guild.members if member.bot)
        human_count = member_count - bot_count
        
        # Format and update channel name
        new_name = format_member_count_name(member_count, bot_count, human_count)
        
        # Only update if name changed (to avoid rate limits)
        if channel.name != new_name:
            await channel.edit(name=new_name, reason="Member count update")
        
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating member count channel {channel_id} in {guild.id}: {e}")
        return False


def setup(bot):
    """Register the member_count command."""
    @bot.tree.command(name="member_count", description="Create or update a channel that displays server member count (moderators only).")
    @app_commands.describe(
        channel_type="Type of channel to create (voice, text, or stage)",
        category="Category to place the channel in (leave empty for top of server)"
    )
    @app_commands.choices(channel_type=[
        app_commands.Choice(name="Voice Channel", value="voice"),
        app_commands.Choice(name="Text Channel", value="text"),
        app_commands.Choice(name="Stage Channel", value="stage"),
    ])
    async def member_count(
        interaction: discord.Interaction,
        channel_type: app_commands.Choice[str],
        category: discord.CategoryChannel = None
    ):
        """Create or update a member count channel."""
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can use this command.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=False)
        
        channel_type_value = channel_type.value
        
        # Get counts
        member_count = interaction.guild.member_count
        bot_count = sum(1 for member in interaction.guild.members if member.bot)
        human_count = member_count - bot_count
        
        # Check if channel already exists
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, channel_type FROM member_count_channels WHERE guild_id=?",
                (interaction.guild.id,)
            )
            existing = await cur.fetchone()
        
        channel_id = None
        channel = None
        was_created = False
        
        if existing:
            existing_channel_id, existing_type = existing
            existing_channel = interaction.guild.get_channel(existing_channel_id)
            
            if existing_channel:
                # Channel exists, update it
                channel_id = existing_channel_id
                channel = existing_channel
                
                # If type changed, we need to recreate
                if existing_type != channel_type_value:
                    try:
                        await existing_channel.delete(reason="Member count channel type changed")
                        channel = None  # Will create new one below
                        # Remove from database since we're creating a new one
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "DELETE FROM member_count_channels WHERE guild_id=?",
                                (interaction.guild.id,)
                            )
                            await db.commit()
                    except Exception as e:
                        return await interaction.followup.send(
                            embed=obsidian_embed(
                                "❌ Error",
                                f"Could not delete existing channel to change type: {e}",
                                color=discord.Color.red(),
                                client=interaction.client,
                            ),
                            ephemeral=True
                        )
                else:
                    # Just update the name and position
                    new_name = format_member_count_name(member_count, bot_count, human_count)
                    try:
                        # Position at top (position 0) - but respect category position
                        edit_kwargs = {
                            "name": new_name,
                            "reason": "Member count channel update"
                        }
                        
                        # Only set position if not in a category, or set category position
                        if category:
                            edit_kwargs["category"] = category
                            # Position within category (0 = top of category)
                            edit_kwargs["position"] = 0
                        else:
                            # Position at top of server (0 = top)
                            edit_kwargs["position"] = 0
                        
                        await channel.edit(**edit_kwargs)
                    except Exception as e:
                        return await interaction.followup.send(
                            embed=obsidian_embed(
                                "❌ Error",
                                f"Could not update channel: {e}",
                                color=discord.Color.red(),
                                client=interaction.client,
                            ),
                            ephemeral=True
                        )
            else:
                # Channel was deleted, remove from database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM member_count_channels WHERE guild_id=?",
                        (interaction.guild.id,)
                    )
                    await db.commit()
                channel = None  # Will create new one below
        
        # Create new channel if needed
        if not channel:
            new_name = format_member_count_name(member_count, bot_count, human_count)
            
            try:
                if channel_type_value == "voice":
                    channel = await interaction.guild.create_voice_channel(
                        name=new_name,
                        category=category,
                        position=0,
                        reason="Member count channel created"
                    )
                elif channel_type_value == "text":
                    channel = await interaction.guild.create_text_channel(
                        name=new_name,
                        category=category,
                        position=0,
                        reason="Member count channel created"
                    )
                elif channel_type_value == "stage":
                    channel = await interaction.guild.create_stage_channel(
                        name=new_name,
                        category=category,
                        position=0,
                        reason="Member count channel created"
                    )
                else:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Error",
                            "Invalid channel type.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                channel_id = channel.id
                was_created = True
                
                # Save to database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO member_count_channels (guild_id, channel_id, channel_type)
                        VALUES (?, ?, ?)
                    """, (interaction.guild.id, channel_id, channel_type_value))
                    await db.commit()
                
            except Exception as e:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Error",
                        f"Could not create channel: {e}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Success message
        channel_type_display = channel_type_value.title()
        fields = [
            ("📢 Channel", channel.mention, True),
            ("📊 Type", channel_type_display, True),
            ("👥 Total Members", f"{member_count:,}", True),
            ("👤 Humans", f"{human_count:,}", True),
            ("🤖 Bots", f"{bot_count:,}", True),
        ]
        
        embed = obsidian_embed(
            "✅ Member Count Channel Ready",
            f"Member count channel **{channel_type_display}** has been {'created' if was_created else 'updated'}.\n\nThe channel name will be updated automatically every 2 minutes with accurate member counts.",
            color=discord.Color.green(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
