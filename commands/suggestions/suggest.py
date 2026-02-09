"""Submit suggestion command."""
import discord  # type: ignore
from discord import app_commands  # type: ignore
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite  # type: ignore

SUGGESTION_CATEGORIES = ["feature", "bug", "improvement", "other"]
SUGGESTION_TEMPLATES = {
    "none": None,
    "bug_report": "**What happened:**\n**Steps to reproduce:**\n**Expected:**\n**Actual:**",
    "feature_request": "**What:**\n**Why:**\n**Details:**",
}


def setup(bot, group=None):
    """Register the suggest command."""
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

        if len(suggestion) < 10:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Suggestion Too Short",
                    "Please provide a more detailed suggestion (at least 10 characters).",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if len(suggestion) > 2000:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Suggestion Too Long",
                    "Please keep your suggestion under 2000 characters.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Store suggestion in database
        created_at = now_utc().isoformat()
        suggestion_id = None
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO suggestions (guild_id, user_id, suggestion_text, category, status, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?)
            """, (interaction.guild.id, interaction.user.id, suggestion, category_val, created_at))
            await db.commit()
            
            # Get the suggestion ID
            cur = await db.execute("SELECT last_insert_rowid()")
            suggestion_id = (await cur.fetchone())[0]
        
        if not suggestion_id:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Failed to submit suggestion. Please try again.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Try to find suggestions channel or create one
        # First check if there's already a suggestions channel (case-insensitive)
        suggestions_channel = None
        for channel in interaction.guild.text_channels:
            if channel.name.lower() in ("suggestions", "suggestion", "💡-suggestions", "💡suggestions"):
                suggestions_channel = channel
                break
        
        # If not found, create one
        if not suggestions_channel:
            try:
                suggestions_channel = await interaction.guild.create_text_channel(
                    name="suggestions",
                    reason="Auto-created for bot suggestions"
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error creating suggestions channel: {e}")
                suggestions_channel = None
        
        if suggestions_channel:
            # Create embed for the suggestion
            fields = [
                ("Suggestion", suggestion, False),
                ("Category", category_val.title(), True),
                ("Status", "⏳ Pending Review", True),
                ("Submitted By", interaction.user.mention, True),
                ("Suggestion ID", f"#{suggestion_id}", True),
            ]
            
            embed = obsidian_embed(
                "💡 New Suggestion",
                "",
                color=discord.Color.blue(),
                author=interaction.user,
                fields=fields,
                client=interaction.client,
            )
            
            try:
                message = await suggestions_channel.send(embed=embed)
                await message.add_reaction("👍")
                await message.add_reaction("👎")
                
                # Update message_id in database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE suggestions SET message_id=? WHERE id=?",
                        (message.id, suggestion_id)
                    )
                    await db.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error posting suggestion to channel: {e}")
        
        # Send confirmation to user
        fields = [
            ("Suggestion ID", f"#{suggestion_id}", True),
            ("Status", "⏳ Pending Review", True),
            ("Note", "Your suggestion has been submitted and will be reviewed by moderators.", False),
        ]
        
        embed = obsidian_embed(
            "✅ Suggestion Submitted",
            "",
            color=discord.Color.green(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
