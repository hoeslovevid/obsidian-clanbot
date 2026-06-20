"""Changelog pages for /whatsnew and /about.

``BOT_VERSION`` in ``core.config`` is the single source of truth for the
current release label. Curate bullets in ``CURRENT_RELEASE_*``; on each
release, archive the previous release into ``CHANGELOG_HISTORY`` with an
explicit version string (historical entries only).
"""
from __future__ import annotations

from core.config import BOT_CHANGELOG, BOT_VERSION

# Current release (version string comes from BOT_VERSION only).
CURRENT_RELEASE_DATE = "2026-06-20"
CURRENT_RELEASE_CHANGES: list[str] = [
    "**Fix** — `/warframe archon` refresh no longer double-defers (InteractionResponded)",
    "**Fix** — `/general setup` checklist button emoji (invalid 🜂 → 🖥️) no longer breaks wizard finish",
    "**Fix** — LFG private threads use `add_user`/`remove_user`; Join/Leave works with Components V2 layout",
]

# Older releases (newest first). Include ``version`` for each archived release.
CHANGELOG_HISTORY: list[dict] = [
    {
        "version": "2.0.9",
        "date": "2026-06-19",
        "changes": [
            "**Fix · Twitch** — validate streamers on add; warn when `/community twitch_setup` missing; live API status in `/community twitch_list`",
            "**Fix · Twitch** — token cache + batch Helix polling, API error logging, 3‑min poll; mod `diagnostics` / `force_check` on list",
        ],
    },
    {
        "version": "2.0.8",
        "date": "2026-06-19",
        "changes": [
            "**Fix** — release/update channel posts use `CURRENT_RELEASE_CHANGES` only (no archived v2.0 batch bullets)",
            "**Fix** — `/updates force_version_update` matches auto announce embed (no command-hash dump)",
        ],
    },
    {
        "version": "2.0.7",
        "date": "2026-06-19",
        "changes": [
            "**QoL · Today** — `/today` unified daily panel (daily, bounties, Baro, LFG, events, pet, onboarding)",
            "**QoL · Notify** — `/wfnotify why_dm` + `test_ping`; DM coalescing for Baro wishlist & price-watch alerts",
            "**QoL · LFG** — **Open squad VC** button; `/lfg preset_save|list|use`; host AFK + badge on posts",
            "**QoL · Social** — `/profile @user compare:True`; onboarding completion reward (+150 coins + badge)",
            "**QoL · UX** — time-aware `/menu` + continue-setup row; expired-panel recovery; weekly recap DM pref",
            "**QoL · Alerts** — Baro wishlist DM action hints; price-watch **Post trade** button; mention keyword expansion",
        ],
    },
    {
        "version": "2.0.6",
        "date": "2026-06-18",
        "changes": [
            "**Fix** — pinned console/world-state: stateless buttons + component_handler-only routing (no add_view double-dispatch)",
            "**Fix** — debug instrumentation removed from production paths",
        ],
    },
    {
        "version": "2.0.5",
        "date": "2026-06-18",
        "changes": [
            "**Fix** — pinned console V2 + world-state persistent buttons; `obsidian_console:*` router",
        ],
    },
    {
        "version": "2.0.4",
        "date": "2026-06-18",
        "changes": [
            "**Fix** — component_handler skip when interaction already done (partial; race with view callbacks)",
        ],
    },
    {
        "version": "2.0.3",
        "date": "2026-06-18",
        "changes": [
            "**Fix** — pinned console V2 + world-state persistent buttons; `obsidian_console:*` router",
        ],
    },
    {
        "version": "2.0.2",
        "date": "2026-06-18",
        "changes": [
            "**Fix** — message economy + automod pass `bot` explicitly (`Message` has no `.client` on deploy)",
            "**Fix** — `archon_check_loop` missing `fetch_archon_hunt_data` import",
        ],
    },
    {
        "version": "2.0.1",
        "date": "2026-06-18",
        "changes": [
            "**2.0.1 batch 16** — `bot/client.py`, `tasks/registry.py`, `handlers/discord_events.py`",
            "**Changelog** — `/whatsnew` lists all v2.0 batches 1–16",
        ],
    },
    {
        "version": "2.0.0",
        "date": "2026-06-18",
        "changes": [
            "**2.0.0 ship** — batches 11–15: handler/loop extractions, interaction router, runner, ~370-line app.py before batch 16",
            "**Loops extracted** — event, ticket, WF feed/check/live, economy, LFG, trading, community, integration, guild stats, VC, moderation",
            "**Handlers extracted** — message, voice, reactions, logs, tracking, member join/leave, guild join/leave, startup",
        ],
    },
    {
        "version": "2.0.0-beta",
        "date": "2026-06-18",
        "changes": [
            "**Beta batch 11** — starboard/reaction roles + message logging out of app.py; recurring events, ticket SLA, devstream, forum loops out of `_core`",
            "**Mod ops** — dashboard Command KPI + SLA target fields; `/admin usage_report` for low-usage prune candidates",
            "**Postgres preview** — `DB_BACKEND` + `DATABASE_URL` scaffold in `core/db.py` (v2.1 migration path)",
            "**Fix** — help category buttons use global command tree",
        ],
    },
    {
        "version": "2.0.0-alpha",
        "date": "2026-06-18",
        "changes": [
            "**Alpha batches 8–10** — economy/giveaway loop modules; member join/leave handlers; `check_command_tree.py` CI gate",
            "**Alpha batches 4–7** — wf_resolve on baro/status/hub/world_state; automod + VC panel handlers; event_loops; onboarding questline; /me chips",
            "**Alpha batches 2–3** — `core/wf_resolve.py`; Baro/WF notify loop split; message economy handler; global sync + health usage prune",
            "**Alpha batch 1** — multi-guild sync policy, Layout v2 hub surfaces, WF resolve layer foundation",
        ],
    },
    {
        "version": "1.99.14",
        "date": "2026-06-18",
        "changes": [
            "**S1** — `/lfg list` browse; guild footer preload; `embed_template` guild_id; empty states + reply sweep",
            "**S2** — `/start` in `/menu`; help path buttons (New/Warframe/Economy/Staff); onboarding progress on `/me`",
            "**S3** — LFG **Notify when open** waitlist DMs; WF footer on list embeds",
            "**S4** — `/admin audit view|export` with pagination; automod appeal staff dismiss/escalate; ticket SLA alerts; warn ladder on dashboard",
            "**S5** — all-bounties bonus; achievement X/Y on profile; command usage heatmap on KPIs; giveaway ending-soon DMs",
            "**S6** — `MAINTENANCE_UNTIL` countdown; feature toggle dependency warnings; mod ops line on `/status`; `record_command_usage` DB",
        ],
    },
    {
        "version": "1.99.13",
        "date": "2026-06-18",
        "changes": [
            "**R1** — `reply_helpers` on menu, claim hub, component_handler; branded VC/LFG/complaint button replies",
            "**R2** — `safe_dm` rollout (automod, welcome, onboarding, background tasks, wf recovery)",
            "**R3** — `merge_wf_footer` on hub + LFG embeds (invasions already wired)",
            "**R4** — `/admin audit` paginated viewer; audit on automod, ticket open, feature toggle; feedback modal pre-fills error code",
            "**R5** — `/start` onboarding guide; first-run nudges on bounties/preferences/achievements; `empty_state_embed` on audit",
            "**R6** — `/admin branding` custom guild footer (cached on embeds); `PRESENCE_MODE=start` for /start discovery",
        ],
    },
    {
        "version": "1.99.12",
        "date": "2026-06-18",
        "changes": [
            "**Q1** — `reply_helpers` rollout (views, LFG, events); WF `merge_wf_footer` on invasions; market context menu embed",
            "**Q2** — `/feedback` + `/admin feedback_setup`; error embed **Send feedback** button; `/about` privacy line",
            "**Q3** — `/menu` getting-started path; first-run nudges for price_watch/preferences/wfnotify/achievements",
            "**Q4** — audit on kick/ban/incident/mass roles; `/admin mod_kpi_setup`; dashboard maintenance/incident alerts",
            "**Q5** — `safe_dm` on digest + price-watch DMs; Presence intent for ticket auto-assign",
            "**Q6** — profile template `category` fix; branded market lookup embed; Layout v2 remains default",
        ],
    },
    {
        "version": "1.99.11",
        "date": "2026-06-18",
        "changes": [
            "**P1** — branded server-only / mods-only replies; unified WF unavailable copy via `wf_copy`",
            "**P2** — `/about` privacy & data; `/status` WF history + maintenance line; ticket open/close DM polish; `/menu` what's-new since last visit",
            "**P3** — audit log on warn + manage_coins; mod dashboard **Staff runbook** announcement drafts",
            "**P4** — pruned **Add to Suggestions** message context menu (5-cap compliance)",
            "**P5** — `MAINTENANCE_MODE` env gate (mods bypass); resilient ticket feedback DMs",
            "**P6** — `/profile_export` JSON download; weekly mod KPI digest loop (`mod_kpi_channel_id`)",
        ],
    },
    {
        "version": "1.99.10",
        "date": "2026-06-18",
        "changes": [
            "**Batch I** — first-run nudges on ticket/trade/LFG/event; `private_results` on `/cooldowns`; compact embeds on `/me`",
            "**Batch J** — hub **My fissures** button; `/claim` Layout v2; clickable favorites in `/help`; onboarding steps 4–6",
            "**Batch J** — right-click **Look up market price** on messages",
            "**Batch K** — price-watch DMs respect quiet hours + **Stop watching** button; digest **Market** section",
            "**Batch L** — LFG creator DM after 2h; trade listing 24h expiry warning; ticket **Reopen** within 24h",
            "**Batch M** — `/admin errors_export`; KPI 7-day ticket trend; notification panel compact/private toggles",
            "**Claim hub** — pets readiness line alongside daily/bounties/investment",
        ],
    },
    {
        "version": "1.99.9",
        "date": "2026-06-18",
        "changes": [
            "**Discovery** — `/menu` adds claim hub + cooldowns; `/recent` uses clickable mentions; `/search` uses live market items",
            "**Shortcuts** — top-level `/cooldowns`; `/claim` in shortcuts; per-feature first-run nudges (ticket, trade, LFG, events)",
            "**Warframe** — notify-when-back persists across restarts; invasion faction preset; Baro wishlist in channel embed",
            "**Market** — `/price_watch`, `/price_unwatch`, `/price_watches` DM when price target is hit",
            "**Events** — **Starting now** ping for GOING RSVPs; **Cancel event** button; **+15m late** (prior release)",
            "**Economy** — `/claim` action buttons (bounties, collect investment); pets in `/cooldowns` + digest",
            "**LFG** — auto-bump stale posts after 30 minutes with no replies",
            "**Moderation** — automod warn DMs; ticket rating optional comment; KPI satisfaction avg; errors persist to DB",
            "**Ops** — `/status` shows your prefs; startup headroom alert to bot-error log; streak reminder uses `/daily` mention",
            "**/me** — shows XP remaining to next level",
        ],
    },
    {
        "version": "1.99.5",
        "date": "2026-06-18",
        "changes": [
            "**Quiet hours** — set `/general preferences quiet_hours:22-7` to silence bot nudge DMs (daily reminder, digest) during your chosen local hours",
            "**Daily digest** — turn individual sections on/off with `/general preferences digest_section:… digest_state:…` (Economy, Events, Baro, Investments)",
        ],
    },
    {
        "version": "1.99.4",
        "date": "2026-06-18",
        "changes": [
            "**Privacy** — your `private_results` preference now also applies to `/economy balance` (others' view) and `/warframe baro`",
            "**Safety** — `/economy manage_coins` now asks for confirmation on large changes (≥100,000 coins)",
        ],
    },
    {
        "version": "1.99.3",
        "date": "2026-06-18",
        "changes": [
            "**`/economy daily`** — after claiming, a one-tap **Claim bounties** button grabs all completed bounties too",
            "**`/economy cooldowns`** — now also shows daily bounty status and reset time",
            "**Fix** — the bounties **Claim** button no longer skips the weekly LFG bounty",
            "**Fix** — the daily streak reminder now DMs users who are actually at risk (claimed yesterday, not today) instead of those who already claimed",
        ],
    },
    {
        "version": "1.99.2",
        "date": "2026-06-18",
        "changes": [
            "**Warframe** — the **🔔 Notify me when back** button now appears on every Warframe command when the API is down (`/warframe baro`, `status`, `hub`, `alerts`, `fissures`, `sortie`, `invasions`, `daily_ops`, `world_state`, `cycles`)",
            "**`/search`** — now also matches Warframe item names and links them to `/trading trade_price`",
            "**Warframe** — embeds show a subtle *data ~Nm old* note when served from cache",
        ],
    },
    {
        "version": "1.99.1",
        "date": "2026-06-16",
        "changes": [
            "**Docs** — the in-app changelog now updates with every commit, so `/whatsnew` always reflects the latest release",
        ],
    },
    {
        "version": "1.99.0",
        "date": "2026-06-16",
        "changes": [
            "**Reminders** — snooze buttons (+10m / +1h / Tomorrow) on delivery, one-tap **Undo** when you cancel, and timezone-aware time parsing",
            "**Discovery** — new `/search` command palette, clickable command mentions in suggestions and bot replies, and data-backed autocomplete (reminder IDs, schedule/poll durations)",
            "**`/economy cooldowns`** — daily, message-reward, and investment cooldowns in one view; the daily claim now links straight to bounties",
            "**Reliability** — global auto-defer prevents *This interaction failed*, DM fallback when the bot can't post a channel message, consistent component error replies, and cooldown messages now show the ready time",
            "**`/admin setup_status`** — shows configured vs missing channels with clickable setup commands",
            "**Preferences** — new `private_results` option keeps personal command output (e.g. `/profile`) private by default",
            "**Warframe** — anyone can refresh public data embeds; a **🔔 Notify me when back** button DMs you once the API recovers",
            "**Empty states** — friendlier list screens with clickable next-step commands (reminders, trades, badges)",
            "**Paginators** — First / Last and jump-to-page buttons with longer session timeouts",
        ],
    },
    {
        "version": "1.98.4",
        "date": "2026-06-10",
        "changes": [
            "**Fix** — `RefreshView` auto-defers before refresh callbacks; fixes broken **Update data** on `/warframe alerts`, baro, status, hub, and related commands",
            "**Fix** — removed duplicate defer calls in Warframe refresh handlers that could cause `InteractionResponded` errors",
        ],
    },
    {
        "version": "1.98.3",
        "date": "2026-06-10",
        "changes": [
            "**Perf** — stale-while-revalidate cache for `/warframe baro` (same pattern as fissures/alerts; ~4.5s waits eliminated)",
            "**Perf** — `warm_hot_warframe_endpoints` and `warframe_cache_warm_loop` now prefetch baro; hub/status benefit via shared cache",
        ],
    },
    {
        "version": "1.98.2",
        "date": "2026-06-10",
        "changes": [
            "**Fix** — `/general poll`, `/general reminder`, and `/moderation schedule` duration parsing on dateparser 1.2.x (`RELATIVE_BASE` via settings)",
        ],
    },
    {
        "version": "1.98.1",
        "date": "2026-06-07",
        "changes": [
            "**Perf** — stale-while-revalidate cache for `/fissures` and `/warframe alerts` (instant response while API refreshes in background)",
            "**Perf** — `warframe_cache_warm_loop` prefetches fissures/alerts every minute; warm on bot ready",
            "**Config** — `WARFRAME_CACHE_STALE_SECONDS` (default 300), `WARFRAME_CACHE_WARM_MINUTES` (default 1)",
        ],
    },
    {
        "version": "1.98.0",
        "date": "2026-06-06",
        "changes": [
            "**Cycles live panel** — `/wfnotify cycle_panel` posts a pinned, auto-updating embed (Cetus, Fortuna, Deimos + progress bars)",
            "**Panel-only mode** — guilds with a live panel skip cycle flip ping spam; background loop refreshes every few minutes",
            "**Notify setup** — `/wfnotify setup` hints to post the live panel after setting a cycles channel",
            "**Config** — `CYCLE_LIVE_UPDATE_MINUTES` (default 5) controls panel refresh interval",
        ],
    },
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


# Discord release posts must never include CHANGELOG_HISTORY — only this release's bullets.
MAX_RELEASE_ANNOUNCE_BULLETS = 12


def get_release_announce_changes() -> list[str]:
    """Bullets for channel/DM release posts (current release only, never archived history)."""
    if CURRENT_RELEASE_CHANGES:
        return list(CURRENT_RELEASE_CHANGES)
    summary = BOT_CHANGELOG.strip()
    if summary:
        return [summary]
    return []


def format_release_summary(changes: list[str], *, max_bullets: int = MAX_RELEASE_ANNOUNCE_BULLETS) -> str:
    """Format changelog bullets for a release embed description."""
    if not changes:
        return "The bot was updated. See **/whatsnew** for details."
    lines = [f"• {b}" for b in changes[:max_bullets]]
    summary = "\n".join(lines)
    if len(changes) > max_bullets:
        summary += f"\n-# …and {len(changes) - max_bullets} more in /whatsnew"
    return summary


def resolve_current_release() -> dict:
    """Current release entry; ``version`` is always ``BOT_VERSION``."""
    changes = get_release_announce_changes()
    if not changes:
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
