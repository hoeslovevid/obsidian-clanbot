"""LFG (Looking for Group) command for Warframe missions."""
import logging
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed, get_mod_role, extract_id
from database import DB_PATH, get_guild_setting, set_guild_setting
import aiosqlite

logger = logging.getLogger(__name__)

_LFG_COLUMNS_READY = False


async def _format_host_line(guild: discord.Guild, member: discord.Member) -> str:
    """Host mention with optional AFK flag and equipped badge."""
    line = member.display_name
    try:
        from database import get_afk_status

        afk = await get_afk_status(guild.id, member.id)
        if afk:
            reason = afk.get("reason") if isinstance(afk, dict) else None
            line += " · 💤 AFK" + (f" ({str(reason)[:40]})" if reason else "")
    except Exception:
        pass
    try:
        from commands.general.profile import get_user_profile_data

        pdata = await get_user_profile_data(guild.id, member.id)
        badge = pdata.get("equipped_badge")
        if badge and isinstance(badge, (list, tuple)) and len(badge) >= 2:
            line = f"{badge[0]} {line}"
    except Exception:
        pass
    return f"{member.mention} ({line})"


async def _ensure_lfg_columns() -> None:
    global _LFG_COLUMNS_READY
    if _LFG_COLUMNS_READY:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("PRAGMA table_info(lfg_posts)")
        cols = {row[1] for row in await cur.fetchall()}
        if "radio_query" not in cols:
            await db.execute("ALTER TABLE lfg_posts ADD COLUMN radio_query TEXT")
            await db.commit()
    _LFG_COLUMNS_READY = True


# Item 35: cycle-aware nudges.
# Mission type -> (cycle key, desired state, friendly noun).
# desired state == None means "we only need to surface the current cycle".
_CYCLE_HINTS: dict[str, tuple[str, Optional[str], str]] = {
    "Eidolon Hunt":   ("cetus",   "night", "Plains"),
    "Plains":         ("cetus",   None,    "Plains"),
    "Profit-Taker":   ("vallis",  None,    "Vallis"),
    "Exploiter Orb":  ("vallis",  "cold",  "Vallis"),
    "Vallis":         ("vallis",  None,    "Vallis"),
    "Cambion Drift":  ("cambion", None,    "Cambion"),
}


def _cycle_hint_for(mission_type: str) -> Optional[tuple[str, Optional[str], str]]:
    if mission_type in _CYCLE_HINTS:
        return _CYCLE_HINTS[mission_type]
    # Sub-string match for things like "Plains - Bounty" if anyone adds them later.
    for key, payload in _CYCLE_HINTS.items():
        if key.lower() in mission_type.lower():
            return payload
    return None


async def _build_cycle_nudge(mission_type: str) -> Optional[str]:
    """Return a single-line cycle nudge for this mission type, or None when irrelevant."""
    hint = _cycle_hint_for(mission_type)
    if hint is None:
        return None
    cycle_key, desired_state, friendly = hint

    try:
        from api.warframe_api import get_all_cycles
        cycles = await get_all_cycles()
    except Exception as e:
        logger.debug(f"[lfg] cycle fetch failed: {e}")
        return None
    if not cycles:
        return None
    cycle = cycles.get(cycle_key)
    if not cycle:
        return None
    state = str(cycle.get("state") or "").lower()
    expiry_raw = cycle.get("expiry") or cycle.get("timeLeft") or ""

    expiry_ts: Optional[int] = None
    if expiry_raw and isinstance(expiry_raw, str):
        try:
            import dateparser  # type: ignore
            dt = dateparser.parse(
                expiry_raw,
                settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if dt:
                expiry_ts = int(dt.timestamp())
        except Exception:
            expiry_ts = None

    emoji_map = {
        "day": "☀️", "night": "🌙",
        "warm": "🔥", "cold": "❄️",
        "vome": "🌑", "fass": "🌕",
    }
    emoji = emoji_map.get(state, "⏳")
    when_part = f" ends <t:{expiry_ts}:R>" if expiry_ts else ""

    if desired_state is None:
        return f"{emoji} {friendly}: {state.title() or 'Unknown'}{when_part}."
    if state == desired_state:
        return f"{emoji} {friendly}: {state.title()} — great for {mission_type}!{when_part}"
    return f"{emoji} {friendly}: {state.title()} (need {desired_state.title()} for {mission_type}){when_part}."


# Common Warframe mission types
MISSION_TYPES = [
    "Elite SO (ESO)",
    "Sanctuary SO",
    "Steel Path",
    "Arbitration",
    "Sortie",
    "Eidolon Hunt",
    "Profit-Taker",
    "Exploiter Orb",
    "Void Fissure",
    "Relic Farming",
    "Resource Farming",
    "Affinity Farming",
    "Index",
    "Disruption",
    "Defense",
    "Survival",
    "Excavation",
    "Interception",
    "Spy",
    "Assassination",
    "Other",
]


class LFGQuickModal(discord.ui.Modal, title="Quick LFG Post"):
    """Modal for template-driven LFG posts."""

    mission_input = discord.ui.TextInput(
        label="Mission type",
        placeholder="Steel Path, Sortie, Archon Hunt, …",
        max_length=80,
        required=True,
    )
    max_players_input = discord.ui.TextInput(
        label="Max players",
        placeholder="4",
        default="4",
        max_length=2,
        required=False,
    )
    duration_input = discord.ui.TextInput(
        label="Duration (hours)",
        placeholder="24",
        default="24",
        max_length=3,
        required=False,
    )
    notes_input = discord.ui.TextInput(
        label="Notes",
        style=discord.TextStyle.paragraph,
        placeholder="Loadout, MR, voice, etc.",
        max_length=500,
        required=False,
    )
    radio_input = discord.ui.TextInput(
        label="Squad radio (optional)",
        placeholder="YouTube playlist URL or search query",
        max_length=200,
        required=False,
    )

    def __init__(self, bot, *, mission_type: str, description: str = ""):
        super().__init__()
        self.bot = bot
        self.mission_input.default = mission_type
        if description:
            self.notes_input.default = description

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_players = int((self.max_players_input.value or "4").strip())
        except ValueError:
            max_players = 4
        try:
            duration_hours = int((self.duration_input.value or "24").strip())
        except ValueError:
            duration_hours = 24
        mission = (self.mission_input.value or "").strip()
        if not mission:
            return await interaction.response.send_message(
                "Mission type is required.", ephemeral=True,
            )
        await create_lfg_post(
            self.bot,
            interaction,
            mission,
            max_players,
            duration_hours,
            (self.notes_input.value or "").strip(),
            None,
            radio_query=(self.radio_input.value or "").strip() or None,
        )


class LFGTemplateView(discord.ui.View):
    """Steel Path / Sortie / Archon quick-post templates."""

    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Steel Path", style=discord.ButtonStyle.primary, emoji="🗡️")
    async def steel_path(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            LFGQuickModal(
                self.bot,
                mission_type="Steel Path",
                description="Steel Path farm — relics, SP fissures, or daily challenge.",
            ),
        )

    @discord.ui.button(label="Sortie", style=discord.ButtonStyle.primary, emoji="🎯")
    async def sortie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            LFGQuickModal(
                self.bot,
                mission_type="Sortie",
                description="Today's sortie — mention loadout & archon shard goals if any.",
            ),
        )

    @discord.ui.button(label="Archon", style=discord.ButtonStyle.primary, emoji="👹")
    async def archon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            LFGQuickModal(
                self.bot,
                mission_type="Other",
                description="Archon Hunt — specify shard/boss in notes. Use /warframe archon for timers.",
            ),
        )

    @discord.ui.button(label="Hints", style=discord.ButtonStyle.secondary, emoji="💡")
    async def hints(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=obsidian_embed(
                "LFG Quick Templates",
                "**Steel Path** — SP fissures, daily bonus, endurance.\n"
                "**Sortie** — 3 missions, modifier-aware loadouts.\n"
                "**Archon** — weekly hunt; check `/warframe archon`.\n\n"
                "Tap a template button to open a pre-filled form, or use `/lfg` with full options.",
                client=interaction.client,
            ),
            ephemeral=True,
        )


async def _format_rsvp_field(
    guild: discord.Guild,
    rsvps: list[tuple[int]],
    max_players: int,
) -> str:
    """Build the Players field body for an LFG post."""
    lines: list[str] = []
    for i, (user_id,) in enumerate(rsvps[:max_players], 1):
        user = guild.get_member(user_id)
        username = user.display_name if user else f"User {user_id}"
        lines.append(f"{i}. {username}")
    remaining = max_players - len(rsvps)
    if remaining > 0:
        lines.append(f"\n_{remaining} slot(s) remaining_")
    else:
        lines.append("\n_**Group is full!**_")
    return "\n".join(lines) if lines else "No players yet"


async def _sync_lfg_thread_member(
    thread: discord.Thread,
    member: discord.Member,
    *,
    action: str,
    creator_id: int,
) -> None:
    """Add/remove a member on an LFG private thread (Thread has no set_permissions)."""
    if action == "JOIN":
        await thread.add_user(member)
    elif action == "LEAVE" and member.id != creator_id:
        await thread.remove_user(member)


async def _rebuild_lfg_fields(
    guild: discord.Guild,
    *,
    mission_type: str,
    creator_id: int,
    max_players: int,
    description: str | None,
    role_tags: str | None,
    scheduled_at: str | None,
    radio_query: str | None,
    expires_at_iso: str | None,
    rsvps: list[tuple[int]],
) -> list[tuple[str, str, bool]]:
    """Rebuild embed/layout fields for an LFG post after RSVP changes."""
    creator = guild.get_member(creator_id)
    host_line = (
        await _format_host_line(guild, creator)
        if creator
        else f"<@{creator_id}>"
    )
    expires_str = "Unknown"
    if expires_at_iso:
        try:
            exp = datetime.fromisoformat(str(expires_at_iso).replace("Z", "+00:00"))
            expires_str = f"<t:{int(exp.timestamp())}:R>"
        except Exception:
            expires_str = str(expires_at_iso)[:40]

    fields: list[tuple[str, str, bool]] = [
        ("🎯 Mission", mission_type, True),
        ("👤 Created by", host_line, True),
        ("⏰ Expires", expires_str, True),
    ]
    if description:
        fields.append(("📝 Notes", str(description)[:500], False))
    if role_tags:
        fields.append(("🏷️ Roles", str(role_tags), True))
    if scheduled_at:
        fields.append(("🕐 Scheduled", str(scheduled_at), True))
    if radio_query:
        fields.append(
            (
                "🎵 Squad radio",
                f"`{str(radio_query)[:120]}`\nTap **Start squad radio** when you're in VC.",
                False,
            )
        )
    fields.append(
        ("👥 Players", await _format_rsvp_field(guild, rsvps, max_players), False)
    )
    cycle_nudge = await _build_cycle_nudge(mission_type)
    if cycle_nudge:
        fields.append(("🌍 World cycle", cycle_nudge, False))
    return fields


async def _edit_lfg_rsvp_message(
    interaction: discord.Interaction,
    view: "LFGView",
    *,
    guild: discord.Guild,
    creator_id: int,
    mission_type: str,
    max_players: int,
    description: str | None,
    role_tags: str | None,
    scheduled_at: str | None,
    radio_query: str | None,
    expires_at_iso: str | None,
    rsvps: list[tuple[int]],
) -> discord.Embed | None:
    """Update the LFG post message after join/leave (embed or Components V2 layout)."""
    message = interaction.message
    if not message:
        return None

    fields = await _rebuild_lfg_fields(
        guild,
        mission_type=mission_type,
        creator_id=creator_id,
        max_players=max_players,
        description=description,
        role_tags=role_tags,
        scheduled_at=scheduled_at,
        radio_query=radio_query,
        expires_at_iso=expires_at_iso,
        rsvps=rsvps,
    )
    embed_for_dm: discord.Embed | None = None

    if message.embeds:
        embed = message.embeds[0].copy()
        for i, field in enumerate(embed.fields):
            if field.name == "Players":
                players_value = next((v for n, v, _ in fields if n == "👥 Players"), field.value)
                embed.set_field_at(i, name="Players", value=players_value, inline=False)
                break
        await interaction.response.edit_message(embed=embed, view=view)
        embed_for_dm = embed
    else:
        from core.help_layout import help_layout_v2_enabled
        from core.lfg_layout import LFGPanelLayout

        if help_layout_v2_enabled():
            creator = guild.get_member(creator_id)
            host_mention = creator.mention if creator else f"<@{creator_id}>"
            layout = LFGPanelLayout(
                lfg_id=view.lfg_id,
                intro=f"> Host: {host_mention} · Mission **{mission_type}**",
                fields=fields,
                on_join=view.join,
                on_leave=view.leave,
                on_filled=view.mark_filled,
                on_radio=view.start_radio if view._has_radio else None,
            )
            await interaction.response.edit_message(view=layout)
        else:
            await interaction.response.edit_message(view=view)

    return embed_for_dm


class LFGView(discord.ui.View):
    """View with RSVP buttons for LFG posts."""
    
    def __init__(self, lfg_id: int, *, has_radio: bool = True):
        super().__init__(timeout=None)
        self.lfg_id = lfg_id
        self._has_radio = has_radio
        join = discord.ui.Button(
            label="Join",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"lfg:{lfg_id}:join",
            row=0,
        )
        join.callback = self.join
        self.add_item(join)
        leave = discord.ui.Button(
            label="Leave",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"lfg:{lfg_id}:leave",
            row=0,
        )
        leave.callback = self.leave
        self.add_item(leave)
        filled = discord.ui.Button(
            label="Mark as Filled",
            style=discord.ButtonStyle.primary,
            emoji="✅",
            custom_id=f"lfg:{lfg_id}:complete",
            row=0,
        )
        filled.callback = self.mark_filled
        self.add_item(filled)
        if has_radio:
            radio = discord.ui.Button(
                label="Start squad radio",
                style=discord.ButtonStyle.secondary,
                emoji="🎵",
                custom_id=f"lfg:{lfg_id}:radio",
                row=1,
            )
            radio.callback = self.start_radio
            self.add_item(radio)
        wait_btn = discord.ui.Button(
            label="Notify when open",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id=f"lfg:{lfg_id}:wait",
            row=1,
        )
        wait_btn.callback = self.notify_when_open
        self.add_item(wait_btn)
        squad_vc = discord.ui.Button(
            label="Open squad VC",
            style=discord.ButtonStyle.secondary,
            emoji="🎙️",
            custom_id=f"lfg:{lfg_id}:squad_vc",
            row=1,
        )
        squad_vc.callback = self.open_squad_vc
        self.add_item(squad_vc)
        copy_btn = discord.ui.Button(
            label="Copy invite",
            style=discord.ButtonStyle.secondary,
            emoji="🔗",
            custom_id=f"lfg:{lfg_id}:copy",
            row=2,
        )
        copy_btn.callback = self.copy_invite
        self.add_item(copy_btn)
        repost = discord.ui.Button(
            label="Re-post",
            style=discord.ButtonStyle.secondary,
            emoji="🔁",
            custom_id=f"lfg:{lfg_id}:repost",
            row=2,
        )

        async def repost_cb(btn_interaction: discord.Interaction):
            from core.lfg_repost import open_lfg_repost_modal

            await open_lfg_repost_modal(btn_interaction, btn_interaction.client, self.lfg_id)

        repost.callback = repost_cb  # type: ignore
        self.add_item(repost)
    
    async def copy_invite(self, interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, message_id, thread_id FROM lfg_posts WHERE id=?",
                (self.lfg_id,),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.followup.send("LFG post not found.", ephemeral=True)
        channel_id, message_id, thread_id = row
        url = None
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                url = thread.jump_url
        if not url and channel_id and message_id:
            url = f"https://discord.com/channels/{interaction.guild.id}/{channel_id}/{message_id}"
        if not url:
            return await interaction.followup.send("Could not build an invite link for this post.", ephemeral=True)
        await interaction.followup.send(
            f"Share this LFG link:\n{url}",
            ephemeral=True,
        )
    
    async def open_squad_vc(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        await interaction.response.defer(ephemeral=True)
        from core.lfg_squad_vc import create_squad_vc_for_lfg

        ok, msg, _vc = await create_squad_vc_for_lfg(
            interaction.client, interaction.guild, self.lfg_id, interaction.user,
        )
        await interaction.followup.send(msg, ephemeral=True)

    async def join(self, interaction: discord.Interaction):
        """Join the LFG group."""
        await self._handle_rsvp(interaction, "JOIN")
    
    async def leave(self, interaction: discord.Interaction):
        """Leave the LFG group."""
        await self._handle_rsvp(interaction, "LEAVE")

    async def notify_when_open(self, interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT max_players, status, mission_type FROM lfg_posts WHERE id=?",
                (self.lfg_id,),
            )
            row = await cur.fetchone()
            if not row:
                from core.reply_helpers import reply_error
                return await reply_error(interaction, "Not found", "LFG post not found.")
            max_players, status, mission_type = row
            if status != "OPEN":
                from core.reply_helpers import reply_error
                return await reply_error(interaction, "Closed", "This LFG post is no longer open.")
            cur = await db.execute(
                "SELECT COUNT(*) FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN'",
                (self.lfg_id,),
            )
            joined = int((await cur.fetchone())[0] or 0)
        if joined < max_players:
            from core.reply_helpers import reply_info
            return await reply_info(
                interaction,
                "Slots available",
                f"**{max_players - joined}** slot(s) open — tap **Join** instead.",
            )
        from core.lfg_waitlist import add_waitlist

        added = await add_waitlist(self.lfg_id, interaction.guild.id, interaction.user.id)
        from core.reply_helpers import reply_success, reply_info
        if added:
            await reply_success(
                interaction,
                "You're on the list",
                f"I'll DM you when **{mission_type}** has an open slot.",
            )
        else:
            await reply_info(interaction, "Already waiting", "You're already on the notify list for this post.")

    async def start_radio(self, interaction: discord.Interaction):
        """Queue the LFG radio playlist in the requester's VC."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Join a voice channel first, then tap **Start squad radio**.",
                ephemeral=True,
            )
        await _ensure_lfg_columns()
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT radio_query, status FROM lfg_posts WHERE id=?",
                (self.lfg_id,),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.followup.send("LFG post not found.", ephemeral=True)
        radio_query, status = row
        if status != "OPEN":
            return await interaction.followup.send("This LFG post is no longer open.", ephemeral=True)
        if not (radio_query or "").strip():
            return await interaction.followup.send(
                "No squad radio was set for this LFG. Host can recreate with a playlist URL or search query.",
                ephemeral=True,
            )
        from core.music_player import enqueue_query
        from database import get_quieter_mode

        text_ch_id = interaction.channel.id if interaction.channel else None
        ok, msg = await enqueue_query(
            interaction.guild,
            interaction.client,
            str(radio_query).strip(),
            interaction.user.id,
            interaction.user.voice.channel,
            text_channel_id=text_ch_id,
            announce=not await get_quieter_mode(interaction.guild.id),
        )
        if ok:
            from core.utils import success_embed

            await interaction.followup.send(
                embed=success_embed("Squad Radio", msg, client=interaction.client),
                ephemeral=True,
            )
        else:
            from core.utils import error_embed

            await interaction.followup.send(
                embed=error_embed("Squad Radio", msg, client=interaction.client),
                ephemeral=True,
            )
    
    async def mark_filled(self, interaction: discord.Interaction):
        """Mark the group as filled (creator only) — keeps post visible with [FILLED] label."""
        from core.lfg_fill import mark_lfg_filled

        await interaction.response.defer(ephemeral=True)
        ok, msg = await mark_lfg_filled(
            self.lfg_id,
            interaction.user.id,
            client=interaction.client,
            guild=interaction.guild,
        )
        if not ok:
            return await interaction.followup.send(msg, ephemeral=True)
        try:
            if interaction.message and interaction.message.embeds:
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                old_title = embed.title or "Looking for Group"
                if not old_title.startswith("[FILLED"):
                    embed.title = f"[FILLED ✅] {old_title}"
                embed.set_footer(text="✅ Group filled — post will auto-archive soon")
                for item in self.children:
                    if isinstance(item, discord.ui.Button) and item.label in ("Join", "Mark as Filled"):
                        item.disabled = True
                from core.safe_message_edit import safe_message_edit

                await safe_message_edit(interaction.message, embed=embed, view=self)
        except Exception:
            pass
        await interaction.followup.send(msg, ephemeral=True)
        try:
            repost_view = discord.ui.View(timeout=120)
            repost_view.add_item(
                discord.ui.Button(
                    label="Re-post same mission",
                    style=discord.ButtonStyle.primary,
                    emoji="🔁",
                    custom_id=f"lfg:{self.lfg_id}:repost",
                )
            )
            await interaction.followup.send(
                "Need another squad? Tap **Re-post** to clone this LFG.",
                view=repost_view,
                ephemeral=True,
            )
        except Exception:
            pass
    
    async def _handle_rsvp(self, interaction: discord.Interaction, response: str):
        """Handle RSVP (join/leave)."""
        if not interaction.guild:
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        channel_id = message_id = mission_type = None
        description = role_tags = scheduled_at = radio_query = expires_at_iso = None
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT creator_id, max_players, status, thread_id, channel_id, message_id, mission_type,
                       description, role_tags, scheduled_at, radio_query, expires_at
                FROM lfg_posts WHERE id=?
                """,
                (self.lfg_id,),
            )
            post = await cur.fetchone()

            if not post:
                from core.reply_helpers import reply_error
                return await reply_error(interaction, "Not found", "LFG post not found.")

            (
                creator_id,
                max_players,
                status,
                thread_id,
                channel_id,
                message_id,
                mission_type,
                description,
                role_tags,
                scheduled_at,
                radio_query,
                expires_at_iso,
            ) = post

            if status != "OPEN":
                from core.reply_helpers import reply_error
                return await reply_error(interaction, "Closed", "This LFG post is no longer open.")
            
            # Check current RSVPs
            cur = await db.execute(
                "SELECT COUNT(*) FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN'",
                (self.lfg_id,)
            )
            current_count = (await cur.fetchone())[0]
            
            if response == "JOIN":
                if current_count >= max_players:
                    from core.reply_helpers import reply_error
                    return await reply_error(
                        interaction,
                        "Group full",
                        f"This group is full ({max_players}/{max_players} players). "
                        "Tap **Notify when open** to get a DM if someone leaves.",
                    )
                
                # Add or update RSVP
                await db.execute("""
                    INSERT INTO lfg_rsvps (lfg_id, user_id, response, created_at)
                    VALUES (?, ?, 'JOIN', ?)
                    ON CONFLICT(lfg_id, user_id) DO UPDATE SET response='JOIN', created_at=?
                """, (self.lfg_id, interaction.user.id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
            else:  # LEAVE
                await db.execute(
                    "DELETE FROM lfg_rsvps WHERE lfg_id=? AND user_id=?",
                    (self.lfg_id, interaction.user.id)
                )
            
            await db.commit()
            
            # Get updated RSVP list
            cur = await db.execute(
                "SELECT user_id FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN' ORDER BY created_at",
                (self.lfg_id,)
            )
            rsvps = await cur.fetchall()
            current_count = len(rsvps)
        
        # Update thread membership if thread exists
        if thread_id and isinstance(interaction.user, discord.Member):
            try:
                thread = interaction.guild.get_thread(thread_id)
                if thread:
                    await _sync_lfg_thread_member(
                        thread,
                        interaction.user,
                        action=response,
                        creator_id=int(creator_id),
                    )
            except Exception as exc:
                logger.error("Failed to update thread membership for LFG %s: %s", self.lfg_id, exc)

        embed = await _edit_lfg_rsvp_message(
            interaction,
            self,
            guild=interaction.guild,
            creator_id=int(creator_id),
            mission_type=str(mission_type or "LFG"),
            max_players=int(max_players),
            description=description,
            role_tags=role_tags,
            scheduled_at=scheduled_at,
            radio_query=radio_query,
            expires_at_iso=expires_at_iso,
            rsvps=rsvps,
        )
        action = "joined" if response == "JOIN" else "left"
        thread_mention = ""
        if thread_id:
            try:
                thread = interaction.guild.get_thread(thread_id)
                if thread:
                    thread_mention = f" Check the thread: {thread.mention}"
            except Exception:
                pass
        await interaction.followup.send(f"You {action} the group! ({current_count}/{max_players}){thread_mention}", ephemeral=True)

        if response == "LEAVE" and current_count < max_players:
            try:
                from core.lfg_waitlist import notify_waitlist

                await notify_waitlist(
                    interaction.client,
                    self.lfg_id,
                    mission=mission_type or "LFG",
                    channel_id=channel_id,
                    message_id=message_id,
                    slots_open=max_players - current_count,
                )
            except Exception:
                pass

        # DM the creator when the group becomes full
        if response == "JOIN" and current_count >= max_players:
            try:
                creator = interaction.guild.get_member(creator_id)
                if creator:
                    from core.utils import obsidian_embed
                    from core.lfg_fill import LFGDMMarkFilledView

                    dm_embed = obsidian_embed(
                        "✅ Your LFG Group is Full!",
                        f"Your **{(embed.title if embed else mission_type) or 'LFG'}** group has reached **{max_players}/{max_players}** players.\n\n"
                        f"The last player to join was **{interaction.user.display_name}**.\n\n"
                        f"Tap **Open squad VC** on the post when you're ready to voice up.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    )
                    dm_view = LFGDMMarkFilledView(self.lfg_id)
                    interaction.client.add_view(dm_view)
                    await creator.send(embed=dm_embed, view=dm_view)
            except (discord.Forbidden, discord.HTTPException):
                pass


async def create_lfg_post(
    bot,
    interaction,
    mission_type: str,
    max_players: int,
    duration_hours: int,
    description: str,
    ping_role_id: int | None,
    *,
    role_tags: str | None = None,
    scheduled_at: str | None = None,
    radio_query: str | None = None,
):
    """Create an LFG post. Used by both /lfg and the Quick LFG context menu."""
    from core.utils import get_mod_role

    if not interaction.guild:
        return await interaction.response.send_message(
            "LFG posts can only be created in a server.",
            ephemeral=True,
        )
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        return await interaction.response.send_message(
            "LFG posts must be created in a text channel or thread.",
            ephemeral=True,
        )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    mention = ""
    if ping_role_id:
        try:
            cooldown_s = await get_guild_setting(interaction.guild.id, "lfg_ping_cooldown_minutes")
            cooldown_min = int(cooldown_s) if cooldown_s and cooldown_s.isdigit() else 30
            last_ping_s = await get_guild_setting(interaction.guild.id, "lfg_last_ping_ts")
            last_ping_ts = int(last_ping_s) if last_ping_s and last_ping_s.isdigit() else 0
            now_ts = int(datetime.now(timezone.utc).timestamp())
            if now_ts - last_ping_ts >= max(0, cooldown_min) * 60:
                role = interaction.guild.get_role(int(ping_role_id))
                if role:
                    mention = role.mention
                    await set_guild_setting(interaction.guild.id, "lfg_last_ping_ts", str(now_ts))
        except Exception:
            pass

    tags_clean = (role_tags or "").strip()[:200] or None
    sched_clean = (scheduled_at or "").strip()[:80] or None
    radio_clean = (radio_query or "").strip()[:200] or None

    await _ensure_lfg_columns()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO lfg_posts (
                guild_id, channel_id, message_id, creator_id, mission_type, player_count,
                max_players, description, created_at, expires_at, status, ping_role_id,
                role_tags, scheduled_at, reminder_sent, radio_query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, 0, ?)
        """, (
            interaction.guild.id,
            interaction.channel.id,
            0,
            interaction.user.id,
            mission_type,
            1,
            max_players,
            description[:500] if description else None,
            datetime.now(timezone.utc).isoformat(),
            expires_at.isoformat(),
            int(ping_role_id or 0),
            tags_clean,
            sched_clean,
            radio_clean,
        ))
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        lfg_id = (await cur.fetchone())[0]

    mission_name = mission_type
    expires_str = f"Expires in {duration_hours}h • <t:{int(expires_at.timestamp())}:R>"
    host_line = await _format_host_line(interaction.guild, interaction.user)
    fields = [
        ("🎯 Mission", mission_name, True),
        ("👤 Created by", host_line, True),
        ("⏰ Expires", expires_str, True),
    ]
    if description:
        fields.append(("📝 Notes", description[:500], False))
    if tags_clean:
        fields.append(("🏷️ Roles", tags_clean, True))
    if sched_clean:
        fields.append(("🕐 Scheduled", sched_clean, True))
    if radio_clean:
        fields.append(("🎵 Squad radio", f"`{radio_clean[:120]}`\nTap **Start squad radio** when you're in VC.", False))
    fields.append(("👥 Players", f"1. {interaction.user.display_name}\n\n_{max_players - 1} slot(s) remaining_", False))
    cycle_nudge: Optional[str] = None
    try:
        cycle_nudge = await _build_cycle_nudge(mission_type)
    except Exception as e:
        logger.debug(f"[lfg] cycle nudge skipped: {e}")
    if cycle_nudge:
        fields.append(("🌍 World cycle", cycle_nudge, False))

    from core.wf_copy import merge_wf_footer
    lfg_footer = merge_wf_footer(f"{footer_for('community_lfg')} · ID {lfg_id}", "warframe:lfg")
    embed = embed_template(
        "showcase",
        "🔍 Looking for Group",
        f"> Host: {interaction.user.mention} · Mission **{mission_name}**",
        category="community",
        fields=fields,
        footer=lfg_footer,
        client=interaction.client,
    )
    view = LFGView(lfg_id, has_radio=bool(radio_clean))

    from core.help_layout import help_layout_v2_enabled
    from core.lfg_layout import LFGPanelLayout

    if help_layout_v2_enabled():
        try:
            layout = LFGPanelLayout(
                lfg_id=lfg_id,
                intro=f"> Host: {interaction.user.mention} · Mission **{mission_name}**",
                fields=fields,
                on_join=view.join,
                on_leave=view.leave,
                on_filled=view.mark_filled,
                on_radio=view.start_radio if bool(radio_clean) else None,
            )
            await interaction.response.send_message(content=mention if mention else None, view=layout)
            message = await interaction.original_response()
            message_id = message.id
        except Exception:
            await interaction.response.send_message(content=mention if mention else None, embed=embed, view=view)
            message = await interaction.original_response()
            message_id = message.id
    else:
        await interaction.response.send_message(content=mention if mention else None, embed=embed, view=view)
        message = await interaction.original_response()
        message_id = message.id

    thread_id = None
    try:
        creator_name = interaction.user.display_name or interaction.user.name
        thread_name = f"{creator_name} - {mission_name}"
        if len(thread_name) > 100:
            max_mission_len = 100 - len(creator_name) - 3
            thread_name = f"{creator_name} - {mission_name[:max_mission_len]}" if max_mission_len > 0 else mission_name[:100]

        try:
            thread = await message.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=1440,
                reason="LFG group discussion thread",
            )
        except discord.HTTPException:
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,
                reason="LFG group discussion thread",
            )

        thread_id = thread.id
        await thread.add_user(interaction.user)
        mod_role = get_mod_role(interaction.guild)
        if mod_role:
            for mod_member in mod_role.members[:25]:
                try:
                    await thread.add_user(mod_member)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        welcome_msg = (
            f"Welcome to the {mission_name} LFG thread!\n\n"
            f"This thread is for coordinating with {interaction.user.mention} and other players who join.\n"
            "Only the creator, RSVPs, and moderators are added automatically."
        )
        await thread.send(welcome_msg)
    except Exception as e:
        logger.error("Failed to create thread for LFG %s: %s", lfg_id, e)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE lfg_posts SET message_id=?, thread_id=? WHERE id=?", (message_id, thread_id, lfg_id))
        await db.commit()

    bot.add_view(view)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lfg_rsvps (lfg_id, user_id, response, created_at) VALUES (?, ?, 'JOIN', ?)",
            (lfg_id, interaction.user.id, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()

    try:
        from core.lfg_extras import notify_lfg_interest
        await notify_lfg_interest(
            bot, interaction.guild,
            mission_type=mission_name,
            role_tags=tags_clean,
            lfg_id=lfg_id,
            creator_id=interaction.user.id,
        )
    except Exception:
        pass

    try:
        from core.first_run_nudge import maybe_first_run_hint
        from core.next_hints import get_next_step_hint

        hint = await maybe_first_run_hint(
            interaction.guild.id,
            interaction.user.id,
            "✅ Your LFG post is live.",
            feature="lfg",
        )
        next_hint = await get_next_step_hint(interaction.guild.id, interaction.user.id, "lfg")
        if next_hint:
            hint = f"{hint}\n-# {next_hint}" if hint else f"-# {next_hint}"
        if hint and ("💡" in hint or "Next:" in hint):
            await interaction.followup.send(hint, ephemeral=True)
    except Exception:
        pass


def setup(bot, group=None):
    """Register the lfg command."""
    if group:
        @group.command(name="quick", description="LFG templates — Steel Path, Sortie, Archon (pre-filled form).")
        async def lfg_quick(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message(
                    "LFG can only be used in a server.", ephemeral=True,
                )
            from core.utils import feature_enabled, feature_off_embed
            if not await feature_enabled(interaction.guild.id, "lfg"):
                return await interaction.response.send_message(
                    embed=feature_off_embed("LFG", client=interaction.client), ephemeral=True,
                )
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "Quick LFG",
                    "Pick a template to open a pre-filled post form.",
                    client=interaction.client,
                ),
                view=LFGTemplateView(bot),
                ephemeral=True,
            )

        @group.command(name="list", description="Browse open LFG posts in this server.")
        async def lfg_list(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Server only.", ephemeral=True)
            from core.utils import feature_enabled, feature_off_embed

            if not await feature_enabled(interaction.guild.id, "lfg"):
                return await interaction.response.send_message(
                    embed=feature_off_embed("LFG", client=interaction.client), ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            from core.lfg_list import LFGListEmptyView, build_lfg_list_embed

            embed = await build_lfg_list_embed(interaction.guild, client=interaction.client)
            view = None
            if embed.description and "No open squad posts" in embed.description:
                view = LFGListEmptyView(bot)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        @group.command(name="preset_save", description="Save an LFG template for one-tap reposting.")
        @app_commands.describe(
            name="Preset name (e.g. hydron)",
            mission_type="Mission type",
            max_players="Max squad size (1-8)",
            description="Default notes",
        )
        async def lfg_preset_save(
            interaction: discord.Interaction,
            name: str,
            mission_type: str,
            max_players: app_commands.Range[int, 1, 8] = 4,
            description: str = "",
        ):
            if not interaction.guild:
                return await interaction.response.send_message("Server only.", ephemeral=True)
            from core.lfg_presets import save_preset

            ok, msg = await save_preset(
                interaction.guild.id,
                interaction.user.id,
                name,
                mission_type,
                max_players,
                description,
            )
            await interaction.response.send_message(msg, ephemeral=True)

        @group.command(name="preset_list", description="List your saved LFG presets.")
        async def lfg_preset_list(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Server only.", ephemeral=True)
            from core.lfg_presets import list_presets

            presets = await list_presets(interaction.guild.id, interaction.user.id)
            if not presets:
                return await interaction.response.send_message(
                    "No presets yet — `/lfg preset_save` to save one.", ephemeral=True,
                )
            lines = [
                f"**{p['name']}** — {p['mission_type']} ({p['max_players']}p)"
                for p in presets
            ]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @group.command(name="preset_use", description="Post an LFG from a saved preset.")
        @app_commands.describe(name="Preset name")
        async def lfg_preset_use(interaction: discord.Interaction, name: str):
            if not interaction.guild:
                return await interaction.response.send_message("Server only.", ephemeral=True)
            from core.lfg_presets import get_preset

            preset = await get_preset(interaction.guild.id, interaction.user.id, name)
            if not preset:
                return await interaction.response.send_message("Preset not found.", ephemeral=True)
            await create_lfg_post(
                bot,
                interaction,
                preset["mission_type"],
                preset["max_players"],
                24,
                preset.get("description") or "",
                None,
                radio_query=preset.get("radio_query") or None,
            )

    command_decorator = group.command(name="lfg", description="Create an LFG post for a Warframe mission.") if group else bot.tree.command(name="lfg", description="Create an LFG post for a Warframe mission.")
    
    @command_decorator
    @app_commands.describe(
        mission_type="Type of mission",
        max_players="Maximum number of players needed (default: 4)",
        description="Optional description or notes",
        duration_hours="Auto-expire after this many hours (default: 24, max: 168)",
        role_ping="Optional role to ping (mention or ID). If omitted, uses server default if set.",
        role_tags="Squad roles — DPS, Support, Steel Path, Sortie, etc. (comma-separated)",
        scheduled_at="When you plan to run (e.g. today 8pm) — reminder ~15m before",
        radio_playlist="Optional YouTube playlist URL or search for squad radio",
    )
    @app_commands.choices(mission_type=[
        app_commands.Choice(name=mt, value=mt) for mt in MISSION_TYPES
    ])
    async def lfg(
        interaction: discord.Interaction,
        mission_type: app_commands.Choice[str],
        max_players: int = 4,
        description: str = "",
        duration_hours: int = 24,
        role_ping: str = "",
        role_tags: str = "",
        scheduled_at: str = "",
        radio_playlist: str = "",
    ):
        """Create an LFG post for a Warframe mission."""
        if not interaction.guild:
            return await interaction.response.send_message("LFG can only be used in a server.", ephemeral=True)
        from core.utils import feature_enabled, feature_off_embed  # Item 85
        if not await feature_enabled(interaction.guild.id, "lfg"):
            return await interaction.response.send_message(embed=feature_off_embed("LFG", client=interaction.client), ephemeral=True)
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message(
                "LFG posts must be created in a text channel or thread.",
                ephemeral=True,
            )
        if max_players < 1 or max_players > 8:
            return await interaction.response.send_message("Max players must be between 1 and 8.", ephemeral=True)
        if duration_hours < 1 or duration_hours > 168:
            duration_hours = 24

        ping_role_id = extract_id(role_ping) if role_ping else None
        if not ping_role_id:
            try:
                default_role_id = await get_guild_setting(interaction.guild.id, "lfg_ping_role_id")
                if default_role_id and default_role_id.isdigit():
                    ping_role_id = int(default_role_id)
            except Exception:
                ping_role_id = None

        await create_lfg_post(
            bot, interaction, mission_type.value, max_players, duration_hours,
            description or "", ping_role_id,
            role_tags=role_tags or None,
            scheduled_at=scheduled_at or None,
            radio_query=radio_playlist or None,
        )
