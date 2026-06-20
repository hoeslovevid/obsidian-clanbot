"""Side-by-side profile comparison."""
from __future__ import annotations

import discord

from core.utils import EMBED_COLORS, format_number, obsidian_embed, render_bar
from database import xp_for_next_level


async def build_compare_embed(
    guild: discord.Guild,
    viewer: discord.Member,
    target: discord.Member,
    viewer_data: dict,
    target_data: dict,
    *,
    client=None,
) -> discord.Embed:
    """Compact compare view when viewing another member's profile."""
    from database import xp_for_level
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT

    def _xp_bar(level: int, xp: int) -> str:
        cur = xp_for_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if level > 0 else 0
        nxt = xp_for_next_level(level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        rng = max(1, nxt - cur)
        pct = min(100, int(100 * (xp - cur) / rng))
        return f"Lv **{level}** · {render_bar(pct)}"

    v_streak = viewer_data.get("daily_streak") or 0
    t_streak = target_data.get("daily_streak") or 0
    v_ach = int(viewer_data.get("achievements_count") or 0)
    t_ach = int(target_data.get("achievements_count") or 0)
    v_total_ach = int(viewer_data.get("achievements_total") or 0)
    t_total_ach = int(target_data.get("achievements_total") or 0)

    fields = [
        (
            f"You · {viewer.display_name}",
            f"💰 {format_number(viewer_data.get('balance') or 0)}\n"
            f"{_xp_bar(viewer_data.get('level') or 0, viewer_data.get('xp') or 0)}\n"
            f"🔥 Streak **{v_streak}** · 🏆 **{v_ach}/{v_total_ach}**",
            True,
        ),
        (
            f"Them · {target.display_name}",
            f"💰 {format_number(target_data.get('balance') or 0)}\n"
            f"{_xp_bar(target_data.get('level') or 0, target_data.get('xp') or 0)}\n"
            f"🔥 Streak **{t_streak}** · 🏆 **{t_ach}/{t_total_ach}**",
            True,
        ),
    ]

    v_voice = viewer_data.get("voice_minutes") or 0
    t_voice = target_data.get("voice_minutes") or 0
    fields.append(
        (
            "Voice time",
            f"You: **{v_voice // 60}h {v_voice % 60}m**\n"
            f"Them: **{t_voice // 60}h {t_voice % 60}m**",
            False,
        ),
    )

    return obsidian_embed(
        f"⚖️ Profile compare",
        f"Quick stats for **{viewer.display_name}** vs **{target.display_name}**.",
        color=EMBED_COLORS["general"],
        fields=fields,
        footer="Full profiles: /profile · /profile @user",
        client=client,
    )
