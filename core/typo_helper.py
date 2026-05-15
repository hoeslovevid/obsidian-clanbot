"""Passive command typo helper.

Listens (via ``bot.on_message``) for short messages that look like a failed
attempt to invoke a slash command (``!balance``, ``/baance``, ``.daily``, …)
and replies with a single suggestion using the closest registered command.

Design choices to avoid noise:
- Only fires for very short messages (≤ ``MAX_LEN`` chars) where the first token
  starts with ``!``, ``/``, ``.``, ``;`` or ``$``.
- Per-user in-memory cooldown (``USER_COOLDOWN_SEC``) so the bot never spams
  the same person twice quickly.
- Per-guild kill switch (``guild_settings`` key ``typo_helper_disabled``).
- Per-user opt-out (``guild_settings`` key ``user_typo_helper:{user_id}``).
- High similarity threshold (``MATCH_CUTOFF``) so it only nudges when it's
  *actually* a likely command attempt.
- Skips messages with code blocks/multiple lines (looks like real chat).

The reply is auto-deleted after ``REPLY_TTL_SEC`` seconds to keep channels tidy.
"""
from __future__ import annotations

import difflib
import logging
import re
import time
from typing import Optional

import discord  # type: ignore

from core.mention_chat import _collect_command_paths
from database import get_guild_setting

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────
MAX_LEN = 50
MATCH_CUTOFF = 0.62           # difflib ratio for the first token / candidate
USER_COOLDOWN_SEC = 300       # 5 minutes between suggestions per user
REPLY_TTL_SEC = 30            # auto-delete suggestion after 30s

# Recognised "command-attempt" prefixes. Discord's slash commands start with
# ``/`` but typing ``/x`` literally still produces plain text in chat.
_PREFIX_RE = re.compile(r"^[!/\.\;\$]([A-Za-z][A-Za-z0-9_-]{1,32})\b")

# Cache of recent (guild_id, user_id) → monotonic ts.
_recent: dict[tuple[int, int], float] = {}

# Common English words we should NEVER suggest commands for, even if a typo is close.
_FALSE_FRIENDS = {
    "ok", "yes", "no", "lol", "wtf", "imo", "tbh", "ily", "thx", "thanks",
    "afk", "brb", "gg", "ggs", "rip", "nice", "cool", "wait", "what", "hi",
    "hey", "hello", "yo", "test", "ping",
}

# Cached command path list (refreshed every CACHE_TTL seconds).
_paths_cache: list[str] = []
_paths_cache_ts: float = 0.0
_PATHS_CACHE_TTL = 60.0


def _get_command_paths(bot) -> list[str]:
    """Cache the full list of slash-command paths so we don't walk the tree per message."""
    global _paths_cache, _paths_cache_ts
    now = time.monotonic()
    if not _paths_cache or now - _paths_cache_ts > _PATHS_CACHE_TTL:
        try:
            _paths_cache = _collect_command_paths(bot) or []
            _paths_cache_ts = now
        except Exception as exc:  # never let a bad walk break message handling
            logger.debug("[typo_helper] command path collection failed: %s", exc)
    return _paths_cache


def _user_on_cooldown(guild_id: int, user_id: int) -> bool:
    key = (guild_id, user_id)
    last = _recent.get(key)
    now = time.monotonic()
    if last is not None and (now - last) < USER_COOLDOWN_SEC:
        return True
    return False


def _mark_used(guild_id: int, user_id: int) -> None:
    _recent[(guild_id, user_id)] = time.monotonic()


def _candidate_token(content: str) -> Optional[str]:
    """Return the candidate command token if the message looks like a slash attempt."""
    if not content:
        return None
    stripped = content.strip()
    if len(stripped) > MAX_LEN:
        return None
    if "\n" in stripped or "```" in stripped:
        return None
    m = _PREFIX_RE.match(stripped)
    if not m:
        return None
    token = m.group(1).lower()
    if token in _FALSE_FRIENDS:
        return None
    return token


def _best_match(token: str, paths: list[str]) -> Optional[str]:
    """Return the closest registered command path for ``token`` if confident."""
    if not paths:
        return None
    # First try matching against last token of each path (e.g. "balance" vs "economy balance").
    last_lookup = {p.split()[-1].lower(): p for p in paths}
    last_keys = list(last_lookup.keys())
    matches = difflib.get_close_matches(token, last_keys, n=1, cutoff=MATCH_CUTOFF)
    if matches:
        return last_lookup[matches[0]]
    # Fallback: full path match (helpful for "ecbalance" → "economy balance").
    full_matches = difflib.get_close_matches(token, [p.lower() for p in paths], n=1, cutoff=MATCH_CUTOFF + 0.1)
    if full_matches:
        casing = {p.lower(): p for p in paths}
        return casing.get(full_matches[0])
    return None


async def _is_disabled(guild_id: int, user_id: int) -> bool:
    """Check guild-wide and per-user opt-out flags."""
    try:
        guild_off = await get_guild_setting(guild_id, "typo_helper_disabled")
        if guild_off in ("1", "true", "True"):
            return True
        user_off = await get_guild_setting(guild_id, f"user_typo_helper:{user_id}")
        if user_off in ("0", "off", "Off", "false", "False"):
            return True
    except Exception as exc:
        logger.debug("[typo_helper] disabled-check failed: %s", exc)
    return False


async def maybe_suggest_command(message: discord.Message, bot) -> bool:
    """Inspect ``message`` and post a suggestion if it looks like a typo'd slash command.

    Returns ``True`` if a suggestion was sent (so callers can decide to skip
    other follow-up logic, e.g. economy cooldown updates).
    """
    if message.author.bot or not message.guild:
        return False
    if not isinstance(message.author, discord.Member):
        return False

    token = _candidate_token(message.content or "")
    if not token:
        return False

    if _user_on_cooldown(message.guild.id, message.author.id):
        return False

    if await _is_disabled(message.guild.id, message.author.id):
        return False

    paths = _get_command_paths(bot)
    match = _best_match(token, paths)
    if not match:
        return False

    _mark_used(message.guild.id, message.author.id)

    suggestion = f"`/{match}`"
    body = (
        f"Did you mean {suggestion}?\n"
        "-# Run that command from the slash menu. "
        "Disable this hint with `/general preferences typo_helper:Off`."
    )
    try:
        await message.reply(
            body,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
            delete_after=REPLY_TTL_SEC,
        )
        return True
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.debug("[typo_helper] reply failed: %s", exc)
        return False
