import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

import aiosqlite
import dateparser
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ============================================================
# Obsidian Clan Bot (Warframe Discord)
# - Join-to-create temporary voice channels in "Temp VCs"
# - Obsidian voice control panels (buttons + modals)
# - Complaints desk (button -> modal -> case embed + staff thread)
# - Mod actions + DM status updates to user
# - Ops events (natural language time parsing, RSVP, reminder)
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError(
        "Missing DISCORD_TOKEN environment variable. "
        "Please set DISCORD_TOKEN in your environment variables or Railway dashboard."
    )

# Optional (faster command sync when set; otherwise global sync)
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

MOD_ROLE_NAME = os.getenv("MOD_ROLE_NAME", "Obsidian Inheritor")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")

# Temp VC config
TEMP_VC_CATEGORY_ID = int(os.getenv("TEMP_VC_CATEGORY_ID", "0") or "0")
TEMP_VC_CATEGORY_NAME = os.getenv("TEMP_VC_CATEGORY_NAME", "Temp VCs")
CREATE_VC_NAME = os.getenv("CREATE_VC_NAME", "➕ Form Squad")
VOICE_IDLE_DELETE_MINUTES = int(os.getenv("VOICE_IDLE_DELETE_MINUTES", "5"))
VC_CLEANUP_INTERVAL_MINUTES = int(os.getenv("VC_CLEANUP_INTERVAL_MINUTES", "2"))

# Channel names (used if IDs not provided / when AUTO_SETUP makes them)
VOICE_PANEL_CHANNEL_ID = int(os.getenv("VOICE_PANEL_CHANNEL_ID", "0") or "0")
VOICE_PANEL_CHANNEL_NAME = os.getenv("VOICE_PANEL_CHANNEL_NAME", "obsidian-console")

COMPLAINTS_CHANNEL_ID = int(os.getenv("COMPLAINTS_CHANNEL_ID", "0") or "0")
COMPLAINTS_CHANNEL_NAME = os.getenv("COMPLAINTS_CHANNEL_NAME", "inheritor-docket")

COMPLAINTS_LOG_CHANNEL_ID = int(os.getenv("COMPLAINTS_LOG_CHANNEL_ID", "0") or "0")
COMPLAINTS_LOG_CHANNEL_NAME = os.getenv("COMPLAINTS_LOG_CHANNEL_NAME", "docket-ledger")

EVENTS_CHANNEL_ID = int(os.getenv("EVENTS_CHANNEL_ID", "0") or "0")
EVENTS_CHANNEL_NAME = os.getenv("EVENTS_CHANNEL_NAME", "ops-board")

AUTO_SETUP = os.getenv("AUTO_SETUP", "true").lower() in ("1", "true", "yes", "y", "on")

# Events
EVENT_REMINDER_MINUTES_BEFORE = int(os.getenv("EVENT_REMINDER_MINUTES_BEFORE", "60"))
EVENT_REMINDER_LOOP_MINUTES = int(os.getenv("EVENT_REMINDER_LOOP_MINUTES", "1"))

# Intents
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.voice_states = True


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def obsidian_embed(title: str, desc: str = "", *, color: discord.Color = discord.Color.dark_grey()) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = now_utc()
    return e


def get_mod_role(guild: discord.Guild) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=MOD_ROLE_NAME)


def is_mod(member: discord.Member) -> bool:
    return any(r.name == MOD_ROLE_NAME for r in member.roles)


def parse_time_natural(text: str) -> Optional[datetime]:
    """
    Returns a timezone-aware datetime in UTC, or None.
    Accepts: "tomorrow 8pm", "Jan 15 7:30pm", etc.
    """
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": TIMEZONE,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TO_TIMEZONE": "UTC",
            "PREFER_DATES_FROM": "future",
        },
    )
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_id(text: str) -> Optional[int]:
    m = re.search(r"(\d{15,25})", text or "")
    return int(m.group(1)) if m else None

def display_case_status(status: str) -> str:
    s = (status or "").strip().upper()
    return {
        "OPEN": "Filed",
        "ACKNOWLEDGED": "Reviewed",
        "NEEDS INFO": "Evidence Requested",
        "RESOLVED": "Closed",
        "REJECTED": "Dismissed",
    }.get(s, status.title() if status else "Unknown")


# --------------------- Bot ---------------------
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        # Sync commands: to a single guild for speed if GUILD_ID set, else global.
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                # Copy global commands to guild, then sync
                try:
                    self.tree.copy_global_to(guild=guild)
                except AttributeError:
                    # copy_global_to might not exist in all versions, skip if missing
                    pass
                await self.tree.sync(guild=guild)
                print(f"[sync] Synced commands to guild {GUILD_ID}")
            else:
                await self.tree.sync()
                print("[sync] Synced commands globally (may take a while to appear)")
        except Exception as e:
            print(f"[sync] Failed to sync commands: {e}")


bot = ClanBot()


# --------------------- DB ---------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_vcs (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_nonempty_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS vc_panels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            details TEXT NOT NULL,
            evidence TEXT,
            status TEXT NOT NULL,
            staff_thread_id INTEGER,
            last_update_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, case_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaint_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            description TEXT NOT NULL,
            role_id INTEGER,
            created_at TEXT NOT NULL,
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            thread_id INTEGER,
            PRIMARY KEY (guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_rsvps (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            PRIMARY KEY (guild_id, message_id, user_id)
        )""")

        await db.commit()


async def get_guild_setting(guild_id: int, key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def set_guild_setting(guild_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guild_settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value),
        )
        await db.commit()


async def log_complaint_action(guild: discord.Guild, case_id: str, actor_id: int, action: str, note: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO complaint_actions(guild_id,case_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?,?)",
            (guild.id, case_id, actor_id, action, note, now_utc().isoformat()),
        )
        await db.commit()

    # Optional ledger channel
    ledger_id = await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    if ledger_id:
        ch = guild.get_channel(ledger_id)
        if ch:
            actor = guild.get_member(actor_id)
            desc = f"**Case:** `{case_id}`\n**Action:** {action}\n**By:** {actor.mention if actor else actor_id}"
            if note:
                desc += f"\n**Note:** {note}"
            await ch.send(embed=obsidian_embed("Docket Ledger", desc, color=discord.Color.dark_grey()))


# --------------------- Setup helpers ---------------------
async def find_or_create_text_channel(guild: discord.Guild, *, name: str) -> discord.TextChannel:
    existing = discord.utils.get(guild.text_channels, name=name)
    if isinstance(existing, discord.TextChannel):
        return existing
    return await guild.create_text_channel(name=name, reason="Obsidian bot auto-setup")


async def resolve_channel_id(
    guild: discord.Guild,
    setting_key: str,
    env_id: int,
    fallback_name: str,
) -> int:
    """
    Resolve a channel ID in this order:
    1) guild_settings value
    2) env ID (if provided)
    3) find by fallback_name (create if AUTO_SETUP)
    Saves the resolved ID into guild_settings.
    """
    saved = await get_guild_setting(guild.id, setting_key)
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            return ch.id

    if env_id:
        ch = guild.get_channel(env_id)
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            await set_guild_setting(guild.id, setting_key, str(ch.id))
            return ch.id

    # find by name
    ch = discord.utils.get(guild.channels, name=fallback_name)
    if ch:
        await set_guild_setting(guild.id, setting_key, str(ch.id))
        return ch.id

    if not AUTO_SETUP:
        return 0

    # create missing text channels only
    if setting_key in ("voice_panel_channel_id", "complaints_channel_id", "complaints_log_channel_id", "events_channel_id"):
        created = await find_or_create_text_channel(guild, name=fallback_name)
        await set_guild_setting(guild.id, setting_key, str(created.id))
        return created.id

    return 0


async def resolve_temp_vc_category(guild: discord.Guild) -> discord.CategoryChannel:
    if TEMP_VC_CATEGORY_ID:
        cat = guild.get_channel(TEMP_VC_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            return cat

    cat = discord.utils.get(guild.categories, name=TEMP_VC_CATEGORY_NAME)
    if isinstance(cat, discord.CategoryChannel):
        return cat

    if not AUTO_SETUP:
        raise RuntimeError("Temp VC category not found. Set TEMP_VC_CATEGORY_ID or TEMP_VC_CATEGORY_NAME.")
    return await guild.create_category(name=TEMP_VC_CATEGORY_NAME, reason="Obsidian bot auto-setup")


async def ensure_join_to_create_channel(guild: discord.Guild) -> int:
    """
    Ensures the join-to-create trigger voice channel exists inside the Temp VCs category.
    Saves it into guild_settings: create_vc_channel_id
    """
    saved = await get_guild_setting(guild.id, "create_vc_channel_id")
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, discord.VoiceChannel):
            return ch.id

    category = await resolve_temp_vc_category(guild)

    existing = discord.utils.get(category.voice_channels, name=CREATE_VC_NAME)
    if isinstance(existing, discord.VoiceChannel):
        await set_guild_setting(guild.id, "create_vc_channel_id", str(existing.id))
        return existing.id

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
    }
    vc = await guild.create_voice_channel(
        name=CREATE_VC_NAME,
        category=category,
        overwrites=overwrites,
        reason="Auto-created join-to-create channel on bot install",
    )
    await set_guild_setting(guild.id, "create_vc_channel_id", str(vc.id))
    return vc.id


async def ensure_core_channels(guild: discord.Guild):
    # Create / resolve core text channels if AUTO_SETUP enabled or IDs set.
    await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)


# --------------------- Voice panel views ---------------------
class RenameVCModal(discord.ui.Modal, title="Recalibrate Comms Node"):
    new_name = discord.ui.TextInput(label="New designation", max_length=80)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        await vc.edit(name=str(self.new_name), reason="Obsidian VC rename")
        await interaction.response.send_message("Renamed.", ephemeral=True)


class InviteModal(discord.ui.Modal, title="Grant Access"):
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        ow = overwrites.get(member, discord.PermissionOverwrite())
        ow.view_channel = True
        ow.connect = True
        overwrites[member] = ow
        await vc.edit(overwrites=overwrites, reason="Obsidian VC invite")
        await interaction.response.send_message(f"Invited {member.mention}.", ephemeral=True)


class RemoveAccessModal(discord.ui.Modal, title="Revoke Access"):
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        if member in overwrites:
            del overwrites[member]
            await vc.edit(overwrites=overwrites, reason="Obsidian VC remove access")
        await interaction.response.send_message(f"Access removed for {member.mention}.", ephemeral=True)


class TransferOwnerModal(discord.ui.Modal, title="Pass Command"):
    target = discord.ui.TextInput(label="New owner (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        new_owner_id = extract_id(str(self.target))
        if not new_owner_id:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        new_owner = interaction.guild.get_member(new_owner_id)
        if not new_owner:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        # Only current owner or mods can transfer
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?", (interaction.guild.id, vc.id))
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Owner record missing.", ephemeral=True)

        current_owner_id = int(row[0])
        actor = interaction.user
        if not isinstance(actor, discord.Member):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        if not (is_mod(actor) or actor.id == current_owner_id):
            return await interaction.response.send_message("Only the owner (or Obsidian Inheritor) can transfer.", ephemeral=True)

        overwrites = vc.overwrites

        old_owner = interaction.guild.get_member(current_owner_id)
        if old_owner:
            ow = overwrites.get(old_owner, discord.PermissionOverwrite())
            ow.manage_channels = False
            ow.move_members = False
            ow.mute_members = False
            ow.deafen_members = False
            overwrites[old_owner] = ow

        ow2 = overwrites.get(new_owner, discord.PermissionOverwrite())
        ow2.view_channel = True
        ow2.connect = True
        ow2.manage_channels = True
        ow2.move_members = True
        ow2.mute_members = True
        ow2.deafen_members = True
        overwrites[new_owner] = ow2

        mod_role = get_mod_role(interaction.guild)
        if mod_role:
            m = overwrites.get(mod_role, discord.PermissionOverwrite())
            m.view_channel = True
            m.connect = True
            overwrites[mod_role] = m

        await vc.edit(overwrites=overwrites, reason="Obsidian transfer ownership")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_vcs SET owner_id=? WHERE guild_id=? AND channel_id=?",
                (new_owner.id, interaction.guild.id, vc.id),
            )
            await db.commit()

        await interaction.response.send_message(f"Ownership transferred to {new_owner.mention}.", ephemeral=True)


class SetLimitSelect(discord.ui.Select):
    def __init__(self, vc_id: int):
        options = [
            discord.SelectOption(label="No limit", value="0"),
            discord.SelectOption(label="2", value="2"),
            discord.SelectOption(label="3", value="3"),
            discord.SelectOption(label="4", value="4"),
            discord.SelectOption(label="6", value="6"),
            discord.SelectOption(label="8", value="8"),
            discord.SelectOption(label="10", value="10"),
            discord.SelectOption(label="12", value="12"),
        ]
        super().__init__(
            placeholder="Set cell capacity…",
            options=options,
            custom_id=f"vc:{vc_id}:setlimit",
        )
        self.vc_id = vc_id

    async def callback(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        try:
            limit = int(self.values[0])
        except ValueError:
            return await interaction.response.send_message("Invalid limit.", ephemeral=True)

        await vc.edit(user_limit=limit, reason="Obsidian VC limit")
        await interaction.response.send_message("Limit updated.", ephemeral=True)


class SetLimitView(discord.ui.View):
    def __init__(self, vc_id: int):
        super().__init__(timeout=120)
        self.add_item(SetLimitSelect(vc_id))


class VCPanelView(discord.ui.View):
    """
    Persistent view per VC (custom_ids include vc_id to avoid collisions).
    We re-register these views on startup for existing temp VCs in the DB.
    """

    def __init__(self, vc_id: int):
        super().__init__(timeout=None)
        self.vc_id = vc_id

        self.add_item(discord.ui.Button(label="Recalibrate", style=discord.ButtonStyle.primary, emoji="✒️", custom_id=f"vc:{vc_id}:rename"))
        self.add_item(discord.ui.Button(label="Capacity", style=discord.ButtonStyle.secondary, emoji="👥", custom_id=f"vc:{vc_id}:limit"))
        self.add_item(discord.ui.Button(label="Seal", style=discord.ButtonStyle.danger, emoji="🔒", custom_id=f"vc:{vc_id}:lock"))
        self.add_item(discord.ui.Button(label="Unseal", style=discord.ButtonStyle.success, emoji="🔓", custom_id=f"vc:{vc_id}:unlock"))
        self.add_item(discord.ui.Button(label="Cloak", style=discord.ButtonStyle.danger, emoji="🫥", custom_id=f"vc:{vc_id}:hide"))
        self.add_item(discord.ui.Button(label="Reveal", style=discord.ButtonStyle.success, emoji="👁️", custom_id=f"vc:{vc_id}:show"))
        self.add_item(discord.ui.Button(label="Grant", style=discord.ButtonStyle.secondary, emoji="🜂", custom_id=f"vc:{vc_id}:invite"))
        self.add_item(discord.ui.Button(label="Revoke", style=discord.ButtonStyle.secondary, emoji="⛓️", custom_id=f"vc:{vc_id}:remove"))
        self.add_item(discord.ui.Button(label="Pass Command", style=discord.ButtonStyle.secondary, emoji="🜁", custom_id=f"vc:{vc_id}:transfer"))
        self.add_item(discord.ui.Button(label="Dissolve", style=discord.ButtonStyle.danger, emoji="🜄", custom_id=f"vc:{vc_id}:disband"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only owner or mods can use most controls
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if is_mod(member):
            return True

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, self.vc_id),
            )
            row = await cur.fetchone()
        return bool(row and int(row[0]) == member.id)

    async def on_timeout(self):
        return


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    panel_ch_id = await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
    if not panel_ch_id:
        return
    panel_ch = guild.get_channel(panel_ch_id)
    if not isinstance(panel_ch, discord.TextChannel):
        return

    embed = obsidian_embed(
        "Obsidian Dojo • Cell Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner.mention}\n\n"
        "Configure your cell channel using the controls below.\n"
        "_Obsidian Inheritors retain oversight._",
        color=discord.Color.dark_grey(),
    )
    view = VCPanelView(vc.id)
    msg = await panel_ch.send(embed=embed, view=view)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO vc_panels(guild_id, channel_id, message_id) VALUES(?,?,?)",
            (guild.id, vc.id, msg.id),
        )
        await db.commit()

    # Register persistent view (so buttons keep working after restart)
    bot.add_view(view)


async def delete_vc_panel_message(guild: discord.Guild, vc_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id FROM vc_panels WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        row = await cur.fetchone()
        if row:
            msg_id = int(row[0])
            await db.execute("DELETE FROM vc_panels WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
            await db.commit()
        else:
            msg_id = 0

    if msg_id:
        ch_id = await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
        ch = guild.get_channel(ch_id) if ch_id else None
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(msg_id)
                await msg.delete()
            except Exception:
                pass


async def delete_temp_vc_and_panel(guild: discord.Guild, vc_id: int, *, reason: str):
    vc = guild.get_channel(vc_id)
    if isinstance(vc, discord.VoiceChannel):
        try:
            await vc.delete(reason=reason)
        except Exception:
            pass

    await delete_vc_panel_message(guild, vc_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM temp_vcs WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
        await db.commit()


# --------------------- Complaints ---------------------
class ComplaintModal(discord.ui.Modal, title="Obsidian Docket Submission"):
    category = discord.ui.TextInput(label="Category", placeholder="harassment / trade / voice conduct / etc.", max_length=60)
    details = discord.ui.TextInput(label="Details", style=discord.TextStyle.paragraph, max_length=1000)
    evidence = discord.ui.TextInput(label="Evidence (optional link)", required=False, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        case_id = f"OBS-{int(now_utc().timestamp())}-{interaction.user.id % 10000}"
        created = now_utc().isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    guild.id,
                    case_id,
                    interaction.user.id,
                    created,
                    str(self.category),
                    str(self.details),
                    str(self.evidence),
                    "OPEN",
                    None,
                    created,
                ),
            )
            await db.commit()

        complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
        ch = guild.get_channel(complaints_id) if complaints_id else None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message(
                "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                ephemeral=True,
            )

        mod_role = get_mod_role(guild)
        mention = mod_role.mention if mod_role else f"@{MOD_ROLE_NAME}"

        desc = f"**Category:** {self.category}\n\n**Details:**\n{self.details}"
        if str(self.evidence).strip():
            desc += f"\n\n**Evidence:** {self.evidence}"

        embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red())
        embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

        view = ComplaintModView(case_id)
        msg = await ch.send(content=mention, embed=embed, view=view)
        bot.add_view(view)

        # Thread for staff discussion (tries private first; falls back)
        thread_id = None
        try:
            thread = await ch.create_thread(
                name=f"{case_id} • Staff Review",
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Private staff thread for complaint",
            )
            thread_id = thread.id
            if mod_role:
                try:
                    await thread.add_user(interaction.user)  # Might fail; ignore
                except Exception:
                    pass
        except Exception:
            try:
                thread = await msg.create_thread(name=f"{case_id} • Staff Review", auto_archive_duration=1440)
                thread_id = thread.id
            except Exception:
                thread = None

        if thread_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                    (thread_id, guild.id, case_id),
                )
                await db.commit()
            try:
                await thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps."))
            except Exception:
                pass

        await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

        await interaction.response.send_message(
            embed=obsidian_embed(
                "Docket Sealed",
                f"Your docket entry has been sealed as **`{case_id}`**.\nYou’ll receive DM docket updates as it progresses.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class ComplaintPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Seal a Report",
                style=discord.ButtonStyle.danger,
                emoji="🩸",
                custom_id="complaints:open",
            )
        )


class RequestInfoModal(discord.ui.Modal, title="Request Evidence"):
    question = discord.ui.TextInput(label="Question to ask the user", style=discord.TextStyle.paragraph, max_length=800)

    def __init__(self, case_id: str):
        super().__init__(timeout=300)
        self.case_id = case_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, self.case_id),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Case not found.", ephemeral=True)

        user_id = int(row[0])

        # Set status, DM user
        await ComplaintModView(self.case_id).set_status(interaction, "NEEDS INFO", dm_override=False)

        user = interaction.guild.get_member(user_id) or await bot.fetch_user(user_id)
        if user:
            try:
                e = obsidian_embed(
                    f"Evidence Requested • {self.case_id}",
                    f"**Directive from Obsidian Inheritors:**\n{self.question}\n\n"
                    "Respond using:\n"
                    f"**/complaint add** (case_id: `{self.case_id}`)\n\n"
                    "_If your DMs are closed, you may not receive updates._",
                    color=discord.Color.orange(),
                )
                await user.send(embed=e)
            except discord.Forbidden:
                pass

        await log_complaint_action(interaction.guild, self.case_id, interaction.user.id, "REQUEST_INFO", str(self.question))
        await interaction.response.send_message("Requested evidence (DM sent if possible).", ephemeral=True)


class ComplaintModView(discord.ui.View):
    """
    Persistent per case (custom_ids include case_id).
    We re-register for OPEN/ACK/NEEDS INFO cases on startup.
    """

    def __init__(self, case_id: str):
        super().__init__(timeout=None)
        self.case_id = case_id

        self.add_item(discord.ui.Button(label="Mark Reviewed", style=discord.ButtonStyle.primary, emoji="🜁", custom_id=f"complaints:{case_id}:ack"))
        self.add_item(discord.ui.Button(label="Close Docket", style=discord.ButtonStyle.success, emoji="🜄", custom_id=f"complaints:{case_id}:resolve"))
        self.add_item(discord.ui.Button(label="Dismiss", style=discord.ButtonStyle.secondary, emoji="🜃", custom_id=f"complaints:{case_id}:reject"))
        self.add_item(discord.ui.Button(label="Request Evidence", style=discord.ButtonStyle.danger, emoji="❗", custom_id=f"complaints:{case_id}:needinfo"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_mod(member)

    async def dm_user(self, guild: discord.Guild, user_id: int, status: str):
        user = guild.get_member(user_id) or await bot.fetch_user(user_id)
        if not user:
            return
        try:
            e = obsidian_embed(f"Docket Update • {self.case_id}", f"Status: **{display_case_status(status)}**")
            await user.send(embed=e)
        except discord.Forbidden:
            pass

    async def set_status(self, interaction: discord.Interaction, status: str, *, dm_override: bool = True) -> Optional[int]:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, self.case_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            user_id = int(row[0])

            await db.execute(
                "UPDATE complaints SET status=?, last_update_at=? WHERE guild_id=? AND case_id=?",
                (status, now_utc().isoformat(), interaction.guild.id, self.case_id),
            )
            await db.commit()

        if dm_override:
            await self.dm_user(interaction.guild, user_id, status)

        await log_complaint_action(interaction.guild, self.case_id, interaction.user.id, f"STATUS:{status}")
        return user_id


# --------------------- Events ---------------------
class RSVPView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Going", style=discord.ButtonStyle.success, emoji="✅", custom_id="events:rsvp:going"))
        self.add_item(discord.ui.Button(label="Maybe", style=discord.ButtonStyle.primary, emoji="❔", custom_id="events:rsvp:maybe"))
        self.add_item(discord.ui.Button(label="Can't", style=discord.ButtonStyle.danger, emoji="❌", custom_id="events:rsvp:no"))

    async def _set_rsvp(self, interaction: discord.Interaction, response: str):
        guild_id = interaction.guild.id
        msg_id = interaction.message.id

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO event_rsvps(guild_id,message_id,user_id,response) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id,message_id,user_id) DO UPDATE SET response=excluded.response",
                (guild_id, msg_id, interaction.user.id, response),
            )
            await db.commit()

            cur = await db.execute(
                "SELECT response, COUNT(*) FROM event_rsvps WHERE guild_id=? AND message_id=? GROUP BY response",
                (guild_id, msg_id),
            )
            rows = await cur.fetchall()

        counts = {"GOING": 0, "MAYBE": 0, "NO": 0}
        for r, c in rows:
            counts[str(r)] = int(c)

        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"✅ {counts['GOING']}  |  ❔ {counts['MAYBE']}  |  ❌ {counts['NO']}")
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("RSVP recorded.", ephemeral=True)


# --------------------- Slash Commands ---------------------
@bot.tree.command(name="setup_obsidian", description="Create/ensure core channels and post Obsidian panels (mods only).")
async def setup_obsidian(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

    await ensure_core_channels(interaction.guild)
    await ensure_join_to_create_channel(interaction.guild)

    # Post panels where command is run (you control placement)
    await interaction.channel.send(
        embed=obsidian_embed(
            "Obsidian Docket",
            "Seal a docket entry for the Inheritors.\n\n"
            "• Provide details & evidence links\n"
            "• False reports may be actioned\n"
            "• You will receive DM docket updates",
            color=discord.Color.red(),
        ),
        view=ComplaintPanel(),
    )

    await interaction.channel.send(
        embed=obsidian_embed(
            "Dojo Comms",
            f"Join **{CREATE_VC_NAME}** inside **{TEMP_VC_CATEGORY_NAME}** to forge a temporary cell channel.\n"
            f"A control panel will appear in **#{VOICE_PANEL_CHANNEL_NAME}** for the squad owner.",
        )
    )

    await interaction.channel.send(
        embed=obsidian_embed(
            "Ops Board",
            "Create events with **/event_create**.\n"
            "Times support natural phrasing (e.g., `tomorrow 8pm`).\n"
            "RSVP buttons + reminder included.",
        )
    )

    await interaction.response.send_message("Obsidian systems deployed.", ephemeral=True)


@bot.tree.command(name="event_create", description="Create an Obsidian Ops event with RSVP + reminder.")
@app_commands.describe(
    title="Event title",
    when="Natural time: 'tomorrow 8pm', 'Jan 14 7:30pm', etc.",
    description="What are we running?",
    role_ping="Optional role @mention or role ID to ping"
)
async def event_create(interaction: discord.Interaction, title: str, when: str, description: str, role_ping: str = ""):
    dt = parse_time_natural(when)
    if not dt:
        return await interaction.response.send_message(
            "Couldn't parse that time. Try: `tomorrow 8pm`, `Jan 14 7:30pm`, etc.",
            ephemeral=True,
        )

    await ensure_core_channels(interaction.guild)
    events_id = await resolve_channel_id(interaction.guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
    ch = interaction.guild.get_channel(events_id) if events_id else None
    if not isinstance(ch, discord.TextChannel):
        return await interaction.response.send_message(
            "Events channel not configured. Set EVENTS_CHANNEL_ID or enable AUTO_SETUP.",
            ephemeral=True,
        )

    # Defer response to prevent Discord from retrying the interaction
    await interaction.response.defer(ephemeral=True)

    ts = int(dt.timestamp())
    role_id = extract_id(role_ping) if role_ping else None
    mention = ""
    if role_id:
        role = interaction.guild.get_role(role_id)
        if role:
            mention = role.mention

    embed = obsidian_embed(
        f"🜂 Ops Order • {title}",
        f"**When:** <t:{ts}:F>  _( <t:{ts}:R> )_\n\n"
        f"**Briefing:**\n{description}",
        color=discord.Color.dark_grey(),
    )
    embed.set_author(name=f"Filed by {interaction.user}", icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text="✅ 0  |  ❔ 0  |  ❌ 0")

    msg = await ch.send(content=mention if mention else None, embed=embed, view=RSVPView())

    # Event thread for chatter
    thread_id = None
    try:
        thread = await msg.create_thread(name=f"{title} • Ops Thread", auto_archive_duration=1440)
        thread_id = thread.id
        await thread.send(embed=obsidian_embed("Ops Thread", "Coordinate here. Keep it clean, keep it sharp."))
    except Exception:
        pass

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events(guild_id,message_id,creator_id,title,start_ts,description,role_id,created_at,reminder_sent,thread_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                interaction.guild.id,
                msg.id,
                interaction.user.id,
                title,
                ts,
                description,
                role_id or 0,
                now_utc().isoformat(),
                0,
                thread_id or 0,
            ),
        )
        await db.commit()

    await interaction.followup.send("Ops event posted.", ephemeral=True)


@bot.tree.command(name="complaint_add", description="Add information to an existing complaint case.")
@app_commands.describe(case_id="Your case id (e.g., OBS-...)", details="Additional details / links / screenshots")
async def complaint_add(interaction: discord.Interaction, case_id: str, details: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, staff_thread_id FROM complaints WHERE guild_id=? AND case_id=?",
            (interaction.guild.id, case_id),
        )
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message("Case not found.", ephemeral=True)

    user_id, staff_thread_id = int(row[0]), int(row[1] or 0)
    if user_id != interaction.user.id:
        return await interaction.response.send_message("You can only add info to your own case.", ephemeral=True)

    await ensure_core_channels(interaction.guild)
    complaints_id = await resolve_channel_id(interaction.guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
    ch = interaction.guild.get_channel(complaints_id) if complaints_id else None

    embed = obsidian_embed(
        f"Case Addendum • {case_id}",
        f"**From:** {interaction.user.mention}\n\n{details}",
        color=discord.Color.orange(),
    )

    if isinstance(ch, discord.TextChannel):
        await ch.send(embed=embed)

    if staff_thread_id:
        thread = interaction.guild.get_thread(staff_thread_id)
        if thread:
            try:
                await thread.send(embed=embed)
            except Exception:
                pass

    await log_complaint_action(interaction.guild, case_id, interaction.user.id, "USER_ADDENDUM", details[:200])
    await interaction.response.send_message("Addendum submitted.", ephemeral=True)


@bot.tree.command(name="complaint_status", description="Check the status of one of your complaint cases.")
@app_commands.describe(case_id="Your case id (e.g., OBS-...)")
async def complaint_status(interaction: discord.Interaction, case_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, status, last_update_at FROM complaints WHERE guild_id=? AND case_id=?",
            (interaction.guild.id, case_id),
        )
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message("Case not found.", ephemeral=True)

    user_id, status, last_update_at = int(row[0]), str(row[1]), str(row[2])
    if user_id != interaction.user.id and not (isinstance(interaction.user, discord.Member) and is_mod(interaction.user)):
        return await interaction.response.send_message("You can only view your own case status.", ephemeral=True)

    await interaction.response.send_message(
        embed=obsidian_embed(
            f"Case Status • {case_id}",
            f"**Status:** {display_case_status(status)}\n**Last update (UTC):** {last_update_at}",
            color=discord.Color.blurple(),
        ),
        ephemeral=True,
    )


@bot.tree.command(name="purge", description="Clear messages from the current channel (mods only).")
@app_commands.describe(
    amount="Number of messages to delete (1-100), or 'all' to delete all messages in channel"
)
async def purge(interaction: discord.Interaction, amount: str):
    # Check if user is a mod
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

    # Check if channel is a text channel
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)

    # Parse amount
    if amount.lower() == "all":
        limit = None  # We'll use a high number for "all"
        delete_count = 9999  # Discord API limits to 100 per call, but we'll loop
    else:
        try:
            limit = int(amount)
            if limit < 1:
                return await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            if limit > 100:
                return await interaction.response.send_message("Amount cannot exceed 100 per command. Use the command multiple times or use 'all'.", ephemeral=True)
            delete_count = limit
        except ValueError:
            return await interaction.response.send_message("Invalid amount. Use a number (1-100) or 'all'.", ephemeral=True)

    # Check bot permissions
    if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
        return await interaction.response.send_message("I don't have permission to manage messages in this channel.", ephemeral=True)

    # Defer response since purge might take a moment
    await interaction.response.defer(ephemeral=True)

    deleted = 0
    try:
        if amount.lower() == "all":
            # Delete in batches of 100 (Discord API limit)
            while True:
                deleted_messages = await interaction.channel.purge(limit=100, check=lambda m: not m.pinned)
                if not deleted_messages:
                    break
                deleted += len(deleted_messages)
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)
        else:
            # Delete specified amount
            deleted_messages = await interaction.channel.purge(limit=limit, check=lambda m: not m.pinned)
            deleted = len(deleted_messages)

        if deleted == 0:
            await interaction.followup.send("No messages were deleted. (Note: Pinned messages are not deleted)", ephemeral=True)
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "Messages Purged",
                    f"Successfully deleted **{deleted}** message(s) from {interaction.channel.mention}.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"An error occurred while deleting messages: {e}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)


# --------------------- Component Router ---------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    """
    We route button/select interactions here so persistent views continue to work after restart.
    Application commands (slash commands) are handled automatically by discord.py.
    """
    # Only handle component interactions (buttons/selects)
    # Let discord.py handle application commands automatically
    if interaction.type != discord.InteractionType.component:
        return

    try:
        cid = interaction.data.get("custom_id") if interaction.data else None
        if not cid:
            return

        # Complaints: open modal
        if cid == "complaints:open":
            await interaction.response.send_modal(ComplaintModal())
            return

        # Complaints: mod actions
        if cid.startswith("complaints:"):
            # complaints:{case_id}:{action}
            parts = cid.split(":")
            if len(parts) == 3:
                _, case_id, action = parts
                if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                    return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

                view = ComplaintModView(case_id)

                if action == "ack":
                    await view.set_status(interaction, "ACKNOWLEDGED")
                    await interaction.response.send_message(f"`{case_id}` marked reviewed.", ephemeral=True)
                    return

                if action == "resolve":
                    await view.set_status(interaction, "RESOLVED")
                    await interaction.response.send_message(f"`{case_id}` closed.", ephemeral=True)
                    return

                if action == "reject":
                    await view.set_status(interaction, "REJECTED")
                    await interaction.response.send_message(f"`{case_id}` dismissed.", ephemeral=True)
                    return

                if action == "needinfo":
                    await interaction.response.send_modal(RequestInfoModal(case_id))
                    return

        # Events: RSVP
        if cid.startswith("events:rsvp:"):
            rsvp_action = cid.split(":")[-1]
            view = RSVPView()
            if rsvp_action == "going":
                await view._set_rsvp(interaction, "GOING")
                return
            if rsvp_action == "maybe":
                await view._set_rsvp(interaction, "MAYBE")
                return
            if rsvp_action == "no":
                await view._set_rsvp(interaction, "NO")
                return

        # Voice: VC panel actions: vc:{vc_id}:{action}
        if cid.startswith("vc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                vc_id_s, action = parts[1], parts[2]
                try:
                    vc_id = int(vc_id_s)
                except ValueError:
                    return await interaction.response.send_message("Invalid channel reference.", ephemeral=True)

                # Permission check (owner or mods)
                member = interaction.user
                if not isinstance(member, discord.Member):
                    return await interaction.response.send_message("Not allowed.", ephemeral=True)

                allowed = is_mod(member)
                if not allowed:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (interaction.guild.id, vc_id),
                        )
                        row = await cur.fetchone()
                    allowed = bool(row and int(row[0]) == member.id)

                if not allowed:
                    return await interaction.response.send_message("Only the squad owner (or Obsidian Inheritor) may do that.", ephemeral=True)

                vc = interaction.guild.get_channel(vc_id)
                if not isinstance(vc, discord.VoiceChannel):
                    return await interaction.response.send_message("Channel not found.", ephemeral=True)

                # Helpers for @everyone overwrite tweaks
                async def edit_everyone(*, connect: Optional[bool] = None, view: Optional[bool] = None):
                    overwrites = vc.overwrites
                    base = overwrites.get(interaction.guild.default_role, discord.PermissionOverwrite())
                    if connect is not None:
                        base.connect = connect
                    if view is not None:
                        base.view_channel = view
                    overwrites[interaction.guild.default_role] = base

                    mod_role = get_mod_role(interaction.guild)
                    if mod_role:
                        m = overwrites.get(mod_role, discord.PermissionOverwrite())
                        m.view_channel = True
                        m.connect = True
                        overwrites[mod_role] = m

                    # Owner stays able to view/connect
                    owner_ow = overwrites.get(member, discord.PermissionOverwrite())
                    owner_ow.view_channel = True
                    owner_ow.connect = True
                    overwrites[member] = owner_ow

                    await vc.edit(overwrites=overwrites, reason="Obsidian VC panel action")

                if action == "rename":
                    await interaction.response.send_modal(RenameVCModal(vc_id))
                    return

                if action == "limit":
                    await interaction.response.send_message("Choose a squad limit:", view=SetLimitView(vc_id), ephemeral=True)
                    return

                if action == "lock":
                    await edit_everyone(connect=False)
                    await interaction.response.send_message("Sealed.", ephemeral=True)
                    return

                if action == "unlock":
                    await edit_everyone(connect=True)
                    await interaction.response.send_message("Unsealed.", ephemeral=True)
                    return

                if action == "hide":
                    await edit_everyone(view=False)
                    await interaction.response.send_message("Cloaked.", ephemeral=True)
                    return

                if action == "show":
                    await edit_everyone(view=True)
                    await interaction.response.send_message("Revealed.", ephemeral=True)
                    return

                if action == "invite":
                    await interaction.response.send_modal(InviteModal(vc_id))
                    return

                if action == "remove":
                    await interaction.response.send_modal(RemoveAccessModal(vc_id))
                    return

                if action == "transfer":
                    await interaction.response.send_modal(TransferOwnerModal(vc_id))
                    return

                if action == "disband":
                    await interaction.response.send_message("Cell dissolved.", ephemeral=True)
                    await delete_temp_vc_and_panel(interaction.guild, vc_id, reason="Disband via panel")
                    return

    except Exception as e:
        # Last-resort error handler
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Something went wrong: {e}", ephemeral=True)
        except Exception:
            pass


# --------------------- Join-to-create logic ---------------------
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not after.channel:
        return

    create_id_s = await get_guild_setting(member.guild.id, "create_vc_channel_id")
    if not (create_id_s and create_id_s.isdigit()):
        return

    create_id = int(create_id_s)
    if after.channel.id != create_id:
        # Track last non-empty times for cleanup
        for ch in (before.channel, after.channel):
            if ch and isinstance(ch, discord.VoiceChannel):
                async with aiosqlite.connect(DB_PATH) as db:
                    # Only track channels we own
                    cur = await db.execute(
                        "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                        (member.guild.id, ch.id),
                    )
                    exists = await cur.fetchone()
                    if exists and len(ch.members) > 0:
                        await db.execute(
                            "UPDATE temp_vcs SET last_nonempty_at=? WHERE guild_id=? AND channel_id=?",
                            (now_utc().isoformat(), member.guild.id, ch.id),
                        )
                        await db.commit()
        return

    guild = member.guild
    category = await resolve_temp_vc_category(guild)
    mod_role = get_mod_role(guild)

    # Create VC
    vc_name = f"{member.display_name} • Obsidian Squad"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
        member: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            manage_channels=True,  # lets them edit it via Discord UI
            move_members=True,
            mute_members=True,
            deafen_members=True,
        ),
    }
    if mod_role:
        overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True, connect=True)

    new_vc = await guild.create_voice_channel(
        name=vc_name,
        category=category,
        overwrites=overwrites,
        reason="Join-to-create Obsidian cell VC",
    )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) VALUES(?,?,?,?,?)",
            (guild.id, new_vc.id, member.id, now_utc().isoformat(), now_utc().isoformat()),
        )
        await db.commit()

    # Move member into new VC
    try:
        await member.move_to(new_vc, reason="Move to created squad VC")
    except discord.Forbidden:
        # Needs Move Members permission
        pass

    # Post control panel
    try:
        await post_vc_panel(guild, new_vc, member)
    except Exception:
        pass


@tasks.loop(minutes=VC_CLEANUP_INTERVAL_MINUTES)
async def temp_vc_cleanup():
    cutoff = now_utc() - timedelta(minutes=VOICE_IDLE_DELETE_MINUTES)

    for guild in bot.guilds:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, last_nonempty_at FROM temp_vcs WHERE guild_id=?",
                (guild.id,),
            )
            rows = await cur.fetchall()

        for channel_id, last_nonempty_at in rows:
            vc = guild.get_channel(int(channel_id))
            if not isinstance(vc, discord.VoiceChannel):
                await delete_temp_vc_and_panel(guild, int(channel_id), reason="Cleanup missing VC")
                continue

            # Never delete join-to-create trigger
            create_id_s = await get_guild_setting(guild.id, "create_vc_channel_id")
            if create_id_s and create_id_s.isdigit() and vc.id == int(create_id_s):
                continue

            try:
                last_dt = datetime.fromisoformat(last_nonempty_at)
            except Exception:
                last_dt = now_utc()

            if len(vc.members) == 0 and last_dt < cutoff:
                await delete_temp_vc_and_panel(guild, vc.id, reason="Temp VC idle cleanup")


@temp_vc_cleanup.before_loop
async def before_temp_vc_cleanup():
    await bot.wait_until_ready()


@tasks.loop(minutes=EVENT_REMINDER_LOOP_MINUTES)
async def event_reminder_loop():
    for guild in bot.guilds:
        events_id = await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
        ch = guild.get_channel(events_id) if events_id else None
        if not isinstance(ch, discord.TextChannel):
            continue

        now_ts = int(now_utc().timestamp())
        soon_ts = int((now_utc() + timedelta(minutes=EVENT_REMINDER_MINUTES_BEFORE)).timestamp())

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT message_id,title,start_ts,role_id FROM events "
                "WHERE guild_id=? AND reminder_sent=0 AND start_ts BETWEEN ? AND ?",
                (guild.id, now_ts, soon_ts),
            )
            rows = await cur.fetchall()

        for message_id, title, start_ts, role_id in rows:
            mention = ""
            if int(role_id or 0):
                role = guild.get_role(int(role_id))
                if role:
                    mention = role.mention

            await ch.send(
                content=mention if mention else None,
                embed=obsidian_embed(
                    "⏳ Operation Reminder",
                    f"**{title}** begins in ~{EVENT_REMINDER_MINUTES_BEFORE} minutes.\n"
                    f"**Time:** <t:{int(start_ts)}:F>  _( <t:{int(start_ts)}:R> )_",
                    color=discord.Color.orange(),
                ),
            )

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE events SET reminder_sent=1 WHERE guild_id=? AND message_id=?",
                    (guild.id, int(message_id)),
                )
                await db.commit()


@event_reminder_loop.before_loop
async def before_event_reminder_loop():
    await bot.wait_until_ready()


# --------------------- Install / startup hooks ---------------------
@bot.event
async def on_guild_join(guild: discord.Guild):
    # Fired when the bot is installed into a server
    try:
        await ensure_core_channels(guild)
        await ensure_join_to_create_channel(guild)
        print(f"[install] Ensured join-to-create in {guild.name}")
    except Exception as e:
        print(f"[install] Setup failed in {guild.name}: {e}")


@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} ({bot.user.id})")

    # Ensure channels + join-to-create exist on startup (covers restarts)
    for g in bot.guilds:
        try:
            await ensure_core_channels(g)
            await ensure_join_to_create_channel(g)
        except Exception as e:
            print(f"[startup] Ensure failed in {g.name}: {e}")

    # Re-register persistent views
    bot.add_view(ComplaintPanel())
    bot.add_view(RSVPView())

    # Re-register VC panel views for existing temp VCs (so their buttons keep working after restart)
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT channel_id FROM temp_vcs WHERE guild_id=?",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (channel_id,) in rows:
                try:
                    bot.add_view(VCPanelView(int(channel_id)))
                except Exception:
                    pass

    # Re-register complaint views for open-ish cases
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT case_id FROM complaints WHERE guild_id=? AND status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (case_id,) in rows:
                try:
                    bot.add_view(ComplaintModView(str(case_id)))
                except Exception:
                    pass

    if not temp_vc_cleanup.is_running():
        temp_vc_cleanup.start()
    if not event_reminder_loop.is_running():
        event_reminder_loop.start()


async def main():
    await init_db()
    try:
        await bot.start(TOKEN)
    except discord.errors.PrivilegedIntentsRequired as e:
        print("\n" + "="*60)
        print("ERROR: Privileged Intents Required")
        print("="*60)
        print("\nThe bot requires privileged intents that must be enabled")
        print("in the Discord Developer Portal.\n")
        print("Required intents:")
        print("  - Server Members Intent (PRIVILEGED)")
        print("\nTo enable:")
        print("1. Go to: https://discord.com/developers/applications/")
        print("2. Select your application")
        print("3. Go to the 'Bot' section")
        print("4. Enable 'SERVER MEMBERS INTENT' under Privileged Gateway Intents")
        print("5. Save changes and restart the bot\n")
        print("="*60 + "\n")
        raise
    except KeyboardInterrupt:
        print("\n[shutdown] Bot stopped by user")
    except Exception as e:
        print(f"\n[error] Bot crashed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
