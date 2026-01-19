"""Manage suggestions command for moderators."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


class SuggestionView(discord.ui.View):
    """View with buttons for managing suggestions."""
    
    def __init__(self, suggestion_id: int):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id
        # Set custom_id for persistence
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "✅ Approve":
                    item.custom_id = f"suggestion:{suggestion_id}:approve"
                elif item.label == "❌ Reject":
                    item.custom_id = f"suggestion:{suggestion_id}:reject"
                elif item.label == "✅ Implemented":
                    item.custom_id = f"suggestion:{suggestion_id}:implemented"
    
    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Approve the suggestion."""
        await self._handle_status(interaction, "APPROVED", "✅ Approved")
    
    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reject the suggestion."""
        await self._handle_status(interaction, "REJECTED", "❌ Rejected")
    
    @discord.ui.button(label="✅ Implemented", style=discord.ButtonStyle.primary)
    async def implemented(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark suggestion as implemented."""
        await self._handle_status(interaction, "IMPLEMENTED", "✅ Implemented")
    
    async def _handle_status(self, interaction: discord.Interaction, status: str, status_display: str):
        """Handle status change."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Update database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE suggestions
                SET status=?, reviewed_by=?, reviewed_at=?
                WHERE id=?
            """, (status, interaction.user.id, now_utc().isoformat(), self.suggestion_id))
            await db.commit()
            
            # Get suggestion details
            cur = await db.execute("""
                SELECT user_id, suggestion_text, message_id
                FROM suggestions
                WHERE id=?
            """, (self.suggestion_id,))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send("Suggestion not found.", ephemeral=True)
        
        user_id, suggestion_text, message_id = row
        
        # Update the original message if it exists
        if message_id:
            try:
                message = await interaction.channel.fetch_message(message_id)
                if message.embeds:
                    embed = message.embeds[0]
                    
                    # Update status field
                    found_status = False
                    for i, field in enumerate(embed.fields):
                        if field.name == "Status":
                            embed.set_field_at(i, name="Status", value=status_display, inline=True)
                            found_status = True
                            break
                    if not found_status:
                        embed.add_field(name="Status", value=status_display, inline=True)
                    
                    # Update color based on status
                    if status == "APPROVED":
                        embed.color = discord.Color.green()
                    elif status == "REJECTED":
                        embed.color = discord.Color.red()
                    elif status == "IMPLEMENTED":
                        embed.color = discord.Color.blue()
                    
                    # Disable buttons
                    for item in self.children:
                        item.disabled = True
                    
                    await message.edit(embed=embed, view=self)
            except discord.NotFound:
                pass
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error updating suggestion message: {e}")
        
        # Try to DM the user who submitted the suggestion
        try:
            user = interaction.guild.get_member(user_id)
            if user:
                status_messages = {
                    "APPROVED": "Your suggestion has been **approved** by the moderators!",
                    "REJECTED": "Your suggestion has been **rejected** by the moderators.",
                    "IMPLEMENTED": "Your suggestion has been **implemented**! Thank you for your contribution!"
                }
                
                message_text = status_messages.get(status, f"Your suggestion status has been updated to: {status}")
                
                embed = obsidian_embed(
                    f"💡 Suggestion Update #{self.suggestion_id}",
                    f"{message_text}\n\n**Your Suggestion:**\n{suggestion_text[:500]}{'...' if len(suggestion_text) > 500 else ''}",
                    color=discord.Color.blue() if status == "APPROVED" else discord.Color.orange() if status == "REJECTED" else discord.Color.green(),
                    client=interaction.client,
                )
                
                await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error DMing user about suggestion: {e}")
        
        await interaction.followup.send(
            f"Suggestion #{self.suggestion_id} has been marked as {status_display}.",
            ephemeral=True
        )


def setup(bot, group=None):
    """Register the suggestions command."""
    command_decorator = group.command(name="suggestions", description="View and manage suggestions (moderators only).") if group else bot.tree.command(name="suggestions", description="View and manage suggestions (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        status="Filter by status (default: all)",
        limit="Number of suggestions to show (default: 10, max: 25)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Pending", value="PENDING"),
        app_commands.Choice(name="Approved", value="APPROVED"),
        app_commands.Choice(name="Rejected", value="REJECTED"),
        app_commands.Choice(name="Implemented", value="IMPLEMENTED"),
    ])
    async def suggestions(
        interaction: discord.Interaction,
        status: app_commands.Choice[str] = None,
        limit: int = 10
    ):
        """View and manage suggestions."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        status_filter = status.value if status and status.value != "all" else None
        
        if limit < 1 or limit > 25:
            limit = 10
        
        # Get suggestions from database
        async with aiosqlite.connect(DB_PATH) as db:
            if status_filter:
                cur = await db.execute("""
                    SELECT id, user_id, suggestion_text, status, created_at, reviewed_by
                    FROM suggestions
                    WHERE guild_id=? AND status=?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (interaction.guild.id, status_filter, limit))
            else:
                cur = await db.execute("""
                    SELECT id, user_id, suggestion_text, status, created_at, reviewed_by
                    FROM suggestions
                    WHERE guild_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (interaction.guild.id, limit))
            
            rows = await cur.fetchall()
        
        if not rows:
            status_text = f" with status '{status_filter}'" if status_filter else ""
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "💡 No Suggestions Found",
                    f"No suggestions{status_text} found.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed with suggestions
        fields = []
        for suggestion_id, user_id, suggestion_text, suggestion_status, created_at, reviewed_by in rows:
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            
            status_emoji = {
                "PENDING": "⏳",
                "APPROVED": "✅",
                "REJECTED": "❌",
                "IMPLEMENTED": "✅"
            }.get(suggestion_status, "❓")
            
            value = f"**Status:** {status_emoji} {suggestion_status}\n"
            value += f"**By:** {username}\n"
            value += f"**Suggestion:** {suggestion_text[:200]}{'...' if len(suggestion_text) > 200 else ''}\n"
            value += f"**ID:** #{suggestion_id}"
            
            fields.append((f"Suggestion #{suggestion_id}", value, False))
        
        status_display = status_filter if status_filter else "All"
        embed = obsidian_embed(
            f"💡 Suggestions ({status_display})",
            f"Showing {len(rows)} suggestion(s). Use buttons on individual suggestion messages to manage them.",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
