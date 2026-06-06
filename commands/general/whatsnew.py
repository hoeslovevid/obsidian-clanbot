"""/whatsnew - paginated changelog viewer with DM subscription.

How to add a new release:
    1. Bump default ``BOT_VERSION`` (and ``BOT_CHANGELOG`` if needed) in ``core/config.py``.
    2. Move ``CURRENT_RELEASE_*`` from ``core/changelog.py`` into ``CHANGELOG_HISTORY``
       with the **previous** version string, then write new ``CURRENT_RELEASE_*`` bullets.

The current page label always uses ``BOT_VERSION``; historical pages keep their
stored version. ``core.release_announce.announce_release_if_needed`` DMs subscribers
when a new ``BOT_VERSION`` is announced.
"""
from __future__ import annotations

import logging
from typing import cast

import discord  # type: ignore
import aiosqlite  # type: ignore
from discord import app_commands  # type: ignore

from core.changelog import get_changelog_pages
from core.utils import obsidian_embed, error_embed, EMBED_COLORS, EMBED_FOOTER_DEFAULT, bullet_list
from database import DB_PATH, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

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
        pages = get_changelog_pages(max_pages=MAX_PAGES)
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

        from core.help_layout import help_layout_v2_enabled
        from core.whatsnew_layout import WhatsNewLayout

        if help_layout_v2_enabled():
            try:
                state = {"page": 0, "subscribed": subscribed}

                async def _rebuild(inter: discord.Interaction):
                    entry = pages[state["page"]]
                    layout = WhatsNewLayout(
                        version=str(entry.get("version", "?")),
                        date=str(entry.get("date", "")).strip(),
                        changes=list(entry.get("changes") or []),
                        page=state["page"],
                        total_pages=len(pages),
                        subscribed=state["subscribed"],
                        on_prev=_prev if len(pages) > 1 else None,
                        on_next=_next if len(pages) > 1 else None,
                        on_subscribe=_subscribe,
                    )
                    await inter.response.edit_message(view=layout)

                async def _prev(inter: discord.Interaction):
                    state["page"] = min(len(pages) - 1, state["page"] + 1)
                    await _rebuild(inter)

                async def _next(inter: discord.Interaction):
                    state["page"] = max(0, state["page"] - 1)
                    await _rebuild(inter)

                async def _subscribe(inter: discord.Interaction):
                    new_state = "0" if state["subscribed"] else "1"
                    await set_guild_setting(
                        inter.guild.id, f"user_changelog_dm:{inter.user.id}", new_state
                    )
                    state["subscribed"] = not state["subscribed"]
                    await _rebuild(inter)
                    try:
                        await inter.followup.send(
                            f"Changelog DMs {'enabled' if state['subscribed'] else 'disabled'}.",
                            ephemeral=True,
                        )
                    except Exception:
                        pass

                entry = pages[0]
                layout = WhatsNewLayout(
                    version=str(entry.get("version", "?")),
                    date=str(entry.get("date", "")).strip(),
                    changes=list(entry.get("changes") or []),
                    page=0,
                    total_pages=len(pages),
                    subscribed=subscribed,
                    on_prev=_prev if len(pages) > 1 else None,
                    on_next=_next if len(pages) > 1 else None,
                    on_subscribe=_subscribe,
                )
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            except Exception:
                pass

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
