"""/tools favorite_* — pin slash commands for one-tap re-use (#14).

Stored in ``guild_settings`` under the key ``user_favorites:{user_id}`` as a
JSON list of ``"economy daily"``-style command paths so the existing settings
cache + replication pipeline picks it up for free.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, success_embed, EMBED_COLORS
from core.mention_chat import _collect_command_paths
from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


MAX_FAVORITES = 15
_KEY_TMPL = "user_favorites:{uid}"


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
async def _load_favorites(guild_id: int, user_id: int) -> list[str]:
    raw = await get_guild_setting(guild_id, _KEY_TMPL.format(uid=user_id))
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if isinstance(x, str)]
    except (ValueError, TypeError):
        pass
    return []


async def _save_favorites(guild_id: int, user_id: int, favorites: list[str]) -> None:
    payload = json.dumps(favorites[:MAX_FAVORITES])
    await set_guild_setting(guild_id, _KEY_TMPL.format(uid=user_id), payload)


def _normalize(path: str) -> str:
    return " ".join(str(path or "").strip().lstrip("/").split())


# ---------------------------------------------------------------------------
# Autocomplete: surface known command paths
# ---------------------------------------------------------------------------
async def _command_path_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    typed = (current or "").lower().strip()
    try:
        paths = _collect_command_paths(interaction.client)
    except Exception:
        paths = []
    if not paths:
        return []
    if typed:
        scored = [p for p in paths if typed in p.lower()]
        scored.sort(key=lambda p: (not p.lower().startswith(typed), len(p)))
    else:
        scored = sorted(paths)
    return [app_commands.Choice(name=p[:100], value=p[:100]) for p in scored[:25]]


# ---------------------------------------------------------------------------
# Command setup
# ---------------------------------------------------------------------------
def setup(bot, group=None):
    add_cmd = (
        group.command(name="favorite_add", description="Pin a slash command to your personal favorites list.")
        if group
        else bot.tree.command(name="favorite_add", description="Pin a slash command to your personal favorites list.")
    )
    rm_cmd = (
        group.command(name="favorite_remove", description="Remove a slash command from your favorites.")
        if group
        else bot.tree.command(name="favorite_remove", description="Remove a slash command from your favorites.")
    )
    list_cmd = (
        group.command(name="favorites", description="Show your pinned slash commands.")
        if group
        else bot.tree.command(name="favorites", description="Show your pinned slash commands.")
    )

    @add_cmd
    @app_commands.describe(command="Slash command path, e.g. economy daily or warframe baro")
    @app_commands.autocomplete(command=_command_path_autocomplete)
    async def favorite_add(interaction: discord.Interaction, command: str):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Server only", "Use this inside a server.", category="warning", client=interaction.client),
                ephemeral=True,
            )
        path = _normalize(command)
        if not path:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid command", "Provide a slash command path like `economy daily`.", category="warning", client=interaction.client),
                ephemeral=True,
            )

        # Validate against the live tree so we never pin a typo'd or removed command.
        try:
            known = {p.lower() for p in _collect_command_paths(interaction.client)}
        except Exception:
            known = set()
        if known and path.lower() not in known:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Unknown command",
                    f"`/{path}` isn't a registered slash command. Pick one from the autocomplete dropdown.",
                    category="warning",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        favs = await _load_favorites(interaction.guild.id, interaction.user.id)
        if path.lower() in (f.lower() for f in favs):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "ℹ️ Already pinned",
                    f"`/{path}` is already in your favorites.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        if len(favs) >= MAX_FAVORITES:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Favorites full",
                    f"You can pin at most **{MAX_FAVORITES}** commands. Remove one with `/tools favorite_remove` first.",
                    category="warning",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        favs.append(path)
        await _save_favorites(interaction.guild.id, interaction.user.id, favs)
        await interaction.response.send_message(
            embed=success_embed(
                "Pinned!",
                f"Added `/{path}` to your favorites ({len(favs)}/{MAX_FAVORITES}).\nView them with `/tools favorites`.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    async def _saved_favorites_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []
        favs = await _load_favorites(interaction.guild.id, interaction.user.id)
        typed = (current or "").lower().strip()
        if typed:
            favs = [f for f in favs if typed in f.lower()]
        return [app_commands.Choice(name=f[:100], value=f[:100]) for f in favs[:25]]

    @rm_cmd
    @app_commands.describe(command="Pinned command to remove")
    @app_commands.autocomplete(command=_saved_favorites_autocomplete)
    async def favorite_remove(interaction: discord.Interaction, command: str):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Server only", "Use this inside a server.", category="warning", client=interaction.client),
                ephemeral=True,
            )
        path = _normalize(command)
        favs = await _load_favorites(interaction.guild.id, interaction.user.id)
        new_favs = [f for f in favs if f.lower() != path.lower()]
        if len(new_favs) == len(favs):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "ℹ️ Not pinned",
                    f"`/{path}` isn't in your favorites.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await _save_favorites(interaction.guild.id, interaction.user.id, new_favs)
        await interaction.response.send_message(
            embed=success_embed(
                "Removed",
                f"`/{path}` is no longer in your favorites ({len(new_favs)}/{MAX_FAVORITES}).",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @list_cmd
    async def favorites_list(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Server only", "Use this inside a server.", category="warning", client=interaction.client),
                ephemeral=True,
            )
        favs = await _load_favorites(interaction.guild.id, interaction.user.id)
        if not favs:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "⭐ Your favorites are empty",
                    "Pin a command with `/tools favorite_add command:economy daily`.\n"
                    "Then run this command to see your shortcuts.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = [f"`{i+1:>2}.` `/{path}`" for i, path in enumerate(favs)]
        embed = obsidian_embed(
            f"⭐ Your favorites ({len(favs)}/{MAX_FAVORITES})",
            "\n".join(lines) + "\n\n-# Use `/tools favorite_remove` to drop one.",
            color=EMBED_COLORS["general"],
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
