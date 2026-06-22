"""Persistent **Try again** for Warframe API failure panels."""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.refresh_panels import (
    get_refresh_panel,
    refresh_followup_ephemeral,
    register_refresh_panel,
    reenable_message_view,
)

logger = logging.getLogger(__name__)

WF_RETRY_CUSTOM_ID = "obsidian:wf_retry"
RetryHandler = Callable[[discord.Interaction, dict[str, Any]], Awaitable[bool]]


def _retry_panel_type(retry_type: str) -> str:
    return f"retry:{retry_type}"


def wf_retry_view(*, timeout: float | None = None) -> discord.ui.View:
    """View with a persistent Try again button (register panel after send)."""
    view = discord.ui.View(timeout=timeout if timeout is not None else None)
    view.add_item(
        discord.ui.Button(
            label="Try again",
            style=discord.ButtonStyle.primary,
            emoji="🔄",
            custom_id=WF_RETRY_CUSTOM_ID,
        )
    )
    return view


async def register_wf_retry_panel(
    message: discord.Message,
    retry_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    await register_refresh_panel(message, _retry_panel_type(retry_type), payload)


async def send_wf_retry_message(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    retry_type: str,
    payload: dict[str, Any],
    owner_user_id: int,
    fetch_probe: Callable[[], Awaitable] | None = None,
    ephemeral: bool = False,
    edit: bool = True,
) -> None:
    """Attach persistent retry view and register panel metadata."""
    from core.wf_recovery import attach_notify_when_back

    full_payload = {**(payload or {}), "owner_user_id": owner_user_id}
    view = attach_notify_when_back(wf_retry_view(), fetch_probe)
    if edit and interaction.response.is_done():
        msg = await interaction.edit_original_response(embed=embed, view=view)
    elif edit:
        await interaction.response.edit_message(embed=embed, view=view)
        msg = await interaction.original_response()
    else:
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral, wait=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
            msg = await interaction.original_response()
    if msg:
        await register_wf_retry_panel(msg, retry_type, full_payload)


async def handle_wf_retry_button(
    bot: discord.Client,
    interaction: discord.Interaction,
) -> None:
    message = interaction.message
    if not message:
        await refresh_followup_ephemeral(
            interaction,
            "This retry button is no longer attached to a message.",
        )
        return

    meta = await get_refresh_panel(message.id)
    if not meta:
        await refresh_followup_ephemeral(
            interaction,
            "This panel expired — run the Warframe command again.",
        )
        return

    panel_type, payload = meta
    if not panel_type.startswith("retry:"):
        await refresh_followup_ephemeral(interaction, "Unknown retry panel.")
        return

    retry_type = panel_type[6:]
    handler = RETRY_HANDLERS.get(retry_type)
    if not handler:
        await refresh_followup_ephemeral(interaction, "Retry handler missing — re-run the command.")
        return

    owner = int(payload.get("owner_user_id") or 0)
    from core.wf_resolve import wf_retry_denied, wf_retry_guard

    if owner and not wf_retry_guard(interaction, owner):
        await wf_retry_denied(interaction)
        return

    if not interaction.response.is_done():
        await interaction.response.defer()

    try:
        ok = await handler(interaction, payload)
        if not ok:
            active = discord.ui.View.from_message(message) if message.components else None
            if active:
                await reenable_message_view(interaction, active)
    except Exception:
        logger.exception("[wf_retry] type=%s message=%s", retry_type, message.id)
        await refresh_followup_ephemeral(
            interaction,
            "Couldn't retry — try again in a moment or re-run the command.",
        )
        active = discord.ui.View.from_message(message) if message.components else None
        if active:
            await reenable_message_view(interaction, active)


class PersistentWfRetryView(ui.View):
    """Startup-registered view for ``obsidian:wf_retry``."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Try again",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id=WF_RETRY_CUSTOM_ID,
    )
    async def retry_button(
        self,
        interaction: discord.Interaction,
        button: ui.Button,
    ) -> None:
        if button.disabled:
            await refresh_followup_ephemeral(
                interaction,
                "This panel expired — run the command again.",
            )
            return
        await handle_wf_retry_button(interaction.client, interaction)


# Handlers registered at end of module after imports to avoid cycles
RETRY_HANDLERS: dict[str, RetryHandler] = {}


def _register_handlers() -> None:
    from core import wf_retry_handlers

    RETRY_HANDLERS.update(wf_retry_handlers.HANDLERS)


_register_handlers()
