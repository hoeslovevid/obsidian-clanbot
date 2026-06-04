"""Show the user's last few slash commands with quick-run hints."""
from __future__ import annotations

from datetime import datetime, timezone

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_hints import COMMAND_HINTS
from core.command_history import get_recent_commands
from core.embed_templates import embed_template
from core.utils import error_embed


def _format_when(iso_ts: str) -> str:
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return f"<t:{int(dt.timestamp())}:R>"
    except Exception:
        return iso_ts[:16].replace("T", " ")


def _hint_for_command(cmd_path: str) -> str | None:
    tip = COMMAND_HINTS.get(cmd_path)
    if tip:
        return tip
    leaf = cmd_path.split()[-1] if cmd_path else ""
    return COMMAND_HINTS.get(leaf)


async def _recent_embed(interaction: discord.Interaction) -> discord.Embed:
    guild = interaction.guild
    user = interaction.user
    assert guild is not None

    recent = await get_recent_commands(guild.id, user.id, limit=5)
    if not recent:
        return embed_template(
            "showcase",
            "🕐 Recent Commands",
            "No recent commands yet.\n\nUse **`/menu`**, **`/search`**, or **`/help`** to get started — they'll show up here.",
            category="general",
            client=interaction.client,
            brand=True,
        )

    lines: list[str] = []
    for cmd_path, at in recent:
        slash = f"`/{cmd_path}`"
        when = _format_when(at)
        hint = _hint_for_command(cmd_path)
        block = f"{slash} · {when}"
        if hint:
            block += f"\n-# {hint}"
        lines.append(block)

    return embed_template(
        "showcase",
        "🕐 Recent Commands",
        "\n\n".join(lines),
        category="general",
        client=interaction.client,
        footer="Tap a command in chat or use /menu • Only you see this",
        brand=True,
    )


def setup(bot, group=None):
    """Register /recent (general subgroup + top-level shortcut)."""

    async def recent_impl(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Use this inside a server.", client=interaction.client),
                ephemeral=True,
            )
        embed = await _recent_embed(interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    if group:
        group.command(name="recent", description="Your last 5 slash commands with quick tips.")(recent_impl)

    shortcut = app_commands.Command(
        name="recent",
        description="Your last 5 slash commands with quick tips (shortcut).",
        callback=recent_impl,
    )
    try:
        bot.tree.add_command(shortcut)
    except Exception:
        pass
