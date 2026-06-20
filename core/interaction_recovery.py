"""User-friendly recovery when component interactions fail or panels expire."""
from __future__ import annotations

import discord

from core.utils import obsidian_embed, EMBED_COLORS


EXPIRED_HINTS: dict[str, str] = {
    "lfg": "Run **`/lfg list`** or refresh the post channel.",
    "claim": "Run **`/claim`** or **`/daily`** again.",
    "me": "Run **`/me`** or **`/today`** for a fresh snapshot.",
    "menu": "Run **`/menu`** to reopen the quick picker.",
    "warframe": "Run **`/warframe hub`** or **`/warframe status`**.",
    "welcome": "Run **`/start`** or **`/menu`** to get started.",
    "notification": "Run **`/notifications`** for your alert summary.",
    "hq": "Run **`/hq`** for the clan dashboard.",
    "suggest": "Run **`/community suggest`** to submit again.",
    "ticket": "Run **`/ticket`** to open a new ticket.",
    "default": "Run the command again to get a fresh panel.",
}


def hint_for_custom_id(custom_id: str | None) -> str:
    if not custom_id:
        return EXPIRED_HINTS["default"]
    cid = custom_id.lower()
    for key, hint in EXPIRED_HINTS.items():
        if key in cid:
            return hint
    return EXPIRED_HINTS["default"]


async def reply_expired_panel(
    interaction: discord.Interaction,
    *,
    custom_id: str | None = None,
    title: str = "Panel expired",
) -> bool:
    """Try to tell the user a panel timed out. Returns True if a reply was sent."""
    hint = hint_for_custom_id(custom_id or (interaction.data or {}).get("custom_id"))
    embed = obsidian_embed(
        f"⏱️ {title}",
        f"This button or menu is no longer active.\n\n{hint}",
        color=EMBED_COLORS["warning"],
        client=interaction.client,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return True
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        return False


def is_expired_interaction(exc: BaseException) -> bool:
    if isinstance(exc, discord.NotFound):
        return "Unknown interaction" in str(exc)
    if isinstance(exc, discord.InteractionResponded):
        return True
    if isinstance(exc, discord.HTTPException) and exc.code in (40060, 10062):
        return True
    return False
