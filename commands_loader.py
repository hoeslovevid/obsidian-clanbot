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
    economy_group = app_commands.Group(name="economy", description="💰 Coins, XP, shop, gambling, and pets")
    warframe_group = app_commands.Group(name="warframe", description="🎮 Baro, cycles, alerts, LFG, builds, and more")
    moderation_group = app_commands.Group(name="mod", description="🛡️ Purge, lock, warn, automod, logging, and moderation tools")
    general_group = app_commands.Group(name="general", description="📋 Help, about, setup, profiles, and server tools")
    tools_group = app_commands.Group(name="tools", description="🔧 Coinflip and utilities")
    community_group = app_commands.Group(name="community", description="👥 Events, tickets, suggestions, applications, and community features")
    music_group = app_commands.Group(name="music", description="🎵 Play, pause, skip, and manage music in voice channels")
    updates_group = app_commands.Group(name="updates", description="📝 Update log and version management")
    giveaways_group = app_commands.Group(name="giveaways", description="🎁 Create, manage, and enter giveaways")
    trading_group = app_commands.Group(name="trading", description="💼 Trading post, prices, and Warframe market lookup")

    # Economy subgroups (stays under 25 items: commands + subgroups)
    economy_pets = app_commands.Group(name="pets", description="Pet shop, care, battles, evolutions, and trading")
    economy_shop = app_commands.Group(name="store", description="Buy items and manage shop (mods)")
    economy_xp = app_commands.Group(name="xp", description="XP, leaderboard, and XP settings")
    economy_group.add_command(economy_pets)
    economy_group.add_command(economy_shop)
    economy_group.add_command(economy_xp)

    # Moderation subgroups
    mod_channel = app_commands.Group(name="channel", description="Lock and unlock channels")
    mod_warn = app_commands.Group(name="warn", description="Warn users and view warnings")
    mod_automod = app_commands.Group(name="automod", description="Auto-moderation configuration")
    mod_role_tools = app_commands.Group(name="role_tools", description="Reaction roles, role menus, level roles, self-assignable")
    moderation_group.add_command(mod_channel)
    moderation_group.add_command(mod_warn)
    moderation_group.add_command(mod_automod)
    moderation_group.add_command(mod_role_tools)

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

    command_modules = [
        "commands.general.help",
        "commands.general.about",
        "commands.general.ping",
        "commands.general.invite",
        "commands.general.member_count",
        "commands.general.setup_obsidian",
        "commands.general.setup_docket",
        "commands.general.sync_commands",
        "commands.general.welcome_setup",
        "commands.general.milestones",
        "commands.general.achievements",
        "commands.general.webhooks",
        "commands.general.rules",
        "commands.general.polls",
        "commands.general.reminder",
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
        "commands.moderation.purge",
        "commands.moderation.reaction_roles",
        "commands.moderation.automod_setup",
        "commands.moderation.automod_status",
        "commands.moderation.roles",
        "commands.moderation.level_roles",
        "commands.moderation.logging",
        "commands.moderation.snipe",
        "commands.moderation.warn",
        "commands.moderation.starboard",
        "commands.moderation.role_menu",
        "commands.moderation.backup",
        "commands.moderation.data_retention",
        "commands.moderation.incident_mode",
        "commands.moderation.kpis",
        "commands.moderation.raid_protection",
        "commands.moderation.embed_builder",
        "commands.moderation.lock",
        "commands.moderation.schedule",
        "commands.moderation.dashboard",
        "commands.moderation.ticket_config",
        "commands.economy.balance",
        "commands.economy.transactions",
        "commands.economy.leaderboard",
        "commands.economy.daily",
        "commands.economy.xp",
        "commands.economy.xpleaderboard",
        "commands.economy.add_coins",
        "commands.economy.manage_xp",
        "commands.economy.xp_settings",
        "commands.economy.invest",
        "commands.economy.shop",
        "commands.economy.shop_manage",
        "commands.economy.gambling",
        "commands.economy.pets",
        "commands.economy.prestige",
        "commands.warframe.baro",
        "commands.warframe.baro_notify",
        "commands.warframe.lfg",
        "commands.warframe.lfg_list",
        "commands.warframe.cycles",
        "commands.warframe.cycle_notify",
        "commands.warframe.invasions",
        "commands.warframe.invasion_notify",
        "commands.warframe.archon",
        "commands.warframe.archon_notify",
        "commands.warframe.warframe_event_notify",
        "commands.warframe.resource",
        "commands.warframe.duviri",
        "commands.warframe.alerts",
        "commands.warframe.alerts_notify",
        "commands.warframe.status",
        "commands.warframe.devstream_notify",
        "commands.warframe.dojo",
        "commands.warframe.warframe_link",
        "commands.warframe.warframe_roles",
        "commands.activity.activity",
        "commands.activity.activity_leaderboard",
        "commands.giveaways.giveaway",
        "commands.giveaways.giveaway_end",
        "commands.giveaways.giveaway_list",
        "commands.giveaways.giveaway_reroll",
        "commands.general.afk",
        "commands.general.server_stats",
        "commands.general.profile",
        "commands.general.bot_status",
        "commands.general.badges",
        "commands.general.announcements",
        "commands.general.cross_server",
        "commands.general.voice_leaderboard",
        "commands.general.coinflip",
        "commands.warframe.build",
        "commands.context_menus",
    ]

    group_mapping = {
        "commands.economy.balance": economy_group,
        "commands.economy.transactions": economy_group,
        "commands.economy.leaderboard": economy_group,
        "commands.economy.daily": economy_group,
        "commands.economy.add_coins": economy_group,
        "commands.economy.gambling": economy_group,
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
        "commands.warframe.baro_notify": warframe_group,
        "commands.warframe.lfg": warframe_group,
        "commands.warframe.lfg_list": warframe_group,
        "commands.warframe.cycles": warframe_group,
        "commands.warframe.cycle_notify": warframe_group,
        "commands.warframe.invasions": warframe_group,
        "commands.warframe.invasion_notify": warframe_group,
        "commands.warframe.archon": warframe_group,
        "commands.warframe.archon_notify": warframe_group,
        "commands.warframe.warframe_event_notify": warframe_group,
        "commands.warframe.resource": warframe_group,
        "commands.warframe.duviri": warframe_group,
        "commands.warframe.alerts": warframe_group,
        "commands.warframe.alerts_notify": warframe_group,
        "commands.warframe.status": warframe_group,
        "commands.warframe.devstream_notify": warframe_group,
        "commands.warframe.dojo": warframe_group,
        "commands.warframe.warframe_link": warframe_group,
        "commands.warframe.warframe_roles": warframe_group,
        "commands.moderation.purge": moderation_group,
        "commands.moderation.logging": moderation_group,
        "commands.moderation.snipe": moderation_group,
        "commands.moderation.starboard": moderation_group,
        "commands.moderation.backup": moderation_group,
        "commands.moderation.data_retention": moderation_group,
        "commands.moderation.incident_mode": moderation_group,
        "commands.moderation.kpis": moderation_group,
        "commands.moderation.raid_protection": moderation_group,
        "commands.moderation.embed_builder": moderation_group,
        "commands.moderation.schedule": moderation_group,
        "commands.moderation.dashboard": moderation_group,
        "commands.moderation.ticket_config": moderation_group,
        "commands.moderation.reaction_roles": mod_role_tools,
        "commands.moderation.automod_setup": mod_automod,
        "commands.moderation.automod_status": mod_automod,
        "commands.moderation.roles": mod_role_tools,
        "commands.moderation.level_roles": mod_role_tools,
        "commands.moderation.role_menu": mod_role_tools,
        "commands.moderation.warn": mod_warn,
        "commands.moderation.lock": mod_channel,
        "commands.general.help": general_group,
        "commands.general.about": general_group,
        "commands.general.ping": community_group,
        "commands.general.invite": community_group,
        "commands.general.member_count": general_group,
        "commands.general.setup_obsidian": general_group,
        "commands.general.setup_docket": general_group,
        "commands.general.sync_commands": general_group,
        "commands.general.welcome_setup": general_group,
        "commands.general.milestones": general_group,
        "commands.general.achievements": general_group,
        "commands.general.webhooks": general_group,
        "commands.general.rules": general_group,
        "commands.general.polls": general_group,
        "commands.general.reminder": community_group,
        "commands.general.reputation": community_group,
        "commands.general.twitch": community_group,
        "commands.general.afk": community_group,
        "commands.general.server_stats": community_group,
        "commands.general.profile": general_group,
        "commands.general.bot_status": general_group,
        "commands.general.badges": general_group,
        "commands.general.announcements": general_group,
        "commands.general.cross_server": general_group,
        "commands.general.voice_leaderboard": general_group,
        "commands.general.coinflip": tools_group,  # Moved: community at 25 limit
        "commands.warframe.build": warframe_group,
        "commands.music.music": music_group,
        "commands.events.event_create": community_group,
        "commands.complaints.submit_complaint": community_group,
        "commands.complaints.request_help": community_group,
        "commands.tickets.ticket": community_group,
        "commands.suggestions.suggest": community_group,
        "commands.suggestions.manage_suggestions": community_group,
        "commands.applications.application": community_group,
        "commands.applications.application_setup": community_group,
        "commands.applications.manage_applications": community_group,
        "commands.trading.trade": trading_group,
        "commands.trading.trade_price": trading_group,
        "commands.trading.trade_search": trading_group,
        "commands.trading.trade_list": trading_group,
        "commands.trading.trade_setup": trading_group,
        "commands.activity.activity": community_group,
        "commands.activity.activity_leaderboard": community_group,
        "commands.giveaways.giveaway": giveaways_group,
        "commands.giveaways.giveaway_end": giveaways_group,
        "commands.giveaways.giveaway_list": giveaways_group,
        "commands.giveaways.giveaway_reroll": giveaways_group,
        "commands.updates.update_log": updates_group,
        "commands.updates.update_log_setup": updates_group,
        "commands.updates.force_version_update": updates_group,
        "commands.context_menus": general_group,
    }

    loaded_count = 0
    failed_modules = []
    for module_name in command_modules:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "setup"):
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
    total_subcommands = sum(
        len(cmd.commands) for cmd in bot.tree.get_commands(guild=None)
        if isinstance(cmd, app_commands.Group)
    )
    print(f"[commands] Total subcommands: {total_subcommands}")
