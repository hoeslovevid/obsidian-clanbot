"""Quick-launch menu for common member commands."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from commands.general.favorites import get_user_favorites
from core.command_history import get_recent_commands
from core.command_shortcuts import find_tree_command
from core.embed_templates import embed_template
from core.utils import obsidian_embed, EMBED_COLORS
from core.config import BOT_VERSION
from core.changelog import get_latest_changelog_entry
from database import get_guild_setting, set_guild_setting

# (label, emoji, command path, hint for parameterized commands)
MENU_ITEMS: list[tuple[str, str, list[str], str | None]] = [
    ("Claim hub", "💰", ["claim"], None),
    ("Claim daily coins", "🎁", ["daily"], None),
    ("My cooldowns", "⏳", ["cooldowns"], None),
    ("My profile", "👤", ["profile"], None),
    ("Quick snapshot (me)", "📊", ["me"], None),
    ("My wallet", "💼", ["economy", "wallet"], None),
    ("Warframe notify setup", "🔔", ["wfnotify", "configure"], None),
    ("Baro Ki'Teer", "🛒", ["baro"], None),
    ("Void fissures", "💎", ["fissures"], None),
    ("Post LFG", "🤝", ["lfg", "lfg"], "Use **`/lfg`** — pick mission type and player count."),
    ("Open ticket", "🎫", ["ticket"], "Use **`/ticket`** — add a short subject."),
    ("Post trade", "💼", ["trade"], "Use **`/trade`** — item name, WTS or WTB."),
    ("Case status", "📋", ["case"], "Use **`/case`** — your case ID (e.g. OBS-...)."),
    ("Create poll", "📊", ["poll"], "Use **`/poll`** — question, options, optional duration."),
    ("Browse all commands", "📖", ["help"], None),
    ("Search commands", "🔍", ["search"], "Use **`/search`** — keyword like `pet`, `baro`, or `ticket`."),
]

AUTO_INVOKE_ALIASES: dict[str, list[list[str]]] = {
    "daily": [["daily"], ["economy", "daily"]],
    "claim": [["claim"]],
    "cooldowns": [["cooldowns"], ["economy", "cooldowns"]],
    "help": [["help"], ["general", "help"]],
    "baro": [["baro"], ["warframe", "baro"]],
    "profile": [["profile"], ["general", "profile"]],
    "me": [["me"], ["general", "me"]],
    "search": [["search"], ["general", "help_search"]],
    "wallet": [["economy", "wallet"]],
    "configure": [["wfnotify", "configure"]],
}


def _resolve_command(bot: discord.Client, path: list[str], guild: discord.Guild | None):
    aliases = AUTO_INVOKE_ALIASES.get(path[-1], [path]) if path else [path]
    for candidate in aliases:
        cmd = find_tree_command(bot, candidate, guild=guild)
        if cmd is not None:
            return cmd, candidate
    return None, path


class QuickMenuSelect(discord.ui.Select):
    def __init__(
        self,
        bot: discord.Client,
        *,
        favorites: list[str],
        recent: list[tuple[str, str]],
        menu_offset: int,
    ):
        options: list[discord.SelectOption] = []
        for i, cmd_path in enumerate(favorites):
            label = f"★ {cmd_path}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    emoji="⭐",
                    value=f"fav:{i}",
                    description="Pinned favorite"[:100],
                )
            )
        for i, (cmd_path, _at) in enumerate(recent):
            label = f"Recent: {cmd_path}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    emoji="🕐",
                    value=f"recent:{i}",
                    description="Run again"[:100],
                )
            )
        for i, (label, emoji, _path, _hint) in enumerate(MENU_ITEMS):
            options.append(
                discord.SelectOption(label=label[:100], emoji=emoji, value=str(menu_offset + i))
            )
        super().__init__(
            placeholder="Pick an action…",
            options=options[:25],
            min_values=1,
            max_values=1,
        )
        self.bot = bot
        self.favorites = favorites
        self.recent = recent
        self.menu_offset = menu_offset

    async def callback(self, interaction: discord.Interaction):
        raw = self.values[0]
        if raw.startswith("fav:"):
            idx = int(raw.split(":", 1)[1])
            if idx < 0 or idx >= len(self.favorites):
                return await interaction.response.send_message("Favorite not found.", ephemeral=True)
            path = self.favorites[idx].split()
            label = f"/{self.favorites[idx]}"
            hint = None
        elif raw.startswith("recent:"):
            idx = int(raw.split(":", 1)[1])
            if idx < 0 or idx >= len(self.recent):
                return await interaction.response.send_message("Recent entry not found.", ephemeral=True)
            path = self.recent[idx][0].split()
            label = f"/{self.recent[idx][0]}"
            hint = None
        else:
            idx = int(raw) - self.menu_offset
            if idx < 0 or idx >= len(MENU_ITEMS):
                return await interaction.response.send_message("Invalid selection.", ephemeral=True)
            label, _emoji, path, hint = MENU_ITEMS[idx]

        if hint:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    label,
                    hint + "\n\nOr browse everything with **`/menu`** → Browse all commands.",
                    color=EMBED_COLORS["general"],
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        cmd, lookup_path = _resolve_command(self.bot, path, interaction.guild)
        if isinstance(cmd, app_commands.Command):
            required = [p for p in cmd.parameters if p.required]
            if not required:
                await cmd.callback(interaction)
                return
            slash = "/" + " ".join(lookup_path)
            param_hint = ", ".join(f"`{p.name}`" for p in required[:3])
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    label,
                    f"Run {slash} — needs: {param_hint}",
                    color=EMBED_COLORS["general"],
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        slash = "/" + " ".join(path)
        await interaction.response.send_message(
            embed=obsidian_embed(
                label,
                f"Run {slash} to continue.",
                color=EMBED_COLORS["general"],
                client=interaction.client,
            ),
            ephemeral=True,
        )


class QuickMenuView(discord.ui.View):
    def __init__(
        self,
        bot: discord.Client,
        *,
        favorites: list[str],
        recent: list[tuple[str, str]],
    ):
        super().__init__(timeout=120)
        offset = len(favorites) + len(recent)
        self.add_item(QuickMenuSelect(bot, favorites=favorites, recent=recent, menu_offset=offset))


def setup(bot, group=None):
    """Register top-level /menu only (discoverability)."""

    async def menu_impl(interaction: discord.Interaction):
        favorites: list[str] = []
        recent: list[tuple[str, str]] = []
        if interaction.guild:
            favorites = await get_user_favorites(interaction.guild.id, interaction.user.id)
            recent = await get_recent_commands(interaction.guild.id, interaction.user.id, limit=5)

        fav_blurb = ""
        if favorites:
            fav_blurb = (
                "**Your favorites** — "
                + " · ".join(f"`/{cmd}`" for cmd in favorites[:6])
                + "\n\n"
            )

        recent_blurb = ""
        if recent:
            recent_blurb = (
                "**Continue where you left off** — "
                + " · ".join(f"`/{cmd}`" for cmd, _ in recent)
                + "\n\n"
            )

        whats_new_blurb = ""
        if interaction.guild:
            try:
                key = f"menu_last_version:{interaction.user.id}"
                last_ver = await get_guild_setting(interaction.guild.id, key) or ""
                if last_ver != BOT_VERSION:
                    entry = get_latest_changelog_entry()
                    bullets = entry.get("changes") or []
                    if bullets:
                        whats_new_blurb = (
                            f"**What's new in v{BOT_VERSION}** — "
                            + " · ".join(str(b)[:80] for b in bullets[:3])
                            + f"\n_Full notes: `/whatsnew`_\n\n"
                        )
                    await set_guild_setting(interaction.guild.id, key, BOT_VERSION)
            except Exception:
                pass

        desc = (
            whats_new_blurb
            + fav_blurb
            + recent_blurb
            + "**Quick start** — pick an action below, or type these shortcuts directly:\n\n"
            "👤 **Me** — `/daily` · `/profile` · `/wallet` · `/me` · `/preferences`\n"
            "🎮 **Warframe** — `/baro` · `/fissures` · `/wfnotify configure` · `/trade`\n"
            "👥 **Community** — `/ticket` · `/case` · `/poll`\n"
            "🔍 **Find anything** — `/search` · `/help` · `/favorites` · `/recent`\n"
        )

        if interaction.guild and not favorites:
            desc += "\n_Pin commands with **`/favorite_add`** — they appear at the top of this menu._"

        embed = embed_template(
            "showcase",
            "⚡ Quick Menu",
            desc,
            category="community",
            footer="Shortcuts work from any channel • Mod tools: /help → Staff tools",
            client=interaction.client,
        )
        view = QuickMenuView(bot, favorites=favorites, recent=recent)

        async def _open_classic_picker(inter: discord.Interaction):
            await inter.response.edit_message(embed=embed, view=view)

        async def _back_to_menu_home(inter: discord.Interaction):
            from core.menu_layout import MenuHomeLayout

            layout = MenuHomeLayout(
                recent_blurb=fav_blurb + recent_blurb,
                on_open_picker=_open_v2_picker,
            )
            await inter.response.edit_message(view=layout)

        async def _open_v2_picker(inter: discord.Interaction):
            from core.menu_layout import MenuPickerLayout, menu_layout_v2_enabled

            if menu_layout_v2_enabled():
                try:
                    layout = MenuPickerLayout(
                        bot,
                        favorites=favorites,
                        recent=recent,
                        on_back=_back_to_menu_home,
                    )
                    await inter.response.edit_message(view=layout)
                    return
                except Exception:
                    pass
            await _open_classic_picker(inter)

        from core.menu_layout import menu_layout_v2_enabled, MenuHomeLayout

        if menu_layout_v2_enabled():
            try:
                layout = MenuHomeLayout(
                    recent_blurb=fav_blurb + recent_blurb,
                    on_open_picker=_open_v2_picker,
                )
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            except Exception:
                pass

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="menu", description="Quick menu — favorites, daily, profile, baro, ticket, trade, and more.")
    async def menu_top(interaction: discord.Interaction):
        await menu_impl(interaction)

    try:
        bot.tree.add_command(menu_top)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("[menu] top-level /menu not registered: %s", e)
