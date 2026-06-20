"""Manage suggestions command for moderators."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from core.utils import obsidian_embed, is_mod
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
                elif item.label == "📋 Under Review":
                    item.custom_id = f"suggestion:{suggestion_id}:under_review"
                elif item.label == "📌 Planned":
                    item.custom_id = f"suggestion:{suggestion_id}:planned"
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
    
    @discord.ui.button(label="📋 Under Review", style=discord.ButtonStyle.secondary)
    async def under_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark suggestion as under review."""
        await self._handle_status(interaction, "UNDER_REVIEW", "📋 Under Review")

    @discord.ui.button(label="📌 Planned", style=discord.ButtonStyle.secondary)
    async def planned(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark suggestion as planned."""
        await self._handle_status(interaction, "PLANNED", "📌 Planned")

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
        if not interaction.guild:
            return await interaction.response.send_message(
                "This can only be used in a server.",
                ephemeral=True,
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
                    elif status == "UNDER_REVIEW":
                        embed.color = discord.Color.blue()
                    elif status == "PLANNED":
                        embed.color = discord.Color.gold()
                    
                    # Disable buttons
                    for item in self.children:
                        item.disabled = True
                    
                    await message.edit(embed=embed, view=self)
            except discord.NotFound:
                pass
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error updating suggestion message: {e}")

        if status == "UNDER_REVIEW" and message_id and interaction.channel:
            try:
                message = await interaction.channel.fetch_message(message_id)
                thread_name = f"staff-{self.suggestion_id}"[:100]
                existing = discord.utils.get(message.threads, name=thread_name)
                if not existing:
                    try:
                        thread = await message.create_thread(
                            name=thread_name,
                            type=discord.ChannelType.private_thread,
                            auto_archive_duration=10080,
                            reason=f"Staff review for suggestion #{self.suggestion_id}",
                        )
                    except discord.HTTPException:
                        thread = await message.create_thread(
                            name=thread_name,
                            auto_archive_duration=10080,
                            reason=f"Staff review for suggestion #{self.suggestion_id}",
                        )
                    await thread.add_user(interaction.user)
                    if isinstance(interaction.user, discord.Member):
                        from core.utils import get_mod_role

                        mod_role = get_mod_role(interaction.guild)
                        if mod_role:
                            for mod in mod_role.members[:20]:
                                try:
                                    await thread.add_user(mod)
                                except (discord.Forbidden, discord.HTTPException):
                                    pass
                    await thread.send(
                        f"Staff thread for suggestion **#{self.suggestion_id}**.\n"
                        f"Submitted by <@{user_id}>.\n\n{suggestion_text[:800]}"
                    )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        
        # DM the user who submitted the suggestion
        try:
            user = interaction.guild.get_member(user_id)
            if user:
                status_messages = {
                    "APPROVED":     ("✅ Your suggestion was **approved**! It may be implemented soon.", discord.Color.green()),
                    "REJECTED":     ("❌ Your suggestion was **rejected** by the moderators.", discord.Color.red()),
                    "IMPLEMENTED":  ("🎉 Your suggestion has been **implemented**! Thank you for your contribution!", discord.Color.blue()),
                    "UNDER_REVIEW": ("📋 Your suggestion is now **under review** by the team.", discord.Color.blurple()),
                    "PLANNED":      ("📌 Your suggestion has been added to the **planned** list!", discord.Color.gold()),
                }
                msg_text, dm_color = status_messages.get(status, (f"Your suggestion status changed to **{status}**.", discord.Color.greyple()))
                server_name = interaction.guild.name

                embed = obsidian_embed(
                    f"💡 Suggestion #{self.suggestion_id} Update",
                    f"{msg_text}\n\n**Server:** {server_name}\n\n"
                    f"**Your Suggestion:**\n{suggestion_text[:500]}{'…' if len(suggestion_text) > 500 else ''}",
                    color=dm_color,
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
        category="Filter by category (default: all)",
        limit="Number of suggestions to show (default: 10, max: 25)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Pending", value="PENDING"),
        app_commands.Choice(name="Under Review", value="UNDER_REVIEW"),
        app_commands.Choice(name="Planned", value="PLANNED"),
        app_commands.Choice(name="Approved", value="APPROVED"),
        app_commands.Choice(name="Rejected", value="REJECTED"),
        app_commands.Choice(name="Implemented", value="IMPLEMENTED"),
    ])
    @app_commands.choices(category=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Feature", value="feature"),
        app_commands.Choice(name="Bug", value="bug"),
        app_commands.Choice(name="Improvement", value="improvement"),
        app_commands.Choice(name="Other", value="other"),
    ])
    async def suggestions(
        interaction: discord.Interaction,
        status: app_commands.Choice[str] = None,
        category: app_commands.Choice[str] = None,
        limit: int = 10
    ):
        """View and manage suggestions."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This can only be used in a server.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        
        status_filter = status.value if status and status.value != "all" else None
        category_filter = category.value if category and category.value != "all" else None
        
        if limit < 1 or limit > 25:
            limit = 10
        
        # Get suggestions from database
        async with aiosqlite.connect(DB_PATH) as db:
            params = [interaction.guild.id]
            where_clauses = ["guild_id=?"]
            if status_filter:
                where_clauses.append("status=?")
                params.append(status_filter)
            if category_filter:
                where_clauses.append("category=?")
                params.append(category_filter)
            params.append(limit)
            where_sql = " AND ".join(where_clauses)
            cur = await db.execute(f"""
                SELECT id, user_id, suggestion_text, status, category, created_at, reviewed_by
                FROM suggestions
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
            """, params)
            
            rows = await cur.fetchall()
        
        if not rows:
            status_text = f" with status '{status_filter}'" if status_filter else ""
            desc = f"No suggestions{status_text} found.\n\n_→ Use `/community suggest` to submit a suggestion, or try a different status/category filter._"
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "💡 No Suggestions Found",
                    desc,
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed with suggestions
        fields = []
        for row in rows:
            suggestion_id, user_id, suggestion_text, suggestion_status = row[0], row[1], row[2], row[3]
            suggestion_category = row[4] if len(row) > 4 else "other"
            created_at = row[5] if len(row) > 5 else None
            reviewed_by = row[6] if len(row) > 6 else None
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            
            status_emoji = {
                "PENDING": "⏳",
                "UNDER_REVIEW": "📋",
                "PLANNED": "📌",
                "APPROVED": "✅",
                "REJECTED": "❌",
                "IMPLEMENTED": "✅"
            }.get(suggestion_status, "❓")
            
            value = f"**Status:** {status_emoji} {suggestion_status}\n"
            value += f"**Category:** {suggestion_category.title()}\n"
            value += f"**By:** {username}\n"
            value += f"**Suggestion:** {suggestion_text[:200]}{'...' if len(suggestion_text) > 200 else ''}\n"
            value += f"**ID:** #{suggestion_id}"
            
            fields.append((f"Suggestion #{suggestion_id}", value, False))
        
        status_display = status_filter if status_filter else "All"
        cat_display = f" • {category_filter}" if category_filter else ""
        status_colors = {"PENDING": discord.Color.orange(), "UNDER_REVIEW": discord.Color.blue(), "PLANNED": discord.Color.gold(), "APPROVED": discord.Color.green(), "REJECTED": discord.Color.red(), "IMPLEMENTED": discord.Color.blue()}
        color = status_colors.get(status_filter, discord.Color.blue()) if status_filter else discord.Color.blue()
        embed = obsidian_embed(
            f"💡 Suggestions ({status_display}{cat_display})",
            f"Showing {len(rows)} suggestion(s). Use buttons on individual suggestion messages to manage them.",
            color=color,
            fields=fields,
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{len(rows)} suggestion(s) • Filter: {status_display}{cat_display}",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
