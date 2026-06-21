"""Rich Twitch go-live notification embeds."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import discord

from core.embed_templates import embed_template


def _stream_thumbnail_url(stream_data: dict[str, Any]) -> Optional[str]:
    raw = stream_data.get("thumbnail_url") or ""
    if not raw:
        login = str(stream_data.get("user_login") or "").lower()
        if login:
            return f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-440x248.jpg"
        return None
    return raw.replace("{width}", "440").replace("{height}", "248")


def _started_relative(started_at: Optional[str]) -> Optional[str]:
    if not started_at:
        return None
    try:
        dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        ts = int(dt.timestamp())
        return f"<t:{ts}:R> (<t:{ts}:f>)"
    except Exception:
        return None


def build_twitch_live_embed(
    stream_data: dict[str, Any],
    *,
    client=None,
) -> discord.Embed:
    """Showcase-style go-live card with game, viewers, preview, and stream title."""
    login = str(stream_data.get("user_login") or "?").lower()
    display = str(stream_data.get("user_name") or login)
    stream_title = str(stream_data.get("title") or "Untitled stream").strip()
    game = str(stream_data.get("game_name") or "Just Chatting")
    viewers = int(stream_data.get("viewer_count") or 0)
    language = str(stream_data.get("language") or "").upper()
    tags = stream_data.get("tags") or []

    fields: list[tuple[str, str, bool]] = [
        ("🎮 Category", game, True),
        ("👀 Viewers", f"**{viewers:,}** watching", True),
    ]
    started = _started_relative(stream_data.get("started_at"))
    if started:
        fields.append(("⏱️ Live since", started, False))
    if language:
        fields.append(("🌐 Language", language, True))
    if tags:
        tag_line = " · ".join(f"`{t}`" for t in list(tags)[:4])
        if len(tags) > 4:
            tag_line += f" +{len(tags) - 4}"
        fields.append(("🏷️ Tags", tag_line, False))

    preview = _stream_thumbnail_url(stream_data)
    desc = f"> **{stream_title[:350]}**"

    return embed_template(
        "showcase",
        f"🔴 {display} is live on Twitch",
        desc,
        category="community",
        thumbnail=preview,
        image=preview,
        fields=fields,
        footer=f"twitch.tv/{login} · Obsidian stream alerts",
        client=client,
    )


class TwitchLiveAlertView(discord.ui.View):
    """Watch stream + profile links on go-live posts."""

    def __init__(self, login: str):
        super().__init__()
        login = login.lower()
        self.add_item(
            discord.ui.Button(
                label="Watch stream",
                style=discord.ButtonStyle.link,
                url=f"https://twitch.tv/{login}",
                emoji="📺",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Open profile",
                style=discord.ButtonStyle.link,
                url=f"https://twitch.tv/{login}/about",
                emoji="👤",
            )
        )
