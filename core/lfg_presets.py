"""Saved LFG presets per user."""
from __future__ import annotations

import json
import logging

import aiosqlite

from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)

MAX_PRESETS = 5


async def ensure_lfg_presets_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lfg_presets (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                preset_name TEXT NOT NULL,
                mission_type TEXT NOT NULL,
                max_players INTEGER NOT NULL DEFAULT 4,
                description TEXT,
                radio_query TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, preset_name)
            )
            """
        )
        await db.commit()


async def save_preset(
    guild_id: int,
    user_id: int,
    name: str,
    mission_type: str,
    max_players: int = 4,
    description: str = "",
    radio_query: str = "",
) -> tuple[bool, str]:
    await ensure_lfg_presets_table()
    pname = name.strip()[:40]
    if not pname:
        return False, "Preset name required."
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_presets WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        count = int(row[0] or 0) if row else 0
        cur = await db.execute(
            "SELECT 1 FROM lfg_presets WHERE guild_id=? AND user_id=? AND preset_name=?",
            (guild_id, user_id, pname),
        )
        exists = bool(await cur.fetchone())
        if not exists and count >= MAX_PRESETS:
            return False, f"You can save up to **{MAX_PRESETS}** presets. Delete one first."
        await db.execute(
            """
            INSERT INTO lfg_presets (guild_id, user_id, preset_name, mission_type, max_players, description, radio_query, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id, user_id, preset_name) DO UPDATE SET
                mission_type=excluded.mission_type,
                max_players=excluded.max_players,
                description=excluded.description,
                radio_query=excluded.radio_query
            """,
            (
                guild_id,
                user_id,
                pname,
                mission_type.strip()[:80],
                max(1, min(8, max_players)),
                (description or "")[:500],
                (radio_query or "")[:200],
                now_utc().isoformat(),
            ),
        )
        await db.commit()
    return True, f"Saved preset **{pname}** — use **`/lfg preset_use`** or the template menu."


async def list_presets(guild_id: int, user_id: int) -> list[dict]:
    await ensure_lfg_presets_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT preset_name, mission_type, max_players, description, radio_query
            FROM lfg_presets WHERE guild_id=? AND user_id=? ORDER BY preset_name
            """,
            (guild_id, user_id),
        )
        rows = await cur.fetchall()
    return [
        {
            "name": r[0],
            "mission_type": r[1],
            "max_players": int(r[2]),
            "description": r[3] or "",
            "radio_query": r[4] or "",
        }
        for r in rows
    ]


async def get_preset(guild_id: int, user_id: int, name: str) -> dict | None:
    await ensure_lfg_presets_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT mission_type, max_players, description, radio_query
            FROM lfg_presets WHERE guild_id=? AND user_id=? AND lower(preset_name)=lower(?)
            """,
            (guild_id, user_id, name.strip()),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "mission_type": row[0],
        "max_players": int(row[1]),
        "description": row[2] or "",
        "radio_query": row[3] or "",
    }


async def delete_preset(guild_id: int, user_id: int, name: str) -> tuple[bool, str]:
    await ensure_lfg_presets_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM lfg_presets WHERE guild_id=? AND user_id=? AND lower(preset_name)=lower(?)",
            (guild_id, user_id, name.strip()),
        )
        await db.commit()
        if cur.rowcount:
            return True, f"Deleted preset **{name.strip()}**."
    return False, "Preset not found."
