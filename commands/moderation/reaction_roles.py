"""Reaction roles commands."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot):
    """Register reaction role commands."""
    
    @bot.tree.command(name="reaction_role_setup", description="Set up reaction roles on a message (mods only).")
    @app_commands.describe(
        message="The message to add reaction roles to (message ID or link)",
        emoji="The emoji to use for this role",
        role="The role to assign when users react"
    )
    async def reaction_role_setup(
        interaction: discord.Interaction,
        message: str,
        emoji: str,
        role: discord.Role
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)
        
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)
        
        # Parse message ID from input (could be just ID, or a message link)
        message_id = None
        try:
            # Try to extract from message link
            if "/" in message:
                message_id = int(message.split("/")[-1])
            else:
                message_id = int(message)
        except ValueError:
            return await interaction.response.send_message("Invalid message ID or link.", ephemeral=True)
        
        # Fetch the message
        try:
            target_message = await interaction.channel.fetch_message(message_id)
        except discord.NotFound:
            return await interaction.response.send_message("Message not found in this channel.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message("I don't have permission to access that message.", ephemeral=True)
        
        # Check if bot can manage roles
        if not interaction.guild.me.guild_permissions.manage_roles:
            return await interaction.response.send_message("I don't have permission to manage roles.", ephemeral=True)
        
        # Check if bot's role is high enough
        if interaction.guild.me.top_role <= role:
            return await interaction.response.send_message("My role must be higher than the role I'm assigning.", ephemeral=True)
        
        # Parse emoji (could be unicode or custom)
        emoji_str = emoji
        try:
            # Try to add the reaction first to validate it
            await target_message.add_reaction(emoji)
        except discord.HTTPException:
            return await interaction.response.send_message("Invalid emoji or I can't use that emoji.", ephemeral=True)
        
        # Store in database
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute("""
                    INSERT INTO reaction_roles (guild_id, message_id, channel_id, emoji, role_id, created_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (interaction.guild.id, message_id, interaction.channel.id, emoji_str, role.id))
                await db.commit()
            except aiosqlite.IntegrityError:
                # Already exists
                return await interaction.response.send_message(
                    f"This emoji ({emoji}) is already set up for a role on this message.",
                    ephemeral=True
                )
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "Reaction Role Added",
                f"Users can now react with {emoji} to get the {role.mention} role.\n"
                f"Message: [Jump to message]({target_message.jump_url})",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
    
    @bot.tree.command(name="reaction_role_remove", description="Remove a reaction role from a message (mods only).")
    @app_commands.describe(
        message="The message ID or link",
        emoji="The emoji to remove"
    )
    async def reaction_role_remove(
        interaction: discord.Interaction,
        message: str,
        emoji: str
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)
        
        # Parse message ID
        message_id = None
        try:
            if "/" in message:
                message_id = int(message.split("/")[-1])
            else:
                message_id = int(message)
        except ValueError:
            return await interaction.response.send_message("Invalid message ID or link.", ephemeral=True)
        
        # Remove from database
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                DELETE FROM reaction_roles
                WHERE guild_id = ? AND message_id = ? AND emoji = ?
            """, (interaction.guild.id, message_id, emoji))
            await db.commit()
            
            if cur.rowcount == 0:
                return await interaction.response.send_message(
                    f"No reaction role found for emoji {emoji} on that message.",
                    ephemeral=True
                )
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "Reaction Role Removed",
                f"Removed reaction role for {emoji}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
    
    @bot.tree.command(name="reaction_role_list", description="List all reaction roles for a message (mods only).")
    @app_commands.describe(
        message="The message ID or link (optional - if not provided, lists all in server)"
    )
    async def reaction_role_list(
        interaction: discord.Interaction,
        message: Optional[str] = None
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            if message:
                # Parse message ID
                message_id = None
                try:
                    if "/" in message:
                        message_id = int(message.split("/")[-1])
                    else:
                        message_id = int(message)
                except ValueError:
                    return await interaction.response.send_message("Invalid message ID or link.", ephemeral=True)
                
                cur = await db.execute("""
                    SELECT emoji, role_id FROM reaction_roles
                    WHERE guild_id = ? AND message_id = ?
                    ORDER BY id
                """, (interaction.guild.id, message_id))
            else:
                cur = await db.execute("""
                    SELECT message_id, emoji, role_id FROM reaction_roles
                    WHERE guild_id = ?
                    ORDER BY message_id, id
                """, (interaction.guild.id,))
            
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.response.send_message(
                "No reaction roles found." + (" for that message." if message else " in this server."),
                ephemeral=True
            )
        
        # Build embed
        if message:
            description = "**Reaction Roles on this message:**\n\n"
            for emoji, role_id in rows:
                role = interaction.guild.get_role(role_id)
                role_name = role.mention if role else f"Unknown Role ({role_id})"
                description += f"{emoji} → {role_name}\n"
        else:
            description = "**All Reaction Roles in this server:**\n\n"
            current_message = None
            for row in rows:
                msg_id, emoji, role_id = row
                role = interaction.guild.get_role(role_id)
                role_name = role.mention if role else f"Unknown Role ({role_id})"
                
                if current_message != msg_id:
                    if current_message is not None:
                        description += "\n"
                    description += f"**Message ID:** {msg_id}\n"
                    current_message = msg_id
                
                description += f"{emoji} → {role_name}\n"
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "Reaction Roles",
                description,
                color=discord.Color.blue(),
            ),
            ephemeral=True,
        )
