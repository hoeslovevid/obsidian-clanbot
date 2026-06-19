"""Command popularity reports for mod health dashboards."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_tree import tree_root_commands


async def guild_top_commands(guild_id: int, *, limit: int = 8) -> list[tuple[str, int]]:
    from database import top_commands

    return await top_commands(guild_id, limit=limit)


def _collect_tree_paths(bot: discord.Client) -> set[str]:
    paths: set[str] = set()

    def walk(cmd, prefix: str = "") -> None:
        name = f"{prefix} {cmd.name}".strip() if prefix else cmd.name
        if isinstance(cmd, app_commands.Group):
            for sub in cmd.commands:
                walk(sub, name)
        else:
            paths.add(name)

    for cmd in tree_root_commands(bot):
        walk(cmd)
    return paths


async def never_used_commands(
    bot: discord.Client,
    guild_id: int,
    *,
    limit: int = 8,
) -> list[str]:
    """Registered slash paths with zero recorded uses in this guild."""
    registered = _collect_tree_paths(bot)
    used = {name for name, _count in await guild_top_commands(guild_id, limit=500)}
    unused = sorted(registered - used, key=str.lower)
    return unused[:limit]


def format_usage_field(
    top: list[tuple[str, int]],
    *,
    unused: list[str],
) -> str:
    lines: list[str] = []
    if top:
        lines.append("**Top commands (this guild)**")
        lines.extend(f"• `/{name}` — {count:,}" for name, count in top[:6])
    else:
        lines.append("_No command usage recorded yet — heatmap fills as members use slash commands._")
    if unused:
        lines.append("")
        lines.append(f"**Never used here** ({len(unused)}+)")
        lines.append(", ".join(f"`/{n}`" for n in unused[:6]))
    prune = format_prune_hint(unused)
    if prune:
        lines.append("")
        lines.append(prune)
    return "\n".join(lines)


def format_prune_hint(unused: list[str], *, min_count: int = 8) -> str | None:
    """Suggest pruning when many registered commands have zero uses."""
    if len(unused) < min_count:
        return None
    sample = ", ".join(f"`/{n}`" for n in unused[:4])
    return (
        f"💡 **Prune candidates:** {len(unused)}+ commands never used here "
        f"({sample}…). Consider hiding niche commands behind `/menu` or removing duplicates."
    )
