"""Changelog pages for /whatsnew and /about.

``BOT_VERSION`` in ``core.config`` is the single source of truth for the
current release label. Curate bullets in ``CURRENT_RELEASE_*``; on each
release, archive the previous release into ``CHANGELOG_HISTORY`` with an
explicit version string (historical entries only).
"""
from __future__ import annotations

from core.config import BOT_CHANGELOG, BOT_VERSION

# Current release (version string comes from BOT_VERSION only).
CURRENT_RELEASE_DATE = "2026-06-06"
CURRENT_RELEASE_CHANGES: list[str] = [
    "**Cycles live panel** — `/wfnotify cycle_panel` posts a pinned, auto-updating embed (Cetus, Fortuna, Deimos + progress bars)",
    "**Panel-only mode** — guilds with a live panel skip cycle flip ping spam; background loop refreshes every few minutes",
    "**Notify setup** — `/wfnotify setup` hints to post the live panel after setting a cycles channel",
    "**Config** — `CYCLE_LIVE_UPDATE_MINUTES` (default 5) controls panel refresh interval",
]

# Older releases (newest first). Include ``version`` for each archived release.
CHANGELOG_HISTORY: list[dict] = [
    {
        "version": "1.97.0",
        "date": "2026-06-06",
        "changes": [
            "**V2 Batch 1** — `/help` category browse, `/menu` picker, `/profile` full card, `/economy wallet` single LayoutView + Refresh",
            "**V2 Batch 2** — `/status`, `/whatsnew`, `/search`, `/daily`, `/me`, `/ticket` open, `/warframe hub` refreshable layouts",
            "**V2 Batch 3** — `/admin console`, `/onboarding`, `/about`, `/recent`, `/favorites`, `/preferences`, `/wfnotify setup` opening screen",
            "**V2 Batch 4** — Music Now Playing panel, LFG post buttons, ticket open confirmation on LayoutView ActionRows",
            "**V2 Batch 5** — `/admin dashboard` refresh snapshot (full dashboard stays classic); heavy mod tools deferred",
            "**Shared** — `core/layout_v2.py` helpers; `HELP_LAYOUT_V2` gate with classic embed fallback on all surfaces",
        ],
    },
    {
        "version": "1.96.0",
        "date": "2026-06-06",
        "changes": [
            "**Temp VC music** — Auto-stop when temp VC closes; `/vc transfer` hands off DJ control; optional temp-VC-only mode",
            "**Squad radio** — LFG posts accept optional playlist/search; **Start squad radio** button queues music in your VC",
            "**Event soundtracks** — Optional `soundtrack` on `/events event_create`; auto-plays at reminder/go-live when bot is in event VC",
            "**VC music bonus** — Extra XP/coins while music plays in your VC (`MUSIC_VC_BONUS_MULTIPLIER`, guild override)",
            "**Hub & Console** — `/warframe hub` shows listeners in VC; Clan Console embed includes now-playing status",
            "**Quieter mode** — LFG radio and event soundtrack announcements respect guild quieter mode",
            "**Config** — `/music config` adds temp VC only, event VC, soundtrack toggle, and bonus multiplier",
        ],
    },
    {
        "version": "1.95.0",
        "date": "2026-06-06",
        "changes": [
            "**Music Path A** — Player logic in `core/music_player.py`; stop/pause/skip/queue/volume register at bot load (bug fix)",
            "**Now Playing panel** — Showcase embed with Skip / Pause / Queue buttons; `safe_message_edit` updates; quieter mode reduces channel spam",
            "**Auto-leave** — Disconnects when VC empty (`MUSIC_AUTO_LEAVE_MINUTES`, default 5)",
            "**DJ & vote-skip** — `music_dj_role_id` guild setting; `/music voteskip` + panel skip for listeners",
            "**Queue tools** — `/music shuffle`, `/music loop`, `/music remove`, `/music clear`, `/music config`",
            "**Channel lock** — Optional `music_channel_id`; queue restore on startup (no auto voice reconnect)",
            "**Playlists** — YouTube playlists up to 50 tracks; SoundCloud/direct URL support with clearer errors",
            "**Feature toggle** — `music` in `/admin features`; hidden from `/search` when disabled",
            "**Deploy** — `ffmpeg` added to Railpack `deploy.aptPackages` for Railway voice playback",
        ],
    },
    {
        "version": "1.94.0",
        "date": "2026-06-06",
        "changes": [
            "**Warframe hub** — Daily Ops, relic planner, Baro wishlist overlap, Twitch line, platform-aware fetches",
            "**Weekly recap** — Optional Sunday channel post (`recap_channel_id` guild setting)",
            "**LFG** — Role tags, scheduled squads + 15m reminder, interest subscribe (`/lfg subscribe`), thread summary on expiry",
            "**Tickets** — Transcript showcase embed with SLA timings; complaint → ticket escalation button",
            "**Clan ops** — Dojo public board, mentorship pairing (`/admin mentorship`), officer live board on dashboard",
            "**Profile** — IGN verification badge, Steam playtime, live server-goal multiplier hint",
            "**Economy** — Weekly LFG bounty; shop rotation week hint; pet gift already available via `/pets gift`",
            "**Applications** — Pipeline stage buttons (Interview → Trial → Accept); incident post-summary embed",
            "**Build** — Weapon/frame autocomplete + Overframe deep links",
            "**Presence** — `PRESENCE_MODE` env: default, menu, degraded, event",
        ],
    },
    {
        "version": "1.93.0",
        "date": "2026-06-06",
        "changes": [
            "**Batch A** — profile/shop/pets/mod context use showcase templates; View Profile matches `/profile` card",
            "**Batch B** — V2 LayoutView default for help, menu, profile, wallet; mobile-friendly density + contextual footers",
            "**Batch C** — `/warframe hub` refreshable hub; `/help` leads with 8 member essentials then category browse",
            "**Batch D** — Warn absorbed into Mod Context; **Open Ticket About User** context menu (5-cap preserved)",
            "**Batch E** — setup wizard adds changelog channel + console/feature-toggle next steps; error **Copy code** button",
            "**Batch F** — `CATEGORY_THUMBNAIL_OVERRIDES` / `EMBED_THUMB_*` env docs; banner via `EMBED_BANNER_URL` on Railway",
        ],
    },
    {
        "version": "1.92.0",
        "date": "2026-06-04",
        "changes": [
            "**Embeds** — showcase templates + contextual footers on giveaways, gambling, polls, warn, and community entry points",
            "**Live edits** — `safe_message_edit` on poll results, giveaway entry counts, and LFG fill updates",
            "**Tickets** — status chips on activity, mod quick-reply buttons (Looking into it / Need more info / Resolved)",
            "**Discovery** — favorites surface in `/help` and `/menu`; onboarding 3-step flow (timezone → platform → menu)",
            "**Trust** — presence shows `BOT_VERSION` + Warframe health; error embeds hint `/ticket` with error code",
            "**Warframe** — platform footer notes on baro, status, and related commands",
            "**V2** — `HELP_LAYOUT_V2` default; fixed warning template color bug in `embed_template`",
            "**Ops** — incident mode embed shows auto-disable timestamp; embed asset env docs for Railway",
        ],
    },
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
