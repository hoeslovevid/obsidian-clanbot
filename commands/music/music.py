"""Music bot commands with YouTube support."""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List, Dict
from datetime import datetime, timezone
import yt_dlp  # type: ignore
import asyncio
import re

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore
import json


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# Suppress yt-dlp warnings
yt_dlp.utils.bug_reports_message = lambda: ''

# yt-dlp options optimized for YouTube
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
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extract_flat': False,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -bufsize 512k'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


def is_youtube_url(query: str) -> bool:
    """Check if query is a YouTube URL."""
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)',
        r'youtube\.com/playlist\?list=',
    ]
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in youtube_patterns)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown')
        self.url = data.get('webpage_url') or data.get('url', '')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', '')
        self.uploader = data.get('uploader', 'Unknown')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """Create a YTDLSource from a URL or search query."""
        loop = loop or asyncio.get_event_loop()
        
        # If it's not a URL, treat it as a search query
        if not is_youtube_url(url) and not url.startswith('http'):
            url = f"ytsearch:{url}"
        
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if 'entries' in data:
                # If it's a search result or playlist, get the first entry
                data = data['entries'][0]
            
            if not data:
                raise ValueError("No video found")
            
            # Get the audio URL
            if stream:
                # For streaming, get the direct URL
                formats = data.get('formats', [])
                audio_url = None
                for fmt in formats:
                    if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                        audio_url = fmt.get('url')
                        break
                if not audio_url:
                    # Fallback to best format
                    audio_url = data.get('url')
                
                if not audio_url:
                    raise ValueError("Could not extract audio URL")
                
                return cls(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), data=data)
            else:
                filename = ytdl.prepare_filename(data)
                return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            raise ValueError(f"Error extracting video info: {str(e)}")


# Queue management per guild
music_queues: Dict[int, List[Dict]] = {}


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
            # Show loading message
            loading_msg = await interaction.followup.send(
                embed=obsidian_embed(
                    "⏳ Loading...",
                    f"Searching for: **{query}**",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
            
            # Extract video info
            player = await YTDLSource.from_url(query, loop=interaction.client.loop, stream=True)
            
            # Initialize queue if needed
            if interaction.guild.id not in music_queues:
                music_queues[interaction.guild.id] = []
            
            # Check if already playing
            if voice_client.is_playing() or voice_client.is_paused():
                # Add to queue
                track_info = {
                    'title': player.title,
                    'url': player.url,
                    'duration': player.duration,
                    'thumbnail': player.thumbnail,
                    'uploader': player.uploader,
                    'requested_by': interaction.user.id,
                    'query': query
                }
                music_queues[interaction.guild.id].append(track_info)
                
                await loading_msg.edit(
                    embed=obsidian_embed(
                        "➕ Added to Queue",
                        f"**{player.title}**\n"
                        f"Position in queue: {len(music_queues[interaction.guild.id])}\n"
                        f"Requested by {interaction.user.mention}",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    )
                )
            else:
                # Play immediately
                track_info = {
                    'title': player.title,
                    'url': player.url,
                    'duration': player.duration,
                    'thumbnail': player.thumbnail,
                    'uploader': player.uploader,
                    'requested_by': interaction.user.id,
                    'query': query
                }
                
                voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                    play_next_in_queue(interaction.guild.id, interaction.client), interaction.client.loop
                ))
                voice_client.source.volume = 0.5
                
                await loading_msg.edit(
                    embed=obsidian_embed(
                        "🎵 Now Playing",
                        f"**{player.title}**\n"
                        f"Uploader: {player.uploader}\n"
                        f"Duration: {format_duration(player.duration)}\n"
                        f"Requested by {interaction.user.mention}",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ).set_thumbnail(url=player.thumbnail) if player.thumbnail else obsidian_embed(
                        "🎵 Now Playing",
                        f"**{player.title}**\n"
                        f"Uploader: {player.uploader}\n"
                        f"Duration: {format_duration(player.duration)}\n"
                        f"Requested by {interaction.user.mention}",
                        color=discord.Color.green(),
                        client=interaction.client,
                    )
                )
            
            # Update database
            queue_json = json.dumps(music_queues.get(interaction.guild.id, []))
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO music_queues 
                    (guild_id, channel_id, voice_channel_id, current_track, queue_json, is_playing, volume, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 50, ?)
                """, (
                    interaction.guild.id,
                    interaction.channel.id if interaction.channel else 0,
                    interaction.user.voice.channel.id,
                    player.title,
                    queue_json,
                    1 if not (voice_client.is_playing() or voice_client.is_paused()) else 0,
                    now_utc().isoformat()
                ))
                await db.commit()
        except Exception as e:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Playback Error",
                    f"Error playing music: {str(e)}\n\n"
                    f"**Tips:**\n"
                    f"• Make sure the URL is valid\n"
                    f"• Try a different search query\n"
                    f"• Check if the video is available",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )


def format_duration(seconds: int) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def play_next_in_queue(guild_id: int, bot):
    """Play the next song in the queue."""
    if guild_id not in music_queues or not music_queues[guild_id]:
        # Queue is empty, update database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE music_queues SET is_playing=0 WHERE guild_id=?
            """, (guild_id,))
            await db.commit()
        return
    
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    
    voice_client = guild.voice_client
    if not voice_client:
        return
    
    # Get next track
    next_track = music_queues[guild_id].pop(0)
    
    try:
        # Create player from stored query or URL
        query = next_track.get('query') or next_track.get('url')
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
            play_next_in_queue(guild_id, bot), bot.loop
        ))
        voice_client.source.volume = 0.5
        
        # Update database
        queue_json = json.dumps(music_queues.get(guild_id, []))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE music_queues 
                SET current_track=?, queue_json=?, is_playing=1, updated_at=?
                WHERE guild_id=?
            """, (player.title, queue_json, now_utc().isoformat(), guild_id))
            await db.commit()
        
        # Notify in channel (if we can find it)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT channel_id FROM music_queues WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
            if row and row[0]:
                channel = guild.get_channel(row[0])
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(
                            embed=obsidian_embed(
                                "🎵 Now Playing",
                                f"**{player.title}**\n"
                                f"Uploader: {player.uploader}\n"
                                f"Duration: {format_duration(player.duration)}",
                                color=discord.Color.green(),
                                client=bot,
                            ).set_thumbnail(url=player.thumbnail) if player.thumbnail else obsidian_embed(
                                "🎵 Now Playing",
                                f"**{player.title}**\n"
                                f"Uploader: {player.uploader}\n"
                                f"Duration: {format_duration(player.duration)}",
                                color=discord.Color.green(),
                                client=bot,
                            )
                        )
                    except:
                        pass
    except Exception as e:
        # Error playing next track, try next one
        await play_next_in_queue(guild_id, bot)
    
    command_decorator = group.command(name="stop", description="Stop music playback and clear queue.") if group else bot.tree.command(name="stop", description="Stop music playback and clear queue.")
    
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
        
        # Clear queue
        if interaction.guild.id in music_queues:
            music_queues[interaction.guild.id].clear()
        
        voice_client.stop()
        await voice_client.disconnect()
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE music_queues SET is_playing=0, queue_json=? WHERE guild_id=?
            """, (json.dumps([]), interaction.guild.id))
            await db.commit()
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "⏹️ Stopped",
                "Music playback stopped and queue cleared.",
                color=discord.Color.blue(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="pause", description="Pause music playback.") if group else bot.tree.command(name="pause", description="Pause music playback.")
    
    @command_decorator
    async def pause(interaction: discord.Interaction):
        """Pause music."""
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
        if not voice_client or not voice_client.is_playing():
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Not Playing",
                    "The bot is not playing music.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        voice_client.pause()
        await interaction.response.send_message(
            embed=obsidian_embed(
                "⏸️ Paused",
                "Music playback paused.",
                color=discord.Color.blue(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="resume", description="Resume music playback.") if group else bot.tree.command(name="resume", description="Resume music playback.")
    
    @command_decorator
    async def resume(interaction: discord.Interaction):
        """Resume music."""
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
        if not voice_client or not voice_client.is_paused():
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Not Paused",
                    "The bot is not paused.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        voice_client.resume()
        await interaction.response.send_message(
            embed=obsidian_embed(
                "▶️ Resumed",
                "Music playback resumed.",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="skip", description="Skip the current song.") if group else bot.tree.command(name="skip", description="Skip the current song.")
    
    @command_decorator
    async def skip(interaction: discord.Interaction):
        """Skip current song."""
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
        if not voice_client or (not voice_client.is_playing() and not voice_client.is_paused()):
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
        await interaction.response.send_message(
            embed=obsidian_embed(
                "⏭️ Skipped",
                "Skipped to the next song.",
                color=discord.Color.blue(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="queue", description="View the music queue.") if group else bot.tree.command(name="queue", description="View the music queue.")
    
    @command_decorator
    async def queue(interaction: discord.Interaction):
        """View queue."""
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
        
        await interaction.response.defer()
        
        # Get current track
        voice_client = interaction.guild.voice_client
        current_track = None
        if voice_client and voice_client.source:
            if hasattr(voice_client.source, 'title'):
                current_track = voice_client.source.title
        
        # Get queue
        queue_list = music_queues.get(interaction.guild.id, [])
        
        if not current_track and not queue_list:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Queue",
                    "The queue is empty.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
        
        # Build queue text
        queue_text = ""
        if current_track:
            queue_text += f"**🎵 Now Playing:** {current_track}\n\n"
        
        if queue_list:
            queue_text += "**📋 Up Next:**\n"
            for i, track in enumerate(queue_list[:10], 1):
                title = track.get('title', 'Unknown')
                duration = format_duration(track.get('duration', 0))
                queue_text += f"{i}. {title} ({duration})\n"
            
            if len(queue_list) > 10:
                queue_text += f"\n... and {len(queue_list) - 10} more"
        else:
            queue_text += "No songs in queue."
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "📋 Music Queue",
                queue_text,
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
    """Handle when playback finishes (deprecated - use play_next_in_queue instead)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE music_queues SET is_playing=0 WHERE guild_id=?
        """, (guild_id,))
        await db.commit()
