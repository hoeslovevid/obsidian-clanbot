"""Warframe build suggestions command - links to Overframe.gg and provides tips."""
import urllib.parse
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed

OVERFRAME_BASE = "https://overframe.gg/build"
OVERFRAME_SEARCH = "https://overframe.gg/builds"

POPULAR_ITEMS = [
    "Saryn", "Wisp", "Nekros", "Khora", "Hildryn", "Protea", "Gara", "Volt",
    "Soma Prime", "Kuva Bramma", "Kuva Nukor", "Tenet Arca Plasmor", "Nikana Prime",
    "Broken War", "Kuva Zarr", "Acceltra", "Laetum", "Phenmor", "Pax Securus",
    "Amar's Anguish", "Revenant", "Baruuk", "Chroma", "Inaros", "Harrow",
]

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


async def item_autocomplete(interaction: discord.Interaction, current: str):
    cur = (current or "").lower()
    matches = [i for i in POPULAR_ITEMS if not cur or cur in i.lower()]
    return [app_commands.Choice(name=m, value=m) for m in matches[:25]]


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
    @app_commands.autocomplete(item=item_autocomplete)
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

        slug = urllib.parse.quote(search.replace(" ", "-").lower())
        deep_url = f"{OVERFRAME_BASE}/{slug}"
        search_url = f"{OVERFRAME_SEARCH}?search={urllib.parse.quote(search)}"
        tips = BUILD_TIPS.get(category_val, BUILD_TIPS["warframe"])

        fields = [
            ("Overframe", f"[Direct build page]({deep_url})\n[Search all builds]({search_url})", False),
            ("Modding tips", tips[:1024], False),
        ]
        embed = embed_template(
            "warframe_status",
            f"🔧 Build: {search}",
            f"Community builds for **{search}** on Overframe.gg",
            variant="world_state",
            fields=fields,
            footer=f"{footer_for('warframe_status')} · Category: {category_val}",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed)
