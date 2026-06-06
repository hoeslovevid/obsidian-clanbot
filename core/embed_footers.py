"""Contextual embed footer strings — prefer these over generic /help hints."""
from __future__ import annotations

from typing import Optional

# Keys map to command surfaces or categories (economy, warframe, etc.).
FOOTERS: dict[str, str] = {
    "default": "Use /help for the full command list",
    "help": "Use /search to find commands · /menu for quick picks",
    "economy_daily": "Streak bonuses at 7d · 14d · 30d · /economy wallet for overview",
    "economy_wallet": "Tap Refresh to update · /economy transactions for history",
    "economy_leaderboard": "/economy daily to climb · /profile for your stats",
    "economy_transfer": "Large transfers need confirmation · balances update instantly",
    "profile": "/achievements for badges · /general set_bio to personalize",
    "me": "/daily · /wallet · /preferences — your quick toolkit",
    "warframe_status": "Tap Update data to refresh · platform follows /preferences",
    "warframe_baro": "Warframe Market link below · /warframe status for everything",
    "warframe_notify": "Recommended: /wfnotify configure · legacy per-type commands still work",
    "trading_price": "Tap Refresh to update · platform follows /preferences",
    "community_events": "RSVP on the ops board · reminders go out before start",
    "community_lfg": "Join with the buttons · thread opens for your squad",
    "community_giveaway": "/giveaways giveaway_list · enter before the timer ends",
    "community_ticket": "/ticket for support · staff see this channel",
    "community_ticket_open": "Staff will reply in your ticket channel · add details anytime",
    "community_rsvp": "RSVP on the ops board · reminders go out before start",
    "economy_transfer_success": "Balances updated · /economy transactions for history",
    "warframe_hub": "/warframe hub to refresh · /wfnotify configure for alerts",
    "moderation_purge": "Mod only · transcript saved when archive is on",
    "moderation_warn": "/warn list to review · templates speed up common reasons",
    "console_hub": "Pinned hub · /menu · /daily · /warframe status · /ticket",
    "status": "v{version} · /whatsnew for release notes · /help if something looks off",
    "onboarding": "Finish any step anytime with /onboarding resume",
    "mention": "/help · /menu · /daily · /warframe status",
}


def footer_for(key: str, *, default: Optional[str] = None, **fmt: object) -> str:
    """Return a footer string; ``fmt`` substitutes into the template (e.g. version=)."""
    raw = FOOTERS.get(key) or default or FOOTERS["default"]
    if fmt:
        try:
            return raw.format(**fmt)
        except (KeyError, ValueError):
            return raw
    return raw
