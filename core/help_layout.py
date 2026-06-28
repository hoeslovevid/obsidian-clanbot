"""Discord Components V2 help hub (LayoutView pilot)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import app_commands, ui  # type: ignore

from core.config import BOT_WEBSITE
from core.command_surface import essentials_help_block
from core.command_tree import find_tree_group
from core.layout_v2 import ACCENT_DEFAULT, footer_display, make_container, v2_enabled
from core.presence import website_host


def help_layout_v2_enabled() -> bool:
    return v2_enabled()


class HelpHomeLayout(ui.LayoutView):
    """V2 layout splash for /help — use **Browse categories** for the category picker."""

    def __init__(
        self,
        *,
        is_mod: bool,
        on_browse: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=300)
        self._on_browse = on_browse

        body = essentials_help_block().replace("**", "")
        lines = body.split("\n")
        if lines and lines[0].startswith("Discovery 12"):
            lines[0] = "## " + lines[0]
        lines.insert(0, "## Command Reference")

        if is_mod:
            lines.append("**Staff:** `/admin dashboard` · `/mod purge` · `/staff sync_commands`")
        lines.append("")
        lines.append(footer_display("help"))

        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))

        row = ui.ActionRow()
        row.add_item(BrowseCategoriesButton(on_browse))
        if BOT_WEBSITE:
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
        self.add_item(row)


class BrowseCategoriesButton(ui.Button):
    def __init__(self, on_browse: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Browse categories", style=discord.ButtonStyle.primary, emoji="📋")
        self._on_browse = on_browse

    async def callback(self, interaction: discord.Interaction):
        await self._on_browse(interaction)


def _group_options(bot, is_mod: bool) -> list[discord.SelectOption]:
    from core.command_search import MOD_ONLY_GROUPS

    group_definitions = {
        "general": ("General", "Help, profile, bio, preferences", "📋"),
        "economy": ("Economy", "Balance, daily, bounties, gambling", "💰"),
        "pets": ("Pets", "Pet shop, care, battles", "🐾"),
        "store": ("Shop", "Browse and buy server items", "🛒"),
        "xp": ("XP", "XP check, leaderboard, settings", "✨"),
        "tools": ("Tools", "Coinflip, achievements, stats", "🔧"),
        "warframe": ("Warframe", "Baro, cycles, alerts, builds", "🎮"),
        "wfnotify": ("Warframe Notify", "Configure alerts panel", "🔔"),
        "lfg": ("LFG", "Looking-for-group posts", "🤝"),
        "community": ("Community", "Tickets, suggestions, applications", "👥"),
        "events": ("Events", "Server events and schedules", "📅"),
        "trading": ("Trading", "Market prices and trading post", "💼"),
        "mod": ("Moderation", "Purge, snipe, lock, schedule", "🛡️"),
        "automod": ("AutoMod", "Spam, caps, links, mentions", "🤖"),
        "warn": ("Warnings", "Warn, templates, mod notes", "🛑"),
        "roletools": ("Role Tools", "Reaction roles, level roles", "🎭"),
        "admin": ("Admin", "Backups, dashboards, applications", "🗄️"),
        "staff": ("Staff", "Sync, webhooks, analytics utilities", "🔧"),
        "giveaways": ("Giveaways", "Create and manage giveaways", "🎁"),
        "updates": ("Updates", "Update log and version management", "📝"),
        "music": ("Music", "Play music in voice channels", "🎵"),
    }
    options: list[discord.SelectOption] = []
    from core.command_tree import tree_root_commands

    for cmd in tree_root_commands(bot):
        if not isinstance(cmd, app_commands.Group):
            continue
        if cmd.name not in group_definitions:
            continue
        if not is_mod and cmd.name in MOD_ONLY_GROUPS:
            continue
        label, desc, emoji = group_definitions[cmd.name]
        options.append(
            discord.SelectOption(label=label, description=desc[:100], emoji=emoji, value=cmd.name)
        )
    return options


_QUICK_PATHS: tuple[tuple[str, str], ...] = (
    ("👋 New here", "general"),
    ("🎮 Warframe", "warframe"),
    ("💰 Economy", "economy"),
    ("🛡️ Staff", "admin"),
)


async def build_category_text(
    bot,
    group: app_commands.Group,
    *,
    guild_id: Optional[int],
    is_mod: bool,
    page: int = 0,
    per_page: int = 15,
) -> tuple[str, int]:
    from commands.general.help import _collect_group_commands
    from core.command_search import filter_entries_for_guild

    collected = _collect_group_commands(group, [group.name])
    if guild_id:
        collected = await filter_entries_for_guild(guild_id, collected, is_mod=is_mod)
    if not collected:
        return "No commands available in this group.", 1
    lines = [f"• `/{path}` — {desc}" for path, desc in collected]
    total_pages = max(1, (len(lines) + per_page - 1) // per_page)
    page_idx = max(0, min(page, total_pages - 1))
    start = page_idx * per_page
    chunk = lines[start : start + per_page]
    header = f"## 📋 {group.name.title()} Commands"
    if total_pages > 1:
        header += f"\n_Page {page_idx + 1} of {total_pages}_"
    body = header + "\n\n" + "\n".join(chunk)
    if start + per_page < len(lines):
        body += f"\n\n_+{len(lines) - start - per_page} more — use pagination_"
    body += f"\n\n{footer_display('help')}"
    return body, total_pages


class HelpBrowseLayout(ui.LayoutView):
    """V2 category browser with select + pagination."""

    def __init__(
        self,
        bot,
        *,
        is_mod: bool,
        guild_id: Optional[int],
        group: Optional[app_commands.Group] = None,
        page: int = 0,
        on_home: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        body: str = "",
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.is_mod = is_mod
        self.guild_id = guild_id
        self.current_group = group
        self.current_page = page
        self._on_home = on_home

        if not body:
            body = "## Browse by category\n\nPick a group from the dropdown below."
            body += f"\n\n{footer_display('help')}"
        self.add_item(make_container([body], accent=ACCENT_DEFAULT))

        row = ui.ActionRow()
        row.add_item(HelpCategorySelect(bot, parent=self, is_mod=is_mod))
        self.add_item(row)

        if not group:
            quick = ui.ActionRow()
            for label, key in _QUICK_PATHS:
                if key == "admin" and not is_mod:
                    continue
                quick.add_item(HelpQuickPathButton(label, key, parent=self))
            if quick.children:
                self.add_item(quick)

        if group:
            nav = ui.ActionRow()
            nav.add_item(HelpPageButton("◀ Prev", -1, self))
            nav.add_item(HelpPageButton("Next ▶", 1, self))
            if on_home:
                nav.add_item(HelpHomeButton(on_home))
            self.add_item(nav)

    async def rebuild(self, interaction: discord.Interaction, *, group: app_commands.Group, page: int):
        text, _pages = await build_category_text(
            self.bot, group, guild_id=self.guild_id, is_mod=self.is_mod, page=page
        )
        new_layout = HelpBrowseLayout(
            self.bot,
            is_mod=self.is_mod,
            guild_id=self.guild_id,
            group=group,
            page=page,
            on_home=self._on_home,
            body=text,
        )
        await interaction.response.edit_message(view=new_layout)


class HelpCategorySelect(ui.Select):
    def __init__(self, bot, *, parent: HelpBrowseLayout, is_mod: bool):
        super().__init__(
            placeholder="Select a command group…",
            options=_group_options(bot, is_mod)[:25],
            min_values=1,
            max_values=1,
        )
        self._parent = parent
        self._bot = bot

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        group = find_tree_group(self._bot, name, guild=interaction.guild)
        if not group:
            return await interaction.response.send_message("Group not found.", ephemeral=True)
        if interaction.guild:
            try:
                from commands.general.onboarding import record_onboarding_step

                await record_onboarding_step(interaction.guild.id, interaction.user.id, "browse_help")
            except Exception:
                pass
        await self._parent.rebuild(interaction, group=group, page=0)


class HelpQuickPathButton(ui.Button):
    def __init__(self, label: str, group_key: str, *, parent: HelpBrowseLayout):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self._group_key = group_key
        self._parent = parent

    async def callback(self, interaction: discord.Interaction):
        group = find_tree_group(self._parent.bot, self._group_key, guild=interaction.guild)
        if not group:
            from core.reply_helpers import reply_error
            return await reply_error(
                interaction, "Not available", f"Group `{self._group_key}` isn't registered."
            )
        if interaction.guild:
            try:
                from commands.general.onboarding import record_onboarding_step

                await record_onboarding_step(interaction.guild.id, interaction.user.id, "browse_help")
            except Exception:
                pass
        await self._parent.rebuild(interaction, group=group, page=0)


class HelpPageButton(ui.Button):
    def __init__(self, label: str, delta: int, parent: HelpBrowseLayout):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._delta = delta
        self._parent = parent

    async def callback(self, interaction: discord.Interaction):
        if not self._parent.current_group:
            return await interaction.response.defer()
        new_page = max(0, self._parent.current_page + self._delta)
        await self._parent.rebuild(interaction, group=self._parent.current_group, page=new_page)


class HelpHomeButton(ui.Button):
    def __init__(self, on_home: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Home", style=discord.ButtonStyle.secondary, emoji="🏠")
        self._on_home = on_home

    async def callback(self, interaction: discord.Interaction):
        await self._on_home(interaction)


class HelpSearchLayout(ui.LayoutView):
    """Lightweight V2 search results."""

    def __init__(self, *, query: str, lines: list[str], match_count: int, suggestion: Optional[str] = None):
        super().__init__(timeout=120)
        body_lines = [f"## 🔍 Command search — `{query}`", ""] + lines[:12]
        if suggestion:
            body_lines.append(f"\n_Did you mean `/{suggestion}`?_")
        body_lines.append("")
        body_lines.append(
            f"-# {match_count} match{'es' if match_count != 1 else ''} · /search or /help command:<name> for details"
        )
        self.add_item(make_container(body_lines, accent=ACCENT_DEFAULT))
