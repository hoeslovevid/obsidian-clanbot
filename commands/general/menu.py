"""Quick-launch menu for common member commands."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_shortcuts import find_tree_command
from core.utils import obsidian_embed, EMBED_COLORS

# (label, emoji, command path, hint for parameterized commands)
MENU_ITEMS: list[tuple[str, str, list[str], str | None]] = [
    ("Claim daily coins", "🎁", ["daily"], None),
    ("My profile", "👤", ["profile"], None),
    ("Quick snapshot (me)", "📊", ["me"], None),
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


class QuickMenuSelect(discord.ui.Select):
    def __init__(self, bot: discord.Client):
        options = [
            discord.SelectOption(label=label[:100], emoji=emoji, value=str(i))
            for i, (label, emoji, _path, _hint) in enumerate(MENU_ITEMS)
        ]
        super().__init__(
            placeholder="Pick an action…",
            options=options[:25],
            min_values=1,
            max_values=1,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        label, _emoji, path, hint = MENU_ITEMS[idx]
        # Top-level shortcut paths are single segment
        lookup_path = path
        cmd = find_tree_command(self.bot, lookup_path, guild=interaction.guild)
        if cmd is None and len(path) > 1:
            cmd = find_tree_command(self.bot, path, guild=interaction.guild)

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

        if isinstance(cmd, app_commands.Command):
            required = [p for p in cmd.parameters if p.required]
            if not required:
                await cmd.callback(interaction)
                return
            # Parameterized command — show slash hint
            slash = "/" + " ".join(path)
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
    def __init__(self, bot: discord.Client):
        super().__init__(timeout=120)
        self.add_item(QuickMenuSelect(bot))


def setup(bot, group=None):
    """Register top-level /menu only (discoverability)."""

    async def menu_impl(interaction: discord.Interaction):
        desc = (
            "**Quick start** — pick an action below, or type these shortcuts directly:\n\n"
            "👤 **Me** — `/daily` · `/profile` · `/me` · `/preferences`\n"
            "🎮 **Warframe** — `/baro` · `/fissures` · `/lfg` · `/trade`\n"
            "👥 **Community** — `/ticket` · `/case` · `/poll`\n"
            "🔍 **Find anything** — `/search` · `/help` · `/favorites`\n"
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
            view=QuickMenuView(bot),
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
