"""Warframe background notification checks (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore

from api.warframe_api import fetch_alerts, fetch_invasions, get_all_cycles
from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, now_utc

logger = logging.getLogger(__name__)

WarnBrokenChannel = Callable[[discord.Guild, int, str], Awaitable[None]]


async def run_cycle_change_notifications(
    bot: discord.Client,
    warn_broken_channel: WarnBrokenChannel,
) -> None:
    cycles_data = await get_all_cycles()
    if not cycles_data:
        return

    for cycle_type, data in cycles_data.items():
        if not data:
            continue

        expiry = data.get("expiry", "")
        if not expiry:
            continue

        try:
            expiry_time = dateparser.parse(
                expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True}
            )
            if not expiry_time:
                continue

            now = datetime.now(timezone.utc)
            time_until_change = expiry_time - now

            if not (0 <= time_until_change.total_seconds() <= 120):
                continue

            cycle_state = None
            cycle_display = None

            if cycle_type == "cetus":
                is_day = data.get("isDay", False)
                cycle_state = "day" if is_day else "night"
                cycle_display = "☀️ Day" if is_day else "🌙 Night"
            elif cycle_type == "vallis":
                is_warm = data.get("isWarm", False)
                cycle_state = "warm" if is_warm else "cold"
                cycle_display = "🔥 Warm" if is_warm else "❄️ Cold"
            elif cycle_type == "cambion":
                state = data.get("state", "").lower()
                cycle_state = state
                cycle_display = (
                    "🔴 Fass"
                    if state == "fass"
                    else "🟢 Vome"
                    if state == "vome"
                    else state.title()
                )

            if not cycle_state:
                continue

            column_map = {
                "cetus": ("cetus_enabled", "Cetus (Plains of Eidolon)"),
                "vallis": ("fortuna_enabled", "Fortuna (Orb Vallis)"),
                "cambion": ("deimos_enabled", "Deimos (Cambion Drift)"),
            }

            column, display_name = column_map.get(cycle_type, (None, None))
            if not column:
                continue

            for guild in bot.guilds:
                try:
                    from core.cycles_live import guild_skips_cycle_pings

                    if await guild_skips_cycle_pings(guild.id):
                        continue

                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            f"SELECT channel_id, {column}, ping_role_id FROM cycle_notification_settings WHERE guild_id=?",
                            (guild.id,),
                        )
                        setting = await cur.fetchone()

                    if not setting or not setting[1]:
                        continue
                except Exception as e:
                    logger.error(
                        "Error checking cycle notification settings for guild %s: %s",
                        guild.id,
                        e,
                    )
                    continue

                channel_id = setting[0]
                ping_role_id = setting[2] if len(setting) > 2 and setting[2] else None
                if not channel_id:
                    continue

                ch = guild.get_channel(channel_id)
                if not isinstance(ch, discord.TextChannel):
                    await warn_broken_channel(guild, channel_id, "Cycle")
                    continue

                ping_content = None
                if ping_role_id:
                    role = guild.get_role(int(ping_role_id))
                    if role:
                        ping_content = role.mention

                try:
                    from core.utils import format_wf_subscriber_mentions, get_wf_subscribers

                    _subs = await get_wf_subscribers(guild.id, "cycles")
                    _sub_text = format_wf_subscriber_mentions(guild, _subs)
                    if _sub_text:
                        ping_content = (
                            f"{ping_content} {_sub_text}" if ping_content else _sub_text
                        )
                except Exception:
                    pass

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        """
                        SELECT 1 FROM cycle_notifications_sent
                        WHERE guild_id=? AND cycle_type=? AND cycle_state=?
                          AND notified_at > datetime('now', '-5 minutes')
                        """,
                        (guild.id, cycle_type, cycle_state),
                    )
                    already_notified = await cur.fetchone()

                if already_notified:
                    continue

                cycle_durations = {
                    "cetus": 150 * 60,
                    "vallis": 26 * 60,
                    "cambion": 100 * 60,
                }
                duration_seconds = cycle_durations.get(cycle_type, 0)
                next_expiry_time = expiry_time + timedelta(seconds=duration_seconds)

                desc = f"**{display_name}** cycle is changing!\n\n"
                desc += f"**New State:** {cycle_display}\n"
                desc += f"**Changes At:** <t:{int(expiry_time.timestamp())}:F>\n"
                desc += (
                    f"**Ends At:** <t:{int(next_expiry_time.timestamp())}:F> "
                    f"_(<t:{int(next_expiry_time.timestamp())}:R>)_"
                )

                embed = obsidian_embed(
                    f"🌍 Cycle Change: {display_name}",
                    desc,
                    color=discord.Color.blue(),
                    client=bot,
                )

                try:
                    await ch.send(content=ping_content, embed=embed)

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            """
                            INSERT INTO cycle_notifications_sent
                                (guild_id, cycle_type, cycle_state, notified_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                guild.id,
                                cycle_type,
                                cycle_state,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        await db.commit()
                except Exception as e:
                    logger.error("Error sending cycle notification to %s: %s", guild.id, e)
                    continue
        except Exception as e:
            logger.error("Error processing %s cycle: %s", cycle_type, e)
            continue


async def run_invasion_notifications(
    bot: discord.Client,
    warn_broken_channel: WarnBrokenChannel,
) -> None:
    invasions_data = await fetch_invasions()
    if not invasions_data:
        return

    for guild in bot.guilds:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT reward_lower, reward_display, channel_id
                    FROM invasion_notification_settings
                    WHERE guild_id=? AND enabled=1
                    """,
                    (guild.id,),
                )
                settings = await cur.fetchall()

            if not settings:
                continue
        except Exception as e:
            logger.error(
                "Error checking invasion notification settings for guild %s: %s",
                guild.id,
                e,
            )
            continue

        for inv in invasions_data:
            invasion_id = inv.get("id", "")
            if not invasion_id:
                continue

            att_obj = inv.get("attacker") or {}
            def_obj = inv.get("defender") or {}
            attacker_reward = att_obj.get("reward") or {}
            defender_reward = def_obj.get("reward") or {}

            rewards_found = []
            for item in attacker_reward.get("countedItems") or []:
                item_type = (item.get("type") or item.get("key") or "").lower()
                if item_type:
                    rewards_found.append(item_type)
            for item in defender_reward.get("countedItems") or []:
                item_type = (item.get("type") or item.get("key") or "").lower()
                if item_type:
                    rewards_found.append(item_type)

            for reward_lower, reward_display, channel_id in settings:
                if reward_lower not in rewards_found or not channel_id:
                    continue

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        """
                        SELECT 1 FROM invasion_notifications_sent
                        WHERE guild_id=? AND invasion_id=? AND reward_lower=?
                        """,
                        (guild.id, invasion_id, reward_lower),
                    )
                    already_notified = await cur.fetchone()

                if already_notified:
                    continue

                ch = guild.get_channel(channel_id)
                if not isinstance(ch, discord.TextChannel):
                    await warn_broken_channel(guild, channel_id, "Invasion")
                    continue

                node = inv.get("node") or inv.get("nodeKey", "Unknown Location")
                attacker = att_obj.get("faction") or att_obj.get("factionKey", "Unknown")
                defender = def_obj.get("faction") or def_obj.get("factionKey", "Unknown")
                completion = inv.get("completion", 0)
                count = inv.get("count", 0)
                required_runs = inv.get("requiredRuns", 0)

                time_str = "—"
                activation = inv.get("activation")
                if activation:
                    try:
                        act_time = dateparser.parse(
                            activation,
                            settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
                        )
                        if act_time:
                            act_utc = (
                                act_time.replace(tzinfo=timezone.utc)
                                if act_time.tzinfo is None
                                else act_time
                            )
                            elapsed = datetime.now(timezone.utc) - act_utc
                            total_sec = max(0, int(elapsed.total_seconds()))
                            time_str = f"{total_sec // 3600}h {(total_sec % 3600) // 60}m active"
                    except Exception:
                        pass
                if time_str == "—" and required_runs:
                    time_str = f"Runs: {count:,}/{required_runs:,}"

                reward_list = []
                for item in attacker_reward.get("countedItems") or []:
                    item_type = item.get("type") or item.get("key", "")
                    if item_type and item_type.lower() == reward_lower:
                        reward_list.append(f"**{attacker}:** {item_type}")
                for item in defender_reward.get("countedItems") or []:
                    item_type = item.get("type") or item.get("key", "")
                    if item_type and item_type.lower() == reward_lower:
                        reward_list.append(f"**{defender}:** {item_type}")

                desc = f"**Location:** {node}\n"
                desc += f"**Factions:** {attacker} vs {defender}\n"
                desc += f"**Progress:** {completion:.1f}%\n"
                desc += f"**Time:** {time_str}\n\n"
                desc += "**Reward Found:**\n" + "\n".join(reward_list)

                embed = obsidian_embed(
                    f"⚔️ Invasion Alert: {reward_display}",
                    desc,
                    color=discord.Color.orange(),
                    client=bot,
                )

                try:
                    await ch.send(embed=embed)

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            """
                            INSERT INTO invasion_notifications_sent
                                (guild_id, invasion_id, reward_lower, notified_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                guild.id,
                                invasion_id,
                                reward_lower,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        await db.commit()
                except Exception as e:
                    logger.error("Error sending invasion notification to %s: %s", guild.id, e)
                    continue


async def run_alert_notifications(bot: discord.Client) -> None:
    alerts = await fetch_alerts()
    if not alerts:
        return

    for guild in bot.guilds:
        try:
            channel_id_str = await get_guild_setting(guild.id, "alerts_notify_channel_id")
            if not channel_id_str:
                channel_id_str = await get_guild_setting(guild.id, "alerts_channel_id")

            if not channel_id_str or not channel_id_str.isdigit():
                continue

            channel_id = int(channel_id_str)
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            for alert in alerts:
                alert_id = alert.get("id")
                if not alert_id:
                    continue

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        """
                        SELECT 1 FROM alert_notifications_sent
                        WHERE guild_id=? AND alert_id=?
                        """,
                        (guild.id, str(alert_id)),
                    )
                    if await cur.fetchone():
                        continue

                    mission_type = alert.get("mission", {}).get("type", "Unknown")
                    mission_node = alert.get("mission", {}).get("node", "Unknown")
                    expiry = alert.get("expiry", "")
                    rewards = alert.get("mission", {}).get("reward", {})
                    reward_items = rewards.get("items", [])

                    desc = f"**Type:** {mission_type}\n"
                    desc += f"**Node:** {mission_node}\n"
                    desc += f"**Expires:** {expiry}\n"
                    if reward_items:
                        desc += f"**Rewards:** {', '.join(reward_items)}"

                    embed = obsidian_embed(
                        "🚨 New Warframe Alert",
                        desc,
                        color=discord.Color.gold(),
                        client=bot,
                    )

                    try:
                        from core.safe_send import safe_channel_send

                        await safe_channel_send(channel, embed=embed)
                        await db.execute(
                            """
                            INSERT INTO alert_notifications_sent (guild_id, alert_id, notified_at)
                            VALUES (?, ?, ?)
                            """,
                            (guild.id, str(alert_id), now_utc().isoformat()),
                        )
                        await db.commit()
                    except Exception as e:
                        logger.error(
                            "Error sending alert notification to guild %s: %s",
                            guild.id,
                            e,
                        )

        except Exception as e:
            logger.error("Error in alert notifications for guild %s: %s", guild.id, e, exc_info=True)
