"""Guild music player: queue, playback, loop/shuffle, persistence."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import aiosqlite  # type: ignore
import discord  # type: ignore
import yt_dlp  # type: ignore

from database import DB_PATH, get_guild_setting
from core.discord_typing import (
    set_voice_source_volume,
    voice_channel_from_vc,
    voice_client as get_voice_client,
)

logger = logging.getLogger(__name__)

MUSIC_AUTO_LEAVE_MINUTES = int(os.getenv("MUSIC_AUTO_LEAVE_MINUTES", "5"))
MUSIC_VOTE_SKIP_RATIO = float(os.getenv("MUSIC_VOTE_SKIP_RATIO", "0.5"))
MUSIC_VC_BONUS_MULTIPLIER = float(os.getenv("MUSIC_VC_BONUS_MULTIPLIER", "1.25"))
PLAYLIST_MAX_TRACKS = int(os.getenv("MUSIC_PLAYLIST_MAX", "50"))

MUSIC_TEMP_VC_ONLY_KEY = "music_temp_vc_only"
MUSIC_EVENT_SOUNDTRACK_KEY = "music_event_soundtrack_enabled"
EVENT_VC_CHANNEL_KEY = "event_vc_channel_id"
MUSIC_VC_BONUS_KEY = "music_vc_bonus_multiplier"

yt_dlp.utils.bug_reports_message = lambda: ""  # pyright: ignore[reportAttributeAccessIssue]

ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 512k",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


def _voice_channel(vc: discord.VoiceClient | None) -> discord.VoiceChannel | None:
    return voice_channel_from_vc(vc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_duration(seconds: int) -> str:
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def is_youtube_url(query: str) -> bool:
    youtube_patterns = [
        r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)",
        r"youtube\.com/playlist\?list=",
    ]
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in youtube_patterns)


def is_playlist_url(query: str) -> bool:
    return bool(re.search(r"playlist\?list=", query, re.IGNORECASE))


def is_direct_media_url(query: str) -> bool:
    if not query.startswith("http"):
        return False
    lower = query.lower()
    if is_youtube_url(query):
        return True
    if "soundcloud.com" in lower:
        return True
    if re.search(r"\.(mp3|wav|ogg|flac|m4a|webm)(\?|$)", lower):
        return True
    return query.startswith("http")


def _friendly_extract_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "soundcloud" in text and ("not available" in text or "404" in text):
        return "That SoundCloud track could not be loaded. It may be private or region-locked."
    if "youtube" in text or "video unavailable" in text:
        return "That YouTube video is unavailable or blocked in your region."
    if "unsupported url" in text or "no video" in text:
        return "Unsupported URL. Try a YouTube link, SoundCloud link, or search terms."
    if "sign in" in text or "confirm your age" in text:
        return "This content requires sign-in and cannot be streamed."
    return f"Could not load audio: {exc}"


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown")
        self.url = data.get("webpage_url") or data.get("url", "")
        self.duration = data.get("duration", 0) or 0
        self.thumbnail = data.get("thumbnail", "")
        self.uploader = data.get("uploader", "Unknown")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, volume=0.5):
        loop = loop or asyncio.get_event_loop()
        fetch_url = url
        if not is_direct_media_url(url) and not url.startswith("http"):
            fetch_url = f"ytsearch:{url}"

        opts = dict(ytdl_format_options)
        if is_playlist_url(fetch_url):
            opts["noplaylist"] = False
            opts["playlistend"] = PLAYLIST_MAX_TRACKS

        local_ytdl = yt_dlp.YoutubeDL(opts) if opts != ytdl_format_options else ytdl

        try:
            data = await loop.run_in_executor(
                None, lambda: local_ytdl.extract_info(fetch_url, download=not stream)
            )
        except Exception as exc:
            raise ValueError(_friendly_extract_error(exc)) from exc

        if "entries" in data:
            entries = [e for e in data["entries"] if e]
            if not entries:
                raise ValueError("No tracks found in that playlist or search.")
            if len(entries) > 1:
                raise PlaylistResult(entries[:PLAYLIST_MAX_TRACKS], data)
            data = entries[0]

        if not data:
            raise ValueError("No audio found for that query.")

        if stream:
            formats = data.get("formats", [])
            audio_url = None
            for fmt in formats:
                if fmt.get("acodec") != "none" and fmt.get("vcodec") == "none":
                    audio_url = fmt.get("url")
                    break
            if not audio_url:
                audio_url = data.get("url")
            if not audio_url:
                raise ValueError("Could not extract a stream URL for this track.")
            return cls(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), data=data, volume=volume)

        filename = local_ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, volume=volume)

    @classmethod
    def track_info_from_data(cls, data: dict, *, query: str, requested_by: int) -> dict:
        return {
            "title": data.get("title", "Unknown"),
            "url": data.get("webpage_url") or data.get("url", ""),
            "duration": data.get("duration", 0) or 0,
            "thumbnail": data.get("thumbnail", ""),
            "uploader": data.get("uploader", "Unknown"),
            "requested_by": requested_by,
            "query": query,
        }


class PlaylistResult(Exception):
    """Raised when extraction returns multiple playlist entries."""

    def __init__(self, entries: list, meta: dict):
        self.entries = entries
        self.meta = meta
        super().__init__(f"Playlist with {len(entries)} track(s)")


@dataclass
class GuildMusicState:
    queue: List[dict] = field(default_factory=list)
    loop_mode: str = "off"  # off | track | queue
    shuffle: bool = False
    vote_skip_votes: Set[int] = field(default_factory=set)
    current_track: Optional[dict] = None
    volume: float = 0.5
    text_channel_id: Optional[int] = None
    voice_channel_id: Optional[int] = None
    panel_message_id: Optional[int] = None
    vc_empty_since: Optional[float] = None


_guild_states: Dict[int, GuildMusicState] = {}


def get_state(guild_id: int) -> GuildMusicState:
    if guild_id not in _guild_states:
        _guild_states[guild_id] = GuildMusicState()
    return _guild_states[guild_id]


def music_queues() -> Dict[int, List[dict]]:
    """Back-compat alias: guild_id -> queue list."""
    return {gid: st.queue for gid, st in _guild_states.items()}


def _cycle_loop_mode(current: str) -> str:
    order = ("off", "track", "queue")
    try:
        idx = order.index(current)
    except ValueError:
        return "off"
    return order[(idx + 1) % len(order)]


def loop_mode_label(mode: str) -> str:
    return {"off": "Off", "track": "Track", "queue": "Queue"}.get(mode, mode.title())


async def persist_guild_state(guild_id: int, *, is_playing: bool) -> None:
    st = get_state(guild_id)
    queue_json = json.dumps(st.queue)
    current_title = (st.current_track or {}).get("title")
    volume_pct = int(round(st.volume * 100))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO music_queues
            (guild_id, channel_id, voice_channel_id, current_track, queue_json, is_playing, volume, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                st.text_channel_id or 0,
                st.voice_channel_id or 0,
                current_title,
                queue_json,
                1 if is_playing else 0,
                volume_pct,
                now_utc().isoformat(),
            ),
        )
        await db.commit()


async def restore_music_queues(bot: discord.Client) -> int:
    """Load in-memory queues from DB where is_playing (best-effort, no voice reconnect)."""
    restored = 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT guild_id, channel_id, voice_channel_id, queue_json, volume
            FROM music_queues WHERE is_playing=1
            """
        )
        rows = await cur.fetchall()
    for guild_id, channel_id, voice_channel_id, queue_json, volume in rows:
        try:
            st = get_state(int(guild_id))
            st.queue = json.loads(queue_json or "[]")
            st.text_channel_id = int(channel_id) if channel_id else None
            st.voice_channel_id = int(voice_channel_id) if voice_channel_id else None
            st.volume = max(0.0, min(1.0, (volume or 50) / 100.0))
            panel_raw = await get_guild_setting(int(guild_id), "music_panel_message_id")
            if panel_raw:
                st.panel_message_id = int(panel_raw)
            restored += 1
        except Exception as exc:
            logger.debug("[music] restore failed guild=%s: %s", guild_id, exc)
    if restored:
        logger.info("[music] Restored queue state for %s guild(s)", restored)
    return restored


async def set_panel_message_id(guild_id: int, message_id: Optional[int]) -> None:
    st = get_state(guild_id)
    st.panel_message_id = message_id
    from database import set_guild_setting

    if message_id:
        await set_guild_setting(guild_id, "music_panel_message_id", str(message_id))
    else:
        await set_guild_setting(guild_id, "music_panel_message_id", "")


def _pop_next_track(st: GuildMusicState) -> Optional[dict]:
    if not st.queue:
        return None
    if st.shuffle:
        idx = random.randrange(len(st.queue))
        return st.queue.pop(idx)
    return st.queue.pop(0)


async def play_next_in_queue(guild_id: int, bot: discord.Client) -> None:
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    voice_client = get_voice_client(guild)
    if not voice_client:
        await persist_guild_state(guild_id, is_playing=False)
        return

    st = get_state(guild_id)
    st.vote_skip_votes.clear()

    loop_mode = st.loop_mode
    previous = st.current_track

    if loop_mode == "track" and previous:
        next_track = previous
    else:
        if loop_mode == "queue" and previous and not st.queue:
            st.queue.append(previous)
        next_track = _pop_next_track(st)

    if not next_track:
        st.current_track = None
        await persist_guild_state(guild_id, is_playing=False)
        await update_now_playing_panel(guild, bot)
        return

    st.current_track = next_track
    query = next_track.get("query") or next_track.get("url") or ""

    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True, volume=st.volume)
        st.current_track = YTDLSource.track_info_from_data(
            player.data,
            query=query,
            requested_by=int(next_track.get("requested_by") or 0),
        )

        def _after(err):
            if err:
                logger.warning("[music] playback error guild=%s: %s", guild_id, err)
            asyncio.run_coroutine_threadsafe(play_next_in_queue(guild_id, bot), bot.loop)

        voice_client.play(player, after=_after)
        set_voice_source_volume(voice_client, st.volume)

        await persist_guild_state(guild_id, is_playing=True)
        await update_now_playing_panel(guild, bot, announce=not await _quieter_announce(guild.id))
    except Exception as exc:
        logger.warning("[music] skip bad track guild=%s: %s", guild_id, exc)
        await play_next_in_queue(guild_id, bot)


async def _quieter_announce(guild_id: int) -> bool:
    try:
        from database import get_quieter_mode

        return await get_quieter_mode(guild_id)
    except Exception:
        return False


def build_now_playing_embed(guild: discord.Guild, client) -> discord.Embed:
    from core.embed_footers import footer_for
    from core.embed_templates import embed_template

    st = get_state(guild.id)
    track = st.current_track
    voice = get_voice_client(guild)
    paused = bool(voice and voice.is_paused())
    playing = bool(voice and voice.is_playing())

    if track:
        title = track.get("title", "Unknown")
        uploader = track.get("uploader", "Unknown")
        duration = format_duration(int(track.get("duration") or 0))
        req_id = track.get("requested_by")
        req_line = f"<@{req_id}>" if req_id else "Unknown"
        desc = (
            f"**{title}**\n"
            f"Uploader: {uploader}\n"
            f"Duration: {duration}\n"
            f"Requested by {req_line}\n\n"
            f"**Loop:** {loop_mode_label(st.loop_mode)} · **Shuffle:** {'On' if st.shuffle else 'Off'}\n"
            f"**Queue:** {len(st.queue)} track(s) · **Volume:** {int(st.volume * 100)}%"
        )
        status = "⏸️ Paused" if paused else ("🎵 Now Playing" if playing else "⏹️ Idle")
        embed = embed_template(
            "showcase",
            status,
            desc,
            category="music",
            footer=footer_for("music"),
            client=client,
        )
        thumb = track.get("thumbnail")
        if thumb:
            embed.set_thumbnail(url=thumb)
        return embed

    if st.queue:
        desc = f"No track loaded — **{len(st.queue)}** in queue.\nUse **/music play** to start."
    else:
        desc = "Nothing playing. Use **/music play** to start."
    return embed_template(
        "showcase",
        "🎵 Music",
        desc,
        category="music",
        footer=footer_for("music"),
        client=client,
    )


def _panel_view_factory(guild_id: int):
    from commands.music.music import MusicPanelView

    return MusicPanelView(guild_id)


def build_now_playing_layout(guild: discord.Guild, bot: discord.Client):
    """Build V2 now-playing panel when HELP_LAYOUT_V2 is enabled."""
    from core.help_layout import help_layout_v2_enabled
    from core.music_panel_layout import MusicPanelLayout

    if not help_layout_v2_enabled():
        return None
    embed = build_now_playing_embed(guild, bot)
    panel = _panel_view_factory(guild.id)
    return MusicPanelLayout(
        guild_id=guild.id,
        title=embed.title or "🎵 Music",
        body=embed.description or "",
        on_skip=panel._on_skip,
        on_toggle=panel._on_toggle,
        on_queue=panel._on_queue,
    )


async def update_now_playing_panel(
    guild: discord.Guild,
    bot: discord.Client,
    *,
    announce: bool = False,
) -> None:
    from core.safe_message_edit import safe_message_edit

    st = get_state(guild.id)
    embed = build_now_playing_embed(guild, bot)
    view = _panel_view_factory(guild.id)
    layout = build_now_playing_layout(guild, bot)

    channel = None
    if st.text_channel_id:
        ch = guild.get_channel(st.text_channel_id)
        if isinstance(ch, discord.TextChannel):
            channel = ch

    if st.panel_message_id and channel:
        try:
            msg = await channel.fetch_message(st.panel_message_id)
            if layout:
                await safe_message_edit(msg, view=layout)
            else:
                await safe_message_edit(msg, embed=embed, view=view)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            st.panel_message_id = None

    if announce and channel and (get_voice_client(guild) and (get_voice_client(guild).is_playing() or get_voice_client(guild).is_paused())):
        try:
            if layout:
                msg = await channel.send(view=layout)
            else:
                msg = await channel.send(embed=embed, view=view)
            await set_panel_message_id(guild.id, msg.id)
        except Exception:
            pass


async def get_vote_skip_ratio(guild_id: int) -> float:
    raw = await get_guild_setting(guild_id, "music_vote_skip_ratio")
    if raw:
        try:
            val = float(raw)
            return max(0.1, min(1.0, val))
        except ValueError:
            pass
    return MUSIC_VOTE_SKIP_RATIO


def listeners_in_vc(guild: discord.Guild) -> list[discord.Member]:
    vch = _voice_channel(get_voice_client(guild))
    if not vch:
        return []
    return [m for m in vch.members if not m.bot]


async def register_vote_skip(member: discord.Member) -> tuple[bool, str, int, int]:
    """Add a vote; returns (should_skip, message, votes, needed)."""
    if not member.voice or not member.voice.channel:
        return False, "Join the bot's voice channel to vote.", 0, 0
    guild = member.guild
    vc = get_voice_client(guild)
    vch = _voice_channel(vc)
    member_ch = member.voice.channel if member.voice else None
    if not vch or not isinstance(member_ch, discord.VoiceChannel) or member_ch.id != vch.id:
        return False, "Join the bot's voice channel to vote.", 0, 0
    if not vc.is_playing() and not vc.is_paused():
        return False, "Nothing is playing right now.", 0, 0

    st = get_state(guild.id)
    if member.id in st.vote_skip_votes:
        ratio = await get_vote_skip_ratio(guild.id)
        listeners = listeners_in_vc(guild)
        needed = max(1, int(len(listeners) * ratio + 0.999))
        return False, "You already voted to skip.", len(st.vote_skip_votes), needed

    st.vote_skip_votes.add(member.id)
    ratio = await get_vote_skip_ratio(guild.id)
    listeners = listeners_in_vc(guild)
    needed = max(1, int(len(listeners) * ratio + 0.999))
    votes = len(st.vote_skip_votes)
    if votes >= needed:
        return True, f"Vote skip passed ({votes}/{needed}).", votes, needed
    return False, f"Vote recorded ({votes}/{needed} needed).", votes, needed


async def clear_guild_playback(
    guild: discord.Guild,
    bot: discord.Client,
    *,
    disconnect: bool = True,
) -> None:
    st = get_state(guild.id)
    st.queue.clear()
    st.current_track = None
    st.vote_skip_votes.clear()
    vc = get_voice_client(guild)
    if vc:
        vc.stop()
        if disconnect:
            await vc.disconnect(force=True)
    await persist_guild_state(guild.id, is_playing=False)
    await update_now_playing_panel(guild, bot)


async def is_temp_vc_channel(guild_id: int, channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=? LIMIT 1",
            (guild_id, channel_id),
        )
        return (await cur.fetchone()) is not None


async def get_music_vc_bonus_multiplier(guild_id: int) -> float:
    raw = await get_guild_setting(guild_id, MUSIC_VC_BONUS_KEY)
    if raw:
        try:
            val = float(raw)
            return max(1.0, min(3.0, val))
        except ValueError:
            pass
    return max(1.0, MUSIC_VC_BONUS_MULTIPLIER)


async def transfer_dj_control(guild_id: int, new_host_id: int) -> None:
    """Reassign requested_by on current track and queue (temp VC host transfer)."""
    st = get_state(guild_id)
    if st.current_track:
        st.current_track["requested_by"] = new_host_id
    for track in st.queue:
        track["requested_by"] = new_host_id


def guild_is_playing_music(guild: discord.Guild) -> bool:
    vc = get_voice_client(guild)
    if not vc or not _voice_channel(vc):
        return False
    return bool(vc.is_playing() or vc.is_paused())


def format_guild_music_line(guild: discord.Guild) -> Optional[str]:
    """One-line status for hub/console embeds."""
    vc = get_voice_client(guild)
    vch = _voice_channel(vc)
    if not vc or not vch or not guild_is_playing_music(guild):
        return None
    st = get_state(guild.id)
    listeners = len([m for m in vch.members if not m.bot])
    title = (st.current_track or {}).get("title", "Music")
    if len(title) > 48:
        title = title[:45] + "…"
    queue_n = len(st.queue)
    queue_hint = f" · **{queue_n}** queued" if queue_n else ""
    return f"🎵 **{listeners}** listening in {vch.mention} — _{title}_{queue_hint}"


def format_music_console_block(guild: discord.Guild) -> Optional[str]:
    """Richer block for Clan Console embed."""
    line = format_guild_music_line(guild)
    if not line:
        return None
    vc = get_voice_client(guild)
    assert vc and _voice_channel(vc)
    status = "Paused" if vc.is_paused() else "Playing"
    return f"**Music** — {status}\n{line}"


async def stop_if_in_channel(
    guild: discord.Guild,
    channel_id: int,
    bot: discord.Client,
) -> None:
    """Stop playback and disconnect when a temp VC is deleted."""
    vc = get_voice_client(guild)
    vch = _voice_channel(vc)
    if not vc or not vch or vch.id != channel_id:
        return
    st = get_state(guild.id)
    if not (vc.is_playing() or vc.is_paused() or st.current_track or st.queue):
        return
    logger.info("[music] stopping playback — temp VC %s deleted in guild %s", channel_id, guild.id)
    await clear_guild_playback(guild, bot, disconnect=True)


async def _ensure_voice(
    guild: discord.Guild,
    voice_channel: discord.VoiceChannel,
) -> discord.VoiceClient:
    vc = get_voice_client(guild)
    vch = _voice_channel(vc)
    if vc and vch and vch.id != voice_channel.id:
        await vc.move_to(voice_channel)
        return vc
    if vc:
        return vc
    connected = await voice_channel.connect()
    if not isinstance(connected, discord.VoiceClient):
        raise RuntimeError("Voice connect did not return VoiceClient")
    return connected


async def enqueue_query(
    guild: discord.Guild,
    bot: discord.Client,
    query: str,
    requested_by: int,
    voice_channel: discord.VoiceChannel,
    *,
    text_channel_id: Optional[int] = None,
    announce: Optional[bool] = None,
) -> tuple[bool, str]:
    """Connect (if needed), play or queue a URL/search. Used by LFG radio and event soundtracks."""
    query = (query or "").strip()
    if not query:
        return False, "No playlist or search query provided."

    try:
        from core.utils import feature_enabled

        if not await feature_enabled(guild.id, "music"):
            return False, "Music is disabled in this server."
    except Exception:
        pass

    st = get_state(guild.id)
    if text_channel_id:
        st.text_channel_id = text_channel_id
    st.voice_channel_id = voice_channel.id

    try:
        voice_client = await _ensure_voice(guild, voice_channel)
    except Exception as exc:
        return False, f"Could not join voice: {exc}"

    if announce is None:
        announce = not await _quieter_announce(guild.id)

    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True, volume=st.volume)
    except PlaylistResult as pl:
        tracks = [
            YTDLSource.track_info_from_data(
                entry,
                query=entry.get("webpage_url") or entry.get("url") or query,
                requested_by=requested_by,
            )
            for entry in pl.entries
        ]
        if voice_client.is_playing() or voice_client.is_paused() or st.current_track:
            st.queue.extend(tracks)
            await persist_guild_state(guild.id, is_playing=True)
            await update_now_playing_panel(guild, bot, announce=announce)
            return True, f"Added **{len(tracks)}** track(s) to the queue."

        first = tracks[0]
        first_query = first.get("query") or first.get("url") or query
        sub_player = await YTDLSource.from_url(
            first_query, loop=bot.loop, stream=True, volume=st.volume
        )
        first_info = YTDLSource.track_info_from_data(
            sub_player.data, query=first_query, requested_by=requested_by
        )
        st.queue.extend(tracks[1:])
        st.current_track = first_info

        def _after(err):
            if err:
                logger.warning("[music] playback error guild=%s: %s", guild.id, err)
            asyncio.run_coroutine_threadsafe(play_next_in_queue(guild.id, bot), bot.loop)

        voice_client.play(sub_player, after=_after)
        if voice_client.source:
            set_voice_source_volume(voice_client, st.volume)
        await persist_guild_state(guild.id, is_playing=True)
        await update_now_playing_panel(guild, bot, announce=announce)
        extra = f" (+{len(tracks) - 1} more queued)" if len(tracks) > 1 else ""
        return True, f"Now playing **{first_info.get('title', 'track')}**{extra}"

    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.warning("[music] enqueue_query failed guild=%s: %s", guild.id, exc)
        return False, f"Playback error: {exc}"

    track_info = YTDLSource.track_info_from_data(
        player.data, query=query, requested_by=requested_by
    )

    if voice_client.is_playing() or voice_client.is_paused():
        st.queue.append(track_info)
        await persist_guild_state(guild.id, is_playing=True)
        await update_now_playing_panel(guild, bot, announce=announce)
        return True, f"Queued **{track_info.get('title', 'track')}** (position {len(st.queue)})."

    st.current_track = track_info

    def _after_single(err):
        if err:
            logger.warning("[music] playback error guild=%s: %s", guild.id, err)
        asyncio.run_coroutine_threadsafe(play_next_in_queue(guild.id, bot), bot.loop)

    voice_client.play(player, after=_after_single)
    if voice_client.source:
        set_voice_source_volume(voice_client, st.volume)
    await persist_guild_state(guild.id, is_playing=True)
    await update_now_playing_panel(guild, bot, announce=announce)
    return True, f"Now playing **{track_info.get('title', 'track')}**."


async def try_start_event_soundtrack(
    guild: discord.Guild,
    bot: discord.Client,
    soundtrack_query: str,
    *,
    event_title: str = "Event",
) -> bool:
    """Auto-queue event soundtrack when bot is already in the configured event VC."""
    query = (soundtrack_query or "").strip()
    if not query:
        return False

    enabled = await get_guild_setting(guild.id, MUSIC_EVENT_SOUNDTRACK_KEY)
    if enabled and enabled.lower() in ("0", "false", "off", "no"):
        return False

    event_vc_raw = await get_guild_setting(guild.id, EVENT_VC_CHANNEL_KEY)
    if not event_vc_raw:
        return False
    try:
        event_vc_id = int(event_vc_raw)
    except ValueError:
        return False

    vc = get_voice_client(guild)
    vch = _voice_channel(vc)
    if not vc or not vch or vch.id != event_vc_id:
        return False

    events_ch_raw = await get_guild_setting(guild.id, "events_channel_id")
    text_ch_id = int(events_ch_raw) if events_ch_raw and events_ch_raw.isdigit() else None

    ok, msg = await enqueue_query(
        guild,
        bot,
        query,
        requested_by=guild.me.id if guild.me else 0,
        voice_channel=vch,
        text_channel_id=text_ch_id,
        announce=not await _quieter_announce(guild.id),
    )
    if ok:
        logger.info("[music] event soundtrack started guild=%s event=%s: %s", guild.id, event_title, msg)
    return ok


async def music_auto_leave_tick(bot: discord.Client) -> None:
    """Disconnect when bot VC is empty for MUSIC_AUTO_LEAVE_MINUTES."""
    import time

    if MUSIC_AUTO_LEAVE_MINUTES <= 0:
        return
    threshold = MUSIC_AUTO_LEAVE_MINUTES * 60
    now = time.monotonic()
    for guild in bot.guilds:
        vc = get_voice_client(guild)
        vch = _voice_channel(vc)
        if not vc or not vch:
            get_state(guild.id).vc_empty_since = None
            continue
        humans = [m for m in vch.members if not m.bot]
        st = get_state(guild.id)
        if humans:
            st.vc_empty_since = None
            continue
        if st.vc_empty_since is None:
            st.vc_empty_since = now
            continue
        if now - st.vc_empty_since >= threshold:
            logger.info("[music] auto-leave guild=%s (empty %sm)", guild.id, MUSIC_AUTO_LEAVE_MINUTES)
            await clear_guild_playback(guild, bot, disconnect=True)
            st.vc_empty_since = None
