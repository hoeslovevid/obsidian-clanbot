"""Discovery 12, help essentials, and command-tree visibility rules."""
from __future__ import annotations

# (path, one-line blurb) — public entry surface for discovery, /start, /help, /about
DISCOVERY_12: list[tuple[str, str]] = [
    ("start", "New here? Quick guide"),
    ("menu", "Shortcut picker"),
    ("help", "Full command reference"),
    ("search", "Find any command by keyword"),
    ("daily", "Claim daily coins & streak"),
    ("claim", "Bounties + investments hub"),
    ("today", "Your day at a glance"),
    ("baro", "Void Trader inventory"),
    ("fissures", "Void fissure missions"),
    ("lfg", "Post or browse squads"),
    ("ticket", "Open a support ticket"),
    ("wfnotify configure", "Warframe alert setup (mods)"),
]

# Hidden from member help/search — use the canonical command instead.
DE_EMPHASIZED_PATHS: frozenset[str] = frozenset({
    "warframe baro",
    "warframe fissures",
    "general help_search",
    "community ticket",
    "trading trade",
    "economy daily",
    "economy wallet",
    "economy bal",
    "economy balance",
    "economy cooldowns",
    "economy leaderboard",
    "warframe status",
    "warframe world_state",
    "warframe worth",
    "warframe hub",
    "wfnotify setup",  # prefer configure wizard
})

# Removed from the slash tree (see commands_loader LEGACY_NOTIFY_MODULES).
REMOVED_LEGACY_NOTIFY_PATHS: frozenset[str] = frozenset({
    "wfnotify baro_notify",
    "wfnotify alerts_notify",
    "wfnotify cycle_notify",
    "wfnotify invasion_notify",
    "wfnotify archon_notify",
    "wfnotify warframe_event_notify",
    "wfnotify devstream_notify",
    "wfnotify forum",
    "wfnotify youtube",
    "wfnotify tennogen",
})

CANONICAL_ALTERNATIVES: dict[str, str] = {
    "warframe baro": "`/baro`",
    "warframe fissures": "`/fissures`",
    "general help_search": "`/search`",
    "community ticket": "`/ticket`",
    "trading trade": "`/trade`",
    "economy daily": "`/daily`",
    "economy wallet": "`/daily` · `/claim` · `/economy wallet`",
    "economy bal": "`/bal`",
    "economy balance": "`/balance`",
    "warframe hub": "`/baro` · `/fissures` · `/warframe hub`",
    "warframe status": "`/status` · `/warframe hub`",
    "warframe world_state": "`/warframe worth` · `/warframe hub`",
    "warframe worth": "`/warframe worth` · `/warframe hub`",
    "wfnotify setup": "`/wfnotify configure`",
}


def discovery_12_block(*, compact: bool = False) -> str:
    """Markdown block for embeds."""
    if compact:
        return " · ".join(f"`/{p}`" for p, _ in DISCOVERY_12)
    lines = [f"• `/{path}` — {blurb}" for path, blurb in DISCOVERY_12]
    return "\n".join(lines)


def essentials_help_block() -> str:
    """Top section for /help and V2 help home."""
    return (
        "**Discovery 12 — start here:**\n\n"
        + discovery_12_block()
        + "\n\n_Use **Browse categories** below for everything else. "
        "Warframe reads: `/baro` · `/fissures` · `/warframe hub`. "
        "Economy: `/daily` · `/claim`._"
    )


def should_hide_from_member_discovery(path: str, *, is_mod: bool) -> bool:
    """True when a path should be omitted from member help/search lists."""
    if is_mod:
        return False
    normalized = (path or "").strip().lower()
    return normalized in DE_EMPHASIZED_PATHS
