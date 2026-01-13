"""Submit suggestion command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot):
    """Register the suggest command."""
    @bot.tree.command(name="suggest", description="Submit a suggestion for the bot (new commands, features, improvements, etc.)")
    @app_commands.describe(suggestion="Your suggestion for the bot (commands, features, improvements, etc.)")
    async def suggest(interaction: discord.Interaction, suggestion: str):
        """Submit a suggestion for the bot."""
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
                INSERT INTO suggestions (guild_id, user_id, suggestion_text, status, created_at)
                VALUES (?, ?, ?, 'PENDING', ?)
            """, (interaction.guild.id, interaction.user.id, suggestion, created_at))
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
        from channels import find_or_create_text_channel
        
        suggestions_channel = await find_or_create_text_channel(
            interaction.guild,
            name="suggestions"
        )
        
        if suggestions_channel:
            # Create embed for the suggestion
            fields = [
                ("Suggestion", suggestion, False),
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
