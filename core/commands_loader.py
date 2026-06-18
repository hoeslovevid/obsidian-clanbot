"""
Command loader - loads and registers all slash commands.
Extracted from bot.py for cleaner organization and faster debugging.
"""
import importlib
import discord  # type: ignore
from discord import app_commands  # type: ignore


def load_all_commands(bot):
    """Load all command modules and organize them into groups."""
    # Create command groups (Discord limit: 25 commands per group)
    economy_group = app_commands.Group(name="economy", description="💰 Coins, daily, gambling, stash, invest, prestige")
    warframe_group = app_commands.Group(name="warframe", description="🎮 Baro, cycles, alerts, builds, and clan info")
    moderation_group = app_commands.Group(name="mod", description="🛡️ Purge, snipe, schedule, raid shield, and core moderation")
    general_group = app_commands.Group(name="general", description="📋 Help, about, setup, profiles, and server tools")
    tools_group = app_commands.Group(name="tools", description="🔧 Coinflip and utilities")
    community_group = app_commands.Group(name="community", description="👥 Events, tickets, suggestions, applications, and community features")
    music_group = app_commands.Group(name="music", description="🎵 Play, pause, skip, and manage music in voice channels")
    updates_group = app_commands.Group(name="updates", description="📝 Update log and version management")
    giveaways_group = app_commands.Group(name="giveaways", description="🎁 Create, manage, and enter giveaways")
    trading_group = app_commands.Group(name="trading", description="💼 Trading post, prices, and Warframe market lookup")
    vc_group = app_commands.Group(name="vc", description="🎙️ Temp voice channel tools (transfer, presets)")
    # Top-level groups split out of /mod to keep its serialized payload under Discord's 8000-char cap
    automod_group = app_commands.Group(name="automod", description="🤖 Auto-moderation (spam, caps, links, mentions)")
    warn_group = app_commands.Group(name="warn", description="🛑 Warnings, templates, and moderator notes")
    roletools_group = app_commands.Group(name="roletools", description="🎭 Reaction roles, level roles, role menus, mass assign")
    admin_group = app_commands.Group(name="admin", description="🗄️ Server admin: retention, incidents, KPIs, applications, data export")
    # Promoted from economy/warframe/community subgroups for the same 8000-char cap reason
    pets_group = app_commands.Group(name="pets", description="🐾 Pet shop, care, battles, evolutions, and marketplace")
    store_group = app_commands.Group(name="store", description="🛒 Browse and buy server shop items")
    xp_group = app_commands.Group(name="xp", description="✨ XP check, leaderboard, settings, and events")
    wfnotify_group = app_commands.Group(
        name="wfnotify",
        description="🔔 Warframe alerts — /wfnotify configure (recommended) or per-type commands",
    )
    lfg_group = app_commands.Group(name="lfg", description="🤝 Warframe LFG: post and browse looking-for-group ads")
    events_group = app_commands.Group(name="events", description="📅 Server events: create, browse, and recurring schedules")

    # NOTE: economy.pets/store/xp and warframe.notify are NOT added as subgroups any more —
    # they each became their own top-level group above to fit Discord's 8000-byte limit.

    # Moderation subgroup that is small enough to keep inside /mod
    mod_channel = app_commands.Group(name="channel", description="Lock and unlock channels")
    moderation_group.add_command(mod_channel)

    # Aliases used by group_mapping below — back-compat names for the promoted subgroups
    mod_warn = warn_group
    mod_automod = automod_group
    mod_role_tools = roletools_group
    economy_pets = pets_group
    economy_shop = store_group
    economy_xp = xp_group
    warframe_notify = wfnotify_group

    bot.tree.add_command(economy_group)
    bot.tree.add_command(warframe_group)
    bot.tree.add_command(moderation_group)
    bot.tree.add_command(general_group)
    bot.tree.add_command(tools_group)
    bot.tree.add_command(community_group)
    bot.tree.add_command(music_group)
    bot.tree.add_command(updates_group)
    bot.tree.add_command(giveaways_group)
    bot.tree.add_command(trading_group)
    bot.tree.add_command(vc_group)
    bot.tree.add_command(automod_group)
    bot.tree.add_command(warn_group)
    bot.tree.add_command(roletools_group)
    bot.tree.add_command(admin_group)
    bot.tree.add_command(pets_group)
    bot.tree.add_command(store_group)
    bot.tree.add_command(xp_group)
    bot.tree.add_command(wfnotify_group)
    bot.tree.add_command(lfg_group)
    bot.tree.add_command(events_group)

    command_modules = [
        "commands.general.help",
        "commands.general.links",
        "commands.general.about",
        "commands.general.ping",
        "commands.general.invite",
        "commands.general.member_count",
        "commands.general.setup_obsidian",
        "commands.general.setup_docket",
        "commands.general.setup_status",
        "commands.general.sync_commands",
        "commands.general.welcome_setup",
        "commands.general.milestones",
        "commands.general.achievements",
        "commands.general.webhooks",
        "commands.general.welcome_recommend",
        "commands.general.rules",
        "commands.general.polls",
        "commands.general.reminder",
        "commands.general.preferences",
        "commands.general.onboarding",
        "commands.general.milestones_next",
        "commands.general.menu",
        "commands.general.search",
        "commands.general.profile_export",
        "commands.general.recent",
        "commands.general.whatsnew",
        "commands.general.reputation",
        "commands.general.twitch",
        "commands.music.music",
        "commands.events.event_create",
        "commands.complaints.submit_complaint",
        "commands.complaints.request_help",
        "commands.tickets.ticket",
        "commands.suggestions.suggest",
        "commands.suggestions.manage_suggestions",
        "commands.applications.application",
        "commands.applications.application_setup",
        "commands.applications.manage_applications",
        "commands.updates.update_log",
        "commands.updates.update_log_setup",
        "commands.updates.force_version_update",
        "commands.trading.trade",
        "commands.trading.trade_price",
        "commands.trading.trade_search",
        "commands.trading.trade_list",
        "commands.trading.trade_setup",
        "commands.trading.price_watch",
        "commands.moderation.purge",
        "commands.moderation.reaction_roles",
        "commands.moderation.automod_setup",
        "commands.moderation.automod_status",
        "commands.moderation.roles",
        "commands.moderation.level_roles",
        "commands.moderation.logging",
        "commands.moderation.snipe",
        "commands.moderation.warn",
        "commands.moderation.mod_notes",
        "commands.moderation.starboard",
        "commands.moderation.role_menu",
        "commands.moderation.role_panel",
        "commands.moderation.backup",
        "commands.moderation.data_retention",
        "commands.moderation.incident_mode",
        "commands.moderation.kpis",
        "commands.moderation.health",
        "commands.moderation.raid_protection",
        "commands.moderation.embed_builder",
        "commands.moderation.lock",
        "commands.moderation.schedule",
        "commands.moderation.dashboard",
        "commands.moderation.mentorship",
        "commands.moderation.feature_toggle",
        "commands.moderation.inactive_role",
        "commands.moderation.ticket_config",
        "commands.economy.balance",
        "commands.economy.wallet",
        "commands.economy.config",
        "commands.economy.transactions",
        "commands.economy.leaderboard",
        "commands.economy.daily",
        "commands.economy.cooldowns",
        "commands.economy.bounties",
        "commands.economy.xp",
        "commands.economy.xpleaderboard",
        "commands.economy.add_coins",
        "commands.economy.manage_xp",
        "commands.economy.xp_settings",
        "commands.economy.stash",
        "commands.economy.invest",
        "commands.economy.shop",
        "commands.economy.shop_manage",
        "commands.economy.gambling",
        "commands.economy.pets",
        "commands.economy.prestige",
        "commands.warframe.baro",
        "commands.warframe.world_state",
        "commands.warframe.baro_notify",
        "commands.warframe.lfg",
        "commands.warframe.lfg_list",
        "commands.warframe.cycles",
        "commands.warframe.cycle_notify",
        "commands.warframe.cycle_panel",
        "commands.warframe.invasions",
        "commands.warframe.invasion_notify",
        "commands.warframe.archon",
        "commands.warframe.archon_notify",
        "commands.warframe.warframe_event_notify",
        "commands.warframe.resource",
        "commands.warframe.duviri",
        "commands.warframe.alerts",
        "commands.warframe.alerts_notify",
        "commands.warframe.fissures",
        "commands.warframe.sortie",
        "commands.warframe.daily_ops",
        "commands.warframe.status",
        "commands.warframe.hub",
        "commands.warframe.devstream_notify",
        "commands.warframe.forum_notify",
        "commands.warframe.youtube_notify",
        "commands.warframe.tennogen_notify",
        "commands.warframe.notify_status",
        "commands.warframe.dojo",
        "commands.warframe.warframe_link",
        "commands.warframe.warframe_roles",
        "commands.warframe.subscribe",
        "commands.warframe.notify_setup",
        "commands.warframe.notify_panel",
        "commands.activity.activity",
        "commands.activity.activity_leaderboard",
        "commands.giveaways.giveaway",
        "commands.giveaways.giveaway_end",
        "commands.giveaways.giveaway_list",
        "commands.giveaways.giveaway_reroll",
        "commands.general.afk",
        "commands.general.server_stats",
        "commands.general.profile",
        "commands.general.me",
        "commands.general.bot_status",
        "commands.general.status",
        "commands.general.console",
        "commands.general.badges",
        "commands.general.announcements",
        "commands.general.cross_server",
        "commands.general.voice_leaderboard",
        "commands.general.coinflip",
        "commands.general.activity_heatmap",
        "commands.general.trivia",
        "commands.general.my_stats",
        "commands.general.favorites",
        "commands.general.phishing",
        "commands.general.server_about",
        "commands.general.server_goals",
        "commands.warframe.build",
        "commands.warframe.drop_tables",
        "commands.context_menus",
        "commands.voice.vc",
    ]

    group_mapping = {
        "commands.economy.balance": economy_group,
        "commands.economy.wallet": economy_group,
        "commands.economy.config": economy_group,
        "commands.economy.transactions": economy_group,
        "commands.economy.leaderboard": economy_group,
        "commands.economy.daily": economy_group,
        "commands.economy.cooldowns": economy_group,
        "commands.economy.bounties": economy_group,
        "commands.economy.add_coins": economy_group,
        "commands.economy.gambling": economy_group,
        "commands.economy.stash": economy_group,
        "commands.economy.invest": economy_group,
        "commands.economy.prestige": economy_group,
        "commands.economy.xp": economy_xp,
        "commands.economy.xpleaderboard": economy_xp,
        "commands.economy.manage_xp": economy_xp,
        "commands.economy.xp_settings": economy_xp,
        "commands.economy.shop": economy_shop,
        "commands.economy.shop_manage": economy_shop,
        "commands.economy.pets": economy_pets,
        "commands.warframe.baro": warframe_group,
        "commands.warframe.world_state": warframe_group,
        "commands.warframe.baro_notify": wfnotify_group,
        # /lfg promoted to its own top-level group
        "commands.warframe.lfg": lfg_group,
        "commands.warframe.lfg_list": lfg_group,
        "commands.warframe.cycles": warframe_group,
        "commands.warframe.cycle_notify": wfnotify_group,
        "commands.warframe.cycle_panel": wfnotify_group,
        "commands.warframe.invasions": warframe_group,
        "commands.warframe.invasion_notify": wfnotify_group,
        "commands.warframe.archon": warframe_group,
        "commands.warframe.archon_notify": wfnotify_group,
        "commands.warframe.warframe_event_notify": wfnotify_group,
        "commands.warframe.resource": warframe_group,
        "commands.warframe.duviri": warframe_group,
        "commands.warframe.alerts": warframe_group,
        "commands.warframe.alerts_notify": wfnotify_group,
        "commands.warframe.fissures": warframe_group,
        "commands.warframe.sortie": warframe_group,
        "commands.warframe.daily_ops": warframe_group,
        "commands.warframe.status": warframe_group,
        "commands.warframe.hub": warframe_group,
        "commands.warframe.devstream_notify": wfnotify_group,
        "commands.warframe.forum_notify": wfnotify_group,
        "commands.warframe.youtube_notify": wfnotify_group,
        "commands.warframe.tennogen_notify": wfnotify_group,
        "commands.warframe.notify_status": wfnotify_group,
        "commands.warframe.dojo": warframe_group,
        "commands.warframe.warframe_link": warframe_group,
        "commands.warframe.warframe_roles": warframe_group,
        "commands.warframe.subscribe": warframe_group,
        "commands.warframe.notify_setup": wfnotify_group,
        "commands.warframe.notify_panel": wfnotify_group,
        # /mod = lightweight, frequently-used moderation
        "commands.moderation.purge": moderation_group,
        "commands.moderation.snipe": moderation_group,
        "commands.moderation.starboard": moderation_group,
        "commands.moderation.raid_protection": moderation_group,
        "commands.moderation.embed_builder": moderation_group,
        "commands.moderation.schedule": moderation_group,
        "commands.moderation.logging": moderation_group,
        "commands.moderation.lock": mod_channel,
        # /admin = heavier server-admin tooling (split out so /mod stays under Discord's 8000-byte cap)
        "commands.moderation.backup": admin_group,
        "commands.moderation.data_retention": admin_group,
        "commands.moderation.incident_mode": admin_group,
        "commands.moderation.kpis": admin_group,
        "commands.moderation.health": admin_group,
        "commands.general.welcome_recommend": admin_group,
        "commands.moderation.dashboard": admin_group,
        "commands.moderation.mentorship": admin_group,
        "commands.moderation.feature_toggle": admin_group,
        "commands.moderation.inactive_role": tools_group,
        "commands.moderation.ticket_config": admin_group,
        "commands.suggestions.manage_suggestions": admin_group,
        "commands.applications.application_setup": admin_group,
        "commands.applications.manage_applications": admin_group,
        # Promoted top-level groups (formerly /mod automod, /mod warn, /mod role_tools)
        "commands.moderation.reaction_roles": roletools_group,
        "commands.moderation.automod_setup": automod_group,
        "commands.moderation.automod_status": automod_group,
        "commands.moderation.roles": roletools_group,
        "commands.moderation.level_roles": roletools_group,
        "commands.moderation.role_menu": roletools_group,
        "commands.moderation.role_panel": roletools_group,
        "commands.moderation.warn": warn_group,
        "commands.moderation.mod_notes": warn_group,
        "commands.general.help": general_group,
        "commands.general.links": general_group,
        "commands.general.about": general_group,
        "commands.general.recent": general_group,
        "commands.general.ping": community_group,
        "commands.general.invite": community_group,
        "commands.general.member_count": general_group,
        "commands.general.setup_obsidian": general_group,
        "commands.general.setup_docket": general_group,
        "commands.general.setup_status": admin_group,
        "commands.general.sync_commands": general_group,
        "commands.general.welcome_setup": general_group,
        "commands.general.milestones": admin_group,           # Moved: general_group payload >8000 bytes
        "commands.general.achievements": tools_group,          # Moved: general_group at 25-cmd limit
        "commands.general.webhooks": admin_group,             # Moved: general_group payload >8000 bytes
        "commands.general.rules": general_group,
        "commands.general.polls": general_group,
        "commands.general.reminder": tools_group,              # Moved: community at 25 limit, general full
        "commands.general.preferences": general_group,
        "commands.general.reputation": community_group,
        "commands.general.twitch": community_group,
        "commands.general.afk": tools_group,
        "commands.general.server_stats": tools_group,          # Moved: community at 25 limit
        "commands.general.profile": general_group,
        "commands.general.me": general_group,
        "commands.general.bot_status": general_group,
        # status → TOP_LEVEL_ONLY (/status); console → admin (mod hub; frees /general 25-cap)
        "commands.general.console": admin_group,
        "commands.general.badges": tools_group,                # Moved: community at 25 limit
        "commands.general.announcements": admin_group,        # Moved: general_group payload >8000 bytes
        "commands.general.cross_server": tools_group,          # Moved: general_group at 25-cmd limit
        "commands.general.voice_leaderboard": tools_group,
        "commands.general.coinflip": tools_group,              # Moved: community at 25 limit
        "commands.general.activity_heatmap": tools_group,
        "commands.general.trivia": tools_group,                # Moved: general_group at 25-cmd limit
        "commands.general.my_stats": tools_group,
        "commands.general.phishing": tools_group,
        "commands.general.server_about": general_group,
        "commands.general.onboarding": tools_group,
        "commands.general.server_goals": tools_group,
        "commands.warframe.build": warframe_group,
        "commands.warframe.drop_tables": warframe_group,
        "commands.music.music": music_group,
        "commands.events.event_create": events_group,         # Moved: community_group payload >8000 bytes
        "commands.complaints.submit_complaint": community_group,
        "commands.complaints.request_help": community_group,
        "commands.tickets.ticket": community_group,
        "commands.suggestions.suggest": community_group,
        "commands.applications.application": community_group,
        "commands.trading.trade": trading_group,
        "commands.trading.trade_price": trading_group,
        "commands.trading.trade_search": trading_group,
        "commands.trading.trade_list": trading_group,
        "commands.trading.trade_setup": trading_group,
        "commands.activity.activity": community_group,
        "commands.activity.activity_leaderboard": tools_group,  # community_group at 25-cmd limit
        "commands.giveaways.giveaway": giveaways_group,
        "commands.giveaways.giveaway_end": giveaways_group,
        "commands.giveaways.giveaway_list": giveaways_group,
        "commands.giveaways.giveaway_reroll": giveaways_group,
        "commands.updates.update_log": updates_group,
        "commands.updates.update_log_setup": updates_group,
        "commands.updates.force_version_update": updates_group,
        "commands.context_menus": general_group,
        "commands.voice.vc": vc_group,
    }

    # Loaded with setup(bot, None) — not attached to /tools (25-subcommand cap).
    TOP_LEVEL_ONLY = {
        "commands.general.favorites",
        "commands.general.menu",
        "commands.general.search",
        "commands.general.profile_export",
        "commands.general.milestones_next",
        "commands.general.whatsnew",
        "commands.general.status",
        "commands.economy.claim",
        "commands.trading.price_watch",
    }

    loaded_count = 0
    failed_modules = []
    for module_name in command_modules:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "setup"):
                if module_name in TOP_LEVEL_ONLY:
                    module.setup(bot, None)
                    loaded_count += 1
                    print(f"[commands] Loaded {module_name} -> top-level only")
                    continue
                group = group_mapping.get(module_name, general_group)
                before_count = len(group.commands) if isinstance(group, app_commands.Group) else 0
                try:
                    module.setup(bot, group)
                    after_count = len(group.commands) if isinstance(group, app_commands.Group) else 0
                    added = after_count - before_count
                    loaded_count += 1
                    status = f"({added} command(s) added)" if added > 0 else "(no commands added)"
                    print(f"[commands] Loaded {module_name} -> {group.name} {status}")
                except ValueError as e:
                    if "maximum number of child commands exceeded" in str(e):
                        print(f"[commands] ERROR: {module_name} - group '{group.name}' has reached 25 command limit!")
                        failed_modules.append(module_name)
                    else:
                        raise
            else:
                print(f"[commands] WARNING: {module_name} has no setup()")
                failed_modules.append(module_name)
        except Exception as e:
            print(f"[commands] ERROR: Failed to load {module_name}: {e}")
            import traceback
            traceback.print_exc()
            failed_modules.append(module_name)

    # Note: Subcommand discovery (/economy help, /warframe help) skipped to stay under
    # Discord's 25-command-per-group limit. Use /help to explore commands by group.

    print(f"[commands] Loaded {loaded_count}/{len(command_modules)} command modules")
    if failed_modules:
        print(f"[commands] WARNING: {len(failed_modules)} failed: {', '.join(failed_modules)}")

    from core.command_shortcuts import register_all_shortcuts
    shortcut_count = register_all_shortcuts(bot)
    print(f"[commands] Registered {shortcut_count} top-level shortcut(s)")

    for cmd in bot.tree.get_commands(guild=None):
        if isinstance(cmd, app_commands.Group):
            n = len(cmd.commands)
            if n > 25:
                print(f"[commands] WARNING: group '/{cmd.name}' has {n} subcommands (Discord max 25)")
            elif n > 23:
                print(f"[commands] HEADROOM: '/{cmd.name}' has {n}/25 subcommands — avoid adding more without a plan")

    total_subcommands = sum(
        len(cmd.commands) for cmd in bot.tree.get_commands(guild=None)
        if isinstance(cmd, app_commands.Group)
    )
    print(f"[commands] Total subcommands: {total_subcommands}")
