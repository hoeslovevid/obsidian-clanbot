"""Complaint status DM helpers (QoL #16)."""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import discord  # type: ignore

from core.utils import obsidian_embed, display_case_status

if TYPE_CHECKING:
    pass

_STATUS_COLORS = {
    "ACKNOWLEDGED": discord.Color.blurple(),
    "NEEDS INFO": discord.Color.orange(),
    "RESOLVED": discord.Color.green(),
    "REJECTED": discord.Color.dark_grey(),
    "OPEN": discord.Color.gold(),
}

_STATUS_EMOJI = {
    "ACKNOWLEDGED": "🔍",
    "NEEDS INFO": "❗",
    "RESOLVED": "✅",
    "REJECTED": "❌",
    "OPEN": "📋",
}

_NEXT_STEPS = {
    "ACKNOWLEDGED": "Staff are reviewing your case. You'll be notified here when the status changes.",
    "NEEDS INFO": (
        "Please reply with the requested details using "
        "`/community submit_complaint` and your case ID."
    ),
    "RESOLVED": "This case is closed. Thank you for your patience.",
    "REJECTED": "This case has been dismissed. Contact staff if you believe this was in error.",
}


def build_complaint_status_embed(
    case_id: str,
    status: str,
    *,
    guild_name: str,
    mod_name: Optional[str] = None,
    note: Optional[str] = None,
    client: Optional[discord.Client] = None,
) -> discord.Embed:
    """Build a rich DM embed for complaint status updates."""
    normalized = (status or "").strip().upper()
    display = display_case_status(status)
    emoji = _STATUS_EMOJI.get(normalized, "📋")
    color = _STATUS_COLORS.get(normalized, discord.Color.blurple())

    lines = [
        f"Your case **`{case_id}`** in **{guild_name}** has been updated.",
        "",
        f"**Status:** {emoji} {display}",
    ]
    if mod_name:
        lines.append(f"**Updated by:** {mod_name}")
    if note and note.strip():
        lines.append("")
        lines.append(f"**Staff note:**\n{note.strip()[:1500]}")
    next_step = _NEXT_STEPS.get(normalized)
    if next_step:
        lines.append("")
        lines.append(f"_{next_step}_")

    return obsidian_embed(
        f"Docket Update • {case_id}",
        "\n".join(lines),
        color=color,
        client=client,
    )


async def send_complaint_status_dm(
    guild: discord.Guild,
    user_id: int,
    case_id: str,
    status: str,
    bot: discord.Client,
    *,
    mod_name: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    """DM the reporter about a status change. Returns False if DMs are blocked."""
    user = guild.get_member(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except (discord.NotFound, discord.HTTPException):
            return True

    embed = build_complaint_status_embed(
        case_id,
        status,
        guild_name=guild.name,
        mod_name=mod_name,
        note=note,
        client=bot,
    )
    try:
        await user.send(embed=embed)
        return True
    except discord.Forbidden:
        return False
