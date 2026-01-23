"""Reaction roles commands - simplified setup similar to rules."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def update_reaction_role_message(guild: discord.Guild, message_id: int, channel_id: int, bot):
    """Update the reaction role message embed with current roles."""
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    # Get all reaction roles for this message
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT emoji, role_id FROM reaction_roles
            WHERE guild_id=? AND message_id=?
            ORDER BY id
        """, (guild.id, message_id))
        roles_list = await cur.fetchall()
        
        # Get message title/description if stored
        # For now, we'll build a simple embed
    
    if not roles_list:
        return  # No roles to display
    
    # Build description
    description = "React with the emojis below to get the corresponding roles:\n\n"
    for emoji, role_id in roles_list:
        role = guild.get_role(role_id)
        role_name = role.mention if role else f"Unknown Role ({role_id})"
        description += f"{emoji} - {role_name}\n"
    
    # Truncate if too long
    if len(description) > 4096:
        description = description[:4093] + "..."
    
    embed = obsidian_embed(
        "🎭 Reaction Roles",
        description,
        color=discord.Color.blue(),
        client=bot,
    )
    
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden):
        pass


def setup(bot, group=None):
    """Register reaction role commands."""
    
    command_decorator = group.command(name="reaction_role", description="Manage reaction roles (moderators only).") if group else bot.tree.command(name="reaction_role", description="Manage reaction roles (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to post/create reaction role message (for create)",
        title="Title for the reaction role message (for create)",
        description="Description for the reaction role message (for create)",
        message_id="Message ID or link (for add/remove to existing message)",
        emoji="Emoji to use (for add/remove)",
        role="Role to assign (for add)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def reaction_role(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        message_id: Optional[str] = None,
        emoji: Optional[str] = None,
        role: Optional[discord.Role] = None
    ):
        """Manage reaction roles - create messages and assign roles."""
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
        
        # Check bot permissions
        if not interaction.guild.me.guild_permissions.manage_roles:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Missing Permissions",
                    "I don't have permission to manage roles. Please grant me the 'Manage Roles' permission.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            if action == "create":
                if not channel:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Channel",
                            "Please specify a channel to post the reaction role message in.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Check if bot can send messages in channel
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
                
                # Create embed
                title_text = title or "🎭 Reaction Roles"
                desc_text = description or "React with the emojis below to get the corresponding roles."
                
                embed = obsidian_embed(
                    title_text,
                    desc_text,
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
                
                # Send message
                try:
                    message = await channel.send(embed=embed)
                    
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "✅ Reaction Role Message Created",
                            f"Reaction role message created in {channel.mention}.\n\n"
                            f"Use `/reaction_role action:Add` to add emoji-role pairs to this message.\n"
                            f"Message ID: `{message.id}`\n"
                            f"[Jump to message]({message.jump_url})",
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
            
            elif action == "add":
                if not message_id or not emoji or not role:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Parameters",
                            "Please provide message_id, emoji, and role to add a reaction role.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Parse message ID
                try:
                    if "/" in message_id:
                        msg_id = int(message_id.split("/")[-1])
                    else:
                        msg_id = int(message_id)
                except ValueError:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Invalid Message ID",
                            "Invalid message ID or link. Please provide a valid message ID or message link.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Check if bot's role is high enough
                if interaction.guild.me.top_role <= role:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Role Hierarchy",
                            "My role must be higher than the role I'm assigning. Please move my role above the target role in the server settings.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Find the message
                message = None
                channel_obj = None
                
                # Try to find message in current channel first
                try:
                    message = await interaction.channel.fetch_message(msg_id)
                    channel_obj = interaction.channel
                except (discord.NotFound, discord.Forbidden):
                    # Try to find in any channel
                    async with aiosqlite.connect(DB_PATH) as db2:
                        cur = await db2.execute("""
                            SELECT channel_id FROM reaction_roles
                            WHERE guild_id=? AND message_id=?
                            LIMIT 1
                        """, (interaction.guild.id, msg_id))
                        row = await cur.fetchone()
                        if row:
                            channel_obj = interaction.guild.get_channel(row[0])
                            if channel_obj:
                                try:
                                    message = await channel_obj.fetch_message(msg_id)
                                except (discord.NotFound, discord.Forbidden):
                                    pass
                
                if not message or not channel_obj:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Message Not Found",
                            "The message was not found. Make sure you're using the correct message ID or link.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Try to add reaction to validate emoji
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Invalid Emoji",
                            "Invalid emoji or I can't use that emoji. Please use a standard Discord emoji or a custom emoji from this server.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Store in database
                try:
                    await db.execute("""
                        INSERT INTO reaction_roles (guild_id, message_id, channel_id, emoji, role_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (interaction.guild.id, msg_id, channel_obj.id, emoji, role.id, now_utc().isoformat()))
                    await db.commit()
                except aiosqlite.IntegrityError:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Already Configured",
                            f"This emoji ({emoji}) is already set up for a role on this message. Use `action:Remove` to remove it first.",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Update the message embed
                await update_reaction_role_message(interaction.guild, msg_id, channel_obj.id, interaction.client)
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Reaction Role Added",
                        f"Users can now react with {emoji} to get the {role.mention} role.\n\n"
                        f"[Jump to message]({message.jump_url})",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "remove":
                if not message_id or not emoji:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Parameters",
                            "Please provide message_id and emoji to remove a reaction role.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Parse message ID
                try:
                    if "/" in message_id:
                        msg_id = int(message_id.split("/")[-1])
                    else:
                        msg_id = int(message_id)
                except ValueError:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Invalid Message ID",
                            "Invalid message ID or link. Please provide a valid message ID or message link.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Remove from database
                cur = await db.execute("""
                    SELECT channel_id FROM reaction_roles
                    WHERE guild_id=? AND message_id=? AND emoji=?
                """, (interaction.guild.id, msg_id, emoji))
                row = await cur.fetchone()
                
                if not row:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Not Found",
                            f"No reaction role found for emoji {emoji} on that message.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                channel_id = row[0]
                
                await db.execute("""
                    DELETE FROM reaction_roles
                    WHERE guild_id=? AND message_id=? AND emoji=?
                """, (interaction.guild.id, msg_id, emoji))
                await db.commit()
                
                # Update the message embed
                await update_reaction_role_message(interaction.guild, msg_id, channel_id, interaction.client)
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Reaction Role Removed",
                        f"Successfully removed reaction role for {emoji}.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "list":
                # Get message ID if provided
                if message_id:
                    try:
                        if "/" in message_id:
                            msg_id = int(message_id.split("/")[-1])
                        else:
                            msg_id = int(message_id)
                    except ValueError:
                        return await interaction.followup.send(
                            embed=obsidian_embed(
                                "❌ Invalid Message ID",
                                "Invalid message ID or link.",
                                color=discord.Color.red(),
                                client=interaction.client,
                            ),
                            ephemeral=True
                        )
                    
                    cur = await db.execute("""
                        SELECT emoji, role_id FROM reaction_roles
                        WHERE guild_id=? AND message_id=?
                        ORDER BY id
                    """, (interaction.guild.id, msg_id))
                else:
                    cur = await db.execute("""
                        SELECT message_id, emoji, role_id FROM reaction_roles
                        WHERE guild_id=?
                        ORDER BY message_id, id
                    """, (interaction.guild.id,))
                
                rows = await cur.fetchall()
                
                if not rows:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "📋 No Reaction Roles",
                            "No reaction roles found." + (" for that message." if message_id else " in this server.") + "\n\nUse `action:Create` to create a reaction role message.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Build embed
                if message_id:
                    desc = "**Reaction Roles on this message:**\n\n"
                    for emoji_val, role_id in rows:
                        role = interaction.guild.get_role(role_id)
                        role_name = role.mention if role else f"Unknown Role ({role_id})"
                        desc += f"{emoji_val} → {role_name}\n"
                else:
                    desc = "**All Reaction Roles in this server:**\n\n"
                    current_message = None
                    for row in rows:
                        msg_id, emoji_val, role_id = row
                        role = interaction.guild.get_role(role_id)
                        role_name = role.mention if role else f"Unknown Role ({role_id})"
                        
                        if current_message != msg_id:
                            if current_message is not None:
                                desc += "\n"
                            desc += f"**Message ID:** {msg_id}\n"
                            current_message = msg_id
                        
                        desc += f"{emoji_val} → {role_name}\n"
                
                # Truncate if too long
                if len(desc) > 4096:
                    desc = desc[:4093] + "..."
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Reaction Roles",
                        desc,
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
