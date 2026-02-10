"""Warframe build suggestions command - links to Overframe.gg and provides tips."""
import urllib.parse
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import obsidian_embed

OVERFRAME_BASE = "https://overframe.gg/builds"
BUILD_TIPS = {
    "warframe": (
        "**Modding tips:**\n"
        "• **Survivability:** Vitality, Steel Fiber, Adaptation, Rolling Guard\n"
        "• **Strength:** Intensify, Transient Fortitude, Blind Rage\n"
        "• **Range:** Stretch, Overextended, Augur Reach\n"
        "• **Efficiency:** Streamline, Fleeting Expertise\n"
        "• **Duration:** Continuity, Narrow Minded, Constitution"
    ),
    "primary": (
        "**Modding tips:**\n"
        "• **Damage:** Serration, Heavy Caliber\n"
        "• **Multishot:** Split Chamber, Vigilante Armaments\n"
        "• **Elements:** Viral (Cold + Toxin) for most content\n"
        "• **Crit:** Point Strike, Vital Sense\n"
        "• **Status:** 60/60 mods for hybrid builds"
    ),
    "secondary": (
        "**Modding tips:**\n"
        "• Same core principles as primaries\n"
        "• **Hornet Strike** for base damage\n"
        "• **Barrel Diffusion** for multishot\n"
        "• Use for Condition Overload primers or CO primers"
    ),
    "melee": (
        "**Modding tips:**\n"
        "• **Pressure Point** or **Condition Overload**\n"
        "• **Blood Rush** + **Weeping Wounds** for crit/status\n"
        "• **Reach** or **Primed Reach** for range\n"
        "• **Berserker Fury** or **Primed Fury** for attack speed"
    ),
}


def setup(bot, group=None):
    """Register the build command."""
    command_decorator = (
        group.command(
            name="build",
            description="Get build links and modding tips for Warframes and weapons.",
        )
        if group
        else bot.tree.command(
            name="build",
            description="Get build links and modding tips for Warframes and weapons.",
        )
    )

    @command_decorator
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Warframe", value="warframe"),
            app_commands.Choice(name="Primary Weapon", value="primary"),
            app_commands.Choice(name="Secondary Weapon", value="secondary"),
            app_commands.Choice(name="Melee Weapon", value="melee"),
        ]
    )
    @app_commands.describe(
        item="Name of the Warframe or weapon (e.g. Excalibur, Soma Prime)",
        category="Type of item for relevant modding tips",
    )
    async def build(
        interaction: discord.Interaction,
        item: str,
        category: app_commands.Choice[str],
    ):
        """Return Overframe.gg search link and modding tips."""
        category_val = category.value if category else "warframe"
        search = item.strip()
        if not search:
            return await interaction.response.send_message(
                "Please provide an item name.",
                ephemeral=True,
            )

        url = f"{OVERFRAME_BASE}?search={urllib.parse.quote(search)}"
        tips = BUILD_TIPS.get(category_val, BUILD_TIPS["warframe"])

        fields = [
            ("Link", f"[Browse builds on Overframe.gg]({url})", False),
            ("Modding tips", tips[:1024], False),
        ]
        embed = obsidian_embed(
            f"🔧 Build: {search}",
            "",
            color=discord.Color.blue(),
            fields=fields,
            thumbnail=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None,
            footer=f"Category: {category_val} • Community builds may vary",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed)
