"""Help command with interactive group selection."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore
from typing import Optional, cast

from core.embed_templates import help_breadcrumb
from core.utils import obsidian_embed, is_mod, ECONOMY_ENABLED, COINS_PER_MESSAGE, COINS_DAILY_REWARD, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, EMBED_COLORS
from core.config import BOT_WEBSITE
from core.presence import website_host


def _collect_group_commands(group: app_commands.Group, prefix: list[str]) -> list[tuple[str, str]]:
    """Recursively collect (path_str, description) for all commands in group and subgroups."""
    result = []
    for cmd in group.commands:
        path = prefix + [cmd.name]
        path_str = " ".join(path)
        if isinstance(cmd, app_commands.Command):
            desc = cmd.description or "No description"
            if len(desc) > 80:
                desc = desc[:77] + "..."
            result.append((path_str, desc))
        elif isinstance(cmd, app_commands.Group):
            result.extend(_collect_group_commands(cmd, path))
    return result


class PageButton(discord.ui.Button):
    """Button for pagination."""
    
    def __init__(self, label: str, action: str, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.action = action
    
    async def callback(self, interaction: discord.Interaction):
        """Handle page navigation."""
        view = cast(Optional[HelpSelectView], self.view)
        if view is None or not view.current_group:
            return await interaction.response.send_message("No group selected.", ephemeral=True)
        
        collected = _collect_group_commands(view.current_group, [view.current_group.name])
        total_commands = len(collected)
        total_pages = (total_commands + view.commands_per_page - 1) // view.commands_per_page
        
        if self.action == "prev" and view.current_page > 0:
            view.current_page -= 1
        elif self.action == "next" and view.current_page < total_pages - 1:
            view.current_page += 1
        else:
            return await interaction.response.defer()
        
        # Update embed with new page
        select_item = next((item for item in view.children if isinstance(item, HelpSelect)), None)
        if select_item:
            await select_item.update_embed(interaction, view.current_group, view.current_page)


class PageSelect(discord.ui.Select):
    """Select menu for jumping to a specific page."""
    
    def __init__(self, total_pages: int, current_page: int):
        options = []
        for i in range(total_pages):
            options.append(
                discord.SelectOption(
                    label=f"Page {i + 1}",
                    value=str(i),
                    default=(i == current_page)
                )
            )
        
        super().__init__(
            placeholder=f"Jump to page...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle page jump."""
        view = cast(Optional[HelpSelectView], self.view)
        if view is None or not view.current_group:
            return await interaction.response.send_message("No group selected.", ephemeral=True)
        
        page = int(self.values[0])
        view.current_page = page
        
        # Update embed with new page
        select_item = next((item for item in view.children if isinstance(item, HelpSelect)), None)
        if select_item:
            await select_item.update_embed(interaction, view.current_group, view.current_page)


class HelpSelectView(discord.ui.View):
    """View with select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.is_user_mod = is_user_mod
        self.current_group = None
        self.current_page = 0
        self.commands_per_page = 15  # Commands per page
        self.add_item(HelpSelect(bot, is_user_mod, self))
    
    async def on_timeout(self):
        """Disable the view when it times out."""
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        try:
            msg = cast(Optional[discord.Message], getattr(self, "message", None))
            if msg is not None and msg.embeds:
                emb = msg.embeds[0]
                if emb.footer and emb.footer.text:
                    emb.set_footer(text=emb.footer.text + " • ⏰ Expired")
                await msg.edit(embed=emb, view=self)
        except Exception:
            pass
    
    def update_pagination_buttons(self):
        """Update pagination buttons based on current state."""
        # Remove existing pagination buttons
        pagination_items = [item for item in self.children if isinstance(item, (PageButton, PageSelect))]
        for item in pagination_items:
            self.remove_item(item)
        
        # Only add pagination if we have a group with multiple pages
        if self.current_group:
            collected = _collect_group_commands(self.current_group, [self.current_group.name])
            total_commands = len(collected)
            total_pages = (total_commands + self.commands_per_page - 1) // self.commands_per_page
            
            if total_pages > 1:
                # Add page navigation buttons
                if self.current_page > 0:
                    self.add_item(PageButton("◀️ Previous", "prev", disabled=False))
                else:
                    self.add_item(PageButton("◀️ Previous", "prev", disabled=True))
                
                # Add page selector (max 25 options, so limit if needed)
                if total_pages <= 25:
                    self.add_item(PageSelect(total_pages, self.current_page))
                
                if self.current_page < total_pages - 1:
                    self.add_item(PageButton("Next ▶️", "next", disabled=False))
                else:
                    self.add_item(PageButton("Next ▶️", "next", disabled=True))


class HelpSelect(discord.ui.Select):
    """Select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool, parent_view):
        self.bot = bot
        self.is_user_mod = is_user_mod
        self.parent_view = parent_view
        
        # Get available groups from bot
        available_groups = {}
        for cmd in bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group):
                available_groups[cmd.name] = cmd
        
        # Define all possible groups with their emojis and descriptions
        group_definitions = {
            "general": ("General", "Help, profile, bio, preferences, polls, rules", "📋"),
            "economy": ("Economy", "Balance, daily, bounties, gambling, invest, stash", "💰"),
            "pets": ("Pets", "Pet shop, care, battles, marketplace", "🐾"),
            "store": ("Shop", "Browse and buy server items", "🛒"),
            "xp": ("XP", "XP check, leaderboard, settings", "✨"),
            "tools": ("Tools", "Coinflip, achievements, voice LB, stats", "🔧"),
            "warframe": ("Warframe", "Baro, cycles, alerts, fissures, builds", "🎮"),
            "wfnotify": ("Warframe Notify", "Baro, cycle, invasion, devstream alerts", "🔔"),
            "lfg": ("LFG", "Looking-for-group posts", "🤝"),
            "community": ("Community", "Tickets, suggestions, complaints, applications", "👥"),
            "events": ("Events", "Server events: create and recurring schedules", "📅"),
            "trading": ("Trading", "Market prices and trading post", "💼"),
            "mod": ("Moderation", "Purge, snipe, lock, schedule, raid shield", "🛡️"),
            "automod": ("AutoMod", "Spam, caps, links, mention filters", "🤖"),
            "warn": ("Warnings", "Warn, templates, moderator notes", "🛑"),
            "roletools": ("Role Tools", "Reaction roles, level roles, mass assign", "🎭"),
            "admin": ("Admin", "Backups, retention, dashboards, applications", "🗄️"),
            "giveaways": ("Giveaways", "Create and manage giveaways", "🎁"),
            "updates": ("Updates", "Update log and version management", "📝"),
            "music": ("Music", "Play music in voice channels", "🎵"),
        }
        
        # Only add options for groups that actually exist
        options = []
        for group_name, (label, description, emoji) in group_definitions.items():
            if group_name in available_groups:
                options.append(
                    discord.SelectOption(
                        label=label,
                        description=description,
                        emoji=emoji,
                        value=group_name
                    )
                )
        
        super().__init__(
            placeholder="Select a command group to view...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle group selection."""
        selected_group = self.values[0]
        
        # Get the group from bot's command tree
        # Use guild=None to get all commands (works for both global and guild-specific)
        group = None
        for cmd in self.bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group) and cmd.name == selected_group:
                group = cmd
                break
        
        if not group:
            # Fallback: try with the interaction's guild if it exists
            if interaction.guild:
                for cmd in self.bot.tree.get_commands(guild=interaction.guild):
                    if isinstance(cmd, app_commands.Group) and cmd.name == selected_group:
                        group = cmd
                        break
        
        if not group:
            return await interaction.response.send_message(
                f"Group '{selected_group}' not found. Please try again.",
                ephemeral=True
            )
        
        # Store current group and reset page
        self.parent_view.current_group = group
        self.parent_view.current_page = 0
        
        # Build and display the page
        await self.update_embed(interaction, group, 0)
    
    async def update_embed(self, interaction: discord.Interaction, group: app_commands.Group, page: int):
        """Update the embed with commands for the specified page."""
        # Build command list (including nested subgroups)
        collected = _collect_group_commands(group, [group.name])
        commands_list = [f"• `/{path}` - {desc}" for path, desc in collected]
        
        if not commands_list:
            commands_text = "No commands available in this group."
            total_pages = 1
        else:
            # Calculate pagination
            total_pages = (len(commands_list) + self.parent_view.commands_per_page - 1) // self.parent_view.commands_per_page
            start_idx = page * self.parent_view.commands_per_page
            end_idx = min(start_idx + self.parent_view.commands_per_page, len(commands_list))
            
            # Get commands for this page
            page_commands = commands_list[start_idx:end_idx]
            
            # Build text, ensuring we don't exceed 1024 chars
            commands_text = ""
            for cmd in page_commands:
                # Check if adding this command would exceed limit
                test_text = commands_text + cmd + "\n" if commands_text else cmd + "\n"
                if len(test_text) > 1020:  # Leave some room
                    break
                commands_text = test_text
            
            # Remove trailing newline
            commands_text = commands_text.rstrip()
            
            # If we couldn't fit all commands on this page, indicate there are more
            if end_idx < len(commands_list):
                remaining = len(commands_list) - end_idx
                if len(commands_text) + len(f"\n... {remaining} more (use pagination)") <= 1024:
                    commands_text += f"\n... {remaining} more (use pagination)"
        
        # Group descriptions and colors per group
        group_descriptions = {
            "general": "📋 General commands: help, profile, bio, trivia, preferences, polls, rules, server setup, and welcome configuration",
            "economy": "💰 Economy: balance, daily, bounties, gambling (slots/dice/roulette), gambling stats, investments, prestige, stash, and transfers",
            "pets": "🐾 Pets: shop, buy, feed, play, evolve, battle other players, list/buy on marketplace",
            "store": "🛒 Server shop: browse items, buy with coins, mods can manage stock",
            "xp": "✨ XP: check level, leaderboard, configure events and settings (mod commands)",
            "tools": "🔧 Tools: coinflip, activity heatmap, voice leaderboard, achievements, server stats, badges, AFK, reminders",
            "warframe": "🎮 Warframe: Baro, cycles, alerts, fissures, invasions, sortie, archon, builds, dojo, roles",
            "wfnotify": "🔔 Warframe notifications: Baro, cycles, invasions, archon, alerts, devstream, forum/youtube/tennogen feeds",
            "lfg": "🤝 LFG: post or browse looking-for-group ads for Warframe activities",
            "community": "👥 Community: tickets, suggestions, applications, complaints, reputation, twitch notifications, activity",
            "events": "📅 Events: create one-off or recurring server events, list upcoming events",
            "trading": "💼 Trading: post trades, browse listings, look up market prices",
            "mod": "🛡️ Moderation: purge, snipe, lock, schedule, raid shield, embed builder, starboard, logging (moderators only)",
            "automod": "🤖 AutoMod: configure spam, caps, link, and mention filters (moderators only)",
            "warn": "🛑 Warnings: warn users, manage templates, attach moderator notes (moderators only)",
            "roletools": "🎭 Role tools: reaction roles, role menus, level roles, mass add/remove (moderators only)",
            "admin": "🗄️ Admin: backups, data retention, incident mode, KPIs, dashboards, applications, suggestions, milestones, announcements, webhooks (moderators only)",
            "giveaways": "🎁 Giveaways: create, list, end, and reroll giveaways",
            "updates": "📝 Updates: update log and version tracking (moderators only)",
            "music": "🎵 Music: play, pause, skip, and manage music in voice channels",
        }
        group_colors = {
            "general":   EMBED_COLORS["general"],
            "economy":   EMBED_COLORS["economy"],
            "pets":      EMBED_COLORS["economy"],
            "store":     EMBED_COLORS["economy"],
            "xp":        EMBED_COLORS["economy"],
            "tools":     EMBED_COLORS["general"],
            "warframe":  EMBED_COLORS["warframe"],
            "wfnotify":  EMBED_COLORS["warframe"],
            "lfg":       EMBED_COLORS["warframe"],
            "community": EMBED_COLORS["community"],
            "events":    EMBED_COLORS["community"],
            "trading":   EMBED_COLORS["warframe"],
            "mod":       EMBED_COLORS["moderation"],
            "automod":   EMBED_COLORS["moderation"],
            "warn":      EMBED_COLORS["moderation"],
            "roletools": EMBED_COLORS["moderation"],
            "admin":     EMBED_COLORS["moderation"],
            "giveaways": EMBED_COLORS["prestige"],
            "updates":   EMBED_COLORS["general"],
            "music":     EMBED_COLORS["community"],
        }
        group_name = group.name.title()
        group_desc = group_descriptions.get(group.name, group.description or "Commands")
        help_color = group_colors.get(group.name, discord.Color.blurple())
        
        # Add page info to description if multiple pages
        if total_pages > 1:
            group_desc += f"\n\n**Page {page + 1} of {total_pages}**"
        
        embed = obsidian_embed(
            f"📋 {help_breadcrumb([group.name])} Commands",
            group_desc,
            color=help_color,
            thumbnail=interaction.client.user.display_avatar.url if interaction.client and interaction.client.user else None,
            fields=[("Commands", commands_text, False)],
            client=interaction.client,
        )
        
        # Add footer with command count (includes nested subgroup commands)
        footer_text = f"{len(collected)} command(s) in this group"
        if total_pages > 1:
            footer_text += f" • Page {page + 1}/{total_pages}"
        embed.set_footer(text=footer_text)
        
        # Update pagination buttons
        self.parent_view.update_pagination_buttons()
        
        # Update the message
        target = interaction.message
        if interaction.response.is_done():
            if target is not None:
                try:
                    await interaction.followup.edit_message(target.id, embed=embed, view=self.parent_view)
                except Exception:
                    try:
                        await target.edit(embed=embed, view=self.parent_view)
                    except Exception:
                        pass
        else:
            await interaction.response.edit_message(embed=embed, view=self.parent_view)


def setup(bot, group=None):
    """Register the help command."""
    command_decorator = group.command(name="help", description="Browse commands — categories, shortcuts, and examples. Try /help or /menu.") if group else bot.tree.command(name="help", description="Browse all bot commands.")
    
    async def _help_command_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete command paths for help."""
        def _paths(cmds, prefix=""):
            out = []
            for c in cmds:
                p = f"{prefix} {c.name}".strip() if prefix else c.name
                if isinstance(c, app_commands.Group):
                    out.extend(_paths(c.commands, p))
                else:
                    out.append(p)
            return out
        cmd_src = bot.tree.get_commands(guild=interaction.guild) if interaction.guild else bot.tree.get_commands()
        all_paths = _paths(cmd_src)
        current_lower = (current or "").lower()
        matches = [p for p in all_paths if not current_lower or current_lower in p.lower()][:25]
        return [app_commands.Choice(name=m, value=m) for m in matches]

    @command_decorator
    @app_commands.describe(command="Optional: get help for a specific command (e.g., 'economy balance', 'community event_create')")
    @app_commands.autocomplete(command=_help_command_autocomplete)
    async def help_command(interaction: discord.Interaction, command: Optional[str] = None):
        """Display an interactive help embed with command groups, or help for a specific command."""
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # If a specific command was requested, show help for that command
        if command:
            await interaction.response.defer(ephemeral=True)
            
            # Parse command (e.g., "economy balance" or "warframe baro")
            parts = command.lower().strip().split()
            
            # Find the command (supports 1–3 levels: economy, economy balance, economy pets shop)
            found_command = None
            commands_source = bot.tree.get_commands(guild=interaction.guild) if interaction.guild else bot.tree.get_commands()
            for cmd in commands_source:
                if cmd.name != parts[0]:
                    continue
                if len(parts) == 1:
                    found_command = cmd
                    break
                if not isinstance(cmd, app_commands.Group):
                    continue
                # parts >= 2: drill into subgroups
                current = cmd
                for i in range(1, len(parts)):
                    sub = next((c for c in current.commands if c.name == parts[i]), None)
                    if not sub:
                        break
                    if i == len(parts) - 1:
                        found_command = sub
                        break
                    if isinstance(sub, app_commands.Group):
                        current = sub
                    else:
                        break
                if found_command:
                    break
            
            # Short examples for common commands
            HELP_EXAMPLES = {
                # Economy
                "economy balance": ["/economy balance", "/economy balance user:@Member", "/bal"],
                "economy daily": ["/economy daily", "/daily"],
                "economy bounties": ["/economy bounties"],
                "economy gamble_stats": ["/economy gamble_stats", "/economy gamble_stats user:@Member"],
                "economy gambling slots": ["/economy gambling slots", "/economy gambling slots bet:500"],
                "economy gambling dice": ["/economy gambling dice bet:200"],
                "economy gambling roulette": ["/economy gambling roulette color:red bet:100"],
                "economy invest": ["/economy invest amount:1000 duration:30 days (25%)"],
                "economy invest_status": ["/economy invest_status"],
                "economy invest_collect": ["/economy invest_collect"],
                "economy invest_withdraw": ["/economy invest_withdraw"],
                "store buy": ["/store buy item_name:Orokin Catalyst"],
                "store browse": ["/store browse"],
                "pets shop": ["/pets shop"],
                "pets buy": ["/pets buy pet_type:Kavat name:Whiskers"],
                "pets feed": ["/pets feed"],
                "pets play": ["/pets play"],
                "pets battle": ["/pets battle opponent:@Member"],
                "xp check": ["/xp check", "/xp check user:@Member"],
                "xp leaderboard": ["/xp leaderboard"],
                "economy stash": ["/economy stash"],
                "economy prestige": ["/economy prestige"],
                # General
                "general profile": ["/general profile", "/general profile user:@Member", "/profile"],
                "general set_bio": ["/general set_bio"],
                "tools achievements": ["/tools achievements", "/tools achievements user:@Member"],
                "tools achievements_leaderboard": ["/tools achievements_leaderboard"],
                "warframe fissures": ["/warframe fissures", "/warframe fissures tier:Lith"],
                "general preferences": ["/general preferences daily_reminder:On levelup_dm:On hide_leaderboards:On", "/general preferences typo_helper:Off"],
                "general trivia": ["/general trivia", "/general trivia difficulty:Hard"],
                "general links": ["/general links"],
                "general about": ["/general about"],
                "general help_search": ["/search query:pet", "/search query:baro", "/general help_search query:ticket"],
                "search": ["/search query:daily", "/search query:trade"],
                "case": ["/case case_id:OBS-..."],
                "community case_status": ["/case case_id:OBS-..."],
                "menu": ["/menu"],
                # Tools
                "tools activity_heatmap": ["/tools activity_heatmap", "/tools activity_heatmap days:30 days", "/tools activity_heatmap user:@Member days:7 days"],
                "tools voice_leaderboard": ["/tools voice_leaderboard"],
                "tools coinflip": ["/tools coinflip"],
                "tools my_stats": ["/tools my_stats", "/tools my_stats user:@Member"],
                "tools favorite_add": ["/favorite_add command:economy daily"],
                "tools favorite_remove": ["/favorite_remove command:economy daily"],
                "tools favorites": ["/favorites"],
                "favorite_add": ["/favorite_add command:baro"],
                "favorites": ["/favorites"],
                "roletools panel_create": ["/roletools panel_create channel:#roles"],
                "roletools panel_delete": ["/roletools panel_delete panel_id:1"],
                # Warframe
                "warframe baro": ["/warframe baro"],
                "warframe cycles": ["/warframe cycles"],
                "warframe fissures": ["/warframe fissures"],
                "warframe sortie": ["/warframe sortie"],
                "warframe daily_ops": ["/warframe daily_ops"],
                "warframe build": ["/warframe build name:Saryn"],
                "warframe drop": ["/warframe drop item:Ash Prime Neuroptics"],
                "warframe invasions": ["/warframe invasions"],
                "warframe archon": ["/warframe archon"],
                # Community
                "events event_create": ["/events event_create name:Sortie Run when:tomorrow 7pm"],
                "community ticket": ["/community ticket subject:Need help with role"],
                "community suggest": ["/community suggest suggestion:Add a weekly bounty"],
                # Moderation
                "mod purge": ["/mod purge amount:50 archive:True"],
                "roletools mass_add": ["/roletools mass_add role:@Member", "/roletools mass_add role:@VIP filter_role:@Verified"],
                "roletools mass_remove": ["/roletools mass_remove role:@TempRole"],
                "warn warn": ["/warn warn user:@User reason:Spam"],
                "warn notes": ["/warn notes user:@User"],
                "automod setup": ["/automod setup feature:Spam Detection enabled:Enable"],
                "automod status": ["/automod status"],
                "admin dashboard": ["/admin dashboard"],
                "admin stats_dashboard": ["/admin stats_dashboard"],
                "admin backup": ["/admin backup"],
                "admin retention": ["/admin retention"],
                "admin announcement": ["/admin announcement create channel:#announcements message:..."],
                "wfnotify cycle_notify": ["/wfnotify cycle_notify cycle_type:Cetus enabled:Enable"],
                "wfnotify baro_notify": ["/wfnotify baro_notify"],
                "lfg create": ["/lfg create activity:Eidolon Hunt"],
                "lfg list": ["/lfg list"],
            }
            if found_command:
                # Build help for specific command
                if isinstance(found_command, app_commands.Command):
                    desc = found_command.description or "No description available."
                    
                    # Add parameter info
                    params_text = ""
                    if found_command.parameters:
                        params_text = "\n\n**Parameters:**\n"
                        for param in found_command.parameters:
                            param_desc = param.description or "No description"
                            required = "Required" if param.required else "Optional"
                            params_text += f"• `{param.name}` ({required}) - {param_desc}\n"
                    
                    # Add usage example (build full path for nested groups)
                    path_parts = parts
                    usage = "/" + " ".join(path_parts)
                    path_key = " ".join(path_parts)
                    examples_text = ""
                    if path_key in HELP_EXAMPLES:
                        ex = HELP_EXAMPLES[path_key]
                        examples_text = "\n\n**Examples:**\n" + "\n".join(f"• `{e}`" for e in ex[:2])
                    
                    embed = obsidian_embed(
                        f"📖 Help: `{usage}`",
                        desc + params_text + f"\n**Usage:** `{usage}`" + examples_text,
                        color=discord.Color.blurple(),
                        client=interaction.client,
                    )
                else:
                    # It's a group
                    embed = obsidian_embed(
                        f"📖 Help: `/{found_command.name}`",
                        found_command.description or "No description available.",
                        color=discord.Color.blurple(),
                        client=interaction.client,
                    )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # Typo hint: suggest similar commands
                from difflib import get_close_matches
                def _all_paths(commands, prefix=""):
                    paths = []
                    for c in commands:
                        p = f"{prefix} {c.name}".strip() if prefix else c.name
                        if isinstance(c, app_commands.Group):
                            paths.extend(_all_paths(c.commands, p))
                        else:
                            paths.append(p)
                    return paths
                all_paths = _all_paths(bot.tree.get_commands(guild=None))
                query = " ".join(parts)
                suggestions = get_close_matches(query, all_paths, n=3, cutoff=0.5)
                if not suggestions:
                    suggestions = get_close_matches(query, all_paths, n=3, cutoff=0.35)
                if not suggestions and len(parts) >= 2:
                    suggestions = get_close_matches(parts[-1], [p.split()[-1] for p in all_paths if len(p.split()) == len(parts)], n=3, cutoff=0.4)
                    if suggestions and all_paths:
                        suggestions = [p for p in all_paths if p.split()[-1] in suggestions][:3]
                hint = ""
                if suggestions:
                    hint = f"\n\n_Did you mean: " + ", ".join(f"`/{s}`" for s in suggestions) + "?_"
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Command Not Found",
                        f"Could not find command: `{command}`.{hint}\n\nUse **`/help`** or **`/search`** to browse commands.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            return
        
        # Get all groups
        # Use guild=None to get all commands (works for both global and guild-specific)
        groups = []
        for cmd in bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group):
                groups.append(cmd)
        
        # Build initial embed — "Start here" mental model + full group list
        desc = (
            "**Start here** — the commands members use most:\n\n"
            "👤 **Me** — `/daily` · `/profile` · `/me` · `/preferences` · `/favorites`\n"
            "🎮 **Warframe** — `/baro` · `/fissures` · `/lfg` · `/trade`\n"
            "👥 **Community** — `/ticket` · `/case` · `/poll` · `/community suggest`\n"
            "🔍 **Find anything** — `/search` keyword · `/menu` quick picker · `/help` full list\n"
        )
        if is_user_mod:
            desc += "\n🛡️ **Mods** — `/mod purge` · `/warn warn` · `/automod status` · `/admin dashboard`\n"

        desc += "\n**All categories** (dropdown below):\n"
        
        group_info = {
            "general": ("📋 General", "General bot commands"),
            "economy": ("💰 Economy", "Economy and coin management"),
            "tools": ("🔧 Tools", "Coinflip and utilities"),
            "warframe": ("🎮 Warframe", "Warframe game information"),
            "community": ("👥 Community", "Community features"),
            "trading": ("💼 Trading", "Trading commands"),
            "mod": ("🛡️ Moderation", "Moderation and server management"),
            "giveaways": ("🎁 Giveaways", "Giveaway commands"),
            "updates": ("📝 Updates", "Update log commands"),
            "music": ("🎵 Music", "Music commands"),
        }
        
        for group in groups:
            if group.name in group_info:
                emoji_name, group_desc = group_info[group.name]
                total = len(_collect_group_commands(group, [group.name]))
                desc += f"{emoji_name} **{group.name.title()}** - {total} command(s)\n"
        
        # Add feature info
        desc += "\n**💬 Features:**\n"
        desc += "• Join-to-Create Voice Channels • Voice Channel Controls\n"
        desc += "• Complaints • Tickets (auto-assign) • Suggestions\n"
        desc += "• Application System • Event RSVP • Trading Post • Giveaways\n"
        desc += "• LFG (Looking for Group) • Twitch stream notifications\n"
        desc += "• Achievements & Milestones • Achievement Leaderboard\n"
        desc += "• XP & Levels • Prestige • Pets • Badges • Profile Bio\n"
        desc += "• Gambling (slots/dice/roulette) + Stats • Daily Bounties with progress\n"
        desc += "• Investments + Early Withdrawal • Activity Heatmap\n"
        desc += "• Mass Role Add/Remove • Refreshable Mod Dashboard\n"
        desc += "• Warframe: Baro, cycles, alerts, link account, achievement roles"
        if ECONOMY_ENABLED:
            desc += f"\n• Economy: {COINS_PER_MESSAGE} coins/msg, {COINS_DAILY_REWARD:,} daily, {COINS_PER_MINUTE_VOICE}/min voice ({MESSAGE_COOLDOWN_SECONDS}s msg cooldown)"
        if BOT_WEBSITE:
            host = website_host() or BOT_WEBSITE
            desc += f"\n\n**🌐 Website:** [{host}]({BOT_WEBSITE}) — also in **`/general links`** and **`/general about`**"
        
        desc += "\n\n**💡 Tips:** Type `/` and start typing (Discord searches names + descriptions). "
        desc += "Pin favorites with **`/favorite_add`**. New? Try **`/menu`**."
        
        help_footer = "Shortcuts: /help /search /menu • /help command:<name> for details"
        if BOT_WEBSITE:
            help_footer += f" • {website_host() or 'Website'}"
        
        embed = obsidian_embed(
            "Command Reference",
            desc,
            template="showcase",
            brand=True,
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else (interaction.client.user.display_avatar.url if interaction.client and interaction.client.user else None),
            footer=help_footer,
            client=interaction.client,
        )
        
        # Create view with select menu
        view = HelpSelectView(bot, is_user_mod)

        async def _open_classic_picker(inter: discord.Interaction):
            await inter.response.edit_message(embed=embed, view=view)

        from core.help_layout import help_layout_v2_enabled, HelpHomeLayout

        if help_layout_v2_enabled():
            try:
                layout = HelpHomeLayout(is_mod=is_user_mod, on_browse=_open_classic_picker)
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            except Exception:
                pass
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    search_decorator = (
        group.command(name="help_search", description="Search commands by keyword — coins, baro, ticket, trade.")
        if group
        else bot.tree.command(name="help_search", description="Search slash commands by keyword.")
    )

    @search_decorator
    @app_commands.describe(query="Keyword to search (command name or description)")
    async def help_search(interaction: discord.Interaction, query: str):
        from core.command_search import search_commands

        q = (query or "").strip()
        if len(q) < 2:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "Search too short",
                    "Use at least **2 characters** (e.g. `pet`, `baro`, `ticket`).",
                    category="warning",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        matches, suggestion = search_commands(interaction.client, q, limit=12)
        if not matches:
            dym_line = f"\n\nDid you mean **`/{suggestion}`**?" if suggestion else ""
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "No matches",
                    f"No commands matched **`{q}`**.{dym_line}\nTry **`/help`** to browse by category or **`/menu`** for quick picks.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        lines = []
        for path, desc, _score in matches:
            line = f"`/{path}`"
            if desc:
                line += f" — {desc[:90]}{'…' if len(desc) > 90 else ''}"
            lines.append(line)

        fields = None
        if suggestion and matches and matches[0][2] < 25:
            fields = [("Did you mean?", f"`/{suggestion}`", False)]

        embed = obsidian_embed(
            f"🔍 Command search — `{q}`",
            "\n".join(lines[:12]),
            color=discord.Color.blurple(),
            fields=fields,
            footer=f"{len(matches)} match{'es' if len(matches) != 1 else ''} • /search or /help command:<name> for details",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
