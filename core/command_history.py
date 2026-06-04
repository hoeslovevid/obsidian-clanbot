"""Recent slash-command history per user (QoL: /recent, /menu)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from database import get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

_MAX_RECENT = 5


def qualified_command_name(interaction) -> str:
    """Build ``group subcommand`` path from an application command interaction."""
    data = getattr(interaction, "data", None) or {}
    if not isinstance(data, dict):
        return ""
    parts: list[str] = []
    name = data.get("name")
    if name:
        parts.append(str(name))
    options = data.get("options") or []
    while options:
        first = options[0]
        if not isinstance(first, dict):
            break
        opt_type = first.get("type")
        # 1 = SUB_COMMAND, 2 = SUB_COMMAND_GROUP
        if opt_type not in (1, 2):
            break
        parts.append(str(first.get("name", "")))
        options = first.get("options") or []
    return " ".join(p for p in parts if p).strip()


async def record_recent_command(guild_id: int, user_id: int, command_name: str) -> None:
    """Store last N unique commands for a user (most recent first)."""
    if not guild_id or not user_id or not command_name:
        return
    key = f"user_recent_cmds:{user_id}"
    raw = await get_guild_setting(guild_id, key)
    try:
        entries: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        entries = []
    now = datetime.now(timezone.utc).isoformat()
    entries = [e for e in entries if e.get("cmd") != command_name]
    entries.insert(0, {"cmd": command_name, "at": now})
    entries = entries[:_MAX_RECENT]
    await set_guild_setting(guild_id, key, json.dumps(entries))


async def get_recent_commands(guild_id: int, user_id: int, *, limit: int = 5) -> list[tuple[str, str]]:
    """Return [(command_name, iso_timestamp), ...]."""
    raw = await get_guild_setting(guild_id, f"user_recent_cmds:{user_id}")
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out: list[tuple[str, str]] = []
    for e in entries[:limit]:
        if isinstance(e, dict) and e.get("cmd"):
            out.append((str(e["cmd"]), str(e.get("at", ""))))
    return out
