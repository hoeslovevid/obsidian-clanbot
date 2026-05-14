"""LFG list command to view active groups (Item 16 — filters & joinable sort)."""
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
import aiosqlite

from core.utils import obsidian_embed, error_embed
from database import DB_PATH, get_user_platform
from views import EmbedPaginator
from commands.warframe.lfg import MISSION_TYPES
from commands.general.preferences import PLATFORM_CHOICES

ITEMS_PER_PAGE = 15


async def mission_type_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for mission type filter. Paginated: top 25 by relevance."""
    from core.utils import AUTOCOMPLETE_MAX_CHOICES
    current_lower = (current or "").lower().strip()
    if not current_lower:
        matches = list(MISSION_TYPES)[:AUTOCOMPLETE_MAX_CHOICES]
    else:
        exact = [m for m in MISSION_TYPES if m.lower() == current_lower]
        start = [m for m in MISSION_TYPES if m.lower().startswith(current_lower) and m not in exact]
        contains = [
            m for m in MISSION_TYPES
            if current_lower in m.lower() and m not in exact and m not in start
        ]
        matches = (exact + start + contains)[:AUTOCOMPLETE_MAX_CHOICES]
    return [app_commands.Choice(name=m, value=m) for m in matches]


def _platform_choices_for_filter() -> list[app_commands.Choice]:
    """Filter version: drop the "(clear)" option used by preferences."""
    return [c for c in PLATFORM_CHOICES if c.value != "-"]


def setup(bot, group=None):
    """Register the lfg_list command."""
    command_decorator = (
        group.command(name="lfg_list", description="View active Looking for Group posts.")
        if group
        else bot.tree.command(name="lfg_list", description="View active Looking for Group posts.")
    )

    @command_decorator
    @app_commands.describe(
        mission_type="Filter by mission type (optional)",
        platform="Show only posts whose creator uses this platform",
        min_open_slots="Hide posts with fewer than this many free seats (default 1 — joinable)",
        include_filled="Also include completed / filled posts (default off)",
        sort="Sort order — defaults to joinable first then expiring soonest",
    )
    @app_commands.autocomplete(mission_type=mission_type_autocomplete)
    @app_commands.choices(platform=_platform_choices_for_filter())
    @app_commands.choices(sort=[
        app_commands.Choice(name="Joinable first (default)", value="joinable"),
        app_commands.Choice(name="Newest first", value="newest"),
        app_commands.Choice(name="Expiring soon", value="expiring_soon"),
    ])
    async def lfg_list(
        interaction: discord.Interaction,
        mission_type: Optional[str] = None,
        platform: Optional[app_commands.Choice[str]] = None,
        min_open_slots: int = 1,
        include_filled: bool = False,
        sort: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a text channel where LFG posts are listed.", client=interaction.client),
                ephemeral=True,
            )
        if mission_type and mission_type not in MISSION_TYPES:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Mission Type",
                    f"'{mission_type}' is not valid. Choose from: {', '.join(list(MISSION_TYPES)[:10])}{'...' if len(MISSION_TYPES) > 10 else ''}",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Status filter (default: hide COMPLETED)
        status_clause = "1=1" if include_filled else "status != 'COMPLETED'"

        # SQL-level order is just a stable secondary; we re-sort in Python so
        # we can put joinable-now posts first regardless of which DB order is
        # cheapest.
        order = "created_at DESC"
        if sort and sort.value == "expiring_soon":
            order = "expires_at ASC"

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            params: list = [interaction.guild.id, interaction.channel.id]
            mission_clause = ""
            if mission_type:
                mission_clause = " AND mission_type LIKE ?"
                params.append(f"%{mission_type}%")

            cur = await db.execute(
                f"""
                SELECT id, creator_id, mission_type, max_players, description,
                       expires_at, created_at, message_id, status
                FROM lfg_posts
                WHERE guild_id=? AND channel_id=? AND {status_clause}
                {mission_clause}
                ORDER BY {order}
                LIMIT 100
                """,
                tuple(params),
            )
            posts = await cur.fetchall()

            counts_by_id: dict[int, int] = {}
            if posts:
                ids = [p[0] for p in posts]
                placeholders = ",".join(["?"] * len(ids))
                cur = await db.execute(
                    f"SELECT lfg_id, COUNT(*) FROM lfg_rsvps WHERE response='JOIN' AND lfg_id IN ({placeholders}) GROUP BY lfg_id",
                    tuple(ids),
                )
                for lfg_id, cnt in await cur.fetchall():
                    counts_by_id[int(lfg_id)] = int(cnt)

        # Optional platform filter — resolved from creator preferences (LFG rows
        # don't carry a platform column).
        if platform and platform.value != "-":
            keep: list = []
            for p in posts:
                creator_id = p[1]
                try:
                    creator_platform = await get_user_platform(interaction.guild.id, creator_id)
                except Exception:
                    creator_platform = None
                if (creator_platform or "pc").lower() == platform.value.lower():
                    keep.append(p)
            posts = keep

        # min_open_slots filter
        if min_open_slots > 0:
            filtered: list = []
            for p in posts:
                lfg_id, _creator, _mt, max_players, *_ = p
                rsvp = counts_by_id.get(int(lfg_id), 0)
                if (max_players - rsvp) >= min_open_slots:
                    filtered.append(p)
            posts = filtered

        # Compute "open" / "filled" tallies for the summary line.
        open_count = 0
        filled_count = 0
        for p in posts:
            lfg_id, _creator, _mt, max_players, *_rest, status = p
            rsvp = counts_by_id.get(int(lfg_id), 0)
            if status == "COMPLETED" or rsvp >= max_players:
                filled_count += 1
            else:
                open_count += 1

        # Sort: joinable first (open seats > 0) then secondary by chosen order.
        def _expiry_ts(p) -> float:
            try:
                dt = datetime.fromisoformat(str(p[5]).replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return float("inf")

        def _created_ts(p) -> float:
            try:
                dt = datetime.fromisoformat(str(p[6]).replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return 0.0

        def _open_seats(p) -> int:
            return max(0, int(p[3]) - counts_by_id.get(int(p[0]), 0))

        sort_value = sort.value if sort else "joinable"
        if sort_value == "newest":
            posts.sort(key=lambda p: (-(_open_seats(p) > 0), -_created_ts(p)))
        elif sort_value == "expiring_soon":
            posts.sort(key=lambda p: (-(_open_seats(p) > 0), _expiry_ts(p)))
        else:  # "joinable" default
            posts.sort(key=lambda p: (-(_open_seats(p) > 0), _expiry_ts(p)))

        if not posts:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🔍 No Active Groups",
                    "There are no active LFG posts matching your filters.\n\nUse `/lfg` to create one!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Build pages
        pages = []
        for i in range(0, len(posts), ITEMS_PER_PAGE):
            page_posts = posts[i : i + ITEMS_PER_PAGE]
            fields = []
            for lfg_id, creator_id, mission_type_val, max_players, description, expires_at, created_at, message_id, status in page_posts:
                rsvp_count = counts_by_id.get(int(lfg_id), 0)
                open_seats = max(0, max_players - rsvp_count)

                creator = interaction.guild.get_member(creator_id)
                creator_name = creator.display_name if creator else f"User {creator_id}"

                try:
                    expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    time_remaining = expiry_dt - datetime.now(timezone.utc)
                    if time_remaining.total_seconds() > 0:
                        hours = int(time_remaining.total_seconds() // 3600)
                        time_str = f"Expires in {hours}h" if hours > 0 else "Expiring soon"
                    else:
                        time_str = "Expired"
                except Exception:
                    time_str = "Unknown"

                status_emoji = "🟢" if open_seats > 0 and status != "COMPLETED" else "⛔"

                value = f"{status_emoji} **{rsvp_count}/{max_players}** · {open_seats} open\n"
                value += f"👤 {creator_name}\n"
                value += f"⏰ {time_str}\n"
                if description:
                    value += f"📝 _{description[:60]}{'...' if len(description) > 60 else ''}_\n"
                jump_link = ""
                if message_id and interaction.channel.id:
                    jump_link = f"\n[Jump to post](https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{message_id})"
                value += f"`ID: {lfg_id}`{jump_link}"

                fields.append((f"🎯 {mission_type_val}", value, True))

            desc_lines = [
                f"**Total: {open_count} open · {filled_count} filled**"
            ]
            applied: list[str] = []
            if mission_type:
                applied.append(f"mission=`{mission_type}`")
            if platform and platform.value != "-":
                applied.append(f"platform=`{platform.value.upper()}`")
            if min_open_slots > 1:
                applied.append(f"min_open_slots=`{min_open_slots}`")
            if include_filled:
                applied.append("filled=included")
            if applied:
                desc_lines.append("Filters: " + ", ".join(applied))
            pages.append({"description": "\n".join(desc_lines), "fields": fields})

        if len(pages) == 1:
            embed = obsidian_embed(
                "🔍 Active LFG Posts",
                pages[0]["description"],
                color=discord.Color.blue(),
                fields=pages[0]["fields"],
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            view = EmbedPaginator(
                "🔍 Active LFG Posts",
                pages,
                color=discord.Color.blue(),
                client=interaction.client,
                total_items=len(posts),
                per_page=ITEMS_PER_PAGE,
            )
            await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)
