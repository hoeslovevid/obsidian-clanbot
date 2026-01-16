"""Voice channel transcription command."""
import discord
from discord import app_commands
import asyncio
import io
import wave
import os
from datetime import datetime, timezone
from typing import Optional

from utils import obsidian_embed, is_mod
from database import now_utc
import aiosqlite
import os


# Store active transcriptions (transcription_id -> voice_client)
_active_transcriptions = {}

# Get DB_PATH and OPENAI_API_KEY from environment
DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class TranscriptionSink(discord.sinks.PCMSink):
    """Custom sink that accumulates audio data for transcription."""
    def __init__(self, transcription_id: int, requested_by: int, channel: discord.VoiceChannel):
        super().__init__()
        self.transcription_id = transcription_id
        self.requested_by = requested_by
        self.channel = channel
        self.audio_data = []
        self.started_at = now_utc()
    
    def write(self, user: discord.Member, pcm: bytes):
        """Write audio data from a user."""
        self.audio_data.append((user.id, pcm))
    
    async def cleanup(self):
        """Called when transcription is stopped - process the audio."""
        # Process audio and transcribe
        try:
            # Combine all audio data
            combined_audio = {user_id: [] for user_id in set(uid for uid, _ in self.audio_data)}
            for user_id, pcm in self.audio_data:
                combined_audio[user_id].append(pcm)
            
            await process_transcription(self.transcription_id, self.requested_by, self.channel, combined_audio, self.started_at)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error processing transcription: {e}", exc_info=True)


async def process_transcription(
    transcription_id: int,
    requested_by: int,
    channel: discord.VoiceChannel,
    audio_data: dict,
    started_at: datetime
):
    """Process recorded audio and transcribe it."""
    if not OPENAI_API_KEY:
        # Update status to failed
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE voice_transcriptions 
                SET status = 'failed', stopped_at = ?
                WHERE id = ?
            """, (now_utc().isoformat(), transcription_id))
            await db.commit()
        
        # Notify user
        try:
            user = channel.guild.get_member(requested_by)
            if user:
                await user.send(embed=obsidian_embed(
                    "❌ Transcription Failed",
                    "Transcription failed because OpenAI API key is not configured.\n"
                    "Please contact a server administrator.",
                    color=discord.Color.red(),
                    client=channel.guild.me.client if hasattr(channel.guild.me, 'client') else None,
                ))
        except Exception:
            pass
        return
    
    if not audio_data:
        # No audio recorded
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE voice_transcriptions 
                SET status = 'completed', stopped_at = ?, transcript = ?
                WHERE id = ?
            """, (now_utc().isoformat(), "No audio was recorded.", transcription_id))
            await db.commit()
        
        try:
            user = channel.guild.get_member(requested_by)
            if user:
                await user.send(embed=obsidian_embed(
                    "📝 Transcription Complete",
                    "The transcription has been completed, but no audio was recorded.\n"
                    "This may happen if no one was speaking during the recording period.",
                    color=discord.Color.orange(),
                    client=channel.guild.me.client if hasattr(channel.guild.me, 'client') else None,
                ))
        except Exception:
            pass
        return
    
    # Combine all audio into one file
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Create a temporary audio file from the accumulated data
        audio_bytes = b''.join(b''.join(audio_list) for audio_list in audio_data.values())
        
        # Convert to format suitable for Whisper (WAV format)
        # Discord sends PCM audio at 48000 Hz, 2 channels, 16-bit
        with io.BytesIO() as wav_buffer:
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(2)  # Stereo
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(48000)  # 48 kHz
                wav_file.writeframes(audio_bytes)
            
            wav_buffer.seek(0)
            
            # Transcribe using Whisper API
            transcript_response = client.audio.transcriptions.create(
                model="whisper-1",
                file=("audio.wav", wav_buffer.read(), "audio/wav"),
                language="en"
            )
            
            transcript = transcript_response.text
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE voice_transcriptions 
                SET status = 'completed', stopped_at = ?, transcript = ?
                WHERE id = ?
            """, (now_utc().isoformat(), transcript, transcription_id))
            await db.commit()
        
        # Calculate duration
        stopped_at = now_utc()
        duration = (stopped_at - started_at).total_seconds()
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        
        # Send DM to requester
        try:
            user = channel.guild.get_member(requested_by)
            if user:
                embed = obsidian_embed(
                    "📝 Voice Transcription Complete",
                    f"**Channel:** {channel.name}\n"
                    f"**Duration:** {minutes}m {seconds}s\n"
                    f"**Date:** <t:{int(started_at.timestamp())}:F>\n\n"
                    f"**Transcript:**\n{transcript[:3900]}",  # Discord embed limit is 4096 chars
                    color=discord.Color.green(),
                    client=channel.guild.me.client if hasattr(channel.guild.me, 'client') else None,
                )
                
                # If transcript is too long, send the rest in a follow-up message
                if len(transcript) > 3900:
                    await user.send(embed=embed)
                    # Send remaining text in chunks
                    remaining = transcript[3900:]
                    while remaining:
                        chunk = remaining[:2000]
                        remaining = remaining[2000:]
                        await user.send(f"**Transcript (continued):**\n```\n{chunk}\n```")
                else:
                    await user.send(embed=embed)
        except discord.Forbidden:
            # User has DMs disabled
            import logging
            logging.getLogger(__name__).warning(f"Could not send transcription DM to user {requested_by} - DMs disabled")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error sending transcription DM: {e}", exc_info=True)
    
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error in transcription processing: {e}", exc_info=True)
        
        # Update status to failed
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE voice_transcriptions 
                SET status = 'failed', stopped_at = ?
                WHERE id = ?
            """, (now_utc().isoformat(), transcription_id))
            await db.commit()
        
        # Notify user of failure
        try:
            user = channel.guild.get_member(requested_by)
            if user:
                await user.send(embed=obsidian_embed(
                    "❌ Transcription Failed",
                    f"An error occurred while processing the transcription:\n```\n{str(e)[:500]}\n```",
                    color=discord.Color.red(),
                    client=channel.guild.me.client if hasattr(channel.guild.me, 'client') else None,
                ))
        except Exception:
            pass


def setup(bot):
    """Register the transcribe command."""
    @bot.tree.command(name="transcribe", description="Start or stop voice channel transcription (moderators only).")
    @app_commands.describe(
        action="Start or stop transcription",
        channel="Voice channel to transcribe (defaults to your current channel)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Start", value="start"),
        app_commands.Choice(name="Stop", value="stop"),
    ])
    async def transcribe(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.VoiceChannel] = None
    ):
        """Start or stop voice channel transcription."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can use transcription.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Error",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not OPENAI_API_KEY:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Configuration Error",
                    "Transcription is not configured. Please set the `OPENAI_API_KEY` environment variable.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        action_value = action.value
        
        if action_value == "start":
            # Determine target channel
            target_channel = channel
            
            # If user is in a voice channel and no channel specified, use their current channel
            if not target_channel and isinstance(interaction.user.voice, discord.VoiceState):
                if interaction.user.voice.channel:
                    target_channel = interaction.user.voice.channel
            
            if not target_channel:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Error",
                        "Please specify a voice channel or join a voice channel first.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check if already transcribing this channel
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id FROM voice_transcriptions 
                    WHERE guild_id = ? AND channel_id = ? AND status = 'recording'
                """, (interaction.guild.id, target_channel.id))
                existing = await cur.fetchone()
                
                if existing:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "⚠️ Already Recording",
                            f"Transcription is already active in {target_channel.mention}.",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
            
            # Check bot permissions
            if not target_channel.permissions_for(interaction.guild.me).connect:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Permission Error",
                        f"I don't have permission to connect to {target_channel.mention}.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Create transcription record
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    INSERT INTO voice_transcriptions 
                    (guild_id, channel_id, requested_by, started_at, status)
                    VALUES (?, ?, ?, ?, 'recording')
                """, (interaction.guild.id, target_channel.id, interaction.user.id, now_utc().isoformat()))
                await db.commit()
                transcription_id = cur.lastrowid
            
            # Connect to voice channel and start recording
            try:
                voice_client = await target_channel.connect()
                
                # Create sink
                sink = TranscriptionSink(transcription_id, interaction.user.id, target_channel)
                voice_client.start_recording(sink, callback=None)
                
                # Store active transcription
                _active_transcriptions[transcription_id] = voice_client
                
                # Store voice_client_id in database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        UPDATE voice_transcriptions 
                        SET voice_client_id = ? WHERE id = ?
                    """, (id(voice_client), transcription_id))
                    await db.commit()
                
                # Send confirmation
                await interaction.response.send_message(
                    embed=obsidian_embed(
                        "🎤 Transcription Started",
                        f"Now recording audio from {target_channel.mention}.\n"
                        f"Use `/transcribe action:Stop` to stop and receive the transcript via DM.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=False
                )
                
            except discord.ClientException as e:
                # Clean up database record
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM voice_transcriptions WHERE id = ?", (transcription_id,))
                    await db.commit()
                
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Error",
                        f"Failed to connect to voice channel: {str(e)}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        elif action_value == "stop":
            # Determine target channel
            target_channel = channel
            if not target_channel and isinstance(interaction.user.voice, discord.VoiceState):
                if interaction.user.voice.channel:
                    target_channel = interaction.user.voice.channel
            
            if not target_channel:
                # Try to find any active transcription in this guild
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT id, channel_id, voice_client_id FROM voice_transcriptions 
                        WHERE guild_id = ? AND status = 'recording'
                    """, (interaction.guild.id,))
                    active = await cur.fetchall()
                
                if not active:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            "No active transcriptions found. Please specify a channel or join the voice channel being transcribed.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Use first active transcription
                transcription_id, channel_id, voice_client_id = active[0]
                target_channel = interaction.guild.get_channel(channel_id)
            else:
                # Find transcription for this channel
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT id, voice_client_id FROM voice_transcriptions 
                        WHERE guild_id = ? AND channel_id = ? AND status = 'recording'
                    """, (interaction.guild.id, target_channel.id))
                    row = await cur.fetchone()
                
                if not row:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Error",
                            f"No active transcription found for {target_channel.mention}.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                transcription_id, voice_client_id = row
            
            # Find and stop the voice client
            voice_client = None
            for tid, vc in _active_transcriptions.items():
                if tid == transcription_id:
                    voice_client = vc
                    break
            
            if not voice_client:
                # Try to find by stored ID
                for vc in interaction.guild.voice_clients:
                    if id(vc) == voice_client_id:
                        voice_client = vc
                        break
            
            if not voice_client:
                # Mark as stopped manually
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        UPDATE voice_transcriptions 
                        SET status = 'stopped', stopped_at = ?
                        WHERE id = ?
                    """, (now_utc().isoformat(), transcription_id))
                    await db.commit()
                
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "⚠️ Warning",
                        "Transcription stopped, but voice client was not found. "
                        "The transcript may not be available.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Stop recording and disconnect
            try:
                voice_client.stop_recording()
                await voice_client.disconnect()
                
                # Remove from active transcriptions
                if transcription_id in _active_transcriptions:
                    del _active_transcriptions[transcription_id]
                
                await interaction.response.send_message(
                    embed=obsidian_embed(
                        "⏹️ Transcription Stopped",
                        f"Stopped recording from {target_channel.mention}.\n"
                        f"Processing transcript... You will receive it via DM shortly.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=False
                )
                
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error stopping transcription: {e}", exc_info=True)
                
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Error",
                        f"Failed to stop transcription: {str(e)}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
