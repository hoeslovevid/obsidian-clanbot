"""Discovery helpers — channel-aware menu, role-based suggestions."""
from __future__ import annotations

import discord

# Maps channel name fragments → MENU_ITEMS path slugs (last segment)
_CHANNEL_SLUG_BIAS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("trade", "market", "barter"), ("trade", "configure", "baro")),
    (("lfg", "squad", "recruit"), ("lfg", "fissures", "configure")),
    (("ticket", "support", "help"), ("ticket", "case", "help")),
    (("welcome", "general", "chat"), ("start", "menu", "help")),
    (("voice", "vc", "comms"), ("lfg", "me", "today")),
    (("warframe", "tenno", "wf"), ("baro", "fissures", "configure", "today")),
]

# Role name fragments → suggestion lines (plain text; menu embed adds them)
_ROLE_SUGGESTIONS: list[tuple[tuple[str, ...], str]] = [
    (("trader", "trade", "merchant"), "**Trader** — `/trade` · `/price_watch` · `/trading trade_price`"),
    (("mentor", "guide", "helper"), "**Mentor** — `/profile` · `/lfg` · `/community ticket`"),
    (("event", "organizer", "host"), "**Events** — `/events` · `/poll` · `/community suggest`"),
    (("mod", "staff", "admin"), "**Staff** — `/mod dashboard` · `/admin setup_status`"),
]


def channel_menu_slug_bias(channel: discord.abc.GuildChannel | None) -> set[str]:
    """Slugs to prioritize when building /menu for this channel."""
    if not channel or not getattr(channel, "name", None):
        return set()
    name = channel.name.lower()
    slugs: set[str] = set()
    for fragments, picks in _CHANNEL_SLUG_BIAS:
        if any(f in name for f in fragments):
            slugs.update(picks)
    return slugs


def reorder_menu_indices(
    menu_items: list,
    *,
    channel: discord.abc.GuildChannel | None = None,
    base_order: list[int] | None = None,
) -> list[int]:
    """Reorder MENU_ITEMS indices with channel bias first, then time-of-day order."""
    if base_order is None:
        base_order = list(range(len(menu_items)))
    bias = channel_menu_slug_bias(channel)
    if not bias:
        return base_order

    def slug_for_idx(idx: int) -> str:
        _label, _emoji, path, _hint = menu_items[idx]
        return (path[-1] if path else "").lower()

    biased = [i for i in base_order if slug_for_idx(i) in bias]
    rest = [i for i in base_order if i not in biased]
    return biased + rest


def role_suggestion_lines(member: discord.Member, *, limit: int = 2) -> list[str]:
    """Up to ``limit`` role-based command hints for /menu."""
    lines: list[str] = []
    role_names = " ".join(r.name.lower() for r in member.roles if r != member.guild.default_role)
    for fragments, line in _ROLE_SUGGESTIONS:
        if any(f in role_names for f in fragments):
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines
