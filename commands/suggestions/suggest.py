"""Submit suggestion command."""
import discord  # type: ignore
from discord import app_commands  # type: ignore
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite  # type: ignore

SUGGESTION_CATEGORIES = ["feature", "bug", "improvement", "other"]
EMBED_COLORS = None  # lazy load from utils


class SuggestionVoteView(discord.ui.View):
    """Persistent 👍/👎 vote buttons on suggestion posts."""

    def __init__(self, suggestion_id: int):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.emoji and str(item.emoji) == "👍":
                    item.custom_id = f"svote:{suggestion_id}:up"
                elif item.emoji and str(item.emoji) == "👎":
                    item.custom_id = f"svote:{suggestion_id}:down"

    async def _handle_vote(self, interaction: discord.Interaction, vote: int):
        async with aiosqlite.connect(DB_PATH) as db:
            # Fetch existing vote
            cur = await db.execute(
                "SELECT vote FROM suggestion_votes WHERE suggestion_id=? AND user_id=?",
                (self.suggestion_id, interaction.user.id),
            )
            row = await cur.fetchone()
            if row and row[0] == vote:
                # Toggle off (remove vote)
                await db.execute(
                    "DELETE FROM suggestion_votes WHERE suggestion_id=? AND user_id=?",
                    (self.suggestion_id, interaction.user.id),
                )
                toggled_off = True
            else:
                await db.execute(
                    """INSERT INTO suggestion_votes (suggestion_id, user_id, vote)
                       VALUES (?, ?, ?)
                       ON CONFLICT(suggestion_id, user_id) DO UPDATE SET vote=excluded.vote""",
                    (self.suggestion_id, interaction.user.id, vote),
                )
                toggled_off = False

            cur2 = await db.execute(
                "SELECT SUM(CASE WHEN vote=1 THEN 1 ELSE 0 END), SUM(CASE WHEN vote=-1 THEN 1 ELSE 0 END) FROM suggestion_votes WHERE suggestion_id=?",
                (self.suggestion_id,),
            )
            counts = await cur2.fetchone()
            upvotes = int(counts[0] or 0)
            downvotes = int(counts[1] or 0)
            await db.commit()

        # Update embed footer to reflect current vote tally
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.set_footer(text=f"👍 {upvotes}  ·  👎 {downvotes}  ·  Mods can manage via /manage_suggestions")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

        action = "removed your vote" if toggled_off else ("upvoted" if vote == 1 else "downvoted")
        await interaction.followup.send(f"✅ You {action} this suggestion.", ephemeral=True)

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.secondary, custom_id="svote:0:up")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, 1)

    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.secondary, custom_id="svote:0:down")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, -1)


async def create_suggestion_from_modal(interaction: discord.Interaction, suggestion: str, category_val: str):
    """Shared logic for creating a suggestion (used by /suggest and Add to Suggestions context menu)."""
    if not interaction.guild:
        return await interaction.followup.send(
            embed=obsidian_embed(
                "❌ Invalid Context",
                "Suggestions can only be submitted in a server.",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    if len(suggestion) < 10:
        return await interaction.followup.send(
            embed=obsidian_embed(
                "❌ Suggestion Too Short",
                "Please provide a more detailed suggestion (at least 10 characters).",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    if len(suggestion) > 2000:
        return await interaction.followup.send(
            embed=obsidian_embed(
                "❌ Suggestion Too Long",
                "Please keep your suggestion under 2000 characters.",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    if category_val not in SUGGESTION_CATEGORIES:
        category_val = "other"

    # Check for suggestions channel before creating DB record
    guild = interaction.guild
    suggestions_channel = None
    for channel in guild.text_channels:
        if channel.name.lower() in ("suggestions", "suggestion", "💡-suggestions", "💡suggestions"):
            suggestions_channel = channel
            break

    if not suggestions_channel:
        return await interaction.followup.send(
            embed=obsidian_embed(
                "❌ No Suggestions Channel",
                "No suggestions channel found. Ask a moderator to create a #suggestions channel or run `/general setup_obsidian` to configure channels.",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    created_at = now_utc().isoformat()
    suggestion_id = None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO suggestions (guild_id, user_id, suggestion_text, category, status, created_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
        """, (guild.id, interaction.user.id, suggestion, category_val, created_at))
        await db.commit()
        try:
            from database import check_and_unlock_achievement
            await check_and_unlock_achievement(guild.id, interaction.user.id, "suggestion_first", None)
        except Exception:
            pass
        cur = await db.execute("SELECT last_insert_rowid()")
        suggestion_id = (await cur.fetchone())[0]

    if not suggestion_id:
        return await interaction.followup.send(
            embed=obsidian_embed("❌ Error", "Failed to submit suggestion. Please try again.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True
        )

    if suggestions_channel:
        fields = [
            ("Suggestion", suggestion, False),
            ("Category", category_val.title(), True),
            ("Status", "⏳ Pending Review", True),
            ("Submitted By", interaction.user.mention, True),
            ("Suggestion ID", f"#{suggestion_id}", True),
        ]
        embed = obsidian_embed(
            "💡 New Suggestion", "", color=discord.Color.blue(),
            author=interaction.user, fields=fields,
            thumbnail=guild.icon.url if guild.icon else None,
            footer=f"👍 0  ·  👎 0  ·  Mods can manage via /manage_suggestions",
            client=interaction.client,
        )
        try:
            from bot import bot as _bot
            vote_view = SuggestionVoteView(suggestion_id)
            _bot.add_view(vote_view)
            message = await suggestions_channel.send(embed=embed, view=vote_view)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE suggestions SET message_id=? WHERE id=?", (message.id, suggestion_id))
                await db.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error posting suggestion to channel: {e}")

    fields = [
        ("Suggestion ID", f"#{suggestion_id}", True),
        ("Status", "⏳ Pending Review", True),
        ("Note", "Your suggestion has been submitted and will be reviewed by moderators.", False),
    ]
    embed = obsidian_embed(
        "✅ Suggestion Submitted", "", color=discord.Color.green(),
        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        fields=fields, footer=f"Suggestion #{suggestion_id} • Use /manage_suggestions to review",
        client=interaction.client,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


SUGGESTION_TEMPLATES = {
    "none": None,
    "bug_report": "**What happened:**\n**Steps to reproduce:**\n**Expected:**\n**Actual:**",
    "feature_request": "**What:**\n**Why:**\n**Details:**",
}


def setup(bot, group=None):
    """Register the suggest and my_suggestions commands."""

    my_suggestions_decorator = group.command(name="my_suggestions", description="List your suggestions and their status.") if group else None
    if my_suggestions_decorator:
        @my_suggestions_decorator
        async def my_suggestions(interaction: discord.Interaction):
            """List user's suggestions."""
            if not interaction.guild:
                return await interaction.response.send_message(
                    embed=obsidian_embed("❌ Invalid Context", "Use in a server.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, suggestion_text, category, status, created_at
                    FROM suggestions WHERE guild_id=? AND user_id=?
                    ORDER BY created_at DESC LIMIT 10
                """, (interaction.guild.id, interaction.user.id))
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "💡 No Suggestions",
                        "You haven't submitted any suggestions. Use `/community suggest` to submit one.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            status_emoji = {"PENDING": "⏳", "APPROVED": "✅", "REJECTED": "❌", "UNDER_REVIEW": "📋", "PLANNED": "📌", "IMPLEMENTED": "✨"}
            lines = []
            for sid, text, category, status, created in rows:
                emoji = status_emoji.get(status, "📋")
                preview = (text[:50] + "…") if len(text) > 50 else text
                lines.append(f"{emoji} **#{sid}** — {status}\n_{preview}_")
            await interaction.followup.send(
                embed=obsidian_embed("💡 My Suggestions", "\n\n".join(lines), color=discord.Color.blue(), client=interaction.client),
                ephemeral=True,
            )

    command_decorator = group.command(name="suggest", description="Submit a suggestion with category and optional template.") if group else bot.tree.command(name="suggest", description="Submit a suggestion with category and optional template.")
    
    @command_decorator
    @app_commands.choices(category=[app_commands.Choice(name=c.title(), value=c) for c in SUGGESTION_CATEGORIES])
    @app_commands.choices(template=[
        app_commands.Choice(name="None", value="none"),
        app_commands.Choice(name="Bug Report", value="bug_report"),
        app_commands.Choice(name="Feature Request", value="feature_request"),
    ])
    @app_commands.describe(
        suggestion="Your suggestion text",
        category="Category of the suggestion",
        template="Optional format template to guide your suggestion",
    )
    async def suggest(
        interaction: discord.Interaction,
        suggestion: str,
        category: app_commands.Choice[str] = None,
        template: app_commands.Choice[str] = None,
    ):
        """Submit a suggestion for the bot."""
        category_val = (category.value if category else "other").lower()
        template_val = template.value if template else "none"
        template_hint = SUGGESTION_TEMPLATES.get(template_val)
        if template_hint and template_val != "none":
            suggestion = f"{template_hint}\n\n{suggestion}" if suggestion else template_hint

        await interaction.response.defer(ephemeral=True)
        await create_suggestion_from_modal(interaction, suggestion, category_val)
