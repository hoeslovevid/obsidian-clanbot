"""Discord Components V2 quick menu (LayoutView pilot)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import app_commands, ui  # type: ignore

from core.config import BOT_WEBSITE
from core.help_layout import help_layout_v2_enabled
from core.layout_v2 import ACCENT_DEFAULT, footer_display, make_container
from core.presence import website_host


def menu_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class MenuHomeLayout(ui.LayoutView):
    """V2 layout splash for /menu — use **Open picker** for the action select."""

    def __init__(
        self,
        *,
        recent_blurb: str,
        on_open_picker: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self._on_open_picker = on_open_picker

        lines = ["## Quick Menu"]
        if recent_blurb:
            lines.extend(["", recent_blurb.strip()])
        lines.extend(
            [
                "",
                "**8 essentials** — `/menu` · `/search` · `/status` · `/whatsnew`",
                "`/profile` · `/daily` · `/warframe hub` · `/ticket`",
                "",
                "Tap **Open picker** for favorites and quick actions.",
                "",
                footer_display("help"),
            ]
        )

        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))

        row = ui.ActionRow()
        row.add_item(OpenMenuPickerButton(on_open_picker))
        if BOT_WEBSITE:
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
        self.add_item(row)


class OpenMenuPickerButton(ui.Button):
    def __init__(self, on_open: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Open picker", style=discord.ButtonStyle.primary, emoji="⚡")
        self._on_open = on_open

    async def callback(self, interaction: discord.Interaction):
        await self._on_open(interaction)


class MenuPickerLayout(ui.LayoutView):
    """V2 quick menu with select — mirrors QuickMenuView."""

    def __init__(
        self,
        bot: discord.Client,
        *,
        favorites: list[str],
        recent: list[tuple[str, str]],
        on_back: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=120)
        lines = [
            "## ⚡ Quick Menu",
            "",
            "Pick an action below — favorites and recents appear first.",
            "",
            footer_display("help"),
        ]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        row = ui.ActionRow()
        row.add_item(_MenuPickerSelect(bot, favorites=favorites, recent=recent))
        self.add_item(row)
        if on_back:
            back_row = ui.ActionRow()
            back = ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="🏠")

            async def _back_cb(inter: discord.Interaction):
                await on_back(inter)

            back.callback = _back_cb  # type: ignore[assignment]
            back_row.add_item(back)
            self.add_item(back_row)


class _MenuPickerSelect(ui.Select):
    def __init__(
        self,
        bot: discord.Client,
        *,
        favorites: list[str],
        recent: list[tuple[str, str]],
    ):
        from commands.general.menu import MENU_ITEMS

        options: list[discord.SelectOption] = []
        menu_offset = len(favorites) + len(recent)
        for i, cmd_path in enumerate(favorites):
            options.append(
                discord.SelectOption(
                    label=f"★ {cmd_path}"[:100],
                    emoji="⭐",
                    value=f"fav:{i}",
                    description="Pinned favorite"[:100],
                )
            )
        for i, (cmd_path, _at) in enumerate(recent):
            options.append(
                discord.SelectOption(
                    label=f"Recent: {cmd_path}"[:100],
                    emoji="🕐",
                    value=f"recent:{i}",
                    description="Run again"[:100],
                )
            )
        for i, (label, emoji, _path, _hint) in enumerate(MENU_ITEMS):
            options.append(
                discord.SelectOption(label=label[:100], emoji=emoji, value=str(menu_offset + i))
            )
        super().__init__(placeholder="Pick an action…", options=options[:25], min_values=1, max_values=1)
        self.bot = bot
        self.favorites = favorites
        self.recent = recent
        self.menu_offset = menu_offset

    async def callback(self, interaction: discord.Interaction):
        from commands.general.menu import MENU_ITEMS, _resolve_command
        from core.utils import EMBED_COLORS, obsidian_embed

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
