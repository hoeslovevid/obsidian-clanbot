"""Poll system commands."""
import asyncio
import discord
from discord import app_commands
from typing import Optional, List
from datetime import datetime, timezone
import json
import time
import logging

from core.utils import obsidian_embed, is_mod, render_bar
from database import DB_PATH, now_utc
import aiosqlite
import dateparser

logger = logging.getLogger(__name__)

# Item 50: throttle live edits to ~once per 5 s per poll to avoid Discord ratelimits.
_LIVE_POLL_LAST_EDIT: dict[int, float] = {}
_LIVE_POLL_PENDING: dict[int, asyncio.Task] = {}
_LIVE_POLL_MIN_INTERVAL = 5.0

_NUMBER_REACTIONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _build_live_poll_embed(question: str, options_list: list, counts: list[int], ends_at: Optional[str]) -> discord.Embed:
    total = sum(counts) or 0
    body_lines: list[str] = []
    for idx, opt in enumerate(options_list):
        c = counts[idx] if idx < len(counts) else 0
        pct = (c / total * 100) if total > 0 else 0.0
        bar = render_bar(pct, length=10, show_pct=False)
        body_lines.append(
            f"{_NUMBER_REACTIONS[idx] if idx < len(_NUMBER_REACTIONS) else f'{idx + 1}.'} "
            f"**{opt}** — {bar} {pct:.0f}% ({c})"
        )
    desc = f"**{question}**\n\n" + "\n".join(body_lines)
    if total == 0:
        desc += "\n\n_No votes yet — react below to vote._"
    if ends_at:
        try:
            end_dt = dateparser.parse(
                ends_at, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}
            )
            if end_dt:
                desc += f"\n\n**Ends:** <t:{int(end_dt.timestamp())}:R>"
        except Exception:
            pass
    return obsidian_embed("📊 Poll", desc, color=discord.Color.blue())


async def _refresh_live_poll(channel: discord.abc.Messageable, message_id: int) -> None:
    """Recompute counts from reactions and edit the poll embed."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT question, options, ends_at, closed FROM polls WHERE message_id=?",
                (message_id,),
            )
            row = await cur.fetchone()
        if not row:
            return
        question, options_json, ends_at, closed = row
        if closed:
            return
        options_list = json.loads(options_json)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        message = await channel.fetch_message(message_id)
        from core.poll_utils import fetch_poll_reaction_counts, build_poll_results_embed
        counts = await fetch_poll_reaction_counts(message, options_list)
        new_embed = build_poll_results_embed(question, options_list, counts, closed=False)
        original = message.embeds[0] if message.embeds else None
        if original and original.footer and original.footer.text and "Poll by" in original.footer.text:
            creator_part = original.footer.text.split("Poll by", 1)[-1].strip()
            if creator_part:
                new_embed.set_footer(text=f"Live results — react to vote • Poll by {creator_part}")
        await message.edit(embed=new_embed)
    except (discord.NotFound, discord.Forbidden):
        return
    except Exception as e:
        logger.debug(f"[poll-live] refresh failed for {message_id}: {e}")


async def _throttled_refresh(channel, message_id: int) -> None:
    """Coalesce burst votes into at most one edit per ``_LIVE_POLL_MIN_INTERVAL``."""
    now = time.monotonic()
    last = _LIVE_POLL_LAST_EDIT.get(message_id, 0.0)
    wait = max(0.0, _LIVE_POLL_MIN_INTERVAL - (now - last))
    if wait > 0:
        await asyncio.sleep(wait)
    _LIVE_POLL_LAST_EDIT[message_id] = time.monotonic()
    _LIVE_POLL_PENDING.pop(message_id, None)
    await _refresh_live_poll(channel, message_id)


def _schedule_live_refresh(client: discord.Client, channel_id: int, message_id: int) -> None:
    if message_id in _LIVE_POLL_PENDING:
        return  # one refresh already queued
    channel = client.get_channel(channel_id)
    if channel is None:
        return
    task = asyncio.create_task(_throttled_refresh(channel, message_id))
    _LIVE_POLL_PENDING[message_id] = task


async def _is_poll_message(message_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM polls WHERE message_id=?", (message_id,)
        )
        return (await cur.fetchone()) is not None


def setup(bot, group=None):
    """Register poll commands."""

    # Item 50: live results bar. Listen for reaction add/remove on poll messages.
    async def _on_poll_reaction(payload: discord.RawReactionActionEvent):
        if not payload.guild_id or not payload.message_id:
            return
        if not await _is_poll_message(payload.message_id):
            return
        _schedule_live_refresh(bot, payload.channel_id, payload.message_id)

    @bot.listen("on_raw_reaction_add")
    async def _poll_reaction_add(payload: discord.RawReactionActionEvent):
        await _on_poll_reaction(payload)

    @bot.listen("on_raw_reaction_remove")
    async def _poll_reaction_remove(payload: discord.RawReactionActionEvent):
        await _on_poll_reaction(payload)

    
    command_decorator = group.command(name="poll", description="Create a poll.") if group else bot.tree.command(name="poll", description="Create a poll.")
    
    @command_decorator
    @app_commands.describe(question="The poll question", options="Comma-separated options (max 10)", duration="How long the poll should last (e.g., '1 hour', '30 minutes')")
    async def poll(interaction: discord.Interaction, question: str, options: str, duration: Optional[str] = None):
        """Create a poll."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        from core.utils import feature_enabled, feature_off_embed  # Item 85
        if not await feature_enabled(interaction.guild.id, "polls"):
            return await interaction.response.send_message(embed=feature_off_embed("Polls", client=interaction.client), ephemeral=True)

        await interaction.response.defer()
        
        # Parse options
        options_list = [opt.strip() for opt in options.split(",") if opt.strip()]
        if len(options_list) < 2:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Options",
                    "Please provide at least 2 options, separated by commas.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        if len(options_list) > 10:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Too Many Options",
                    "Maximum 10 options allowed.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Parse duration
        ends_at = None
        if duration:
            parsed_duration = dateparser.parse(duration, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}, relative_base=datetime.now(timezone.utc))
            if parsed_duration:
                ends_at = parsed_duration.isoformat()
        
        # Create poll embed
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options_list)])
        poll_text = f"**{question}**\n\n{options_text}"
        
        if ends_at:
            poll_text += f"\n\n**Ends:** <t:{int(dateparser.parse(ends_at, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}).timestamp())}:R>"
        
        embed = obsidian_embed(
            "📊 Poll",
            poll_text,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        embed.set_footer(text=f"Poll by {interaction.user.display_name}")
        
        # Send poll message
        message = await interaction.channel.send(embed=embed)
        
        # Add reaction buttons for each option
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i in range(len(options_list)):
            try:
                await message.add_reaction(reactions[i])
            except discord.HTTPException:
                pass
        
        # Store poll in database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO polls (guild_id, channel_id, message_id, creator_id, question, options, ends_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.channel.id, message.id, interaction.user.id, question, json.dumps(options_list), ends_at, now_utc().isoformat()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Poll Created",
                f"Poll has been created: {message.jump_url}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="poll_results", description="View poll results.") if group else bot.tree.command(name="poll_results", description="View poll results.")
    
    @command_decorator
    @app_commands.describe(message_id="The poll message ID")
    async def poll_results(interaction: discord.Interaction, message_id: str):
        """View poll results."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            msg_id = int(message_id)
        except ValueError:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Message ID",
                    "Please provide a valid message ID.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get poll
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT question, options, ends_at FROM polls
                WHERE guild_id=? AND message_id=?
            """, (interaction.guild.id, msg_id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Poll Not Found",
                        "No poll found with that message ID.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            question, options_json, ends_at = row
            options_list = json.loads(options_json)
            
            # Get message and count reactions
            try:
                channel = interaction.guild.get_channel(interaction.channel.id)
                if not channel:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Channel Not Found",
                            "Could not find the channel.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                message = await channel.fetch_message(msg_id)
                reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                
                results = []
                total_votes = 0
                for i, option in enumerate(options_list):
                    if i < len(reactions):
                        reaction = discord.utils.get(message.reactions, emoji=reactions[i])
                        count = reaction.count - 1 if reaction else 0  # Subtract 1 for bot's reaction
                        total_votes += count
                        results.append((option, count))
                
                # Build results text with percentages
                results_text = ""
                for opt, count in results:
                    percentage = (count / total_votes * 100) if total_votes > 0 else 0
                    bar_length = int(percentage / 5)  # 20 chars max
                    bar = "█" * bar_length + "░" * (20 - bar_length)
                    results_text += f"**{opt}**\n{bar} {count} votes ({percentage:.1f}%)\n\n"
                
                if total_votes > 0:
                    results_text += f"**Total Votes:** {total_votes}"
                else:
                    results_text += "**No votes yet.**"
                
                embed = obsidian_embed(
                    f"📊 Poll Results: {question}",
                    results_text,
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.NotFound:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Message Not Found",
                        "Could not find the poll message.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
