"""Consistent empty-state embeds for lists and browse commands."""
from __future__ import annotations

import discord

from core.embed_templates import embed_template


def empty_state_embed(
    title: str,
    body: str,
    *,
    category: str = "general",
    action_hint: str | None = None,
    client=None,
) -> discord.Embed:
    desc = body
    if action_hint:
        desc += f"\n\n_{action_hint}_"
    return embed_template(
        "showcase",
        title,
        desc,
        category=category,
        client=client,
        brand=True,
    )
