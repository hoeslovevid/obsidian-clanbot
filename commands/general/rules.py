"""Server rules commands."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def update_rules_channel_message(guild: discord.Guild, bot):
    """Update the rules message in the configured channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get rules channel settings
        cur = await db.execute("""
            SELECT channel_id, message_id FROM rules_channel_settings WHERE guild_id=?
        """, (guild.id,))
        row = await cur.fetchone()
        
        if not row or not row[0]:
            return  # No channel configured
        
        channel_id, message_id = row
        channel = guild.get_channel(channel_id)
        
        if not isinstance(channel, discord.TextChannel):
            return  # Channel doesn't exist
        
        # Get all rules
        cur = await db.execute("""
            SELECT rule_number, rule_text FROM server_rules
            WHERE guild_id=? ORDER BY rule_number
        """, (guild.id,))
        rules_list = await cur.fetchall()
        
        # Build rules embed
        if not rules_list:
            rules_text = "No rules have been set for this server yet."
        else:
            rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
        
        # Truncate if too long (Discord embed description limit is 4096)
        if len(rules_text) > 4096:
            rules_text = rules_text[:4093] + "..."
        
        embed = obsidian_embed(
            "📜 Server Rules",
            rules_text,
            color=discord.Color.blue(),
            client=bot,
        )
        
        # Try to update existing message or send new one
        try:
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=embed)
                    return  # Successfully updated
                except discord.NotFound:
                    # Message was deleted, send a new one
                    pass
                except discord.Forbidden:
                    # No permission, skip
                    return
            
            # Send new message
            message = await channel.send(embed=embed)
            
            # Update database with new message ID
            await db.execute("""
                INSERT OR REPLACE INTO rules_channel_settings (guild_id, channel_id, message_id)
                VALUES (?, ?, ?)
            """, (guild.id, channel_id, message.id))
            await db.commit()
        except discord.Forbidden:
            # No permission to send/edit messages
            pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error updating rules channel message: {e}")


def setup(bot, group=None):
    """Register rules commands."""
    
    command_decorator = group.command(name="rules", description="View server rules.") if group else bot.tree.command(name="rules", description="View server rules.")
    
    @command_decorator
    async def rules(interaction: discord.Interaction):
        """Display server rules."""
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
        
        # Get rules
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT rule_number, rule_text FROM server_rules
                WHERE guild_id=? ORDER BY rule_number
            """, (interaction.guild.id,))
            rules_list = await cur.fetchall()
            
            # Check if user has accepted
            cur = await db.execute("""
                SELECT 1 FROM rule_acceptances WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            has_accepted = await cur.fetchone() is not None
        
        if not rules_list:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📜 Server Rules",
                    "No rules have been set for this server yet.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build rules text
        rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
        
        if not has_accepted:
            rules_text += "\n\n⚠️ **You have not accepted these rules yet. Use `/accept_rules` to accept them.**"
        
        embed = obsidian_embed(
            "📜 Server Rules",
            rules_text,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="accept_rules", description="Accept the server rules.") if group else bot.tree.command(name="accept_rules", description="Accept the server rules.")
    
    @command_decorator
    async def accept_rules(interaction: discord.Interaction):
        """Accept server rules."""
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
        
        # Check if rules exist
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT 1 FROM server_rules WHERE guild_id=?", (interaction.guild.id,))
            if not await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Rules",
                        "No rules have been set for this server yet.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check if already accepted
            cur = await db.execute("""
                SELECT 1 FROM rule_acceptances WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Accepted",
                        "You have already accepted the server rules.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Record acceptance
            await db.execute("""
                INSERT OR REPLACE INTO rule_acceptances (guild_id, user_id, accepted_at)
                VALUES (?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, now_utc().isoformat()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Rules Accepted",
                "You have accepted the server rules. Thank you!",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="rules_setup", description="Set up server rules (moderators only).") if group else bot.tree.command(name="rules_setup", description="Set up server rules (moderators only).")
    
    @command_decorator
    @app_commands.describe(action="Action to perform", rule_number="Rule number (for add/edit/remove)", rule_text="Rule text (for add/edit)", channel="Channel to post rules (for set_channel)")
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="edit", value="edit"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="Set Channel", value="set_channel"),
    ])
    async def rules_setup(interaction: discord.Interaction, action: str, rule_number: Optional[int] = None, rule_text: Optional[str] = None, channel: Optional[discord.TextChannel] = None):
        """Manage server rules."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            if action == "add":
                if not rule_text:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Rule Text",
                            "Please provide the rule text.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Get next rule number
                cur = await db.execute("""
                    SELECT MAX(rule_number) FROM server_rules WHERE guild_id=?
                """, (interaction.guild.id,))
                row = await cur.fetchone()
                next_number = (row[0] or 0) + 1
                
                await db.execute("""
                    INSERT INTO server_rules (guild_id, rule_number, rule_text, created_at)
                    VALUES (?, ?, ?, ?)
                """, (interaction.guild.id, next_number, rule_text, now_utc().isoformat()))
                await db.commit()
                
                # Update rules channel message if configured
                await update_rules_channel_message(interaction.guild, interaction.client)
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Added",
                        f"Rule #{next_number} has been added.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "edit":
                if not rule_number or not rule_text:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Parameters",
                            "Please provide both rule number and rule text.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    UPDATE server_rules SET rule_text=? WHERE guild_id=? AND rule_number=?
                """, (rule_text, interaction.guild.id, rule_number))
                await db.commit()
                
                # Update rules channel message if configured
                await update_rules_channel_message(interaction.guild, interaction.client)
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Updated",
                        f"Rule #{rule_number} has been updated.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "remove":
                if not rule_number:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Rule Number",
                            "Please provide the rule number to remove.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    DELETE FROM server_rules WHERE guild_id=? AND rule_number=?
                """, (interaction.guild.id, rule_number))
                await db.commit()
                
                # Update rules channel message if configured
                await update_rules_channel_message(interaction.guild, interaction.client)
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Removed",
                        f"Rule #{rule_number} has been removed.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "list":
                cur = await db.execute("""
                    SELECT rule_number, rule_text FROM server_rules
                    WHERE guild_id=? ORDER BY rule_number
                """, (interaction.guild.id,))
                rules_list = await cur.fetchall()
                
                if not rules_list:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "📜 Server Rules",
                            "No rules have been set yet.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
                embed = obsidian_embed(
                    "📜 Server Rules",
                    rules_text,
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            
            elif action == "set_channel":
                if not channel:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Channel",
                            "Please specify a channel to post rules in.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Check if bot has permission to send messages in the channel
                if not channel.permissions_for(interaction.guild.me).send_messages:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Permission Denied",
                            f"I don't have permission to send messages in {channel.mention}.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Get all rules
                cur = await db.execute("""
                    SELECT rule_number, rule_text FROM server_rules
                    WHERE guild_id=? ORDER BY rule_number
                """, (interaction.guild.id,))
                rules_list = await cur.fetchall()
                
                if not rules_list:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ No Rules",
                            "Please add some rules first before setting up the rules channel.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Build rules embed
                rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
                
                # Truncate if too long (Discord embed description limit is 4096)
                if len(rules_text) > 4096:
                    rules_text = rules_text[:4093] + "..."
                
                embed = obsidian_embed(
                    "📜 Server Rules",
                    rules_text,
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
                
                # Check if there's an existing message to update
                cur = await db.execute("""
                    SELECT message_id FROM rules_channel_settings WHERE guild_id=?
                """, (interaction.guild.id,))
                row = await cur.fetchone()
                existing_message_id = row[0] if row else None
                
                try:
                    if existing_message_id:
                        # Try to update existing message if it's in the same channel
                        try:
                            # Get existing channel ID
                            cur = await db.execute("""
                                SELECT channel_id FROM rules_channel_settings WHERE guild_id=?
                            """, (interaction.guild.id,))
                            existing_row = await cur.fetchone()
                            existing_channel_id = existing_row[0] if existing_row else None
                            
                            if existing_channel_id == channel.id:
                                # Same channel, try to update existing message
                                message = await channel.fetch_message(existing_message_id)
                                await message.edit(embed=embed)
                                
                                await interaction.followup.send(
                                    embed=obsidian_embed(
                                        "✅ Rules Channel Updated",
                                        f"Rules message has been updated in {channel.mention}.",
                                        color=discord.Color.green(),
                                        client=interaction.client,
                                    ),
                                    ephemeral=True
                                )
                                return
                        except discord.NotFound:
                            # Message was deleted, send a new one
                            pass
                    
                    # Send new message
                    message = await channel.send(embed=embed)
                    
                    # Save channel and message ID
                    await db.execute("""
                        INSERT OR REPLACE INTO rules_channel_settings (guild_id, channel_id, message_id)
                        VALUES (?, ?, ?)
                    """, (interaction.guild.id, channel.id, message.id))
                    await db.commit()
                    
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "✅ Rules Channel Set",
                            f"Rules have been posted to {channel.mention}. The message will automatically update whenever rules are changed.",
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
                    logging.getLogger(__name__).error(f"Error setting rules channel: {e}")
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Error",
                            f"Failed to set rules channel: {str(e)}",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
