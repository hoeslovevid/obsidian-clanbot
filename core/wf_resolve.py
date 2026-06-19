"""Unified Warframe command helpers — platform, fetch status, unavailable UX."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import discord  # type: ignore

from core.cache_utils import freshness_note, invalidate
from core.utils import warframe_data_unavailable_embed, BUTTON_ONLY_RUNNER_MSG
from core.wf_copy import merge_wf_footer
from views import RetryView


async def wf_platform(interaction: discord.Interaction) -> str:
    """Resolve platform from guild + user preferences (defaults to pc)."""
    if not interaction.guild:
        return "pc"
    return await wf_platform_for(interaction.guild.id, interaction.user.id)


async def wf_platform_for(guild_id: int | None, user_id: int) -> str:
    if not guild_id:
        return "pc"
    from core.warframe_platform import resolve_warframe_platform

    return await resolve_warframe_platform(guild_id, user_id)


def wf_daily_ops_cache_keys(platform: str) -> tuple[str, str, str]:
    plat = (platform or "pc").strip().lower()
    return (
        f"warframe:steelPath:{plat}",
        f"warframe:arbitration:{plat}",
        f"warframe:nightwave:{plat}",
    )


async def wf_invalidate_daily_ops(platform: str) -> None:
    for key in wf_daily_ops_cache_keys(platform):
        await wf_invalidate(key)


def wf_fetch_failed(data: Any) -> bool:
    """True when an API wrapper returned None (hard failure)."""
    return data is None


def wf_cycles_split(
    cycles_data: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Split cycle payload into successful entries and missing keys."""
    if not cycles_data:
        return {}, ["cetus", "vallis", "cambion"]
    success = {k: v for k, v in cycles_data.items() if v is not None}
    failed = [k for k in ("cetus", "vallis", "cambion") if k not in success]
    return success, failed


def wf_footer(base: str, cache_key: str, *, stale_after: float = 120.0) -> str:
    """Standard Warframe embed footer with cache-age suffix."""
    return merge_wf_footer(base, cache_key, stale_after=stale_after)


def wf_footer_with_freshness(base: str, cache_key: str) -> str:
    """Footer string with optional freshness note (cycles-style)."""
    note = freshness_note(cache_key)
    return (base or "").rstrip() + note if note else base


async def wf_invalidate(*keys: str) -> None:
    """Invalidate one or more cache key prefixes."""
    for key in keys:
        if key:
            invalidate(key)


async def wf_send_unavailable(
    interaction: discord.Interaction,
    *,
    owner_user_id: int,
    on_retry: Callable[[discord.Interaction], Awaitable[None]],
    fetch_probe: Optional[Callable[[], Awaitable[Any]]] = None,
    ephemeral: bool = True,
):
    """Standard unavailable embed + notify-when-back retry view."""
    from core.wf_recovery import attach_notify_when_back

    view = attach_notify_when_back(RetryView(on_retry), fetch_probe)
    if interaction.response.is_done():
        return await interaction.followup.send(
            embed=warframe_data_unavailable_embed(interaction.client),
            view=view,
            ephemeral=ephemeral,
        )
    return await interaction.response.send_message(
        embed=warframe_data_unavailable_embed(interaction.client),
        view=view,
        ephemeral=ephemeral,
    )


def wf_retry_guard(interaction: discord.Interaction, owner_user_id: int) -> bool:
    """Return True if the button presser is allowed to retry (original invoker)."""
    return interaction.user.id == owner_user_id


async def wf_retry_denied(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
