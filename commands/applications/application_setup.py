"""Application setup command for moderators."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the application_setup command."""
    command_decorator = group.command(name="application_setup", description="Configure the clan application system (moderators only).") if group else bot.tree.command(name="application_setup", description="Configure the clan application system (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        channel="The channel where users can apply (leave empty to use current channel)",
        action="What to configure",
        description="Brief description of the application (for Post Panel action)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set Channel", value="set_channel"),
        app_commands.Choice(name="Post Panel", value="post_panel"),
        app_commands.Choice(name="Add Question", value="add_question"),
        app_commands.Choice(name="Remove Question", value="remove_question"),
        app_commands.Choice(name="View Questions", value="view_questions"),
        app_commands.Choice(name="Clear Questions", value="clear_questions"),
    ])
    async def application_setup(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None,
        description: Optional[str] = None
    ):
        """Configure the application system."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        action_value = action.value
        
        if action_value == "set_channel":
            target_channel = channel or interaction.channel
            if not isinstance(target_channel, discord.TextChannel):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Channel",
                        "Please specify a valid text channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO application_settings (guild_id, channel_id)
                    VALUES (?, ?)
                """, (interaction.guild.id, target_channel.id))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Application Channel Set",
                    f"Application channel set to {target_channel.mention}.\n\nUsers can now use `/application` in this channel to start an application.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action_value == "add_question":
            from modals import ApplicationQuestionModal
            modal = ApplicationQuestionModal(interaction.guild.id)
            await interaction.followup.send(
                "Please fill out the form to add a question.",
                ephemeral=True
            )
            try:
                await interaction.user.send(embed=obsidian_embed(
                    "Add Application Question",
                    "Please fill out the form below to add a question to the application.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ), view=None)
                await interaction.user.send("Use the button below to add a question:", view=ApplicationQuestionView(interaction.guild.id))
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Cannot Send DM",
                        "I cannot send you a DM. Please enable DMs from server members.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        elif action_value == "remove_question":
            # Get all questions
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, question_order, question_text
                    FROM application_questions
                    WHERE guild_id = ?
                    ORDER BY question_order
                """, (interaction.guild.id,))
                questions = await cur.fetchall()
            
            if not questions:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Questions",
                        "There are no questions configured yet.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Create a select menu for choosing which question to remove
            options = []
            for q_id, order, text in questions:
                display_text = text[:100] if len(text) <= 100 else text[:97] + "..."
                options.append(discord.SelectOption(
                    label=f"Question {order}",
                    description=display_text,
                    value=str(q_id)
                ))
            
            view = RemoveQuestionView(questions)
            select = discord.ui.Select(
                placeholder="Select a question to remove...",
                options=options[:25],  # Discord limit
                custom_id="remove_question_select"
            )
            view.add_item(select)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "Remove Question",
                    "Select a question to remove:",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                view=view,
                ephemeral=True
            )
        
        elif action_value == "view_questions":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT question_order, question_text
                    FROM application_questions
                    WHERE guild_id = ?
                    ORDER BY question_order
                """, (interaction.guild.id,))
                questions = await cur.fetchall()
            
            if not questions:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Questions",
                        "There are no questions configured yet. Use the 'Add Question' action to add questions.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            fields = []
            for order, text in questions:
                fields.append((f"Question {order}", text, False))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "Application Questions",
                    f"Total questions: {len(questions)}",
                    color=discord.Color.blue(),
                    fields=fields,
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action_value == "clear_questions":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    DELETE FROM application_questions
                    WHERE guild_id = ?
                """, (interaction.guild.id,))
                await db.commit()
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Questions Cleared",
                    "All application questions have been removed.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action_value == "post_panel":
            # Check if application channel is set
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT channel_id FROM application_settings WHERE guild_id = ?
                """, (interaction.guild.id,))
                row = await cur.fetchone()
            
            if not row or not row[0]:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Application Channel Not Set",
                        "Please set the application channel first using 'Set Channel' action.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check if there are questions
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT COUNT(*) FROM application_questions WHERE guild_id = ?
                """, (interaction.guild.id,))
                count = (await cur.fetchone())[0]
            
            if count == 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Questions Configured",
                        "Please add some questions first using 'Add Question' action.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            target_channel = channel or interaction.channel
            if not isinstance(target_channel, discord.TextChannel):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Channel",
                        "Please specify a valid text channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check if bot can send messages
            if not target_channel.permissions_for(interaction.guild.me).send_messages:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        f"I don't have permission to send messages in {target_channel.mention}.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Build description
            panel_desc = description or "Click the button below to start your clan application. You'll receive questions via DM to complete your application."
            
            # Truncate if too long
            if len(panel_desc) > 4096:
                panel_desc = panel_desc[:4093] + "..."
            
            # Create embed
            embed = obsidian_embed(
                "📝 Clan Application",
                panel_desc,
                color=discord.Color.blue(),
                client=interaction.client,
            )
            
            # Create view with button
            from views import ApplicationPanelView
            view = ApplicationPanelView(interaction.guild.id)
            bot.add_view(view)
            
            # Check if there's an existing panel to update
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT panel_channel_id, panel_message_id FROM application_settings WHERE guild_id = ?
                """, (interaction.guild.id,))
                row = await cur.fetchone()
                existing_panel_channel_id = row[0] if row and row[0] else None
                existing_panel_message_id = row[1] if row and row[1] else None
            
            try:
                if existing_panel_message_id and existing_panel_channel_id == target_channel.id:
                    # Try to update existing message
                    try:
                        existing_message = await target_channel.fetch_message(existing_panel_message_id)
                        await existing_message.edit(embed=embed, view=view)
                        
                        # Update description in database
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("""
                                UPDATE application_settings 
                                SET panel_description = ?
                                WHERE guild_id = ?
                            """, (description or panel_desc, interaction.guild.id))
                            await db.commit()
                        
                        await interaction.followup.send(
                            embed=obsidian_embed(
                                "✅ Application Panel Updated",
                                f"Application panel has been updated in {target_channel.mention}.",
                                color=discord.Color.green(),
                                client=interaction.client,
                            ),
                            ephemeral=True
                        )
                        return
                    except discord.NotFound:
                        # Message was deleted, send a new one
                        pass
                
                # Send new message
                message = await target_channel.send(embed=embed, view=view)
                
                # Save panel info
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        UPDATE application_settings 
                        SET panel_channel_id = ?, panel_message_id = ?, panel_description = ?
                        WHERE guild_id = ?
                    """, (target_channel.id, message.id, description or panel_desc, interaction.guild.id))
                    await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Application Panel Posted",
                        f"Application panel has been posted to {target_channel.mention}.\n\nUsers can click the button to start an application.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        f"I don't have permission to send messages in {target_channel.mention}.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error posting application panel: {e}")
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Error",
                        f"Failed to post application panel: {str(e)}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )


class ApplicationQuestionView(discord.ui.View):
    """View with button to open question modal."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
    
    @discord.ui.button(label="Add Question", style=discord.ButtonStyle.primary, custom_id="add_question_btn")
    async def add_question_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from modals import ApplicationQuestionModal
        modal = ApplicationQuestionModal(self.guild_id)
        await interaction.response.send_modal(modal)


class RemoveQuestionView(discord.ui.View):
    """View for removing questions."""
    def __init__(self, questions: list):
        super().__init__(timeout=300)
        self.questions = questions
    
    @discord.ui.select(custom_id="remove_question_select")
    async def remove_question_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)
        
        question_id = int(select.values[0])
        
        # Get question info before deleting
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT question_order, question_text
                FROM application_questions
                WHERE id = ?
            """, (question_id,))
            question_info = await cur.fetchone()
            
            if question_info:
                order, text = question_info
                # Delete the question
                await db.execute("""
                    DELETE FROM application_questions
                    WHERE id = ?
                """, (question_id,))
                
                # Reorder remaining questions
                await db.execute("""
                    UPDATE application_questions
                    SET question_order = question_order - 1
                    WHERE guild_id = (SELECT guild_id FROM application_questions WHERE id = ? LIMIT 1)
                    AND question_order > ?
                """, (question_id, order))
                await db.commit()
                
                await interaction.response.send_message(
                    embed=obsidian_embed(
                        "✅ Question Removed",
                        f"Question {order} has been removed:\n\n{text[:200]}",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("Question not found.", ephemeral=True)
