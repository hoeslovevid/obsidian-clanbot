"""Quick-launch menu for common member commands."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_history import get_recent_commands
from core.command_shortcuts import find_tree_command
from core.utils import obsidian_embed, EMBED_COLORS

# (label, emoji, command path, hint for parameterized commands)
MENU_ITEMS: list[tuple[str, str, list[str], str | None]] = [
    ("Claim daily coins", "🎁", ["daily"], None),
    ("My profile", "👤", ["profile"], None),
    ("Quick snapshot (me)", "📊", ["me"], None),
    ("My wallet", "💼", ["economy", "wallet"], None),
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

# Extra lookup paths for safe no-arg auto-invoke (shortcut + nested)
AUTO_INVOKE_ALIASES: dict[str, list[list[str]]] = {
    "daily": [["daily"], ["economy", "daily"]],
    "help": [["help"], ["general", "help"]],
    "baro": [["baro"], ["warframe", "baro"]],
    "profile": [["profile"], ["general", "profile"]],
    "me": [["me"], ["general", "me"]],
    "search": [["search"], ["general", "help_search"]],
    "wallet": [["economy", "wallet"]],
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
        recent: list[tuple[str, str]],
        menu_offset: int,
    ):
        options: list[discord.SelectOption] = []
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
        self.recent = recent
        self.menu_offset = menu_offset

    async def callback(self, interaction: discord.Interaction):
        raw = self.values[0]
        if raw.startswith("recent:"):
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
    def __init__(self, bot: discord.Client, *, recent: list[tuple[str, str]]):
        super().__init__(timeout=120)
        self.add_item(QuickMenuSelect(bot, recent=recent, menu_offset=len(recent)))


def setup(bot, group=None):
    """Register top-level /menu only (discoverability)."""

    async def menu_impl(interaction: discord.Interaction):
        recent: list[tuple[str, str]] = []
        if interaction.guild:
            recent = await get_recent_commands(interaction.guild.id, interaction.user.id, limit=5)

        recent_blurb = ""
        if recent:
            recent_blurb = "**Recent** — " + " · ".join(f"`/{cmd}`" for cmd, _ in recent) + "\n\n"

        desc = (
            recent_blurb
            + "**Quick start** — pick an action below, or type these shortcuts directly:\n\n"
            "👤 **Me** — `/daily` · `/profile` · `/wallet` · `/me` · `/preferences`\n"
            "🎮 **Warframe** — `/baro` · `/fissures` · `/lfg` · `/trade`\n"
            "👥 **Community** — `/ticket` · `/case` · `/poll`\n"
            "🔍 **Find anything** — `/search` · `/help` · `/favorites` · `/recent`\n"
        )
        embed = obsidian_embed(
            "⚡ Quick Menu",
            desc,
            color=EMBED_COLORS["community"],
            footer="Shortcuts work from any channel • Mod tools: /help → Moderation",
            client=interaction.client,
        )
        await interaction.response.send_message(
            embed=embed,
            view=QuickMenuView(bot, recent=recent),
            ephemeral=True,
        )

    @app_commands.command(name="menu", description="Quick menu — daily, profile, baro, ticket, trade, and more.")
    async def menu_top(interaction: discord.Interaction):
        await menu_impl(interaction)

    try:
        bot.tree.add_command(menu_top)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("[menu] top-level /menu not registered: %s", e)
