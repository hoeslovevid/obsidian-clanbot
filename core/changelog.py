"""Changelog pages for /whatsnew and /about.

``BOT_VERSION`` in ``core.config`` is the single source of truth for the
current release label. Curate bullets in ``CURRENT_RELEASE_*``; on each
release, archive the previous release into ``CHANGELOG_HISTORY`` with an
explicit version string (historical entries only).
"""
from __future__ import annotations

from core.config import BOT_CHANGELOG, BOT_VERSION

# Current release (version string comes from BOT_VERSION only).
CURRENT_RELEASE_DATE = "2026-06-04"
CURRENT_RELEASE_CHANGES: list[str] = [
    "**Embeds** — showcase templates + contextual footers on giveaways, gambling, polls, warn, and community entry points",
    "**Live edits** — `safe_message_edit` on poll results, giveaway entry counts, and LFG fill updates",
    "**Tickets** — status chips on activity, mod quick-reply buttons (Looking into it / Need more info / Resolved)",
    "**Discovery** — favorites surface in `/help` and `/menu`; onboarding 3-step flow (timezone → platform → menu)",
    "**Trust** — presence shows `BOT_VERSION` + Warframe health; error embeds hint `/ticket` with error code",
    "**Warframe** — platform footer notes on baro, status, and related commands",
    "**V2** — `HELP_LAYOUT_V2` default; fixed warning template color bug in `embed_template`",
    "**Ops** — incident mode embed shows auto-disable timestamp; embed asset env docs for Railway",
]

# Older releases (newest first). Include ``version`` for each archived release.
CHANGELOG_HISTORY: list[dict] = [
    {
        "version": "1.91.2",
        "date": "2026-06-04",
        "changes": [
            "**Fix** — VC panel edits coalesced per guild with skip-if-unchanged (fewer Discord 429 PATCH warnings)",
            "**Fix** — `safe_message_edit` paces channel edits; Baro live loop 5m + skip redundant embed updates",
            "**Config** — default `VC_PANEL_UPDATE_DEBOUNCE_SECONDS` raised to 8",
        ],
    },
    {
        "version": "1.91.1",
        "date": "2026-06-04",
        "changes": [
            "**Fix** — deploy posts one showcase release embed per `BOT_VERSION` (no duplicate simple update embeds)",
            "**Release** — changelog text from `core/changelog.py` only; stale `BOT_CHANGELOG` env no longer drives channel posts",
        ],
    },
    {
        "version": "1.91.0",
        "date": "2026-06-04",
        "changes": [
            "**Discovery** — `/search` and `/help` hide guild-disabled features; mod-only groups hidden from members",
            "**Menu** — favorites-first picker with showcase empty-state hint for `/favorite_add`",
            "**Warframe notify** — `/wfnotify configure` wizard (recommended); panel + legacy subcommands unchanged",
            "**Status** — clear degraded state when Warframe API/cache is unhealthy",
            "**Embeds** — showcase templates on bounties, gambling, trade price, giveaways; ticket status chips + SLA hint",
            "**Ops** — command-tree headroom warnings at load; see `docs/COMMAND_BUDGET.md`",
        ],
    },
    {
        "version": "1.90.0",
        "date": "2026-06-04",
        "changes": [
            "**Release** — version label aligned with Railway `BOT_VERSION` deploy tracking",
            "**Versioning** — `/about`, `/whatsnew`, `/status`, release announce, and update logs all use `BOT_VERSION`",
            "**Deploy** — set `BOT_VERSION` on Railway when shipping; keep `core/config.py` default in sync",
        ],
    },
    {
        "version": "1.7.1",
        "date": "2026-06-04",
        "changes": [
            "**Fix** — slash-command sync: `/general` exceeded Discord's 25-subcommand cap after v1.7.0",
            "**Commands** — `/status` is top-level only; Clan Console hub is `/admin console` (mods)",
        ],
    },
    {
        "version": "1.7.0",
        "date": "2026-06-04",
        "changes": [
            "**Clan Console** — `/admin console` posts a pinned hub (Menu, Daily, Status, Ticket, Help)",
            "**Status** — `/status` shows version, latency, and Warframe API health hint",
            "**Embeds** — contextual footers, showcase templates on economy/community commands",
            "**Brand** — `EMBED_LOGO_URL` footer/thumbnail; `EMBED_BANNER_URL` documented for Railway",
            "**Confirm UX** — unified warning-style confirms for transfer, purge, and ticket close",
            "**Release posts** — auto-announce `BOT_VERSION` to `changelog_channel_id` when configured",
            "**V2 pilots** — optional LayoutView splash for `/profile` and `/economy wallet` (`HELP_LAYOUT_V2`)",
            "**Mentions** — @bot replies use showcase embeds; incident mode copy improved",
            "**Onboarding** — welcome DM uses showcase template (3-step button flow unchanged)",
        ],
    },
    {
        "version": "1.6.0",
        "date": "2026-06-04",
        "changes": [
            "**Embeds** — unified `embed_template` / showcase styling across commands",
            "**Banner** — `EMBED_BANNER_URL` env override; default GitHub raw `obsidian_embed_banner.png`",
            "**Caches** — shared cache helpers and warmer API paths; fewer redundant fetches",
            "**Startup** — slash sync only when `BOT_VERSION` changes (faster restarts)",
            "**Digest 2.0** — richer mod digest loop and dashboard/health observability",
            "**Menu V2** — categorized `/menu` with optional media-gallery banner (`HELP_LAYOUT_V2`)",
            "**Help V2** — searchable help, link rows, and clearer command discovery",
            "**Preferences** — DM toggles plus per-user Warframe platform preference",
            "**Phase 5 UX** — link rows on showcase embeds; `menu_layout` command pilots",
            "**Tickets** — ticket panel/control embeds use dedicated ticket styling",
            "**Warframe** — Baro/status polish and platform-aware world-state lookups",
            "**Fix** — `get_incident_mode` imported from `incident_mode` (health/dashboard)",
            "**Fix** — VC panel embed updates debounced (`VC_PANEL_UPDATE_DEBOUNCE_SECONDS`)",
            "**Fix** — slow-command tracking without setting attrs on frozen `Interaction`",
            "**Fix** — `server_about` LinkRowView import on deploy",
            "**Fix** — Help V2 no longer mixes link rows with classic `HelpSelectView`",
        ],
    },
    {
        "version": "1.5.0",
        "date": "2026-05-14",
        "changes": [
            "/whatsnew changelog viewer with DM subscription",
            "Mod Context popup (right-click → all mod tools in one ephemeral embed)",
            "/mod purge: filter by user/contains/older_than/from_bots + confirm step",
            "/warframe vc: host transfer command and panel button hand-off",
            "VC presets: save/apply/list/delete favourite VC configs",
            "Idle VC revival vote: closed VCs can be brought back with 3 clicks",
            "Live poll results bar — embed updates as votes come in",
            "Cycle-aware LFG nudges (Plains/Vallis/Cambion timing)",
            "Saved warn reason templates with autocomplete on /mod warn",
            "Pet evolution stages (Baby → Young → Adult → Elder)",
            "/preferences unsubscribe_all and subscribe_all DM shortcuts",
            "Right-click 'Explain command' context menu",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-05-10",
        "changes": [
            "Earlier QoL batch — investments DMs, profile polish, cycle notify",
            "Mod stats dashboard refresh button",
            "Trading post and Warframe market refinements",
        ],
    },
]


def resolve_current_release() -> dict:
    """Current release entry; ``version`` is always ``BOT_VERSION``."""
    changes: list[str] = list(CURRENT_RELEASE_CHANGES)
    if not changes:
        summary = BOT_CHANGELOG.strip()
        if summary:
            changes = [summary]
        else:
            for entry in CHANGELOG_HISTORY:
                if str(entry.get("version", "")) == BOT_VERSION:
                    changes = list(entry.get("changes") or [])
                    break
    return {
        "version": BOT_VERSION,
        "date": CURRENT_RELEASE_DATE,
        "changes": changes,
    }


def get_latest_changelog_entry() -> dict:
    """Latest release for /about and similar previews."""
    return resolve_current_release()


def get_changelog_pages(*, max_pages: int = 5) -> list[dict]:
    """Paginated changelog (newest first), capped at ``max_pages``."""
    pages = [resolve_current_release(), *CHANGELOG_HISTORY]
    return pages[:max_pages]
