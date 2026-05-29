"""/whatsnew - paginated changelog viewer with DM subscription.

How to add a new release entry:
    Append a dict to ``CHANGELOG`` (newest first). Schema:
        {"version": "1.5.0", "date": "2026-05-14", "changes": ["..."]}

The /whatsnew command shows the last 5 entries (newest first), one per
page, with a 🔔 button that lets users opt into changelog DMs.
``core.version_tracking.check_and_post_updates`` will additionally DM any
user with ``user_changelog_dm:{user_id} == "1"`` when a new bot version
is detected.
"""
from __future__ import annotations

import logging
from typing import cast

import discord  # type: ignore
import aiosqlite  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, error_embed, EMBED_COLORS, EMBED_FOOTER_DEFAULT, bullet_list
from database import DB_PATH, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


# Hand-curated changelog. Add new entries to the TOP. Old entries get rolled off
# by the 5-entry paginator but stay in this list for /whatsnew history.
CHANGELOG: list[dict] = [
    {
        "version": "1.5.0",
        "date": "2026-05-14",
        "changes": [
            "/whatsnew changelog viewer with DM subscription",
            "Mod Context popup (right-click → all mod tools in one ephemeral embed)",
            "/mod purge: filter by user/contains/older_than/from_bots + confirm step",
            "/warframe vc: host transfer command and panel button hand-off",
            "VC presets: save/apply/list/delete favourite VC configs",
            "Idle VC revival vote: closed VCs can be brought back with 3 clicks",
            "Live poll results bar — embed updates as votes come in",
            "Cycle-aware LFG nudges (Plains/Vallis/Cambion timing)",
            "Saved warn reason templates with autocomplete on /mod warn",
            "Pet evolution stages (Baby → Young → Adult → Elder)",
            "/preferences unsubscribe_all and subscribe_all DM shortcuts",
            "Right-click 'Explain command' context menu",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-05-10",
        "changes": [
            "Earlier QoL batch — investments DMs, profile polish, cycle notify",
            "Mod stats dashboard refresh button",
            "Trading post and Warframe market refinements",
        ],
    },
]


MAX_PAGES = 5


def _entry_to_embed(entry: dict, page: int, total_pages: int, client: discord.Client | None) -> discord.Embed:
    version = str(entry.get("version", "?"))
    date = str(entry.get("date", "")).strip()
    changes = entry.get("changes") or []

    header = f"Released {date}" if date else "Recent changes"
    desc = f"_{header}_\n\n" + bullet_list([str(c) for c in changes[:25]])
    embed = obsidian_embed(
        f"📝 What's New • v{version}",
        desc,
        category="general",
        footer=f"Page {page + 1}/{total_pages} • {EMBED_FOOTER_DEFAULT}",
        client=client,
        brand=True,
    )
    return embed


class _SubscribeButton(discord.ui.Button):
    def __init__(self, *, subscribed: bool):
        label = "🔕 Unsubscribe from changelog DMs" if subscribed else "🔔 Subscribe to changelog DMs"
        style = discord.ButtonStyle.secondary if subscribed else discord.ButtonStyle.primary
        super().__init__(label=label, style=style, custom_id="whatsnew:subscribe")
        self.subscribed = subscribed

    async def callback(self, interaction: discord.Interaction):
        view = cast(WhatsNewView, self.view)
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        new_state = "0" if self.subscribed else "1"
        await set_guild_setting(
            interaction.guild.id, f"user_changelog_dm:{interaction.user.id}", new_state
        )
        self.subscribed = not self.subscribed
        self.label = (
            "🔕 Unsubscribe from changelog DMs" if self.subscribed else "🔔 Subscribe to changelog DMs"
        )
        self.style = (
            discord.ButtonStyle.secondary if self.subscribed else discord.ButtonStyle.primary
        )
        await interaction.response.edit_message(view=view)
        state_text = "enabled" if self.subscribed else "disabled"
        try:
            await interaction.followup.send(
                f"Changelog DMs {state_text}.", ephemeral=True
            )
        except Exception:
            pass


class WhatsNewView(discord.ui.View):
    def __init__(self, pages: list[dict], *, subscribed: bool, client: discord.Client | None = None, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.page = 0
        self.client = client
        # Pagination buttons added first so they sit before the subscribe button
        self.prev_btn = discord.ui.Button(
            label="◀ Older", style=discord.ButtonStyle.secondary, custom_id="whatsnew:prev"
        )
        self.next_btn = discord.ui.Button(
            label="Newer ▶", style=discord.ButtonStyle.secondary, custom_id="whatsnew:next"
        )
        self.prev_btn.callback = self._prev
        self.next_btn.callback = self._next
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)
        self.subscribe_btn = _SubscribeButton(subscribed=subscribed)
        self.add_item(self.subscribe_btn)
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = self.page >= len(self.pages) - 1  # older = higher index
        self.next_btn.disabled = self.page <= 0

    def build_embed(self) -> discord.Embed:
        return _entry_to_embed(self.pages[self.page], self.page, len(self.pages), self.client)

    async def _prev(self, interaction: discord.Interaction):
        self.page = min(len(self.pages) - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


async def get_changelog_subscribers(guild_id: int) -> list[int]:
    """Return user ids that opted into changelog DMs for this guild."""
    prefix = f"user_changelog_dm:"
    out: list[int] = []
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT key, value FROM guild_settings WHERE guild_id=? AND key LIKE ?",
            (guild_id, prefix + "%"),
        )
        rows = await cur.fetchall()
    for key, value in rows:
        if value != "1":
            continue
        try:
            out.append(int(str(key).split(":", 1)[1]))
        except (ValueError, IndexError):
            continue
    return out


def setup(bot, group=None):
    """Register /whatsnew (and /general whatsnew when called with the general group)."""

    async def _whatsnew_impl(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        pages = CHANGELOG[:MAX_PAGES]
        if not pages:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "📝 What's New",
                    "No changelog entries yet. Updates will appear here automatically.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        sub_val = await get_guild_setting(
            interaction.guild.id, f"user_changelog_dm:{interaction.user.id}"
        )
        subscribed = sub_val == "1"

        view = WhatsNewView(pages, subscribed=subscribed, client=interaction.client)
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True
        )

    # Always expose a top-level /whatsnew shortcut (registered first so a full
    # group doesn't drop the shortcut too).
    @app_commands.command(name="whatsnew", description="See what's new in the bot's most recent releases.")
    async def whatsnew_top(interaction: discord.Interaction):
        await _whatsnew_impl(interaction)

    try:
        bot.tree.add_command(whatsnew_top)
    except Exception as e:
        logger.debug(f"[whatsnew] Top-level /whatsnew not registered: {e}")

    # /tools is at Discord's 25-subcommand cap — top-level /whatsnew only.
