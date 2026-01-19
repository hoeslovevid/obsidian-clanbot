"""Music bot commands."""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from datetime import datetime, timezone
import yt_dlp  # type: ignore
import asyncio

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore
import json


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# Suppress yt-dlp warnings
yt_dlp.utils.bug_reports_message = lambda: ''

# yt-dlp options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


def setup(bot, group=None):
    """Register music commands."""
    
    command_decorator = group.command(name="play", description="Play music from a URL or search query.") if group else bot.tree.command(name="play", description="Play music from a URL or search query.")
    
    @command_decorator
    @app_commands.describe(query="YouTube URL or search query")
    async def play(interaction: discord.Interaction, query: str):
        """Play music."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Not in Voice Channel",
                    "You must be in a voice channel to use this command.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        voice_client = interaction.guild.voice_client
        if not voice_client:
            try:
                voice_client = await interaction.user.voice.channel.connect()
            except Exception as e:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Connection Failed",
                        f"Could not connect to voice channel: {e}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
        
        try:
            player = await YTDLSource.from_url(query, loop=interaction.client.loop, stream=True)
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                handle_playback_finished(interaction.guild.id), interaction.client.loop
            ))
            voice_client.source.volume = 0.5
            
            # Update queue
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO music_queues 
                    (guild_id, channel_id, voice_channel_id, current_track, queue_json, is_playing, volume, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, 50, ?)
                """, (
                    interaction.guild.id,
                    interaction.channel.id if interaction.channel else 0,
                    interaction.user.voice.channel.id,
                    player.title,
                    json.dumps([]),
                    now_utc().isoformat()
                ))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "🎵 Now Playing",
                    f"**{player.title}**\n"
                    f"Requested by {interaction.user.mention}",
                    color=discord.Color.green(),
                    client=interaction.client,
                )
            )
        except Exception as e:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Playback Error",
                    f"Error playing music: {e}",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
    
    command_decorator = group.command(name="stop", description="Stop music playback.") if group else bot.tree.command(name="stop", description="Stop music playback.")
    
    @command_decorator
    async def stop(interaction: discord.Interaction):
        """Stop music."""
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
        
        voice_client = interaction.guild.voice_client
        if not voice_client:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Not Playing",
                    "The bot is not playing music.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        voice_client.stop()
        await voice_client.disconnect()
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE music_queues SET is_playing=0 WHERE guild_id=?
            """, (interaction.guild.id,))
            await db.commit()
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "⏹️ Stopped",
                "Music playback stopped.",
                color=discord.Color.blue(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="volume", description="Set music volume (0-100).") if group else bot.tree.command(name="volume", description="Set music volume (0-100).")
    
    @command_decorator
    @app_commands.describe(volume="Volume level (0-100)")
    async def volume(interaction: discord.Interaction, volume: int):
        """Set volume."""
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
        
        if volume < 0 or volume > 100:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Volume",
                    "Volume must be between 0 and 100.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.source:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Not Playing",
                    "The bot is not playing music.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        voice_client.source.volume = volume / 100
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE music_queues SET volume=? WHERE guild_id=?
            """, (volume, interaction.guild.id))
            await db.commit()
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔊 Volume Set",
                f"Volume set to {volume}%.",
                color=discord.Color.blue(),
                client=interaction.client,
            )
        )


async def handle_playback_finished(guild_id: int):
    """Handle when playback finishes."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE music_queues SET is_playing=0 WHERE guild_id=?
        """, (guild_id,))
        await db.commit()
