"""Auto-moderation status command."""
import discord
from discord import app_commands

from utils import obsidian_embed
from database import get_auto_mod_settings


def setup(bot, group=None):
    """Register the automod_status command."""
    command_decorator = group.command(name="automod_status", description="View current auto-moderation settings.") if group else bot.tree.command(name="automod_status", description="View current auto-moderation settings.")
    
    @command_decorator
    async def automod_status(interaction: discord.Interaction):
        """Display current auto-moderation settings."""
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Error",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        settings = await get_auto_mod_settings(interaction.guild.id)
        
        if not settings:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "⚠️ Auto-Moderation Not Configured",
                    "Auto-moderation is not yet configured. Use `/automod_setup` to configure it.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=False
            )
        
        # Build fields
        fields = [
            ("🔧 Status", "✅ Enabled" if settings["enabled"] else "❌ Disabled", True),
        ]
        
        if settings["enabled"]:
            # Spam
            spam_status = "✅" if settings["spam_enabled"] else "❌"
            fields.append((f"{spam_status} Spam Detection", f"Threshold: {settings['spam_threshold']} messages in {settings['spam_interval']}s", True))
            
            # Caps
            caps_status = "✅" if settings["caps_enabled"] else "❌"
            fields.append((f"{caps_status} Caps Filter", f"Threshold: {settings['caps_threshold']}% (min {settings['caps_min_length']} chars)", True))
            
            # Links
            links_status = "✅" if settings["links_enabled"] else "❌"
            fields.append((f"{links_status} Link Filter", "Enabled" if settings["links_enabled"] else "Disabled", True))
            
            # Mentions
            mention_status = "✅" if settings["mention_enabled"] else "❌"
            fields.append((f"{mention_status} Mention Limit", f"Max {settings['mention_limit']} mentions", True))
            
            # Punishment
            action_name = settings["punishment_action"].title()
            duration_text = f" ({settings['punishment_duration']} min)" if settings["punishment_duration"] else ""
            fields.append(("⚖️ Punishment", f"{action_name}{duration_text}", True))
            
            # Log channel
            log_channel = "Not set"
            if settings["log_channel_id"]:
                channel = interaction.guild.get_channel(settings["log_channel_id"])
                if channel:
                    log_channel = channel.mention
            
            fields.append(("📝 Log Channel", log_channel, True))
        
        embed = obsidian_embed(
            "🛡️ Auto-Moderation Status",
            "Current auto-moderation configuration for this server.",
            color=discord.Color.blue() if settings["enabled"] else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
