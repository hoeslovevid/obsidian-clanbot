"""Right-click 'Explain command' helper (Item 63).

We try three strategies in order:

1. ``message.interaction_metadata.command_name`` (discord.py 2.4+) — most precise.
2. Footer / field text scan for ``/<path>``.
3. Fuzzy match against the embed title across all registered commands.
"""
from __future__ import annotations

import logging
import re
from difflib import get_close_matches
from typing import Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, error_embed, EMBED_FOOTER_DEFAULT

logger = logging.getLogger(__name__)


_COMMAND_TOKEN_RE = re.compile(r"/([\w_]+(?:\s+[\w_]+){0,2})")


def _all_command_paths(bot) -> list[str]:
    paths: list[str] = []

    def _walk(group, prefix: list[str]):
        for cmd in getattr(group, "commands", []):
            current = prefix + [cmd.name]
            if isinstance(cmd, app_commands.Group):
                _walk(cmd, current)
            else:
                paths.append(" ".join(current))

    try:
        for top in bot.tree.get_commands(guild=None):
            if isinstance(top, app_commands.Group):
                _walk(top, [top.name])
            else:
                paths.append(top.name)
    except Exception as e:
        logger.debug(f"[explain] tree walk failed: {e}")
    return paths


def _resolve_command(bot, parts: list[str]):
    """Drill down through bot.tree to find the command matching ``parts``."""
    try:
        commands_source = bot.tree.get_commands(guild=None)
        for cmd in commands_source:
            if cmd.name != parts[0]:
                continue
            if len(parts) == 1:
                return cmd
            if not isinstance(cmd, app_commands.Group):
                continue
            current = cmd
            for i in range(1, len(parts)):
                sub = next((c for c in current.commands if c.name == parts[i]), None)
                if not sub:
                    return None
                if i == len(parts) - 1:
                    return sub
                if isinstance(sub, app_commands.Group):
                    current = sub
                else:
                    return None
    except Exception as e:
        logger.debug(f"[explain] resolve failed: {e}")
    return None


def _scan_message_for_command(message: discord.Message) -> Optional[str]:
    """Scan footer/fields/title for a /command token."""
    haystack: list[str] = []
    for e in message.embeds:
        if e.footer and e.footer.text:
            haystack.append(e.footer.text)
        for f in e.fields:
            haystack.append(f.name)
            haystack.append(str(f.value))
        if e.description:
            haystack.append(e.description)
        if e.title:
            haystack.append(e.title)
    if message.content:
        haystack.append(message.content)
    for text in haystack:
        for m in _COMMAND_TOKEN_RE.finditer(text):
            candidate = m.group(1).strip()
            # only accept up to three tokens, lowercase
            parts = candidate.split()
            if 1 <= len(parts) <= 3:
                return " ".join(parts)
    return None


def _fuzzy_title_match(bot, message: discord.Message) -> Optional[str]:
    if not message.embeds or not message.embeds[0].title:
        return None
    title = re.sub(r"[^\w\s]", " ", message.embeds[0].title).lower()
    title_tokens = title.split()
    if not title_tokens:
        return None
    paths = _all_command_paths(bot)
    # Try matching the title (without leading emoji words) against command paths.
    candidates = []
    for path in paths:
        plast = path.split()[-1]
        if plast in title_tokens:
            candidates.append(path)
    if candidates:
        return candidates[0]
    # Last resort: full-title fuzzy.
    matches = get_close_matches(" ".join(title_tokens[:3]), [p.lower() for p in paths], n=1, cutoff=0.55)
    if matches:
        # Map back to original casing
        for p in paths:
            if p.lower() == matches[0]:
                return p
    return None


def _format_command_details(cmd, parts: list[str], client) -> discord.Embed:
    path = "/" + " ".join(parts)
    desc = (cmd.description or "_(no description)_") if hasattr(cmd, "description") else "_(no description)_"
    fields = [("Usage", f"`{path}`", False)]
    params = getattr(cmd, "parameters", None) or []
    if params:
        param_lines = []
        for p in params:
            req = "Required" if getattr(p, "required", False) else "Optional"
            param_lines.append(f"• `{p.name}` ({req}) — {p.description or 'No description'}")
        fields.append(("Parameters", "\n".join(param_lines)[:1024], False))
    return obsidian_embed(
        f"📖 {path}",
        desc,
        category="general",
        fields=fields,
        footer=f"Identified via context menu • {EMBED_FOOTER_DEFAULT}",
        client=client,
    )


class _RunHintView(discord.ui.View):
    def __init__(self, command_path: str):
        super().__init__(timeout=120)
        self.command_path = command_path

    @discord.ui.button(label="Run it now", style=discord.ButtonStyle.primary, emoji="▶️")
    async def run_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"Type `/` in any channel and pick **{self.command_path}** from the slash-command picker.",
            ephemeral=True,
        )


async def build_explanation(interaction: discord.Interaction, message: discord.Message):
    bot = interaction.client

    if not interaction.guild:
        return (
            error_embed("Invalid Context", "Use this in a server.", client=bot),
            discord.ui.View(),
        )

    # Strategy 1: interaction_metadata
    parts: Optional[list[str]] = None
    meta = getattr(message, "interaction_metadata", None)
    if meta is not None:
        name = getattr(meta, "command_name", None) or getattr(meta, "name", None)
        if name:
            parts = str(name).strip().split()

    # Strategy 2: scan footer/fields
    if not parts:
        token = _scan_message_for_command(message)
        if token:
            parts = token.split()

    # Strategy 3: fuzzy title match
    if not parts:
        guess = _fuzzy_title_match(bot, message)
        if guess:
            parts = guess.split()

    if not parts:
        return (
            obsidian_embed(
                "📖 Couldn't identify the command",
                "I couldn't tell which command produced this message. "
                "Try `/general help` (or `/help search`) for similar commands.",
                category="general",
                client=bot,
            ),
            discord.ui.View(),
        )

    cmd = _resolve_command(bot, parts)
    if cmd is None:
        # Try shortening (e.g. it picked up extra noise)
        for n in range(len(parts) - 1, 0, -1):
            cmd = _resolve_command(bot, parts[:n])
            if cmd is not None:
                parts = parts[:n]
                break

    if cmd is None:
        return (
            obsidian_embed(
                "📖 Couldn't identify the command",
                "I spotted what looked like a command path but couldn't resolve it. "
                "Try `/general help` for the full list.",
                category="general",
                client=bot,
            ),
            discord.ui.View(),
        )

    embed = _format_command_details(cmd, parts, bot)
    view = _RunHintView("/" + " ".join(parts))
    return embed, view
