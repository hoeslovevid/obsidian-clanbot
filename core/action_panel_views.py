"""Actionable panel views — Clan HQ, notifications, today."""
from __future__ import annotations

import discord
from discord import ui


async def handle_panel_action(interaction: discord.Interaction, custom_id: str) -> bool:
    """Route ``panel:*`` button clicks. Returns True if handled."""
    if not custom_id.startswith("panel:"):
        return False

    parts = custom_id.split(":")
    if len(parts) < 3:
        return False
    _prefix, panel, action = parts[0], parts[1], parts[2]

    if panel == "notifications":
        return await _handle_notifications_action(interaction, action)
    if panel == "today":
        return await _handle_today_action(interaction, action)
    if panel == "hq":
        return await _handle_hq_action(interaction, action)
    return False


async def _handle_notifications_action(interaction: discord.Interaction, action: str) -> bool:
    if not interaction.guild:
        from core.reply_helpers import reply_server_only

        await reply_server_only(interaction)
        return True

    gid = interaction.guild.id
    uid = interaction.user.id

    if action == "test_ping":
        await interaction.response.defer(ephemeral=True)
        from core.safe_send import safe_dm_or_hint
        from core.utils import obsidian_embed

        embed = obsidian_embed(
            "🔔 Test ping",
            "If you received this in DMs, personal notifications are working!\n\n"
            "Channel alerts (Baro, cycles) are separate — configure those with **`/wfnotify configure`**.",
            color=discord.Color.green(),
            client=interaction.client,
        )
        sent = await safe_dm_or_hint(
            interaction.user,
            interaction,
            what_failed="Couldn't send the test DM.",
            embed=embed,
        )
        if sent:
            await interaction.followup.send("✅ Test DM sent — check your DMs.", ephemeral=True)
        else:
            await interaction.followup.send(
                "Couldn't deliver a test DM. Enable DMs from server members or run **`/wfnotify why_dm`**.",
                ephemeral=True,
            )
        return True

    if action == "toggle_digest":
        from database import get_digest_dm, set_digest_dm

        current = await get_digest_dm(gid, uid)
        await set_digest_dm(gid, uid, not current)
        state = "On" if not current else "Off"
        await interaction.response.send_message(
            f"Daily digest DM is now **{state}**. Use **`/preferences digest_dm`** for section toggles.",
            ephemeral=True,
        )
        return True

    hints = {
        "wfnotify": "Run **`/wfnotify configure`** — Baro, cycles, alerts, and fissures.",
        "price_watch": "Run **`/price_watch`** to track market prices · **`/price_watches`** to list yours.",
        "baro_feed": "Mods: set guild Baro channel with **`/wfnotify configure`**.",
    }
    if action in hints:
        await interaction.response.send_message(hints[action], ephemeral=True)
        return True

    await interaction.response.send_message(
        "Run **`/notifications`** again for a fresh panel.",
        ephemeral=True,
    )
    return True


async def _handle_today_action(interaction: discord.Interaction, action: str) -> bool:
    if not interaction.guild:
        from core.reply_helpers import reply_server_only

        await reply_server_only(interaction)
        return True

    hints = {
        "daily": "Run **`/daily`** to claim your streak reward.",
        "claim": "Run **`/claim`** for ready bounties · **`/daily`** for coins.",
        "baro": "Run **`/baro`** or **`/warframe baro`** — check your wishlist matches.",
        "menu": "Run **`/menu`** for shortcuts to profile, LFG, tickets, and more.",
    }
    if action in hints:
        await interaction.response.send_message(hints[action], ephemeral=True)
        return True

    if action == "refresh":
        from commands.general.today import refresh_today_panel

        await refresh_today_panel(interaction)
        return True

    return False


async def _handle_hq_action(interaction: discord.Interaction, action: str) -> bool:
    if not interaction.guild:
        from core.reply_helpers import reply_server_only

        await reply_server_only(interaction)
        return True

    hints = {
        "lfg": "Run **`/lfg list`** to browse open squads · **`/lfg quick`** for templates.",
        "events": "Run **`/events`** to see upcoming ops · **`/poll`** for quick votes.",
        "baro": "Run **`/baro`** for inventory · **`/warframe hub`** for the full dashboard.",
        "notifications": "Run **`/notifications`** for your alert summary.",
    }
    if action in hints:
        await interaction.response.send_message(hints[action], ephemeral=True)
        return True
    return False


def notifications_panel_view(*, guild_id: int, user_id: int) -> discord.ui.View:
    """Refreshable notifications dashboard."""
    from views import RefreshView

    payload = {"guild_id": guild_id, "user_id": user_id}
    view = RefreshView.panel("notifications", payload=payload, timeout=300)
    row = ui.ActionRow()
    row.add_item(
        ui.Button(
            label="Test DM ping",
            style=discord.ButtonStyle.primary,
            emoji="📨",
            custom_id="panel:notifications:test_ping",
        )
    )
    row.add_item(
        ui.Button(
            label="Toggle digest",
            style=discord.ButtonStyle.secondary,
            emoji="📬",
            custom_id="panel:notifications:toggle_digest",
        )
    )
    row.add_item(
        ui.Button(
            label="WF notify",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id="panel:notifications:wfnotify",
        )
    )
    view.add_item(row)
    row2 = ui.ActionRow()
    row2.add_item(
        ui.Button(
            label="Price watches",
            style=discord.ButtonStyle.secondary,
            emoji="💰",
            custom_id="panel:notifications:price_watch",
        )
    )
    view.add_item(row2)
    return view


def clan_hq_panel_view(*, guild_id: int, user_id: int) -> discord.ui.View:
    from views import RefreshView

    payload = {"guild_id": guild_id, "user_id": user_id}
    view = RefreshView.panel("clan_hq", payload=payload, timeout=None)
    row = ui.ActionRow()
    row.add_item(
        ui.Button(
            label="Open LFG",
            style=discord.ButtonStyle.primary,
            emoji="🤝",
            custom_id="panel:hq:lfg",
        )
    )
    row.add_item(
        ui.Button(
            label="Events",
            style=discord.ButtonStyle.secondary,
            emoji="📅",
            custom_id="panel:hq:events",
        )
    )
    row.add_item(
        ui.Button(
            label="Baro",
            style=discord.ButtonStyle.secondary,
            emoji="🛒",
            custom_id="panel:hq:baro",
        )
    )
    row.add_item(
        ui.Button(
            label="Alerts",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id="panel:hq:notifications",
        )
    )
    view.add_item(row)
    return view


def today_panel_view(
    *,
    guild_id: int,
    user_id: int,
    show_daily: bool,
    show_baro: bool,
) -> discord.ui.View:
    from views import RefreshView

    payload = {"guild_id": guild_id, "user_id": user_id}
    view = RefreshView.panel("today", payload=payload, timeout=300)
    row = ui.ActionRow()
    if show_daily:
        row.add_item(
            ui.Button(
                label="Claim daily",
                style=discord.ButtonStyle.success,
                emoji="🎁",
                custom_id="panel:today:daily",
            )
        )
    row.add_item(
        ui.Button(
            label="Claim hub",
            style=discord.ButtonStyle.primary,
            emoji="💰",
            custom_id="panel:today:claim",
        )
    )
    if show_baro:
        row.add_item(
            ui.Button(
                label="Baro",
                style=discord.ButtonStyle.secondary,
                emoji="🛒",
                custom_id="panel:today:baro",
            )
        )
    row.add_item(
        ui.Button(
            label="Menu",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="panel:today:menu",
        )
    )
    view.add_item(row)
    return view
