"""Browse open LFG posts with empty-state templates."""
from __future__ import annotations

import aiosqlite
import discord

from core.utils import obsidian_embed, EMBED_COLORS
from database import DB_PATH


async def build_lfg_list_embed(guild: discord.Guild, *, client=None) -> discord.Embed:
    """List open LFG posts for the guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id, mission_type, max_players, creator_id, channel_id, message_id
            FROM lfg_posts
            WHERE guild_id=? AND status='OPEN'
            ORDER BY created_at DESC LIMIT 12
            """,
            (guild.id,),
        )
        rows = await cur.fetchall()

    if not rows:
        return obsidian_embed(
            "🤝 Open LFG Posts",
            "No open squad posts right now.\n\n"
            "Be the first — use the buttons below or run **`/lfg quick`** for templates.",
            color=EMBED_COLORS.get("warframe", discord.Color.dark_grey()),
            footer="Host? **`/lfg preset_save`** saves your loadouts for one-tap reposts",
            client=client,
        )

    lines: list[str] = []
    for lfg_id, mission, max_p, creator_id, channel_id, message_id in rows:
        host = guild.get_member(int(creator_id))
        host_label = host.display_name if host else f"<@{creator_id}>"
        link = ""
        if channel_id and message_id:
            link = f" — [jump](https://discord.com/channels/{guild.id}/{channel_id}/{message_id})"
        lines.append(f"• **{mission}** ({max_p}p) · {host_label}{link}")

    body = "\n".join(lines)
    if len(rows) >= 12:
        body += "\n-# Showing latest 12 open posts"
    return obsidian_embed(
        f"🤝 Open LFG · {guild.name}",
        body,
        color=EMBED_COLORS.get("warframe", discord.Color.dark_grey()),
        footer=f"{len(rows)} open · /lfg to post · /lfg quick for templates",
        client=client,
    )


class LFGListEmptyView(discord.ui.View):
    """Quick templates when no open LFG posts exist."""

    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Steel Path", style=discord.ButtonStyle.primary, emoji="🗡️")
    async def steel_path(self, interaction: discord.Interaction, button: discord.ui.Button):
        from commands.warframe.lfg import LFGQuickModal

        await interaction.response.send_modal(
            LFGQuickModal(
                self.bot,
                mission_type="Steel Path",
                description="Steel Path farm — relics, SP fissures, or daily challenge.",
            ),
        )

    @discord.ui.button(label="Sortie", style=discord.ButtonStyle.primary, emoji="🎯")
    async def sortie(self, interaction: discord.Interaction, button: discord.ui.Button):
        from commands.warframe.lfg import LFGQuickModal

        await interaction.response.send_modal(
            LFGQuickModal(
                self.bot,
                mission_type="Sortie",
                description="Today's sortie — mention loadout & archon shard goals if any.",
            ),
        )

    @discord.ui.button(label="Post LFG", style=discord.ButtonStyle.success, emoji="🤝")
    async def post_lfg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Run **`/lfg`** and pick a mission type, or **`/lfg quick`** for more templates.",
            ephemeral=True,
        )
