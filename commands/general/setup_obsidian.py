"""Setup Obsidian command - interactive channel configuration."""
import asyncio
import discord
from discord import app_commands
from typing import Optional, List, Tuple

from utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting, get_configured_channel_id

# Channel config: (setting_key, display_name, default_channel_name, channel_type)
# channel_type: "text" or "category"
CHANNEL_CONFIGS: List[Tuple[str, str, str, str]] = [
    ("voice_panel_channel_id", "Voice Panel", "obsidian-console", "text"),
    ("events_channel_id", "Events (Ops Board)", "ops-board", "text"),
    ("complaints_channel_id", "Complaints (Docket)", "inheritor-docket", "text"),
    ("complaints_log_channel_id", "Complaints Log (Ledger)", "docket-ledger", "text"),
    ("temp_vc_category_id", "Temp VC Category", "Temp VCs", "category"),
]

_setup_in_progress = set()


class SetupChannelSelect(discord.ui.Select):
    """Select menu for choosing a channel or Create/Skip."""

    def __init__(
        self,
        guild: discord.Guild,
        step_index: int,
        setting_key: str,
        display_name: str,
        default_name: str,
        channel_type: str,
    ):
        self._guild = guild
        self._step_index = step_index
        self._setting_key = setting_key
        self._display_name = display_name
        self._default_name = default_name
        self._channel_type = channel_type

        if channel_type == "category":
            channels = [c for c in guild.categories if isinstance(c, discord.CategoryChannel)]
        else:
            channels = [c for c in guild.text_channels if isinstance(c, discord.TextChannel)]

        options: List[discord.SelectOption] = []
        for ch in channels[:23]:  # Max 23 to leave room for Create + Skip
            options.append(discord.SelectOption(label=f"#{ch.name}", value=str(ch.id), description=ch.name[:100]))
        options.append(discord.SelectOption(label="➕ Create new channel", value="__create__", description=f"Bot creates #{default_name}"))
        options.append(discord.SelectOption(label="⏭️ Skip (don't configure)", value="__skip__", description="Commands for this channel will be unavailable"))

        super().__init__(
            placeholder=f"Select {display_name} channel...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("You must be a moderator to configure channels.", ephemeral=True)
            return

        value = self.values[0]
        if value == "__skip__":
            await set_guild_setting(interaction.guild.id, self._setting_key, "0")
            result = f"**{self._display_name}** skipped. Commands requiring this channel will be unavailable."
        elif value == "__create__":
            try:
                if self._channel_type == "category":
                    ch = await interaction.guild.create_category(name=self._default_name, reason="Setup via /setup_obsidian")
                else:
                    ch = await interaction.guild.create_text_channel(name=self._default_name, reason="Setup via /setup_obsidian")
                await set_guild_setting(interaction.guild.id, self._setting_key, str(ch.id))
                result = f"**{self._display_name}**: Created {ch.mention}"
            except discord.Forbidden:
                result = f"**{self._display_name}**: Failed to create (missing permissions)"
            except Exception as e:
                result = f"**{self._display_name}**: Error creating: {e}"
        else:
            ch = interaction.guild.get_channel(int(value))
            if ch and isinstance(ch, (discord.TextChannel, discord.CategoryChannel)):
                await set_guild_setting(interaction.guild.id, self._setting_key, str(ch.id))
                result = f"**{self._display_name}**: Set to {ch.mention}"
            else:
                result = f"**{self._display_name}**: Channel not found."

        view = self.view
        if isinstance(view, SetupObsidianView):
            await view.advance(interaction, result)


class SetupObsidianView(discord.ui.View):
    """Sequential setup view - one channel type per step."""

    def __init__(self, guild: discord.Guild, step_index: int = 0):
        super().__init__(timeout=300)
        self.guild = guild
        self.step_index = step_index
        self.results: List[str] = []
        self._add_select()

    def _add_select(self):
        self.clear_items()
        if self.step_index >= len(CHANNEL_CONFIGS):
            return
        sk, display_name, default_name, channel_type = CHANNEL_CONFIGS[self.step_index]
        self.add_item(
            SetupChannelSelect(
                self.guild,
                self.step_index,
                sk,
                display_name,
                default_name,
                channel_type,
            )
        )

    async def advance(self, interaction: discord.Interaction, result: str):
        self.results.append(result)
        self.step_index += 1
        if self.step_index >= len(CHANNEL_CONFIGS):
            # Done
            from config import CREATE_VC_NAME, TEMP_VC_CATEGORY_NAME
            from bot import ensure_join_to_create_channel

            # Ensure join-to-create channel if Temp VC category was configured
            temp_cat_id = await get_configured_channel_id(interaction.guild.id, "temp_vc_category_id")
            if temp_cat_id:
                try:
                    await ensure_join_to_create_channel(interaction.guild)
                except Exception:
                    pass

            summary = "\n".join(self.results)
            embed = obsidian_embed(
                "✅ Setup Complete",
                f"Channel configuration saved:\n\n{summary}\n\n"
                "• Voice Panel: VC control panels appear here when users create temp channels\n"
                "• Events: Use `/community event_create` to post events here\n"
                "• Complaints: Use `/general setup_docket` to post the complaint panel\n"
                "• Temp VC: Join-to-create voice channels in this category",
                color=discord.Color.green(),
                client=interaction.client,
            )
            self.stop()
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.NotFound:
                await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            self._add_select()
            sk, display_name, _, _ = CHANNEL_CONFIGS[self.step_index]
            embed = obsidian_embed(
                f"Setup • Step {self.step_index + 1}/{len(CHANNEL_CONFIGS)}: {display_name}",
                f"Choose a channel for **{display_name}**, have the bot create one, or skip.\n\n"
                f"*Previous: {result}*",
                color=discord.Color.blurple(),
                client=interaction.client,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.NotFound:
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        try:
            if self.message:
                await self.message.edit(content="⏰ Setup timed out. Run /general setup_obsidian again.", view=self)
        except Exception:
            pass


def setup(bot, group=None):
    """Register the setup_obsidian command."""
    command_decorator = (
        group.command(name="setup_obsidian", description="Configure voice, events, complaints, and core channels (mods only).")
        if group
        else bot.tree.command(name="setup_obsidian", description="Configure voice, events, complaints, and core channels (mods only).")
    )

    @command_decorator
    async def setup_obsidian(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not a moderator in this server.", ephemeral=True)

        interaction_key = f"{interaction.guild.id}:{interaction.channel.id}:{interaction.user.id}"
        if interaction_key in _setup_in_progress:
            return await interaction.response.send_message("Setup already in progress in this channel.", ephemeral=True)

        _setup_in_progress.add(interaction_key)
        try:
            await interaction.response.defer(ephemeral=True)
            sk, display_name, _, _ = CHANNEL_CONFIGS[0]
            embed = obsidian_embed(
                f"Setup • Step 1/{len(CHANNEL_CONFIGS)}: {display_name}",
                "Select an existing channel, create a new one, or skip. "
                "Skipped channels will make related commands unavailable until configured.",
                color=discord.Color.blurple(),
                client=interaction.client,
            )
            view = SetupObsidianView(interaction.guild, 0)
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = msg
        finally:
            asyncio.create_task(_clear_setup_flag(interaction_key))


async def _clear_setup_flag(key: str):
    await asyncio.sleep(2)
    _setup_in_progress.discard(key)
