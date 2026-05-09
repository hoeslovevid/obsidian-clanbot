"""Twitch integration commands."""
import discord
from discord import app_commands
from typing import Optional
import aiohttp
import os

from core.utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def get_twitch_access_token() -> Optional[str]:
    """Get Twitch app access token."""
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    
    if not client_id or not client_secret:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token")
    except Exception:
        return None


async def check_twitch_stream(streamer_name: str, access_token: str) -> Optional[dict]:
    """Check if a Twitch streamer is live."""
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    if not client_id:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.twitch.tv/helix/streams?user_login={streamer_name}",
                headers={
                    "Client-ID": client_id,
                    "Authorization": f"Bearer {access_token}"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    streams = data.get("data", [])
                    if streams:
                        return streams[0]
                    return None
    except Exception:
        return None


def setup(bot, group=None):
    """Register Twitch commands."""
    
    command_decorator = group.command(name="twitch_setup", description="Configure Twitch stream notifications (moderators only).") if group else bot.tree.command(name="twitch_setup", description="Configure Twitch stream notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        channel="Channel to send notifications to",
        ping_role="Role to ping when streamers go live (optional)",
        enabled="Enable or disable notifications"
    )
    async def twitch_setup(interaction: discord.Interaction, channel: discord.TextChannel, ping_role: Optional[discord.Role] = None, enabled: bool = True):
        """Configure Twitch notifications."""
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
            # Check if ping_role_id column exists, if not add it
            try:
                cur = await db.execute("PRAGMA table_info(twitch_settings)")
                columns = await cur.fetchall()
                column_names = [col[1] for col in columns]
                if "ping_role_id" not in column_names:
                    await db.execute("ALTER TABLE twitch_settings ADD COLUMN ping_role_id INTEGER")
                    await db.commit()
            except Exception:
                pass
            
            await db.execute("""
                INSERT OR REPLACE INTO twitch_settings (guild_id, channel_id, enabled, ping_role_id)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, channel.id, 1 if enabled else 0, ping_role.id if ping_role else None))
            await db.commit()
        
        ping_text = f"**Ping Role:** {ping_role.mention}" if ping_role else "**Ping Role:** None (no role will be pinged)"
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Twitch Notifications Configured",
                f"**Channel:** {channel.mention}\n{ping_text}\n**Status:** {'Enabled' if enabled else 'Disabled'}\n\n"
                "Use `/twitch_add` to add streamers to monitor.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="twitch_add", description="Add a Twitch streamer to monitor (moderators only).") if group else bot.tree.command(name="twitch_add", description="Add a Twitch streamer to monitor (moderators only).")
    
    @command_decorator
    @app_commands.describe(streamer_name="Twitch username")
    async def twitch_add(interaction: discord.Interaction, streamer_name: str):
        """Add a Twitch streamer."""
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
            # Check if already exists
            cur = await db.execute("""
                SELECT 1 FROM twitch_streamers WHERE guild_id=? AND streamer_name=?
            """, (interaction.guild.id, streamer_name.lower()))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Added",
                        f"{streamer_name} is already being monitored.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await db.execute("""
                INSERT INTO twitch_streamers (guild_id, streamer_name, last_live_status)
                VALUES (?, ?, 0)
            """, (interaction.guild.id, streamer_name.lower()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Streamer Added",
                f"{streamer_name} has been added to the monitoring list.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="twitch_remove", description="Remove a Twitch streamer from monitoring (moderators only).") if group else bot.tree.command(name="twitch_remove", description="Remove a Twitch streamer from monitoring (moderators only).")
    
    @command_decorator
    @app_commands.describe(streamer_name="Twitch username")
    async def twitch_remove(interaction: discord.Interaction, streamer_name: str):
        """Remove a Twitch streamer."""
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
            cur = await db.execute("""
                DELETE FROM twitch_streamers WHERE guild_id=? AND streamer_name=?
            """, (interaction.guild.id, streamer_name.lower()))
            await db.commit()
            
            if cur.rowcount == 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Not Found",
                        f"{streamer_name} is not being monitored.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Streamer Removed",
                f"{streamer_name} has been removed from the monitoring list.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="twitch_list", description="List all monitored Twitch streamers.") if group else bot.tree.command(name="twitch_list", description="List all monitored Twitch streamers.")
    
    @command_decorator
    async def twitch_list(interaction: discord.Interaction):
        """List monitored streamers."""
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT streamer_name, last_live_status FROM twitch_streamers
                WHERE guild_id=? ORDER BY streamer_name
            """, (interaction.guild.id,))
            streamers = await cur.fetchall()
        
        if not streamers:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📺 Monitored Streamers",
                    "No streamers are being monitored. Use `/twitch_add` to add one.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        streamer_list = "\n".join([
            f"• **{name}** {'🔴 Live' if status else '⚫ Offline'}"
            for name, status in streamers
        ])
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "📺 Monitored Streamers",
                streamer_list,
                color=discord.Color.purple(),
                client=interaction.client,
            ),
            ephemeral=True
        )
