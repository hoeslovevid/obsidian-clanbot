"""Re-post a previous LFG with a pre-filled modal."""
from __future__ import annotations

import aiosqlite
import discord

from database import DB_PATH


async def open_lfg_repost_modal(
    interaction: discord.Interaction,
    bot,
    lfg_id: int,
) -> bool:
    """Open a pre-filled LFG modal for the post host. Returns True if modal was sent."""
    if not interaction.guild:
        from core.reply_helpers import reply_server_only

        await reply_server_only(interaction)
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT creator_id, mission_type, max_players, description, radio_query
            FROM lfg_posts WHERE id=? AND guild_id=?
            """,
            (lfg_id, interaction.guild.id),
        )
        row = await cur.fetchone()
    if not row:
        from core.reply_helpers import reply_error

        await reply_error(interaction, "Not found", "LFG post not found.")
        return False

    creator_id, mission_type, max_players, description, radio_query = row
    if interaction.user.id != int(creator_id):
        await interaction.response.send_message(
            "Only the original host can re-post this squad.",
            ephemeral=True,
        )
        return False

    from commands.warframe.lfg import LFGQuickModal

    modal = LFGQuickModal(
        bot,
        mission_type=str(mission_type or "Other"),
        description=str(description or ""),
    )
    modal.max_players_input.default = str(max_players or 4)
    if radio_query:
        modal.radio_input.default = str(radio_query)[:200]
    await interaction.response.send_modal(modal)
    return True
