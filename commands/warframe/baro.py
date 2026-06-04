"""Baro Ki'Teer tracker command."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import aiosqlite
import dateparser
import discord
from discord import app_commands

from api.warframe_api import get_baro_status, wf_staleness_for_path
from core.embed_templates import embed_template
from core.utils import (
    BUTTON_ONLY_RUNNER_MSG,
    format_number,
    warframe_data_unavailable_embed,
)
from database import (
    DB_PATH,
    get_baro_inventory_hash,
    set_baro_inventory_hash,
)
from views import RefreshView, RetryView

logger = logging.getLogger(__name__)

BARO_INVENTORY_PAGE_SIZE = 15


def _parse_baro_item_name(item: dict) -> str:
    """Extract readable item name from API response. Handles 'item', 'itemType', 'itemName'."""
    name = item.get("item") or item.get("itemName")
    if name:
        return str(name)
    raw = item.get("itemType", "")
    if not raw:
        return "Unknown"
    parts = str(raw).strip("/").split("/")
    last = parts[-1] if parts else raw
    return last.replace("_", " ").replace("-", " ").title()


def _inventory_hash(inventory: list) -> str:
    parts = []
    for item in inventory:
        parts.append(f"{_parse_baro_item_name(item)}|{item.get('itemType', '')}")
    digest = hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()
    return digest[:32]


def format_baro_time(expiry_time: datetime) -> str:
    """Format time remaining for Baro."""
    time_remaining = expiry_time - datetime.now(timezone.utc)
    total_seconds = int(time_remaining.total_seconds())

    if total_seconds < 0:
        return "Expired"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_inventory_block(
    inventory: list,
    *,
    page: int = 0,
    mark_new: bool = False,
) -> tuple[str, int, int]:
    """Return (inventory_text, page_count, total_items)."""
    if not inventory:
        return "Inventory not available yet.", 1, 0

    total = len(inventory)
    page_count = max(1, (total + BARO_INVENTORY_PAGE_SIZE - 1) // BARO_INVENTORY_PAGE_SIZE)
    page = max(0, min(page, page_count - 1))
    start = page * BARO_INVENTORY_PAGE_SIZE
    chunk = inventory[start : start + BARO_INVENTORY_PAGE_SIZE]

    lines = []
    total_ducats = 0
    total_credits = 0
    for item in chunk:
        item_name = _parse_baro_item_name(item)
        prefix = "🆕 " if mark_new else ""
        ducats = int(item.get("ducats") or item.get("ducatPrice") or 0)
        credits = int(item.get("credits") or item.get("creditPrice") or 0)
        total_ducats += ducats
        total_credits += credits
        lines.append(f"`{prefix}{item_name}`")
        lines.append(f"💎 {format_number(ducats)} ducats • 💰 {format_number(credits)} credits\n")

    header = f"_Page {page + 1}/{page_count} · {total} items_\n\n" if page_count > 1 else ""
    body = header + "\n".join(lines)
    if page_count > 1:
        body += f"\n_Use ◀ ▶ to browse inventory_"
    return body, page_count, total


def build_baro_embed(
    baro_data: dict,
    is_active: bool,
    client,
    *,
    guild_id: Optional[int] = None,
    page: int = 0,
    mark_new: Optional[bool] = None,
) -> discord.Embed:
    """Build the Baro embed. Used for both initial display and updates."""
    location = baro_data.get("location", "Unknown")
    activation = baro_data.get("activation", "")
    expiry = baro_data.get("expiry", "")
    inventory = baro_data.get("inventory", []) or []

    cached_at = wf_staleness_for_path("pc/voidTrader")

    if is_active:
        try:
            expiry_time = dateparser.parse(expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
            if expiry_time:
                time_str = format_baro_time(expiry_time)
                expiry_discord = f"<t:{int(expiry_time.timestamp())}:R>"
            else:
                time_str = "Unknown"
                expiry_discord = "Unknown"
        except Exception:
            time_str = "Unknown"
            expiry_discord = "Unknown"

        show_new = bool(mark_new)
        inventory_list, _, total_items = _format_inventory_block(
            inventory, page=page, mark_new=show_new,
        )

        fields = [
            ("📍 Location", location, True),
            ("⏰ Leaves", f"{time_str}\n{expiry_discord}", True),
            ("📦 Inventory", inventory_list, False),
        ]

        if inventory:
            total_ducats = sum(int(i.get("ducats") or i.get("ducatPrice") or 0) for i in inventory)
            total_credits = sum(int(i.get("credits") or i.get("creditPrice") or 0) for i in inventory)
            fields.append(
                (
                    "💰 Total",
                    f"💎 **{format_number(total_ducats)}** ducats  ·  💰 **{format_number(total_credits)}** credits",
                    True,
                ),
            )
            if total_items > BARO_INVENTORY_PAGE_SIZE:
                fields.append(
                    ("📄 Pages", f"{(total_items + BARO_INVENTORY_PAGE_SIZE - 1) // BARO_INVENTORY_PAGE_SIZE} pages", True),
                )

        return embed_template(
            "warframe_status",
            "🛒 Baro Ki'Teer",
            f"> 🟢 **Currently Active** — leaves {expiry_discord}",
            variant="baro",
            platform="pc",
            client=client,
            cached_at=cached_at,
            fields=fields,
            footer="PC data · Use Refresh · See also: /warframe cycles, /warframe alerts",
        )

    fields = []
    countdown_line = ""
    last_visit_text = ""
    lv = baro_data.get("_last_visit")
    if lv:
        _arr, dep, loc, inv_json = lv
        last_visit_text = f"\n\n**Last visit:** {loc} • Left {dep[:10] if dep else '—'}"
        if inv_json:
            try:
                inv = json.loads(inv_json)
                items = [_parse_baro_item_name(i) for i in inv[:5]]
                last_visit_text += f"\n_Items: {', '.join(items)}{'...' if len(inv) > 5 else ''}_"
            except Exception:
                pass
    if activation:
        try:
            activation_time = dateparser.parse(
                activation, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if activation_time:
                time_until = activation_time - datetime.now(timezone.utc)
                if time_until.total_seconds() > 0:
                    total_s = int(time_until.total_seconds())
                    days = total_s // 86400
                    hours = (total_s % 86400) // 3600
                    mins = (total_s % 3600) // 60
                    time_str = f"{days}d {hours}h {mins}m"
                    arrival_discord = f"<t:{int(activation_time.timestamp())}:R>"
                    countdown_line = f"\n\n**Countdown:** {time_str} until arrival\n{arrival_discord}"
                    fields = [
                        ("⏰ Next Arrival", f"{time_str}\n{arrival_discord}", True),
                        ("📍 Location", location if location != "Unknown" else "TBA", True),
                    ]
                else:
                    countdown_line = "\n\nBaro just left. Next visit in ~2 weeks."
                    fields = [
                        ("⏰ Status", "Recently departed", True),
                        ("📍 Location", location if location != "Unknown" else "TBA", True),
                    ]
            else:
                fields = [
                    ("⏰ Next Arrival", "Unknown", True),
                    ("📍 Location", location if location != "Unknown" else "TBA", True),
                ]
        except Exception:
            fields = [
                ("⏰ Next Arrival", "Unknown", True),
                ("📍 Location", location if location != "Unknown" else "TBA", True),
            ]
    else:
        fields = [
            ("⏰ Next Arrival", "Unknown", True),
            ("📍 Location", location if location != "Unknown" else "TBA", True),
        ]

    return embed_template(
        "warframe_status",
        "🛒 Baro Ki'Teer",
        "> 🔴 **Not Currently Active**\n\nPrepare your ducats for the next visit!"
        + countdown_line
        + last_visit_text,
        variant="baro",
        platform="pc",
        client=client,
        cached_at=cached_at,
        fields=fields,
        footer="PC data · Baro visits every ~2 weeks",
    )


class BaroInventoryView(discord.ui.View):
    """Paginated Baro inventory with refresh."""

    def __init__(
        self,
        *,
        guild_id: Optional[int],
        is_active: bool,
        baro_data: dict,
        mark_new: bool,
        refresh_callback: Callable,
        page: int = 0,
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)
        from core.embed_links import add_link_row, baro_link_buttons

        add_link_row(self, baro_link_buttons())
        self.guild_id = guild_id
        self.is_active = is_active
        self.baro_data = baro_data
        self.mark_new = mark_new
        self.refresh_callback = refresh_callback
        self.page = page
        self._update_nav_buttons()

    def _inventory(self) -> list:
        return self.baro_data.get("inventory", []) or []

    def _page_count(self) -> int:
        inv = self._inventory()
        if not inv:
            return 1
        return max(1, (len(inv) + BARO_INVENTORY_PAGE_SIZE - 1) // BARO_INVENTORY_PAGE_SIZE)

    def _update_nav_buttons(self):
        count = self._page_count()
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "baro_inv_prev":
                item.disabled = self.page <= 0
            elif item.custom_id == "baro_inv_next":
                item.disabled = self.page >= count - 1

    def build_embed(self, client) -> discord.Embed:
        return build_baro_embed(
            self.baro_data,
            self.is_active,
            client,
            guild_id=self.guild_id,
            page=self.page,
            mark_new=self.mark_new,
        )

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="baro_inv_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(interaction.client), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="baro_inv_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self._page_count() - 1, self.page + 1)
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(interaction.client), view=self)

    @discord.ui.button(label="Update data", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await self.refresh_callback(interaction)


async def _resolve_mark_new(guild_id: Optional[int], inventory: list) -> bool:
    if not guild_id or not inventory:
        return False
    current = _inventory_hash(inventory)
    old = await get_baro_inventory_hash(guild_id)
    return bool(old and old != current)


async def _persist_inventory_hash(guild_id: Optional[int], inventory: list) -> None:
    if guild_id and inventory:
        await set_baro_inventory_hash(guild_id, _inventory_hash(inventory))


def setup(bot, group=None):
    """Register the baro command."""
    command_decorator = (
        group.command(
            name="baro",
            description="Baro Ki'Teer void trader — inventory, arrival, departure timer.",
        )
        if group
        else bot.tree.command(
            name="baro",
            description="View Baro Ki'Teer's current visit and inventory.",
        )
    )

    @command_decorator
    async def baro(interaction: discord.Interaction):
        """Display Baro Ki'Teer's current status and inventory."""
        await interaction.response.defer(ephemeral=False)

        guild_id = interaction.guild.id if interaction.guild else None
        is_active, baro_data = await get_baro_status()
        if baro_data and not is_active:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT arrival_time, departure_time, location, inventory_json "
                    "FROM baro_visits ORDER BY id DESC LIMIT 1"
                )
                baro_data["_last_visit"] = await cur.fetchone()

        if not baro_data:

            async def on_retry(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != interaction.user.id:
                    return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
                await btn_interaction.response.defer()
                new_active, new_data = await get_baro_status()
                if not new_data:
                    return await btn_interaction.followup.send(
                        "Still can't reach the stats server. Try **Try again** again in a minute.",
                        ephemeral=True,
                    )
                if new_data and not new_active:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT arrival_time, departure_time, location, inventory_json "
                            "FROM baro_visits ORDER BY id DESC LIMIT 1"
                        )
                        new_data["_last_visit"] = await cur.fetchone()
                mark = await _resolve_mark_new(guild_id, new_data.get("inventory", []) or [])
                emb = build_baro_embed(new_data, new_active, interaction.client, guild_id=guild_id, mark_new=mark)
                await btn_interaction.message.edit(embed=emb, view=None)
                await _persist_inventory_hash(guild_id, new_data.get("inventory", []) or [])

            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                view=RetryView(on_retry),
                ephemeral=True,
            )

        inventory = baro_data.get("inventory", []) or []
        mark_new = await _resolve_mark_new(guild_id, inventory)
        embed = build_baro_embed(
            baro_data, is_active, interaction.client, guild_id=guild_id, mark_new=mark_new,
        )

        async def on_refresh(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.response.send_message(BUTTON_ONLY_RUNNER_MSG, ephemeral=True)
            await btn_interaction.response.defer()
            from core.cache_utils import invalidate

            invalidate("warframe:baro")
            new_active, new_data = await get_baro_status()
            if not new_data:
                await btn_interaction.followup.send(
                    "Couldn't refresh Baro yet — stats server is still struggling. Try again soon.",
                    ephemeral=True,
                )
                return
            if new_data and not new_active:
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT arrival_time, departure_time, location, inventory_json "
                        "FROM baro_visits ORDER BY id DESC LIMIT 1"
                    )
                    new_data["_last_visit"] = await cur.fetchone()
            inv = new_data.get("inventory", []) or []
            mark = await _resolve_mark_new(guild_id, inv)
            view = _baro_view_for(
                guild_id=guild_id,
                is_active=new_active,
                baro_data=new_data,
                mark_new=mark,
                refresh_callback=on_refresh,
                client=interaction.client,
            )
            new_emb = build_baro_embed(
                new_data, new_active, interaction.client, guild_id=guild_id, mark_new=mark,
            )
            await btn_interaction.message.edit(embed=new_emb, view=view)
            await _persist_inventory_hash(guild_id, inv)

        view = _baro_view_for(
            guild_id=guild_id,
            is_active=is_active,
            baro_data=baro_data,
            mark_new=mark_new,
            refresh_callback=on_refresh,
            client=interaction.client,
        )
        message = await interaction.followup.send(embed=embed, view=view, ephemeral=False)
        await _persist_inventory_hash(guild_id, inventory)

        if is_active and interaction.guild and isinstance(interaction.channel, discord.TextChannel):
            expiry = baro_data.get("expiry", "")
            if expiry:
                try:
                    expiry_time = dateparser.parse(
                        expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
                    )
                    if expiry_time:
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                """
                                INSERT OR REPLACE INTO baro_live_messages
                                (guild_id, channel_id, message_id, expiry_time, created_at)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    interaction.guild.id,
                                    interaction.channel.id,
                                    message.id,
                                    expiry_time.isoformat(),
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                            )
                            await db.commit()
                except Exception as e:
                    logger.error("Error storing Baro message for live updates: %s", e)


def _baro_view_for(
    *,
    guild_id: Optional[int],
    is_active: bool,
    baro_data: dict,
    mark_new: bool,
    refresh_callback: Callable,
    client,
) -> discord.ui.View:
    inventory = baro_data.get("inventory", []) or []
    if is_active and inventory:
        return BaroInventoryView(
            guild_id=guild_id,
            is_active=is_active,
            baro_data=baro_data,
            mark_new=mark_new,
            refresh_callback=refresh_callback,
        )
    from core.embed_links import add_link_row, baro_link_buttons

    view = RefreshView(refresh_callback)
    add_link_row(view, baro_link_buttons())
    return view
