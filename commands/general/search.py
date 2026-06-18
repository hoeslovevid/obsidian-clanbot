"""/search — a command palette: find a command by keyword, get clickable results."""
import difflib

import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS


def _matching_items(query: str, limit: int = 6) -> list[str]:
    """Warframe item names from the trade_price popular list matching the query."""
    try:
        from commands.trading.trade_price import POPULAR_ITEMS
    except Exception:
        return []
    q = query.lower()
    if len(q) < 2:
        return []
    starts = [i for i in POPULAR_ITEMS if i.lower().startswith(q)]
    contains = [i for i in POPULAR_ITEMS if q in i.lower() and i not in starts]
    return (starts + contains)[:limit]


def _all_leaf_commands(client: discord.Client):
    """Yield (qualified_name, description) for every non-group command in the tree."""
    out = []
    try:
        for cmd in client.tree.walk_commands():
            if isinstance(cmd, app_commands.Group):
                continue
            out.append((cmd.qualified_name, getattr(cmd, "description", "") or ""))
    except Exception:
        pass
    return out


def _score(query: str, name: str, desc: str) -> float:
    q = query.lower()
    name_l = name.lower()
    score = 0.0
    if q == name_l or q == name_l.split()[-1]:
        score += 5
    if q in name_l:
        score += 3
    if q in desc.lower():
        score += 1.5
    score += difflib.SequenceMatcher(None, q, name_l).ratio()
    # token overlap (e.g. "baro price" matches "trade_price")
    q_tokens = set(q.split())
    name_tokens = set(name_l.replace("_", " ").split())
    if q_tokens & name_tokens:
        score += 1.0
    return score


def setup(bot, group=None):
    # Registered TOP_LEVEL_ONLY → always /search.
    decorator = bot.tree.command(
        name="search",
        description="Find a command by keyword — returns clickable matches.",
    )

    @decorator
    @app_commands.describe(query="What do you want to do? e.g. 'baro', 'reminder', 'price'")
    async def search(interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        from core.command_mentions import command_mention

        q = (query or "").strip()
        if not q:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🔎 Search",
                    "Give me a keyword, e.g. `baro`, `reminder`, or `price`.",
                    color=EMBED_COLORS.get("general", discord.Color.blue()),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        scored = [
            (s, name, desc)
            for name, desc in _all_leaf_commands(interaction.client)
            if (s := _score(q, name, desc)) >= 1.2
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:8]
        items = _matching_items(q)

        if not top and not items:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🔎 No matches",
                    f"Nothing matched **{q}**.\n\n"
                    f"Browse everything with {command_mention('help', fallback='`/help`')}, "
                    f"or look up a Warframe item with "
                    f"{command_mention('trading trade_price', fallback='`/trading trade_price`')}.",
                    color=EMBED_COLORS.get("general", discord.Color.blue()),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        fields = []
        if top:
            lines = []
            for _, name, desc in top:
                mention = command_mention(name, fallback=f"`/{name}`")
                short = (desc[:80] + "…") if len(desc) > 80 else desc
                lines.append(f"{mention} — {short}" if short else mention)
            fields.append(("Commands", "\n".join(lines), False))

        if items:
            tp = command_mention("trading trade_price", fallback="`/trading trade_price`")
            item_lines = " · ".join(f"`{name}`" for name in items)
            fields.append(
                ("Warframe items", f"{item_lines}\n-# Look up prices with {tp}", False)
            )

        await interaction.followup.send(
            embed=obsidian_embed(
                f"🔎 Results for “{q}”",
                "",
                color=EMBED_COLORS.get("general", discord.Color.blue()),
                fields=fields,
                footer="Tip: click a command to run it instantly",
                client=interaction.client,
            ),
            ephemeral=True,
        )
