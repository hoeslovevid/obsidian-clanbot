"""Pin your most-used slash commands for quick access."""
from __future__ import annotations

import json
import logging

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_search import collect_command_entries
from core.utils import obsidian_embed, error_embed, success_embed, EMBED_COLORS
from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

MAX_FAVORITES = 8
_KEY_PREFIX = "cmd_favorites:"


def _favorites_key(user_id: int) -> str:
    return f"{_KEY_PREFIX}{user_id}"


async def get_user_favorites(guild_id: int, user_id: int) -> list[str]:
    raw = await get_guild_setting(guild_id, _favorites_key(user_id))
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(p) for p in data[:MAX_FAVORITES]]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


async def set_user_favorites(guild_id: int, user_id: int, paths: list[str]) -> None:
    clean = paths[:MAX_FAVORITES]
    await set_guild_setting(guild_id, _favorites_key(user_id), json.dumps(clean))


async def _command_path_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    entries = collect_command_entries(interaction.client)
    current_lower = (current or "").lower()
    choices: list[app_commands.Choice[str]] = []
    for path, desc in entries:
        if current_lower and current_lower not in path.lower() and current_lower not in desc.lower():
            continue
        label = path if len(path) <= 100 else path[:97] + "..."
        choices.append(app_commands.Choice(name=label, value=path))
        if len(choices) >= 25:
            break
    return choices


def setup(bot, group=None):
    """Top-level only — ``/tools`` is at Discord's 25-subcommand cap."""
    group = None  # force /favorites, /favorite_add, /favorite_remove

    async def _favorites_impl(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        favs = await get_user_favorites(interaction.guild.id, interaction.user.id)
        if not favs:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "⭐ Your Favorites",
                    "You haven't pinned any commands yet.\n\n"
                    "Add one with **`/favorite_add`** — e.g. `economy daily`, `baro`, `ticket`.\n\n"
                    "**Quick shortcuts:** `/daily` `/profile` `/baro` `/search` `/menu`",
                    color=EMBED_COLORS["general"],
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        from core.command_mentions import command_mention

        lines = [f"{i + 1}. {command_mention(path, fallback=f'`/{path}`')}" for i, path in enumerate(favs)]
        embed = obsidian_embed(
            "⭐ Your Favorites",
            "\n".join(lines) + f"\n\n_{len(favs)}/{MAX_FAVORITES} slots used_",
            color=EMBED_COLORS["general"],
            footer="Tip: type / then the command name — favorites are for quick reference",
            client=interaction.client,
        )
        from core.compact_layouts import FavoritesLayout
        from core.help_layout import help_layout_v2_enabled

        if help_layout_v2_enabled():
            try:
                layout = FavoritesLayout(
                    body="\n".join(lines),
                    slots_used=len(favs),
                    max_slots=MAX_FAVORITES,
                )
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            except Exception:
                pass
        await interaction.response.send_message(embed=embed, ephemeral=True)

    fav_decorator = (
        group.command(name="favorites", description="View your pinned favorite commands.")
        if group
        else bot.tree.command(name="favorites", description="View your pinned favorite commands.")
    )

    @fav_decorator
    async def favorites(interaction: discord.Interaction):
        await _favorites_impl(interaction)

    add_decorator = (
        group.command(name="favorite_add", description="Pin a command to your favorites list.")
        if group
        else bot.tree.command(name="favorite_add", description="Pin a command to your favorites list.")
    )

    @add_decorator
    @app_commands.autocomplete(command=_command_path_autocomplete)
    @app_commands.describe(command="Command path (e.g. economy daily, warframe baro, ticket)")
    async def favorite_add(interaction: discord.Interaction, command: str):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        path = (command or "").strip().lower()
        valid = {p for p, _ in collect_command_entries(interaction.client)}
        if path not in valid:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Unknown command",
                    f"`{path}` isn't a registered command.\nUse **`/search`** to find the right path.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        favs = await get_user_favorites(interaction.guild.id, interaction.user.id)
        if path in favs:
            return await interaction.response.send_message(
                embed=error_embed("Already pinned", f"`/{path}` is already in your favorites.", client=interaction.client),
                ephemeral=True,
            )
        if len(favs) >= MAX_FAVORITES:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Favorites full",
                    f"You can pin up to **{MAX_FAVORITES}** commands. Remove one with **`/favorite_remove`** first.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        favs.append(path)
        await set_user_favorites(interaction.guild.id, interaction.user.id, favs)
        await interaction.response.send_message(
            embed=success_embed("Pinned!", f"Added **`/{path}`** to your favorites ({len(favs)}/{MAX_FAVORITES}).", client=interaction.client),
            ephemeral=True,
        )

    remove_decorator = (
        group.command(name="favorite_remove", description="Remove a command from your favorites.")
        if group
        else bot.tree.command(name="favorite_remove", description="Remove a command from your favorites.")
    )

    @remove_decorator
    @app_commands.autocomplete(command=_command_path_autocomplete)
    @app_commands.describe(command="Command path to unpin")
    async def favorite_remove(interaction: discord.Interaction, command: str):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        path = (command or "").strip().lower()
        favs = await get_user_favorites(interaction.guild.id, interaction.user.id)
        if path not in favs:
            return await interaction.response.send_message(
                embed=error_embed("Not pinned", f"`/{path}` isn't in your favorites.", client=interaction.client),
                ephemeral=True,
            )
        favs = [p for p in favs if p != path]
        await set_user_favorites(interaction.guild.id, interaction.user.id, favs)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Unpinned **`/{path}`**.", client=interaction.client),
            ephemeral=True,
        )
