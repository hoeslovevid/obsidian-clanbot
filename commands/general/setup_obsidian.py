"""Setup Obsidian command."""
import asyncio
import discord

from utils import obsidian_embed, is_mod

# Track in-flight setup commands to prevent duplicates
_setup_in_progress = set()


def setup(bot, group=None):
    """Register the setup_obsidian command."""
    command_decorator = group.command(name="setup_obsidian", description="Create/ensure core channels and post bot panels (mods only).") if group else bot.tree.command(name="setup_obsidian", description="Create/ensure core channels and post bot panels (mods only).")
    
    @command_decorator
    async def setup_obsidian(interaction: discord.Interaction):
        # Import bot-specific functions inside the command to avoid circular imports
        from bot import ensure_join_to_create_channel
        from bot import CREATE_VC_NAME, TEMP_VC_CATEGORY_NAME, VOICE_PANEL_CHANNEL_NAME
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)

        # Prevent duplicate execution
        interaction_key = f"{interaction.guild.id}:{interaction.channel.id}:{interaction.user.id}"
        if interaction_key in _setup_in_progress:
            if not interaction.response.is_done():
                await interaction.response.send_message("Setup already in progress...", ephemeral=True)
            return
        
        try:
            _setup_in_progress.add(interaction_key)
            
            # Respond first, then do the work
            await interaction.response.defer(ephemeral=True)

            # Only ensure channels needed for Dojo Comms and Ops Board
            from bot import resolve_channel_id
            from bot import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
            from bot import EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME
            
            await resolve_channel_id(interaction.guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
            await resolve_channel_id(interaction.guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
            await ensure_join_to_create_channel(interaction.guild)

            # Post panels where command is run
            await interaction.channel.send(
                embed=obsidian_embed(
                    "Voice Channels",
                    f"Join **{CREATE_VC_NAME}** inside **{TEMP_VC_CATEGORY_NAME}** to create a temporary voice channel.\n"
                    f"A control panel will appear in **#{VOICE_PANEL_CHANNEL_NAME}** for the squad owner.",
                )
            )

            await interaction.channel.send(
                embed=obsidian_embed(
                    "Events",
                    "Create events with **/event_create**.\n"
                    "Times support natural phrasing (e.g., `tomorrow 8pm`).\n"
                    "RSVP buttons + reminder included.",
                )
            )

            await interaction.followup.send("Setup complete.", ephemeral=True)
        finally:
            await asyncio.sleep(1)
            _setup_in_progress.discard(interaction_key)
