"""Ticket system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import random
import string
import asyncio
import re

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


def generate_ticket_id(username: str, subject: str) -> str:
    """Generate a ticket ID based on username and subject."""
    # Clean username: remove special characters, spaces, make lowercase
    clean_username = re.sub(r'[^a-zA-Z0-9]', '', username.lower())[:15]  # Max 15 chars
    
    # Clean subject: remove special characters except hyphens, spaces become hyphens, make lowercase
    clean_subject = re.sub(r'[^a-zA-Z0-9\s-]', '', subject.lower())
    clean_subject = re.sub(r'\s+', '-', clean_subject)  # Replace spaces with hyphens
    clean_subject = clean_subject[:30]  # Max 30 chars
    
    # Format: username-subject
    ticket_id = f"{clean_username}-{clean_subject}"
    
    # Ensure it's not too long (Discord channel names have limits)
    if len(ticket_id) > 50:
        # Truncate subject if needed
        max_subject_len = 50 - len(clean_username) - 1  # -1 for hyphen
        clean_subject = clean_subject[:max_subject_len]
        ticket_id = f"{clean_username}-{clean_subject}"
    
    return ticket_id


async def create_ticket_channel(guild: discord.Guild, user: discord.Member, ticket_id: str, subject: str) -> Optional[discord.TextChannel]:
    """Create a ticket channel for a user."""
    # Get or create ticket category
    category_name = "Tickets"
    category = discord.utils.get(guild.categories, name=category_name)
    
    if not category:
        try:
            category = await guild.create_category(category_name)
        except discord.Forbidden:
            return None
    
    # Create channel - use ticket_id directly (already formatted)
    channel_name = ticket_id.lower()
    
    # Ensure channel name meets Discord requirements (lowercase, no spaces, max 100 chars)
    channel_name = channel_name.replace(' ', '-').lower()[:100]
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        }
        
        # Add mods
        for member in guild.members:
            if is_mod(member):
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket created by {user.display_name}"
        )
        return channel
    except discord.Forbidden:
        return None


def setup(bot, group=None):
    """Register ticket commands."""
    
    command_decorator = group.command(name="ticket", description="Create a support ticket.") if group else bot.tree.command(name="ticket", description="Create a support ticket.")
    
    @command_decorator
    @app_commands.describe(subject="Subject of your ticket")
    async def ticket(interaction: discord.Interaction, subject: str):
        """Create a support ticket."""
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
        
        if not isinstance(interaction.user, discord.Member):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not create ticket.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Generate ticket ID based on username and subject
        username = interaction.user.display_name or interaction.user.name
        ticket_id = generate_ticket_id(username, subject)
        
        # Check if ticket ID already exists, append number if needed
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
            counter = 1
            original_ticket_id = ticket_id
            while await cur.fetchone():
                # Append counter to make it unique
                ticket_id = f"{original_ticket_id}-{counter}"
                # Ensure it doesn't exceed Discord's channel name limit (100 chars)
                if len(ticket_id) > 50:
                    # Truncate original and add counter
                    max_base_len = 50 - len(str(counter)) - 1  # -1 for hyphen
                    ticket_id = f"{original_ticket_id[:max_base_len]}-{counter}"
                cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
                counter += 1
        
        # Create ticket channel
        channel = await create_ticket_channel(interaction.guild, interaction.user, ticket_id, subject)
        
        if not channel:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Error",
                    "I don't have permission to create channels. Please contact an administrator.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Store ticket in database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO tickets (guild_id, user_id, channel_id, ticket_id, subject, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
            """, (interaction.guild.id, interaction.user.id, channel.id, ticket_id, subject, now_utc().isoformat()))
            await db.commit()
        
        # Send welcome message in ticket channel
        embed = obsidian_embed(
            f"Ticket #{ticket_id}",
            f"**Subject:** {subject}\n\n"
            f"**Created by:** {interaction.user.mention}\n"
            f"**Status:** Open\n\n"
            f"Staff will respond shortly. Use `/ticket close` to close this ticket.",
            color=discord.Color.green(),
            client=interaction.client,
        )
        await channel.send(embed=embed)
        await channel.send(f"{interaction.user.mention}, your ticket has been created!")
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Ticket Created",
                f"Your ticket has been created: {channel.mention}\n**Ticket ID:** `{ticket_id}`",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="ticket_close", description="Close a support ticket (moderators only).") if group else bot.tree.command(name="ticket_close", description="Close a support ticket (moderators only).")
    
    @command_decorator
    @app_commands.describe(reason="Reason for closing the ticket")
    async def ticket_close(interaction: discord.Interaction, reason: Optional[str] = None):
        """Close a support ticket."""
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
        
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Channel",
                    "This command can only be used in a ticket channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        # Find ticket
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT ticket_id, user_id, status FROM tickets
                WHERE guild_id=? AND channel_id=?
            """, (interaction.guild.id, interaction.channel.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Not a Ticket",
                        "This channel is not a ticket channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            ticket_id, user_id, status = row
            
            if status == 'closed':
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Closed",
                        "This ticket is already closed.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    )
                )
            
            # Update ticket status
            await db.execute("""
                UPDATE tickets SET status='closed', closed_at=?, closed_by=?
                WHERE guild_id=? AND channel_id=?
            """, (now_utc().isoformat(), interaction.user.id, interaction.guild.id, interaction.channel.id))
            await db.commit()
        
        # Send closing message
        embed = obsidian_embed(
            f"Ticket #{ticket_id} Closed",
            f"**Closed by:** {interaction.user.mention}\n"
            f"**Reason:** {reason or 'No reason provided'}\n\n"
            f"This ticket will be archived in 10 seconds.",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        await interaction.channel.send(embed=embed)
        
        # Archive channel after delay
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.display_name}")
        except discord.Forbidden:
            pass
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Ticket Closed",
                f"Ticket #{ticket_id} has been closed and archived.",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
