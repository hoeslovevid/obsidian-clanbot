"""Dashboard feature catalog — toggleable modules and always-on bot capabilities."""
from __future__ import annotations

from typing import Any

from core.utils import TOGGLEABLE_FEATURES

# Groups appear in this order on the dashboard Features tab.
FEATURE_GROUP_ORDER: tuple[str, ...] = (
    "Core & Voice",
    "Community",
    "Warframe",
    "Economy",
    "Moderation",
    "Music",
    "Admin & Staff",
)

# ``id`` matches TOGGLEABLE_FEATURES keys when ``toggleable`` is True.
FEATURE_CATALOG: tuple[dict[str, Any], ...] = (
    # Core & Voice
    {
        "id": "voice",
        "group": "Core & Voice",
        "label": "Voice channels",
        "desc": "Join-to-create temp VCs, control panels, rename, limit, and lock.",
        "toggleable": False,
        "hint": "Configure in Setup tab",
    },
    {
        "id": "complaints",
        "group": "Core & Voice",
        "label": "Complaints & docket",
        "desc": "Inheritor docket channel, case threading, and complaint logs.",
        "toggleable": False,
        "hint": "Configure in Setup tab",
    },
    # Community
    {
        "id": "tickets",
        "group": "Community",
        "label": "Support tickets",
        "desc": "Ticket system with SLA tracking, transcripts, and staff inbox.",
        "toggleable": False,
        "hint": "Use /community ticket in Discord",
    },
    {
        "id": "suggestions",
        "group": "Community",
        "label": "Suggestions",
        "desc": "Member suggestion posts with review workflow.",
        "toggleable": False,
        "hint": "Configure in Setup tab",
    },
    {
        "id": "applications",
        "group": "Community",
        "label": "Applications",
        "desc": "Clan/application forms with approve/deny flow.",
        "toggleable": False,
        "hint": "Use /admin applications in Discord",
    },
    {
        "id": "lfg",
        "group": "Community",
        "label": "LFG squads",
        "desc": "Looking-for-group posts with fill tracking.",
        "toggleable": True,
    },
    {
        "id": "polls",
        "group": "Community",
        "label": "Polls",
        "desc": "Server polls with live result updates.",
        "toggleable": True,
    },
    {
        "id": "events",
        "group": "Community",
        "label": "Events & RSVP",
        "desc": "Scheduled events, natural-language times, and reminders.",
        "toggleable": True,
    },
    {
        "id": "giveaways",
        "group": "Community",
        "label": "Giveaways",
        "desc": "Create giveaways with entry buttons and winner selection.",
        "toggleable": False,
        "hint": "Manage in Giveaways tab",
    },
    {
        "id": "reminders",
        "group": "Community",
        "label": "Reminders",
        "desc": "Personal and server reminders with scheduling.",
        "toggleable": False,
        "hint": "Use /general remind in Discord",
    },
    {
        "id": "reputation",
        "group": "Community",
        "label": "Reputation",
        "desc": "Member rep scores and leaderboards.",
        "toggleable": False,
        "hint": "Use /community rep in Discord",
    },
    {
        "id": "twitch",
        "group": "Community",
        "label": "Twitch notifications",
        "desc": "Stream go-live alerts for watched channels.",
        "toggleable": False,
        "hint": "Use /community twitch_add in Discord",
    },
    {
        "id": "starboard",
        "group": "Community",
        "label": "Starboard",
        "desc": "Highlight popular messages in a dedicated channel.",
        "toggleable": False,
        "hint": "Use /mod starboard_setup in Discord",
    },
    # Warframe
    {
        "id": "warframe",
        "group": "Warframe",
        "label": "Baro, cycles & missions",
        "desc": "Baro Ki'Teer, open-world cycles, sortie, fissures, and drop tables.",
        "toggleable": False,
        "hint": "See Warframe tab",
    },
    {
        "id": "notifications",
        "group": "Warframe",
        "label": "WF alerts & feeds",
        "desc": "Alert pings, forum, YouTube, and devstream notification feeds.",
        "toggleable": True,
        "hint": "Configure feeds in Setup tab",
    },
    {
        "id": "trade",
        "group": "Warframe",
        "label": "Trading & market",
        "desc": "Trading post, market price lookup, and WM search.",
        "toggleable": True,
    },
    {
        "id": "wf_account",
        "group": "Warframe",
        "label": "Account linking",
        "desc": "Link Discord to Warframe/Steam for playtime roles.",
        "toggleable": False,
        "hint": "Use /warframe link in Discord",
    },
    # Economy
    {
        "id": "economy_passive",
        "group": "Economy",
        "label": "Passive economy",
        "desc": "Background coin and XP gains from activity.",
        "toggleable": True,
    },
    {
        "id": "economy",
        "group": "Economy",
        "label": "Coins & wallet",
        "desc": "Daily rewards, transfers, stash, and prestige.",
        "toggleable": False,
        "hint": "Use /economy commands in Discord",
    },
    {
        "id": "xp",
        "group": "Economy",
        "label": "XP & levels",
        "desc": "Activity XP, level-ups, and leaderboards.",
        "toggleable": False,
        "hint": "Configure level-up channel in Setup",
    },
    {
        "id": "store",
        "group": "Economy",
        "label": "Shop",
        "desc": "Server shop items and purchases.",
        "toggleable": False,
        "hint": "Use /store in Discord",
    },
    {
        "id": "pets",
        "group": "Economy",
        "label": "Pets",
        "desc": "Pet collection, care, battles, and shop.",
        "toggleable": True,
    },
    {
        "id": "gambling",
        "group": "Economy",
        "label": "Gambling",
        "desc": "Casino games and betting commands.",
        "toggleable": True,
    },
    {
        "id": "bounties",
        "group": "Economy",
        "label": "Bounties & achievements",
        "desc": "Weekly bounties, achievements, and profile badges.",
        "toggleable": False,
        "hint": "Use /economy bounties in Discord",
    },
    # Moderation
    {
        "id": "mod_tools",
        "group": "Moderation",
        "label": "Moderation tools",
        "desc": "Purge, snipe, lock, slowmode, and scheduled actions.",
        "toggleable": False,
        "hint": "Use /mod commands in Discord",
    },
    {
        "id": "warnings",
        "group": "Moderation",
        "label": "Warnings & notes",
        "desc": "Warn members, templates, and mod notes.",
        "toggleable": False,
        "hint": "Use /warn in Discord",
    },
    {
        "id": "automod",
        "group": "Moderation",
        "label": "AutoMod",
        "desc": "Spam, caps, links, mentions, and raid protection.",
        "toggleable": False,
        "hint": "Use /automod in Discord",
    },
    {
        "id": "logging",
        "group": "Moderation",
        "label": "Audit & logging",
        "desc": "Mod audit log, bot errors, and ticket transcripts.",
        "toggleable": False,
        "hint": "Configure in Setup tab",
    },
    {
        "id": "roletools",
        "group": "Moderation",
        "label": "Role tools",
        "desc": "Reaction roles, level roles, and role menus.",
        "toggleable": False,
        "hint": "Use /roletools in Discord",
    },
    # Music
    {
        "id": "music",
        "group": "Music",
        "label": "Music playback",
        "desc": "Play, pause, skip, and queue music in voice.",
        "toggleable": True,
    },
    # Admin & Staff
    {
        "id": "admin",
        "group": "Admin & Staff",
        "label": "Admin utilities",
        "desc": "Backups, KPIs, incident mode, and server dashboards.",
        "toggleable": False,
        "hint": "Use /admin in Discord",
    },
    {
        "id": "staff",
        "group": "Admin & Staff",
        "label": "Staff tools",
        "desc": "Command sync, webhooks, and analytics utilities.",
        "toggleable": False,
        "hint": "Use /staff in Discord",
    },
    {
        "id": "updates",
        "group": "Admin & Staff",
        "label": "Update log",
        "desc": "Bot version announcements and changelog channel.",
        "toggleable": False,
        "hint": "Configure changelog in Setup",
    },
)


def build_features_payload(toggle_states: dict[str, bool]) -> list[dict[str, Any]]:
    """Merge catalog entries with live on/off state for toggleable features."""
    items: list[dict[str, Any]] = []
    for entry in FEATURE_CATALOG:
        row = {
            "id": entry["id"],
            "group": entry["group"],
            "label": entry["label"],
            "desc": entry["desc"],
            "toggleable": bool(entry.get("toggleable")),
            "hint": entry.get("hint"),
        }
        if row["toggleable"]:
            row["enabled"] = toggle_states.get(entry["id"], True)
        items.append(row)
    return items
