"""Music bot commands — /music group."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, cast

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.music_player import (
    EVENT_VC_CHANNEL_KEY,
    MUSIC_EVENT_SOUNDTRACK_KEY,
    MUSIC_TEMP_VC_ONLY_KEY,
    MUSIC_VC_BONUS_KEY,
    PlaylistResult,
    YTDLSource,
    _cycle_loop_mode,
    build_now_playing_embed,
    clear_guild_playback,
    format_duration,
    get_state,
    get_vote_skip_ratio,
    is_temp_vc_channel,
    loop_mode_label,
    persist_guild_state,
    play_next_in_queue,
    register_vote_skip,
    set_panel_message_id,
    update_now_playing_panel,
)
from core.utils import error_embed, feature_enabled, feature_off_embed, is_mod, success_embed
from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

MUSIC_DJ_ROLE_KEY = "music_dj_role_id"
MUSIC_CHANNEL_KEY = "music_channel_id"


def _voice_client(guild: discord.Guild) -> discord.VoiceClient | None:
    """Return guild voice client when it is a concrete VoiceClient (not VoiceProtocol)."""
    vc = guild.voice_client
    return vc if isinstance(vc, discord.VoiceClient) else None


def _set_source_volume(vc: discord.VoiceClient, volume: float) -> None:
    source = vc.source
    if isinstance(source, discord.PCMVolumeTransformer):
        source.volume = volume


def _cmd_decorator(group, bot, name: str, description: str):
    if group:
        return group.command(name=name, description=description)
    return bot.tree.command(name=name, description=description)


async def _music_enabled(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if not await feature_enabled(interaction.guild.id, "music"):
        await interaction.response.send_message(
            embed=feature_off_embed("Music", action_hint="Ask a mod to enable it via /admin features.", client=interaction.client),
            ephemeral=True,
        )
        return False
    return True


async def _guild_only(interaction: discord.Interaction) -> bool:
    if interaction.guild and isinstance(interaction.user, discord.Member):
        return True
    await interaction.response.send_message(
        embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
        ephemeral=True,
    )
    return False


async def _channel_allowed(interaction: discord.Interaction) -> bool:
    assert interaction.guild
    locked = await get_guild_setting(interaction.guild.id, MUSIC_CHANNEL_KEY)
    if not locked:
        return True
    try:
        locked_id = int(locked)
    except ValueError:
        return True
    if interaction.channel_id == locked_id:
        return True
    vc = _voice_client(interaction.guild)
    member = interaction.user
    bot_channel = vc.channel if vc else None
    if (
        vc
        and isinstance(bot_channel, discord.abc.GuildChannel)
        and isinstance(member, discord.Member)
        and member.voice
        and member.voice.channel
        and member.voice.channel.id == bot_channel.id
    ):
        return True
    ch = interaction.guild.get_channel(locked_id)
    hint = ch.mention if ch else f"<#{locked_id}>"
    await interaction.response.send_message(
        embed=error_embed(
            "Wrong Channel",
            f"Music commands are restricted to {hint} (or join the bot's voice channel).",
            client=interaction.client,
        ),
        ephemeral=True,
    )
    return False


async def _has_dj(member: discord.Member) -> bool:
    if is_mod(member):
        return True
    raw = await get_guild_setting(member.guild.id, MUSIC_DJ_ROLE_KEY)
    if not raw:
        return False
    try:
        role_id = int(raw)
    except ValueError:
        return False
    return any(r.id == role_id for r in member.roles)


async def _require_dj(interaction: discord.Interaction) -> bool:
    assert isinstance(interaction.user, discord.Member)
    if await _has_dj(interaction.user):
        return True
    await interaction.response.send_message(
        embed=error_embed(
            "DJ Only",
            "You need the DJ role or mod permissions for this action.",
            action_hint="Ask a moderator or use vote-skip to skip tracks.",
            client=interaction.client,
        ),
        ephemeral=True,
    )
    return False


async def _require_voice(interaction: discord.Interaction) -> bool:
    if isinstance(interaction.user, discord.Member) and interaction.user.voice and interaction.user.voice.channel:
        return True
    await interaction.response.send_message(
        embed=error_embed("Not in Voice", "You must be in a voice channel.", client=interaction.client),
        ephemeral=True,
    )
    return False


async def _temp_vc_allowed(interaction: discord.Interaction) -> bool:
    assert interaction.guild and isinstance(interaction.user, discord.Member)
    raw = await get_guild_setting(interaction.guild.id, MUSIC_TEMP_VC_ONLY_KEY)
    if not raw or raw.lower() in ("0", "false", "off", "no"):
        return True
    ch = interaction.user.voice.channel if interaction.user.voice else None
    if ch and await is_temp_vc_channel(interaction.guild.id, ch.id):
        return True
    await interaction.response.send_message(
        embed=error_embed(
            "Temp VC Only",
            "Music is restricted to **temp squad VCs** in this server.",
            action_hint="Create a squad via the join-to-create channel, then try again.",
            client=interaction.client,
        ),
        ephemeral=True,
    )
    return False


class MusicPanelView(discord.ui.View):
    """Persistent now-playing controls (one view instance per guild)."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        skip = discord.ui.Button(
            label="Skip",
            style=discord.ButtonStyle.primary,
            custom_id=f"music:{guild_id}:skip",
            row=0,
        )
        skip.callback = self._on_skip
        self.add_item(skip)
        toggle = discord.ui.Button(
            label="Pause",
            style=discord.ButtonStyle.secondary,
            custom_id=f"music:{guild_id}:toggle",
            row=0,
        )
        toggle.callback = self._on_toggle
        self.add_item(toggle)
        queue = discord.ui.Button(
            label="Queue",
            style=discord.ButtonStyle.secondary,
            custom_id=f"music:{guild_id}:queue",
            row=0,
        )
        queue.callback = self._on_queue
        self.add_item(queue)

    async def _guild(self, interaction: discord.Interaction) -> Optional[discord.Guild]:
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("This panel belongs to another server.", ephemeral=True)
            return None
        if not await feature_enabled(interaction.guild.id, "music"):
            await interaction.response.send_message(
                embed=feature_off_embed("Music", client=interaction.client),
                ephemeral=True,
            )
            return None
        return interaction.guild

    async def _on_skip(self, interaction: discord.Interaction):
        guild = await self._guild(interaction)
        if not guild or not isinstance(interaction.user, discord.Member):
            return
        dj = await _has_dj(interaction.user)
        if not dj:
            should_skip, msg, _, _ = await register_vote_skip(interaction.user)
            if not should_skip:
                return await interaction.response.send_message(msg, ephemeral=True)
        vc = _voice_client(guild)
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)
        await update_now_playing_panel(guild, interaction.client)

    async def _on_toggle(self, interaction: discord.Interaction):
        guild = await self._guild(interaction)
        if not guild:
            return
        vc = _voice_client(guild)
        if not vc:
            return await interaction.response.send_message("Not connected.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        await update_now_playing_panel(guild, interaction.client)

    async def _on_queue(self, interaction: discord.Interaction):
        guild = await self._guild(interaction)
        if not guild:
            return
        await interaction.response.send_message(
            embed=_queue_embed(guild, interaction.client),
            ephemeral=True,
        )


def _queue_embed(guild: discord.Guild, client) -> discord.Embed:
    st = get_state(guild.id)
    lines = []
    if st.current_track:
        lines.append(f"**Now:** {st.current_track.get('title', 'Unknown')}")
    if st.queue:
        lines.append("")
        lines.append("**Up next:**")
        for i, track in enumerate(st.queue[:10], 1):
            lines.append(f"{i}. {track.get('title', 'Unknown')} ({format_duration(int(track.get('duration') or 0))})")
        if len(st.queue) > 10:
            lines.append(f"_…and {len(st.queue) - 10} more_")
    elif not st.current_track:
        lines.append("Queue is empty.")
    return embed_template(
        "showcase",
        "📋 Music Queue",
        "\n".join(lines) or "Queue is empty.",
        category="music",
        footer=footer_for("music"),
        client=client,
    )


async def _start_playback(
    interaction: discord.Interaction,
    player: YTDLSource,
    track_info: dict,
    *,
    query: str,
) -> None:
    assert interaction.guild
    assert isinstance(interaction.user, discord.Member)
    guild = interaction.guild
    guild_id = guild.id
    client = interaction.client
    st = get_state(guild_id)
    st.text_channel_id = interaction.channel.id if interaction.channel else st.text_channel_id
    member_voice = interaction.user.voice
    assert member_voice and member_voice.channel
    st.voice_channel_id = member_voice.channel.id
    st.current_track = track_info
    st.volume = st.volume or 0.5

    voice_client = _voice_client(guild)
    assert voice_client

    def _after(err):
        if err:
            logger.warning("[music] playback error guild=%s: %s", guild_id, err)
        asyncio.run_coroutine_threadsafe(
            play_next_in_queue(guild_id, client),
            client.loop,
        )

    voice_client.play(player, after=_after)
    _set_source_volume(voice_client, st.volume)

    await persist_guild_state(guild_id, is_playing=True)
    embed = build_now_playing_embed(guild, client)
    view = MusicPanelView(guild_id)
    msg = cast(
        discord.WebhookMessage,
        await interaction.followup.send(embed=embed, view=view),
    )
    await set_panel_message_id(guild_id, msg.id)


def setup(bot: commands.Bot, group=None):
    """Register music commands."""

    @_cmd_decorator(group, bot, "play", "Play music from a URL or search query.")
    @app_commands.describe(query="YouTube/SoundCloud URL or search query")
    async def play(interaction: discord.Interaction, query: str):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _channel_allowed(interaction):
            return
        if not await _require_voice(interaction):
            return
        if not await _temp_vc_allowed(interaction):
            return
        if not await _require_dj(interaction):
            return

        await interaction.response.defer()
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        member_voice = interaction.user.voice
        assert member_voice and member_voice.channel
        voice_client = _voice_client(interaction.guild)
        if not voice_client:
            try:
                voice_client = await member_voice.channel.connect()
            except Exception as exc:
                return await interaction.followup.send(
                    embed=error_embed("Connection Failed", str(exc), client=interaction.client),
                )

        try:
            loading = cast(
                discord.WebhookMessage,
                await interaction.followup.send(
                    embed=embed_template(
                        "showcase",
                        "⏳ Loading…",
                        f"Searching for: **{query}**",
                        category="music",
                        client=interaction.client,
                    ),
                ),
            )

            try:
                player = await YTDLSource.from_url(query, loop=interaction.client.loop, stream=True, volume=get_state(interaction.guild.id).volume)
            except PlaylistResult as pl:
                st = get_state(interaction.guild.id)
                tracks = [
                    YTDLSource.track_info_from_data(
                        entry,
                        query=entry.get("webpage_url") or entry.get("url") or query,
                        requested_by=interaction.user.id,
                    )
                    for entry in pl.entries
                ]
                if voice_client.is_playing() or voice_client.is_paused() or st.current_track:
                    st.queue.extend(tracks)
                    await loading.edit(
                        embed=success_embed(
                            "Playlist Added",
                            f"Added **{len(tracks)}** track(s) to the queue.",
                            client=interaction.client,
                        ),
                    )
                    await persist_guild_state(interaction.guild.id, is_playing=True)
                    await update_now_playing_panel(interaction.guild, interaction.client)
                    return

                first = tracks[0]
                first_query = first.get("query") or first.get("url") or query
                sub_player = await YTDLSource.from_url(
                    first_query,
                    loop=interaction.client.loop,
                    stream=True,
                    volume=st.volume,
                )
                first_info = YTDLSource.track_info_from_data(
                    sub_player.data,
                    query=first_query,
                    requested_by=interaction.user.id,
                )
                st.queue.extend(tracks[1:])
                await loading.delete()
                await _start_playback(interaction, sub_player, first_info, query=query)
                if len(tracks) > 1:
                    await interaction.followup.send(
                        embed=success_embed(
                            "Playlist Queued",
                            f"Now playing first track; **{len(tracks) - 1}** more in queue.",
                            client=interaction.client,
                        ),
                    )
                return

            track_info = YTDLSource.track_info_from_data(
                player.data,
                query=query,
                requested_by=interaction.user.id,
            )
            st = get_state(interaction.guild.id)

            if voice_client.is_playing() or voice_client.is_paused():
                st.queue.append(track_info)
                await loading.edit(
                    embed=success_embed(
                        "Added to Queue",
                        f"**{track_info['title']}**\nPosition: **{len(st.queue)}**",
                        client=interaction.client,
                    ),
                )
                await persist_guild_state(interaction.guild.id, is_playing=True)
                await update_now_playing_panel(interaction.guild, interaction.client)
            else:
                await loading.delete()
                await _start_playback(interaction, player, track_info, query=query)
        except ValueError as exc:
            await interaction.followup.send(
                embed=error_embed(
                    "Playback Error",
                    str(exc),
                    action_hint="Try another link or search terms.",
                    client=interaction.client,
                ),
            )
        except Exception as exc:
            await interaction.followup.send(
                embed=error_embed("Playback Error", str(exc), client=interaction.client),
            )

    @_cmd_decorator(group, bot, "stop", "Stop playback and clear the queue.")
    async def stop(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        if not vc:
            return await interaction.response.send_message(
                embed=error_embed("Not Playing", "The bot is not in a voice channel.", client=interaction.client),
                ephemeral=True,
            )
        await clear_guild_playback(interaction.guild, interaction.client, disconnect=True)  # type: ignore[arg-type]
        await interaction.response.send_message(
            embed=success_embed("Stopped", "Playback stopped and queue cleared.", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "pause", "Pause playback.")
    async def pause(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        if not vc or not vc.is_playing():
            return await interaction.response.send_message(
                embed=error_embed("Not Playing", "Nothing is playing.", client=interaction.client),
                ephemeral=True,
            )
        vc.pause()
        await interaction.response.send_message(
            embed=success_embed("Paused", "Playback paused.", client=interaction.client),
        )
        await update_now_playing_panel(interaction.guild, interaction.client)  # type: ignore[arg-type]

    @_cmd_decorator(group, bot, "resume", "Resume playback.")
    async def resume(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        if not vc or not vc.is_paused():
            return await interaction.response.send_message(
                embed=error_embed("Not Paused", "Playback is not paused.", client=interaction.client),
                ephemeral=True,
            )
        vc.resume()
        await interaction.response.send_message(
            embed=success_embed("Resumed", "Playback resumed.", client=interaction.client),
        )
        await update_now_playing_panel(interaction.guild, interaction.client)  # type: ignore[arg-type]

    @_cmd_decorator(group, bot, "skip", "Skip the current track (DJ/mod or vote-skip).")
    async def skip(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        assert isinstance(interaction.user, discord.Member)
        dj = await _has_dj(interaction.user)
        if not dj:
            return await interaction.response.send_message(
                embed=error_embed(
                    "DJ Only",
                    "Use **/music voteskip** or ask a DJ to skip.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            return await interaction.response.send_message(
                embed=error_embed("Not Playing", "Nothing to skip.", client=interaction.client),
                ephemeral=True,
            )
        vc.stop()
        await interaction.response.send_message(
            embed=success_embed("Skipped", "Playing next track…", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "voteskip", "Vote to skip the current track.")
    async def voteskip(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        assert isinstance(interaction.user, discord.Member)
        should_skip, msg, votes, needed = await register_vote_skip(interaction.user)
        if should_skip:
            vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
            if vc:
                vc.stop()
            await interaction.response.send_message(
                embed=success_embed("Vote Skip", msg, client=interaction.client),
            )
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @_cmd_decorator(group, bot, "queue", "View the music queue.")
    async def queue_cmd(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        await interaction.response.send_message(
            embed=_queue_embed(interaction.guild, interaction.client),  # type: ignore[arg-type]
            ephemeral=True,
        )

    @_cmd_decorator(group, bot, "volume", "Set volume (0–100).")
    @app_commands.describe(volume="Volume level (0–100)")
    async def volume(interaction: discord.Interaction, volume: int):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        if volume < 0 or volume > 100:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Volume", "Volume must be 0–100.", client=interaction.client),
                ephemeral=True,
            )
        vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        if not vc or not vc.source:
            return await interaction.response.send_message(
                embed=error_embed("Not Playing", "Nothing is playing.", client=interaction.client),
                ephemeral=True,
            )
        st = get_state(interaction.guild.id)  # type: ignore[union-attr]
        st.volume = volume / 100.0
        _set_source_volume(vc, st.volume)
        await persist_guild_state(interaction.guild.id, is_playing=True)  # type: ignore[union-attr]
        await interaction.response.send_message(
            embed=success_embed("Volume", f"Set to **{volume}%**.", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "shuffle", "Toggle shuffle mode for the queue.")
    async def shuffle(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        st = get_state(interaction.guild.id)  # type: ignore[union-attr]
        st.shuffle = not st.shuffle
        await interaction.response.send_message(
            embed=success_embed("Shuffle", f"Shuffle is now **{'on' if st.shuffle else 'off'}**.", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "loop", "Cycle loop mode: off → track → queue.")
    async def loop_cmd(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        st = get_state(interaction.guild.id)  # type: ignore[union-attr]
        st.loop_mode = _cycle_loop_mode(st.loop_mode)
        await interaction.response.send_message(
            embed=success_embed("Loop", f"Loop mode: **{loop_mode_label(st.loop_mode)}**.", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "remove", "Remove a track from the queue by position.")
    @app_commands.describe(position="Queue position (1 = next up)")
    async def remove(interaction: discord.Interaction, position: int):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        st = get_state(interaction.guild.id)  # type: ignore[union-attr]
        if position < 1 or position > len(st.queue):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Position", f"Enter 1–{len(st.queue) or 0}.", client=interaction.client),
                ephemeral=True,
            )
        removed = st.queue.pop(position - 1)
        play_vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        await persist_guild_state(interaction.guild.id, is_playing=bool(play_vc and play_vc.is_playing()))  # type: ignore[union-attr]
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Removed **{removed.get('title', 'track')}**.", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "clear", "Clear the queue (keeps current track).")
    async def clear(interaction: discord.Interaction):
        if not await _guild_only(interaction):
            return
        if not await _music_enabled(interaction):
            return
        if not await _require_dj(interaction):
            return
        st = get_state(interaction.guild.id)  # type: ignore[union-attr]
        count = len(st.queue)
        st.queue.clear()
        play_vc = _voice_client(interaction.guild)  # type: ignore[arg-type]
        await persist_guild_state(
            interaction.guild.id,  # type: ignore[union-attr]
            is_playing=bool(play_vc and (play_vc.is_playing() or play_vc.is_paused())),
        )
        await interaction.response.send_message(
            embed=success_embed("Queue Cleared", f"Removed **{count}** track(s).", client=interaction.client),
        )

    @_cmd_decorator(group, bot, "config", "Configure DJ role, music channel, and vote-skip ratio (mods).")
    @app_commands.describe(
        dj_role="Role allowed to control music (optional)",
        music_channel="Text channel for music commands (optional)",
        vote_skip_ratio="Fraction of listeners needed to skip (0.1–1.0, optional)",
        temp_vc_only="Restrict /music play to temp squad VCs only (optional)",
        event_soundtrack="Auto-play event soundtracks when bot is in event VC (optional)",
        event_vc="Voice channel for event soundtracks (optional)",
        vc_bonus_multiplier="XP/coin bonus while music plays in same VC (1.0–3.0, optional)",
    )
    async def config(
        interaction: discord.Interaction,
        dj_role: Optional[discord.Role] = None,
        music_channel: Optional[discord.TextChannel] = None,
        vote_skip_ratio: Optional[float] = None,
        temp_vc_only: Optional[bool] = None,
        event_soundtrack: Optional[bool] = None,
        event_vc: Optional[discord.VoiceChannel] = None,
        vc_bonus_multiplier: Optional[float] = None,
    ):
        if not await _guild_only(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods Only", "Only moderators can configure music.", client=interaction.client),
                ephemeral=True,
            )
        assert interaction.guild
        updates = []
        if dj_role is not None:
            await set_guild_setting(interaction.guild.id, MUSIC_DJ_ROLE_KEY, str(dj_role.id))
            updates.append(f"**DJ role:** {dj_role.mention}")
        if music_channel is not None:
            await set_guild_setting(interaction.guild.id, MUSIC_CHANNEL_KEY, str(music_channel.id))
            updates.append(f"**Music channel:** {music_channel.mention}")
        if vote_skip_ratio is not None:
            ratio = max(0.1, min(1.0, vote_skip_ratio))
            await set_guild_setting(interaction.guild.id, "music_vote_skip_ratio", str(ratio))
            updates.append(f"**Vote-skip ratio:** {ratio:.0%}")
        if temp_vc_only is not None:
            await set_guild_setting(interaction.guild.id, MUSIC_TEMP_VC_ONLY_KEY, "1" if temp_vc_only else "0")
            updates.append(f"**Temp VC only:** {'On' if temp_vc_only else 'Off'}")
        if event_soundtrack is not None:
            await set_guild_setting(interaction.guild.id, MUSIC_EVENT_SOUNDTRACK_KEY, "1" if event_soundtrack else "0")
            updates.append(f"**Event soundtracks:** {'On' if event_soundtrack else 'Off'}")
        if event_vc is not None:
            await set_guild_setting(interaction.guild.id, EVENT_VC_CHANNEL_KEY, str(event_vc.id))
            updates.append(f"**Event VC:** {event_vc.mention}")
        if vc_bonus_multiplier is not None:
            bonus = max(1.0, min(3.0, vc_bonus_multiplier))
            await set_guild_setting(interaction.guild.id, MUSIC_VC_BONUS_KEY, str(bonus))
            updates.append(f"**VC music bonus:** {bonus:.2f}×")
        if not updates:
            dj_raw = await get_guild_setting(interaction.guild.id, MUSIC_DJ_ROLE_KEY)
            ch_raw = await get_guild_setting(interaction.guild.id, MUSIC_CHANNEL_KEY)
            ratio = await get_vote_skip_ratio(interaction.guild.id)
            temp_raw = await get_guild_setting(interaction.guild.id, MUSIC_TEMP_VC_ONLY_KEY)
            evt_snd = await get_guild_setting(interaction.guild.id, MUSIC_EVENT_SOUNDTRACK_KEY)
            evt_vc = await get_guild_setting(interaction.guild.id, EVENT_VC_CHANNEL_KEY)
            bonus_raw = await get_guild_setting(interaction.guild.id, MUSIC_VC_BONUS_KEY)
            dj_line = f"<@&{dj_raw}>" if dj_raw else "_Not set_"
            ch_line = f"<#{ch_raw}>" if ch_raw else "_Any channel_"
            temp_line = "On" if temp_raw and temp_raw.lower() in ("1", "true", "on", "yes") else "Off"
            snd_line = "On" if not evt_snd or evt_snd.lower() not in ("0", "false", "off", "no") else "Off"
            evt_vc_line = f"<#{evt_vc}>" if evt_vc else "_Not set_"
            bonus_line = bonus_raw if bonus_raw else "_Env default_"
            return await interaction.response.send_message(
                embed=embed_template(
                    "showcase",
                    "🎵 Music Config",
                    (
                        f"**DJ role:** {dj_line}\n**Music channel:** {ch_line}\n**Vote-skip ratio:** {ratio:.0%}\n"
                        f"**Temp VC only:** {temp_line}\n**Event soundtracks:** {snd_line}\n"
                        f"**Event VC:** {evt_vc_line}\n**VC music bonus:** {bonus_line}"
                    ),
                    category="music",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed("Music Config", "\n".join(updates), client=interaction.client),
            ephemeral=True,
        )


async def handle_playback_finished(guild_id: int):
    """Legacy hook — use play_next_in_queue instead."""
    await persist_guild_state(guild_id, is_playing=False)
