"""Explain why a user did or didn't receive a bot DM."""
from __future__ import annotations

import discord

from core.utils import obsidian_embed, EMBED_COLORS
from database import get_digest_dm, get_guild_setting, get_quieter_mode


async def build_notify_explain_embed(
    guild: discord.Guild,
    user: discord.abc.User,
    *,
    client=None,
) -> discord.Embed:
    """Ephemeral-friendly explainer for DM delivery."""
    uid = user.id
    gid = guild.id
    lines: list[str] = []

    digest_on = await get_digest_dm(gid, uid)
    lines.append(f"**Daily digest DMs:** {'On' if digest_on else 'Off'} (`/preferences digest_dm`)")

    dr = await get_guild_setting(gid, f"user_daily_reminder:{uid}")
    lines.append(f"**Daily streak reminders:** {'On' if dr == '1' else 'Off'}")

    quieter = await get_quieter_mode(gid)
    if quieter:
        lines.append("**Guild quieter mode:** On — fewer channel pings; DMs preferred where possible.")

    from core.quiet_hours import in_quiet_hours, get_quiet_hours_label

    qh = await get_quiet_hours_label(gid, uid)
    if qh:
        blocked = await in_quiet_hours(gid, uid)
        lines.append(
            f"**Quiet hours:** {qh} — "
            + ("**active now** (nudge DMs suppressed)" if blocked else "not active now")
        )
    else:
        lines.append("**Quiet hours:** Not set (`/preferences quiet_hours`)")

    inv = await get_guild_setting(gid, f"user_investment_dm:{uid}")
    lines.append(f"**Investment maturity DMs:** {'On' if inv == '1' else 'Off'}")

    lines.extend([
        "",
        "**Discord settings** — Server DMs must be allowed for this server.",
        "If DMs are blocked, the bot falls back to ephemeral replies or channel posts.",
        "",
        "Use **`/wfnotify test_ping`** to verify DM delivery.",
    ])

    return obsidian_embed(
        "🔔 Why didn't I get a DM?",
        "\n".join(lines),
        color=EMBED_COLORS["general"],
        footer="Warframe channel alerts are separate from personal DMs",
        client=client,
    )
