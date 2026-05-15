"""Pet system commands."""
import discord  # type: ignore
from discord import app_commands  # type: ignore
from typing import Optional
from datetime import datetime, timedelta, timezone
import random

from core.utils import obsidian_embed
from database import DB_PATH, now_utc, get_user_balance, remove_coins, add_coins
from views import ConfirmView
import aiosqlite
import dateparser

# Pet type battle bonuses (attack_mult, defense_mult)
PET_TYPE_BONUSES = {
    "Dragon": (1.15, 1.0),
    "Wolf": (1.1, 1.05),
    "Phoenix": (1.12, 0.98),
    "Robot": (1.0, 1.15),
    "Fox": (1.08, 1.02),
    "Cat": (1.05, 1.03),
    "Rabbit": (0.95, 1.08),
}
DEFAULT_BONUS = (1.0, 1.0)

BATTLE_COOLDOWN_MINUTES = 5
MIN_HUNGER_TO_BATTLE = 20
MIN_HAPPINESS_TO_BATTLE = 20
ABANDONMENT_COOLDOWN_HOURS = 24
BATTLE_WINNER_COINS_BASE = 15
BATTLE_LOSER_COINS = 5
BATTLE_XP_WINNER = 20
BATTLE_XP_LOSER = 8

# Pet icons: Twemoji CDN (reliable, Discord-friendly)
PET_ICONS = {
    "Dog": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f436.png",
    "Cat": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f431.png",
    "Bird": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f426.png",
    "Fish": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f41f.png",
    "Rabbit": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f430.png",
    "Fox": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f98a.png",
    "Robot": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f916.png",
    "Wolf": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f43a.png",
    "Dragon": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f409.png",
    "Phoenix": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f525.png",
}
DEFAULT_PET_ICON = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/1f43e.png"

# Compact emoji per pet type (for tight UI like footers / inline lines).
# Keep aligned with PET_ICONS keys above.
PET_EMOJIS: dict[str, str] = {
    "Dog": "🐶",
    "Cat": "🐱",
    "Bird": "🐦",
    "Fish": "🐠",
    "Rabbit": "🐰",
    "Fox": "🦊",
    "Robot": "🤖",
    "Wolf": "🐺",
    "Dragon": "🐉",
    "Phoenix": "🔥",
}
DEFAULT_PET_EMOJI = "🐾"


def get_pet_emoji(pet_type: Optional[str]) -> str:
    """Return a compact emoji for a pet type (falls back to 🐾)."""
    if not pet_type:
        return DEFAULT_PET_EMOJI
    return PET_EMOJIS.get(str(pet_type).strip(), DEFAULT_PET_EMOJI)


# --- Item 56: Pet evolution stages -----------------------------------------
PET_STAGE_NAMES: tuple[str, ...] = ("Baby", "Young", "Adult", "Elder")
PET_STAGE_SUFFIX: tuple[str, ...] = ("", "✨", "🌟", "💫")


def _pet_age_days(created_at: Optional[str]) -> int:
    if not created_at:
        return 0
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def pet_stage(created_at: Optional[str]) -> int:
    """Return 0..3 for Baby/Young/Adult/Elder based on age in days."""
    days = _pet_age_days(created_at)
    if days >= 90:
        return 3
    if days >= 30:
        return 2
    if days >= 7:
        return 1
    return 0


def get_pet_emoji_with_stage(pet_type: Optional[str], created_at: Optional[str]) -> str:
    """Stage-aware variant used by pet card / leaderboards."""
    base = get_pet_emoji(pet_type)
    suffix = PET_STAGE_SUFFIX[pet_stage(created_at)]
    return f"{base}{suffix}" if suffix else base


async def _maybe_announce_stage_change(
    interaction: discord.Interaction,
    user_id: int,
    created_at: Optional[str],
    pet_name: Optional[str] = None,
    pet_type: Optional[str] = None,
) -> None:
    """If the pet's stage advanced since we last recorded it, celebrate (Item 56)."""
    if not interaction.guild:
        return
    from database import get_guild_setting, set_guild_setting
    # Lazy fill-in: caller can pass None for name/type and we fetch.
    if not pet_name or not pet_type:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT pet_name, pet_type FROM pets WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, user_id),
                )
                row = await cur.fetchone()
            if row:
                pet_name = pet_name or str(row[0])
                pet_type = pet_type or str(row[1])
        except Exception:
            pass
    pet_name = pet_name or "Your pet"
    stage_now = pet_stage(created_at)
    raw_prev = await get_guild_setting(interaction.guild.id, f"pet_stage:{user_id}")
    try:
        stage_prev = int(raw_prev) if raw_prev is not None else -1
    except ValueError:
        stage_prev = -1
    if stage_now <= stage_prev:
        return
    await set_guild_setting(interaction.guild.id, f"pet_stage:{user_id}", str(stage_now))
    stage_name = PET_STAGE_NAMES[stage_now]
    emoji = get_pet_emoji_with_stage(pet_type, created_at)
    embed = obsidian_embed(
        f"🎂 {pet_name} evolved!",
        f"{emoji} **{pet_name}** has matured into a **{stage_name}** pet!",
        category="prestige",
        client=interaction.client,
    )
    # Respect achievement_notify preference for the DM fallback.
    pref = await get_guild_setting(interaction.guild.id, f"user_achievement_notify:{user_id}")
    use_dm = pref != "0"
    member = interaction.guild.get_member(user_id)
    posted_anywhere = False
    try:
        if interaction.channel and hasattr(interaction.channel, "send"):
            await interaction.channel.send(embed=embed)
            posted_anywhere = True
    except Exception:
        posted_anywhere = False
    if not posted_anywhere and use_dm and member:
        try:
            await member.send(embed=embed)
        except Exception:
            pass

    # Achievement hook: ignore failures — the bot's achievement system
    # uses pre-defined IDs, so we just keep the embed-only celebration.
    try:
        from database import check_and_unlock_achievement  # type: ignore
        await check_and_unlock_achievement(interaction.guild.id, user_id, f"pet_evolved_{stage_name.lower()}")
    except Exception:
        pass


PETS_PER_PAGE = 4


class PetShopView(discord.ui.View):
    """Pagination view for pet shop."""

    def __init__(self, pets: list, *, client=None, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.pets = pets
        self.client = client
        self.page = 0
        self.total_pages = max(1, (len(pets) + PETS_PER_PAGE - 1) // PETS_PER_PAGE)
        self._update_buttons()

    def _update_buttons(self):
        for c in self.children:
            if getattr(c, "custom_id", "") == "pet_shop_prev":
                c.disabled = self.page <= 0
            elif getattr(c, "custom_id", "") == "pet_shop_next":
                c.disabled = self.page >= self.total_pages - 1

    def _build_embed(self) -> discord.Embed:
        start = self.page * PETS_PER_PAGE
        page_pets = self.pets[start : start + PETS_PER_PAGE]
        first_pet_type = page_pets[0][0] if page_pets else None
        thumbnail = PET_ICONS.get(first_pet_type, DEFAULT_PET_ICON) if first_pet_type else DEFAULT_PET_ICON

        lines = []
        for pet_type, price, max_level, desc in page_pets:
            lines.append(f"**{pet_type}** • {price:,} coins • Max Lv.{max_level}\n{desc}")

        desc = "Browse pets below. Use the buttons to change pages.\n\n" + "\n\n".join(lines)
        footer = f"Page {self.page + 1}/{self.total_pages} • Use /pets buy to purchase"
        return obsidian_embed(
            "🐾 Pet Shop",
            desc,
            color=discord.Color.gold(),
            thumbnail=thumbnail,
            footer=footer,
            client=self.client,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="pet_shop_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="pet_shop_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


# Pet leveling constants
EXP_PER_LEVEL = 75  # XP needed = level * EXP_PER_LEVEL (e.g. 75 for L1->L2, 150 for L2->L3)
EXP_FEED = 8
EXP_PLAY = 15

# Decay: hunger and happiness decrease over time when not tended
HUNGER_DECAY_PER_HOUR = 2
HAPPINESS_DECAY_PER_HOUR = 1


def _exp_needed_for_level(level: int) -> int:
    """XP required to level up from current level to next."""
    return level * EXP_PER_LEVEL


def _apply_decay(
    current: int,
    last_action_at: Optional[str],
    created_at: str,
    decay_per_hour: int,
) -> int:
    """Compute effective value after decay since last action. Uses created_at if last_action_at is None."""
    ref = last_action_at or created_at
    try:
        ref_time = dateparser.parse(ref, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
        if ref_time:
            hours = (datetime.now(timezone.utc) - ref_time).total_seconds() / 3600
            decayed = current - int(hours * decay_per_hour)
            return max(0, min(100, decayed))
    except Exception:
        pass
    return current


def _battle_stats(level: int, pet_type: str) -> tuple[int, int, int]:
    """Return (hp, attack, defense) for battle."""
    hp = 30 + level * 4
    attack = 3 + level
    defense = 1 + level // 2
    atk_mult, def_mult = PET_TYPE_BONUSES.get(pet_type, DEFAULT_BONUS)
    return hp, int(attack * atk_mult), int(defense * def_mult)


def _resolve_battle(
    p1: tuple[str, str, int, int, int, int, int],
    p2: tuple[str, str, int, int, int, int, int],
) -> tuple[int, list[str]]:
    """
    Resolve a battle. p1/p2 = (pet_name, pet_type, level, hp, attack, defense, user_id).
    Returns (winner_user_id, log_lines).
    """
    name1, type1, lv1, hp1, atk1, def1, uid1 = p1
    name2, type2, lv2, hp2, atk2, def2, uid2 = p2
    log = []

    while hp1 > 0 and hp2 > 0:
        # P1 attacks P2
        dmg = max(1, int(atk1 * random.uniform(0.85, 1.15) - def2 * 0.4))
        hp2 -= dmg
        log.append(f"**{name1}** hits **{name2}** for {dmg} damage!")
        if hp2 <= 0:
            break
        # P2 attacks P1
        dmg = max(1, int(atk2 * random.uniform(0.85, 1.15) - def1 * 0.4))
        hp1 -= dmg
        log.append(f"**{name2}** hits **{name1}** for {dmg} damage!")

    winner = uid1 if hp2 <= 0 else uid2
    return winner, log


class PetBattleChallengeView(discord.ui.View):
    """View with Accept/Decline for pet battle challenges."""

    def __init__(self, challenger_id: int, defender_id: int, guild_id: int, challenger_name: str, defender_name: str, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.guild_id = guild_id
        self.challenger_name = challenger_name
        self.defender_name = defender_name
        self.resolved = False

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defender_id:
            return await interaction.response.send_message("Only the challenged player can accept.", ephemeral=True)
        if self.resolved:
            return await interaction.response.send_message("This challenge was already resolved.", ephemeral=True)
        self.resolved = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)

        # Resolve battle
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pet_name, pet_type, level, hunger, happiness, last_fed_at, last_played_at, created_at
                FROM pets WHERE guild_id=? AND user_id=?
            """, (self.guild_id, self.challenger_id))
            row1 = await cur.fetchone()
            cur = await db.execute("""
                SELECT pet_name, pet_type, level, hunger, happiness, last_fed_at, last_played_at, created_at
                FROM pets WHERE guild_id=? AND user_id=?
            """, (self.guild_id, self.defender_id))
            row2 = await cur.fetchone()

        if not row1 or not row2:
            return await interaction.followup.send("One or both pets are no longer available.", ephemeral=True)

        n1, t1, lv1, h1, hp1, lf1, lp1, c1 = row1
        n2, t2, lv2, h2, hp2, lf2, lp2, c2 = row2

        h1_eff = _apply_decay(h1, lf1, c1, HUNGER_DECAY_PER_HOUR)
        hp1_eff = _apply_decay(hp1, lp1, c1, HAPPINESS_DECAY_PER_HOUR)
        h2_eff = _apply_decay(h2, lf2, c2, HUNGER_DECAY_PER_HOUR)
        hp2_eff = _apply_decay(hp2, lp2, c2, HAPPINESS_DECAY_PER_HOUR)

        if h1_eff < MIN_HUNGER_TO_BATTLE or hp1_eff < MIN_HAPPINESS_TO_BATTLE:
            return await interaction.followup.send(
                f"{self.challenger_name}'s pet is too hungry or unhappy to battle (need {MIN_HUNGER_TO_BATTLE}+ hunger, {MIN_HAPPINESS_TO_BATTLE}+ happiness)."
            )
        if h2_eff < MIN_HUNGER_TO_BATTLE or hp2_eff < MIN_HAPPINESS_TO_BATTLE:
            return await interaction.followup.send(
                f"{self.defender_name}'s pet is too hungry or unhappy to battle."
            )

        hp_a, atk_a, def_a = _battle_stats(lv1, t1)
        hp_b, atk_b, def_b = _battle_stats(lv2, t2)

        p1 = (n1, t1, lv1, hp_a, atk_a, def_a, self.challenger_id)
        p2 = (n2, t2, lv2, hp_b, atk_b, def_b, self.defender_id)
        winner_uid, log_lines = _resolve_battle(p1, p2)

        loser_uid = self.defender_id if winner_uid == self.challenger_id else self.challenger_id
        winner_name = self.challenger_name if winner_uid == self.challenger_id else self.defender_name
        loser_name = self.defender_name if loser_uid == self.defender_id else self.challenger_name

        # Rewards: coins and XP
        coins_win = BATTLE_WINNER_COINS_BASE + (lv1 + lv2)  # Scale slightly with combined level
        await add_coins(self.guild_id, winner_uid, coins_win, "PET_BATTLE", "Won pet battle")
        await add_coins(self.guild_id, loser_uid, BATTLE_LOSER_COINS, "PET_BATTLE", "Lost pet battle")

        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now_utc().isoformat()
            # Winner XP
            cur = await db.execute("SELECT experience, level FROM pets WHERE guild_id=? AND user_id=?", (self.guild_id, winner_uid))
            row = await cur.fetchone()
            if row:
                exp, lvl = row
                exp += BATTLE_XP_WINNER
                exp_needed = _exp_needed_for_level(lvl)
                while exp >= exp_needed:
                    exp -= exp_needed
                    lvl += 1
                    exp_needed = _exp_needed_for_level(lvl)
                cur2 = await db.execute("SELECT max_level FROM pet_types pt JOIN pets p ON p.pet_type=pt.pet_type WHERE p.guild_id=? AND p.user_id=?", (self.guild_id, winner_uid))
                max_lv = (await cur2.fetchone())[0]
                lvl = min(lvl, max_lv)
                await db.execute("UPDATE pets SET experience=?, level=? WHERE guild_id=? AND user_id=?", (exp, lvl, self.guild_id, winner_uid))
            # Loser XP
            cur = await db.execute("SELECT experience, level FROM pets WHERE guild_id=? AND user_id=?", (self.guild_id, loser_uid))
            row = await cur.fetchone()
            if row:
                exp, lvl = row
                exp += BATTLE_XP_LOSER
                exp_needed = _exp_needed_for_level(lvl)
                while exp >= exp_needed:
                    exp -= exp_needed
                    lvl += 1
                    exp_needed = _exp_needed_for_level(lvl)
                cur2 = await db.execute("SELECT max_level FROM pet_types pt JOIN pets p ON p.pet_type=pt.pet_type WHERE p.guild_id=? AND p.user_id=?", (self.guild_id, loser_uid))
                max_lv = (await cur2.fetchone())[0]
                lvl = min(lvl, max_lv)
                await db.execute("UPDATE pets SET experience=?, level=? WHERE guild_id=? AND user_id=?", (exp, lvl, self.guild_id, loser_uid))
            # Cooldowns
            await db.execute("""
                INSERT OR REPLACE INTO pet_battle_cooldowns (guild_id, user_id, last_battle_at)
                VALUES (?, ?, ?), (?, ?, ?)
            """, (self.guild_id, self.challenger_id, now_str, self.guild_id, self.defender_id, now_str))
            # Battle stats
            await db.execute("""
                INSERT INTO pet_battle_stats (guild_id, user_id, wins, losses)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET wins = wins + 1
            """, (self.guild_id, winner_uid))
            await db.execute("""
                INSERT INTO pet_battle_stats (guild_id, user_id, wins, losses)
                VALUES (?, ?, 0, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET losses = losses + 1
            """, (self.guild_id, loser_uid))
            cur = await db.execute("SELECT wins FROM pet_battle_stats WHERE guild_id=? AND user_id=?", (self.guild_id, winner_uid))
            winner_wins = (await cur.fetchone())[0] if cur else 1
            await db.commit()
            # Achievement triggers (after commit)
            try:
                from database import check_and_unlock_achievement
                if winner_wins == 1:
                    await check_and_unlock_achievement(self.guild_id, winner_uid, "pet_battle_win", interaction.client, interaction=interaction)
                elif winner_wins >= 5:
                    await check_and_unlock_achievement(self.guild_id, winner_uid, "pet_battle_5", interaction.client, interaction=interaction)
            except Exception:
                pass

        log_text = "\n".join(log_lines[-6:])  # Last 6 lines
        if len(log_lines) > 6:
            log_text = "..." + log_text
        result_embed = obsidian_embed(
            "⚔️ Pet Battle Result",
            f"**{winner_name}** wins!\n\n{log_text}\n\n"
            f"🏆 **{winner_name}** +{coins_win} coins, +{BATTLE_XP_WINNER} XP\n"
            f"💔 **{loser_name}** +{BATTLE_LOSER_COINS} coins, +{BATTLE_XP_LOSER} XP",
            color=discord.Color.green() if winner_uid == self.challenger_id else discord.Color.blue(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=result_embed)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary)
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defender_id:
            return await interaction.response.send_message("Only the challenged player can decline.", ephemeral=True)
        if self.resolved:
            return await interaction.response.send_message("Already resolved.", ephemeral=True)
        self.resolved = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"**{self.defender_name}** declined the pet battle challenge.",
            embed=None,
            view=self,
        )

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if not self.resolved:
            self.resolved = True
            try:
                await self.message.edit(
                    content="⏰ Challenge timed out.",
                    embed=None,
                    view=self,
                )
            except Exception:
                pass


def setup(bot, group=None):
    """Register pet commands."""
    
    command_decorator = group.command(name="shop", description="View available pets to buy.") if group else bot.tree.command(name="shop", description="View available pets to buy.")
    
    @command_decorator
    async def pet_shop(interaction: discord.Interaction):
        """View pet shop."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pet_type, base_price, max_level, description FROM pet_types
                ORDER BY base_price
            """)
            pets = await cur.fetchall()
            
            if not pets:
                # Initialize default pets (must run inside same connection)
                default_pets = [
                    ("Dog", 100, 50, "A loyal companion"),
                    ("Cat", 150, 60, "An independent friend"),
                    ("Bird", 80, 40, "A cheerful winged friend"),
                    ("Fish", 75, 35, "A calm aquarium buddy"),
                    ("Rabbit", 120, 55, "A soft and speedy pal"),
                    ("Fox", 200, 70, "A clever and curious companion"),
                    ("Robot", 300, 80, "A mechanical companion"),
                    ("Wolf", 350, 85, "A fierce and loyal guardian"),
                    ("Dragon", 500, 100, "A powerful mythical creature"),
                    ("Phoenix", 600, 100, "A legendary fire bird that rises again"),
                ]
                for pet_type, price, max_level, desc in default_pets:
                    await db.execute("""
                        INSERT OR IGNORE INTO pet_types (pet_type, base_price, max_level, description)
                        VALUES (?, ?, ?, ?)
                    """, (pet_type, price, max_level, desc))
                await db.commit()
                cur = await db.execute("""
                    SELECT pet_type, base_price, max_level, description FROM pet_types
                    ORDER BY base_price
                """)
                pets = await cur.fetchall()
        
        view = PetShopView(pets, client=interaction.client)
        await interaction.followup.send(
            embed=view._build_embed(),
            view=view,
        )
    
    async def pet_type_autocomplete(interaction: discord.Interaction, current: str):
        """Autocomplete for pet types. Paginated: returns top 25 by relevance."""
        from core.utils import AUTOCOMPLETE_MAX_CHOICES
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT pet_type FROM pet_types ORDER BY pet_type")
            rows = await cur.fetchall()
        all_types = [r[0] for r in rows]
        current_lower = (current or "").lower().strip()
        if not current_lower:
            matches = all_types[:AUTOCOMPLETE_MAX_CHOICES]
        else:
            exact = [t for t in all_types if t.lower() == current_lower]
            start = [t for t in all_types if t.lower().startswith(current_lower) and t not in exact]
            contains = [t for t in all_types if current_lower in t.lower() and t not in exact and t not in start]
            matches = (exact + start + contains)[:AUTOCOMPLETE_MAX_CHOICES]
        return [app_commands.Choice(name=m, value=m) for m in matches]

    command_decorator = group.command(name="buy", description="Buy a pet.") if group else bot.tree.command(name="buy", description="Buy a pet.")
    
    @command_decorator
    @app_commands.describe(pet_type="Type of pet to buy", pet_name="Name for your pet")
    @app_commands.autocomplete(pet_type=pet_type_autocomplete)
    async def pet_buy(interaction: discord.Interaction, pet_type: str, pet_name: str):
        """Buy a pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        from core.utils import feature_enabled, feature_off_embed  # Item 85
        if not await feature_enabled(interaction.guild.id, "pets"):
            return await interaction.response.send_message(embed=feature_off_embed("Pets", client=interaction.client), ephemeral=True)

        await interaction.response.defer()
        
        # Check if user already has a pet
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT 1 FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Have Pet",
                        "You already have a pet! Use `/pet` to view it.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    )
                )
            # Check abandonment cooldown
            cur = await db.execute("""
                SELECT abandoned_at FROM pet_abandonments WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            abandon_row = await cur.fetchone()
            if abandon_row:
                try:
                    abandoned_at = dateparser.parse(abandon_row[0], settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
                    if abandoned_at:
                        hours_since = (datetime.now(timezone.utc) - abandoned_at).total_seconds() / 3600
                        if hours_since < ABANDONMENT_COOLDOWN_HOURS:
                            remaining = ABANDONMENT_COOLDOWN_HOURS - hours_since
                            return await interaction.followup.send(
                                embed=obsidian_embed(
                                    "⏳ Adoption Cooldown",
                                    f"You released a pet recently. Wait **{remaining:.1f} hours** before adopting again.",
                                    color=discord.Color.orange(),
                                    client=interaction.client,
                                )
                            )
                except Exception:
                    pass
            
            # Get pet type info
            cur = await db.execute("""
                SELECT base_price FROM pet_types WHERE pet_type=?
            """, (pet_type,))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Pet Type",
                        f"Pet type '{pet_type}' not found. Use `/pets shop` to see available pets.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            price = row[0]
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            
            if balance < price:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Insufficient Funds",
                        f"You need {price} coins to buy a {pet_type}. You have {balance} coins.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            # Buy pet
            await remove_coins(interaction.guild.id, interaction.user.id, price, "PET", f"Purchased {pet_type} pet")
            
            await db.execute("""
                INSERT INTO pets (guild_id, user_id, pet_name, pet_type, level, experience, hunger, happiness, created_at)
                VALUES (?, ?, ?, ?, 1, 0, 100, 100, ?)
            """, (interaction.guild.id, interaction.user.id, pet_name, pet_type, now_utc().isoformat()))
            await db.commit()
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "pet_first", getattr(interaction.client, "bot", interaction.client), interaction=interaction)
            except Exception:
                pass

        embed = obsidian_embed(
            "✅ Pet Purchased",
            f"You bought **{pet_name}** ({pet_type}) for {price:,} coins!\n\n"
            "Use `/pet` to view your pet, `/pet_feed` to feed it, and `/pet_play` to play with it.",
            color=discord.Color.green(),
            thumbnail=PET_ICONS.get(pet_type, DEFAULT_PET_ICON),
            footer=f"Pet: {pet_name} • Type: {pet_type}",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
    
    command_decorator = group.command(name="view", description="View your pet.") if group else bot.tree.command(name="view", description="View your pet.")
    
    @command_decorator
    async def pet(interaction: discord.Interaction):
        """View pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT p.pet_name, p.pet_type, p.level, p.experience, p.hunger, p.happiness,
                       p.last_fed_at, p.last_played_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🐾 No Pet",
                    "You don't have a pet yet! Use `/pets shop` to see available pets and `/pets buy` to buy one.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
        
        pet_name, pet_type, level, exp, hunger, happiness, last_fed, last_played, created_at, max_level = row
        
        # Apply decay for display (hunger/happiness decrease over time)
        hunger = _apply_decay(hunger, last_fed, created_at, HUNGER_DECAY_PER_HOUR)
        happiness = _apply_decay(happiness, last_played, created_at, HAPPINESS_DECAY_PER_HOUR)
        
        exp_needed = _exp_needed_for_level(level)
        stage_idx = pet_stage(created_at)
        stage_name = PET_STAGE_NAMES[stage_idx]
        stage_emoji = get_pet_emoji_with_stage(pet_type, created_at)
        pet_text = (
            f"**Name:** {pet_name}\n"
            f"**Type:** {pet_type} {stage_emoji}\n"
            f"**Stage:** {stage_name} ({_pet_age_days(created_at)}d old)\n"
            f"**Level:** {level} / {max_level}\n"
        )
        pet_text += f"**Experience:** {exp}/{exp_needed}\n"
        pet_text += f"**Hunger:** {hunger}/100 {'🍽️' if hunger < 50 else '✅'}\n"
        pet_text += f"**Happiness:** {happiness}/100 {'😢' if happiness < 50 else '😊'}\n"

        # Item 56: announce stage change if applicable.
        try:
            await _maybe_announce_stage_change(
                interaction, interaction.user.id, created_at, pet_name, pet_type
            )
        except Exception:
            pass
        
        if last_fed:
            try:
                fed_time = dateparser.parse(last_fed, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if fed_time:
                    hours_since_fed = (datetime.now(timezone.utc) - fed_time).total_seconds() / 3600
                    pet_text += f"\n**Last Fed:** {int(hours_since_fed)} hours ago"
            except:
                pass
        
        embed = obsidian_embed(
            f"🐾 {pet_name}",
            pet_text,
            color=discord.Color.gold(),
            thumbnail=PET_ICONS.get(pet_type, DEFAULT_PET_ICON),
            footer=f"Level {level}/{max_level} • Feed and play to keep your pet happy!",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)

    command_decorator = group.command(name="rename", description="Rename your pet.") if group else bot.tree.command(name="rename", description="Rename your pet.")
    @command_decorator
    @app_commands.describe(new_name="New name for your pet")
    async def pet_rename(interaction: discord.Interaction, new_name: str):
        """Rename your pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True
            )
        new_name = (new_name or "").strip()
        if not new_name or len(new_name) > 50:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Name", "Name must be 1–50 characters.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True
            )
        await interaction.response.defer()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT pet_name FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ No Pet", "You don't have a pet! Use `/pets buy` to buy one.", color=discord.Color.red(), client=interaction.client),
                )
            await db.execute(
                "UPDATE pets SET pet_name=? WHERE guild_id=? AND user_id=?",
                (new_name, interaction.guild.id, interaction.user.id),
            )
            await db.commit()
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Pet Renamed",
                f"Your pet is now called **{new_name}**.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
        )

    command_decorator = group.command(name="abandon", description="Release your pet. You must wait 24h before adopting again.") if group else bot.tree.command(name="abandon", description="Release your pet. You must wait 24h before adopting again.")
    @command_decorator
    async def pet_abandon(interaction: discord.Interaction):
        """Abandon your pet. Cooldown applies before adopting again."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True
            )
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT pet_name, pet_type FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message(
                    embed=obsidian_embed("❌ No Pet", "You don't have a pet to abandon.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            pet_name, pet_type = row

        embed = obsidian_embed(
            "⚠️ Confirm Abandon",
            f"Release **{pet_name}** ({pet_type})? You cannot adopt a new pet for 24 hours.",
            color=discord.Color.orange(),
            client=interaction.client,
        )

        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if not confirmed:
                await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                return
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.followup.send("Only you can confirm abandoning your pet.", ephemeral=True)
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM pets WHERE guild_id=? AND user_id=?", (interaction.guild.id, interaction.user.id))
                await db.execute(
                    "INSERT OR REPLACE INTO pet_abandonments (guild_id, user_id, abandoned_at) VALUES (?, ?, ?)",
                    (interaction.guild.id, interaction.user.id, now_utc().isoformat()),
                )
                await db.commit()
            await btn_interaction.followup.send(
                embed=obsidian_embed(
                    "💔 Pet Released",
                    f"**{pet_name}** ({pet_type}) has been released. You can adopt a new pet in **24 hours**.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        view = ConfirmView(on_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    command_decorator = group.command(name="feed", description="Feed your pet (costs 10 coins).") if group else bot.tree.command(name="feed", description="Feed your pet (costs 10 coins).")
    
    @command_decorator
    async def pet_feed(interaction: discord.Interaction):
        """Feed pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        cost = 10
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins to feed your pet. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT p.hunger, p.experience, p.level, p.pet_type, p.last_fed_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Pet",
                        "You don't have a pet! Use `/pets buy` to buy one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            hunger, exp, level, pet_type, last_fed_at, created_at, max_level = row
            hunger = _apply_decay(hunger, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            hunger = min(100, hunger + 20)  # Increase hunger by 20, max 100
            exp = exp + EXP_FEED
            
            # Level-up logic (cap at max_level)
            new_level = level
            while new_level < max_level and exp >= _exp_needed_for_level(new_level):
                exp -= _exp_needed_for_level(new_level)
                new_level += 1
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Pet food")
            await db.execute("""
                UPDATE pets SET hunger=?, experience=?, level=?, last_fed_at=? WHERE guild_id=? AND user_id=?
            """, (hunger, exp, new_level, now_utc().isoformat(), interaction.guild.id, interaction.user.id))
            await db.commit()

        try:
            await _maybe_announce_stage_change(interaction, interaction.user.id, created_at, None, pet_type)
        except Exception:
            pass

        if new_level >= 25 and level < 25:
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "pet_level_25", interaction.client, interaction=interaction)
            except Exception:
                pass
        level_up_text = f"\n🎉 **Level Up!** Your pet is now level {new_level}!" if new_level > level else ""
        await interaction.followup.send(
            embed=obsidian_embed(
                "🍽️ Pet Fed",
                f"Your pet has been fed! Hunger: {hunger}/100{level_up_text}",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )
    
    command_decorator = group.command(name="care", description="Feed and play with your pet in one go (costs 15 coins).") if group else bot.tree.command(name="care", description="Feed and play with your pet in one go (costs 15 coins).")

    @command_decorator
    async def pet_care(interaction: discord.Interaction):
        """Batch action: feed + play with pet (costs 15 coins)."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        await interaction.response.defer()

        cost = 15
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)

        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins for pet care (feed + play). You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT p.hunger, p.happiness, p.experience, p.level, p.last_fed_at, p.last_played_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()

            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Pet",
                        "You don't have a pet! Use `/pets buy` to buy one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )

            hunger, happiness, exp, level, last_fed_at, last_played_at, created_at, max_level = row
            hunger = _apply_decay(hunger, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            happiness = _apply_decay(happiness, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)
            hunger = min(100, hunger + 20)
            happiness = min(100, happiness + 15)
            exp = exp + EXP_FEED + EXP_PLAY

            new_level = level
            while new_level < max_level and exp >= _exp_needed_for_level(new_level):
                exp -= _exp_needed_for_level(new_level)
                new_level += 1

            now_str = now_utc().isoformat()
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Pet care (feed + play)")
            await db.execute("""
                UPDATE pets SET hunger=?, happiness=?, experience=?, level=?, last_fed_at=?, last_played_at=?
                WHERE guild_id=? AND user_id=?
            """, (hunger, happiness, exp, new_level, now_str, now_str, interaction.guild.id, interaction.user.id))
            await db.commit()

        try:
            await _maybe_announce_stage_change(interaction, interaction.user.id, created_at)
        except Exception:
            pass

        if new_level >= 25 and level < 25:
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "pet_level_25", interaction.client, interaction=interaction)
            except Exception:
                pass
        level_up_text = f"\n🎉 **Level Up!** Your pet is now level {new_level}!" if new_level > level else ""
        await interaction.followup.send(
            embed=obsidian_embed(
                "🐾 Pet Cared For",
                f"Fed and played with your pet!\n**Hunger:** {hunger}/100 • **Happiness:** {happiness}/100{level_up_text}",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )

    command_decorator = group.command(name="play", description="Play with your pet (costs 5 coins).") if group else bot.tree.command(name="play", description="Play with your pet (costs 5 coins).")
    
    @command_decorator
    async def pet_play(interaction: discord.Interaction):
        """Play with pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        cost = 5
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"You need {cost} coins to play with your pet. You have {balance} coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT p.happiness, p.experience, p.level, p.last_played_at, p.created_at, pt.max_level
                FROM pets p
                JOIN pet_types pt ON p.pet_type = pt.pet_type
                WHERE p.guild_id=? AND p.user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Pet",
                        "You don't have a pet! Use `/pets buy` to buy one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            happiness, exp, level, last_played_at, created_at, max_level = row
            happiness = _apply_decay(happiness, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)
            happiness = min(100, happiness + 15)  # Increase happiness by 15
            exp = exp + EXP_PLAY  # Gain experience
            
            # Level-up logic (cap at max_level, carry over excess exp)
            new_level = level
            while new_level < max_level and exp >= _exp_needed_for_level(new_level):
                exp -= _exp_needed_for_level(new_level)
                new_level += 1
            
            await remove_coins(interaction.guild.id, interaction.user.id, cost, "PET", "Play with pet")
            await db.execute("""
                UPDATE pets SET happiness=?, experience=?, level=?, last_played_at=?
                WHERE guild_id=? AND user_id=?
            """, (happiness, exp, new_level, now_utc().isoformat(), interaction.guild.id, interaction.user.id))
            await db.commit()

        try:
            await _maybe_announce_stage_change(interaction, interaction.user.id, created_at)
        except Exception:
            pass

        if new_level >= 25 and level < 25:
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "pet_level_25", interaction.client, interaction=interaction)
            except Exception:
                pass
        level_up_text = f"\n🎉 **Level Up!** Your pet is now level {new_level}!" if new_level > level else ""

        await interaction.followup.send(
            embed=obsidian_embed(
                "🎮 Played with Pet",
                f"Your pet had fun! Happiness: {happiness}/100{level_up_text}",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )

    command_decorator = group.command(name="battle", description="Challenge another user's pet to a battle!") if group else bot.tree.command(name="battle", description="Challenge another user's pet to a battle!")

    @command_decorator
    @app_commands.describe(opponent="The user whose pet you want to challenge")
    async def pet_battle(interaction: discord.Interaction, opponent: discord.Member):
        """Challenge another user's pet to a battle."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        from core.utils import feature_enabled, feature_off_embed  # Item 85
        if not await feature_enabled(interaction.guild.id, "pets"):
            return await interaction.response.send_message(embed=feature_off_embed("Pets", client=interaction.client), ephemeral=True)
        if opponent.id == interaction.user.id:
            return await interaction.response.send_message("You can't battle your own pet!", ephemeral=True)
        if opponent.bot:
            return await interaction.response.send_message("You can't challenge a bot's pet!", ephemeral=True)

        await interaction.response.defer()

        async with aiosqlite.connect(DB_PATH) as db:
            # Check challenger has pet
            cur = await db.execute("""
                SELECT pet_name, pet_type, level, hunger, happiness, last_fed_at, last_played_at, created_at
                FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row1 = await cur.fetchone()
            if not row1:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ No Pet", "You need a pet to battle! Use `/pets buy` to get one.", color=discord.Color.red(), client=interaction.client),
                )
            # Check defender has pet
            cur = await db.execute("""
                SELECT pet_name FROM pets WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, opponent.id))
            if not await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ No Opponent Pet", f"{opponent.display_name} doesn't have a pet.", color=discord.Color.red(), client=interaction.client),
                )
            # Cooldown check
            now_str = now_utc().isoformat()
            cur = await db.execute(
                "SELECT last_battle_at FROM pet_battle_cooldowns WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            cd_row = await cur.fetchone()
            if cd_row:
                try:
                    last = dateparser.parse(cd_row[0], settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
                    if last:
                        mins = (datetime.now(timezone.utc) - last).total_seconds() / 60
                        if mins < BATTLE_COOLDOWN_MINUTES:
                            left = int(BATTLE_COOLDOWN_MINUTES - mins)
                            return await interaction.followup.send(
                                embed=obsidian_embed("⏳ Cooldown", f"You can battle again in {left} minutes.", color=discord.Color.orange(), client=interaction.client),
                            )
                except Exception:
                    pass

        n1, t1, lv1, h1, hp1, lf1, lp1, c1 = row1
        h1_eff = _apply_decay(h1, lf1, c1, HUNGER_DECAY_PER_HOUR)
        hp1_eff = _apply_decay(hp1, lp1, c1, HAPPINESS_DECAY_PER_HOUR)
        if h1_eff < MIN_HUNGER_TO_BATTLE or hp1_eff < MIN_HAPPINESS_TO_BATTLE:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🐾 Pet Too Tired",
                    f"Your pet needs at least {MIN_HUNGER_TO_BATTLE} hunger and {MIN_HAPPINESS_TO_BATTLE} happiness to battle. Feed and play with it first!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
            )

        view = PetBattleChallengeView(
            challenger_id=interaction.user.id,
            defender_id=opponent.id,
            guild_id=interaction.guild.id,
            challenger_name=interaction.user.display_name,
            defender_name=opponent.display_name,
        )
        embed = obsidian_embed(
            "⚔️ Pet Battle Challenge",
            f"**{interaction.user.display_name}** challenges **{opponent.display_name}** to a pet battle!\n\n"
            f"Challenger's pet: **{n1}** ({t1}) Lv.{lv1}\n\n"
            f"{opponent.display_name}, click **Accept** to fight or **Decline** to back out.",
            color=discord.Color.gold(),
            client=interaction.client,
        )
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    # Pet evolve
    command_decorator = group.command(name="evolve", description="Evolve your pet when it reaches the required level.") if group else bot.tree.command(name="evolve", description="Evolve your pet when it reaches the required level.")
    @command_decorator
    async def pet_evolve(interaction: discord.Interaction):
        """Evolve pet to next tier."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT p.id, p.pet_name, p.pet_type, p.level, p.experience, p.evolution_tier
                FROM pets p WHERE p.guild_id=? AND p.user_id=?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ No Pet", "You don't have a pet.", color=discord.Color.red(), client=interaction.client),
                )
            pet_id, pet_name, pet_type, level, exp, evo_tier = row
            evo_tier = evo_tier or 0
            if evo_tier >= 1:
                return await interaction.followup.send(
                    embed=obsidian_embed("✅ Already Evolved", "Your pet has already evolved!", color=discord.Color.blue(), client=interaction.client),
                )
            cur = await db.execute("SELECT evolved_type, required_level FROM pet_evolutions WHERE base_type=?", (pet_type,))
            evo_row = await cur.fetchone()
            if not evo_row:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Cannot Evolve", f"{pet_type} cannot evolve.", color=discord.Color.red(), client=interaction.client),
                )
            evolved_type, req_level = evo_row
            if level < req_level:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Level Too Low", f"Your pet needs level {req_level} to evolve into {evolved_type}. Current: {level}.", color=discord.Color.red(), client=interaction.client),
                )
            await db.execute(
                "UPDATE pets SET pet_type=?, evolution_tier=1 WHERE id=?",
                (evolved_type, pet_id),
            )
            await db.commit()
            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "pet_evolved", interaction.client, interaction=interaction)
            except Exception:
                pass
        await interaction.followup.send(
            embed=obsidian_embed(
                "✨ Pet Evolved!",
                f"**{pet_name}** evolved from {pet_type} to **{evolved_type}**!",
                color=discord.Color.gold(),
                client=interaction.client,
            ),
        )

    # Pet list (for sale)
    command_decorator = group.command(name="list", description="List your pet for sale on the marketplace.") if group else bot.tree.command(name="list", description="List your pet for sale on the marketplace.")
    @command_decorator
    @app_commands.describe(price="Asking price in coins")
    async def pet_list(interaction: discord.Interaction, price: int):
        """List pet for sale."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        if price < 1:
            return await interaction.response.send_message("Price must be at least 1 coin.", ephemeral=True)
        await interaction.response.defer()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT id, pet_name, pet_type, level FROM pets WHERE guild_id=? AND user_id=?", (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            if not row:
                return await interaction.followup.send(embed=obsidian_embed("❌ No Pet", "You don't have a pet.", color=discord.Color.red(), client=interaction.client))
            pet_id, pet_name, pet_type, level = row
            cur = await db.execute("SELECT 1 FROM pet_listings WHERE pet_id=?", (pet_id,))
            if await cur.fetchone():
                return await interaction.followup.send(embed=obsidian_embed("❌ Already Listed", "Your pet is already listed.", color=discord.Color.orange(), client=interaction.client))
            await db.execute(
                "INSERT INTO pet_listings (guild_id, pet_id, seller_id, price, listed_at) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, pet_id, interaction.user.id, price, now_utc().isoformat()),
            )
            await db.commit()
        await interaction.followup.send(
            embed=obsidian_embed("✅ Pet Listed", f"**{pet_name}** ({pet_type}) Lv.{level} listed for {price:,} coins. Use `/pets marketplace` to browse.", color=discord.Color.green(), client=interaction.client),
        )

    # Pet marketplace (browse and buy)
    command_decorator = group.command(name="marketplace", description="Browse and buy pets listed for sale.") if group else bot.tree.command(name="marketplace", description="Browse and buy pets listed for sale.")
    @command_decorator
    async def pet_marketplace(interaction: discord.Interaction):
        """Browse pet marketplace."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pl.id, pl.pet_id, pl.seller_id, pl.price, p.pet_name, p.pet_type, p.level
                FROM pet_listings pl
                JOIN pets p ON pl.pet_id = p.id
                WHERE pl.guild_id=? AND p.guild_id=?
                ORDER BY pl.listed_at DESC
                LIMIT 20
            """, (interaction.guild.id, interaction.guild.id))
            rows = await cur.fetchall()
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed("📦 Pet Marketplace", "No pets are listed for sale. Use `/pets list` to list yours!", color=discord.Color.blue(), client=interaction.client),
            )
        fields = []
        for listing_id, pet_id, seller_id, price, pet_name, pet_type, level in rows:
            seller = interaction.guild.get_member(seller_id)
            seller_name = seller.display_name if seller else f"User {seller_id}"
            fields.append((f"#{listing_id} {pet_name} ({pet_type}) Lv.{level}", f"💰 {price:,} coins\n👤 Seller: {seller_name}\n`/pets buy_listed {listing_id}`", True))
        await interaction.followup.send(
            embed=obsidian_embed("📦 Pet Marketplace", "Pets for sale. Use `/pets buy_listed listing_id:N` to purchase.", color=discord.Color.gold(), fields=fields, client=interaction.client),
        )

    # Pet buy listed
    command_decorator = group.command(name="buy_listed", description="Buy a pet from the marketplace.") if group else bot.tree.command(name="buy_listed", description="Buy a pet from the marketplace.")
    @command_decorator
    @app_commands.describe(listing_id="The listing ID from /pets marketplace")
    async def pet_buy_listed(interaction: discord.Interaction, listing_id: int):
        """Buy a listed pet."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT pl.id, pl.pet_id, pl.seller_id, pl.price, p.pet_name, p.pet_type, p.level
                FROM pet_listings pl
                JOIN pets p ON pl.pet_id = p.id
                WHERE pl.guild_id=? AND pl.id=?
            """, (interaction.guild.id, listing_id))
            row = await cur.fetchone()
            if not row:
                return await interaction.followup.send(embed=obsidian_embed("❌ Not Found", "Listing not found.", color=discord.Color.red(), client=interaction.client))
            _, pet_id, seller_id, price, pet_name, pet_type, level = row
            if seller_id == interaction.user.id:
                return await interaction.followup.send(embed=obsidian_embed("❌ Can't Buy", "You can't buy your own pet.", color=discord.Color.red(), client=interaction.client))
            if balance < price:
                return await interaction.followup.send(embed=obsidian_embed("❌ Insufficient Funds", f"You need {price:,} coins. You have {balance:,}.", color=discord.Color.red(), client=interaction.client))
            cur = await db.execute("SELECT 1 FROM pets WHERE guild_id=? AND user_id=?", (interaction.guild.id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.followup.send(embed=obsidian_embed("❌ Already Have Pet", "You must not have a pet to buy one. Use `/pet_list` to sell yours first.", color=discord.Color.red(), client=interaction.client))
            await remove_coins(interaction.guild.id, interaction.user.id, price, "PET_TRADE", f"Bought {pet_name} from marketplace")
            await add_coins(interaction.guild.id, seller_id, price, "PET_TRADE", f"Sold {pet_name}")
            await db.execute("UPDATE pets SET user_id=? WHERE id=?", (interaction.user.id, pet_id))
            await db.execute("DELETE FROM pet_listings WHERE id=?", (listing_id,))
            await db.commit()
        await interaction.followup.send(
            embed=obsidian_embed("✅ Pet Purchased", f"You bought **{pet_name}** ({pet_type}) Lv.{level} for {price:,} coins!", color=discord.Color.green(), client=interaction.client),
        )

    # ------------------------------------------------------------------
    # Item 75 — Pet gifting (two-step confirm + recipient accept/decline)
    # ------------------------------------------------------------------
    command_decorator = group.command(
        name="gift",
        description="Gift your pet to another member (they must accept within 24h)."
    ) if group else bot.tree.command(name="gift", description="Gift your pet to another member.")

    @command_decorator
    @app_commands.describe(recipient="Who should receive your pet?")
    async def pet_gift(interaction: discord.Interaction, recipient: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Server only.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        if recipient.bot or recipient.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Recipient", "You can't gift a pet to yourself or a bot.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id, pet_name, pet_type, level FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            mine = await cur.fetchone()
            if not mine:
                return await interaction.response.send_message(
                    embed=obsidian_embed("❌ No Pet", "You don't own a pet to gift.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True,
                )
            cur = await db.execute(
                "SELECT 1 FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, recipient.id),
            )
            if await cur.fetchone():
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Recipient Already Has a Pet",
                        f"{recipient.display_name} already has a pet. They must release theirs (`/pets abandon`) before they can accept a gifted one.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            cur = await db.execute(
                "SELECT 1 FROM pet_listings WHERE pet_id=?",
                (mine[0],),
            )
            if await cur.fetchone():
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Pet Is Listed",
                        "Unlist your pet from the marketplace before gifting it.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )

        pet_id, pet_name, pet_type, pet_level = mine
        preview = obsidian_embed(
            "🎁 Confirm Gift",
            f"Gift **{pet_name}** ({pet_type}) Lv.{pet_level} to {recipient.mention}?\n\n"
            "They will receive a DM (or fall back to a server ping) and must accept within **24 hours**.",
            color=discord.Color.gold(),
            thumbnail=PET_ICONS.get(pet_type, DEFAULT_PET_ICON),
            client=interaction.client,
        )

        async def on_giver_confirm(btn_inter: discord.Interaction, confirmed: bool):
            if btn_inter.user.id != interaction.user.id:
                try:
                    await btn_inter.response.send_message("Only the gifter can confirm.", ephemeral=True)
                except Exception:
                    pass
                return
            if not confirmed:
                try:
                    await btn_inter.followup.send("Gift cancelled.", ephemeral=True)
                except Exception:
                    pass
                return
            await _send_pet_gift_offer(
                btn_inter, interaction.guild, interaction.user, recipient,
                pet_id, pet_name, pet_type, pet_level,
            )

        view = ConfirmView(on_giver_confirm)
        await interaction.response.send_message(embed=preview, view=view, ephemeral=True)

    command_decorator = group.command(
        name="care_all",
        description="Feed and play with all of your pets in one go (costs 15 coins)."
    ) if group else bot.tree.command(name="care_all", description="Feed and play with all of your pets in one go.")

    @command_decorator
    async def pet_care_all(interaction: discord.Interaction):
        """Item 77 — batch care. Single-pet schema means this is functionally
        identical to `/pets care`, but presents a per-pet summary."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Server only.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()

        cost = 15
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        if balance < cost:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Funds",
                    f"Caring for all pets costs **{cost} coins**. You have **{balance:,}**.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )

        results, total_cost = await _care_all_user_pets(
            interaction.guild.id, interaction.user.id, cost,
        )
        if not results:
            return await interaction.followup.send(
                embed=obsidian_embed("❌ No Pets", "You don't own any pets yet. Use `/pets buy` to get one!", color=discord.Color.red(), client=interaction.client),
            )

        bullet_lines: list[str] = []
        for r in results:
            line = (
                f"• **{r['pet_name']}** ({r['pet_type']}) — "
                f"Fed (+{r['hunger_delta']} hunger), Played (+{r['happiness_delta']} happiness)"
            )
            if r["leveled_up"]:
                line += f" · 🎉 Lv.{r['old_level']}→**Lv.{r['new_level']}**"
            bullet_lines.append(line)

        await interaction.followup.send(
            embed=obsidian_embed(
                "🐾 Pet Care Complete",
                "\n".join(bullet_lines) + f"\n\n**Cost:** {total_cost:,} coins",
                color=discord.Color.green(),
                client=interaction.client,
            )
        )


# ---------------------------------------------------------------------------
# Helpers shared by Item 75 (gift) and Item 77 (care_all)
# ---------------------------------------------------------------------------
class _PetGiftAcceptView(discord.ui.View):
    """Recipient-side Accept/Decline view for Item 75 pet gifting.

    Persistent-friendly: uses `timeout=24h` so a stale DM expires; the
    actual ownership swap happens on the Accept callback.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        giver_id: int,
        recipient_id: int,
        pet_id: int,
        pet_name: str,
        pet_type: str,
        pet_level: int,
    ):
        super().__init__(timeout=24 * 3600)
        self.guild_id = guild_id
        self.giver_id = giver_id
        self.recipient_id = recipient_id
        self.pet_id = pet_id
        self.pet_name = pet_name
        self.pet_type = pet_type
        self.pet_level = pet_level
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.recipient_id:
            try:
                await interaction.response.send_message(
                    "Only the gift recipient can use these buttons.", ephemeral=True,
                )
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return await interaction.response.send_message("This gift was already resolved.", ephemeral=True)
        self.resolved = True
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM pets WHERE id=? AND guild_id=?",
                (self.pet_id, self.guild_id),
            )
            row = await cur.fetchone()
            if not row or int(row[0]) != self.giver_id:
                try:
                    await interaction.followup.send("Sorry — this pet is no longer available to gift.", ephemeral=True)
                except Exception:
                    pass
                return
            cur = await db.execute(
                "SELECT 1 FROM pets WHERE guild_id=? AND user_id=?",
                (self.guild_id, self.recipient_id),
            )
            if await cur.fetchone():
                try:
                    await interaction.followup.send(
                        "You already have a pet — release it first if you want to accept this gift.",
                        ephemeral=True,
                    )
                except Exception:
                    pass
                return
            await db.execute(
                "UPDATE pets SET user_id=? WHERE id=?",
                (self.recipient_id, self.pet_id),
            )
            now_iso = now_utc().isoformat()
            desc = f"Gifted {self.pet_name} ({self.pet_type}) Lv.{self.pet_level} to user {self.recipient_id}"
            await db.execute(
                "INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at) "
                "VALUES (?, ?, 0, 'PET_GIFT', ?, ?)",
                (self.guild_id, self.giver_id, desc, now_iso),
            )
            await db.execute(
                "INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at) "
                "VALUES (?, ?, 0, 'PET_GIFT', ?, ?)",
                (self.guild_id, self.recipient_id, f"Received {self.pet_name} ({self.pet_type}) from user {self.giver_id}", now_iso),
            )
            await db.commit()

        try:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "🎉 Pet Accepted",
                    f"**{self.pet_name}** ({self.pet_type}) is now yours! Use `/pets view` to say hi.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        except Exception:
            pass

        try:
            giver = interaction.client.get_user(self.giver_id) or await interaction.client.fetch_user(self.giver_id)
            if giver:
                await giver.send(
                    embed=obsidian_embed(
                        "🎁 Gift Accepted",
                        f"<@{self.recipient_id}> accepted **{self.pet_name}**. Take care, parting is hard!",
                        color=discord.Color.green(),
                        client=interaction.client,
                    )
                )
        except Exception:
            pass

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, emoji="✖")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return await interaction.response.send_message("Already resolved.", ephemeral=True)
        self.resolved = True
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        try:
            giver = interaction.client.get_user(self.giver_id) or await interaction.client.fetch_user(self.giver_id)
            if giver:
                await giver.send(
                    embed=obsidian_embed(
                        "💔 Gift Declined",
                        f"<@{self.recipient_id}> declined **{self.pet_name}**. Your pet stays with you.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    )
                )
        except Exception:
            pass

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True


async def _send_pet_gift_offer(
    btn_interaction: discord.Interaction,
    guild: discord.Guild,
    giver: discord.abc.User,
    recipient: discord.Member,
    pet_id: int,
    pet_name: str,
    pet_type: str,
    pet_level: int,
) -> None:
    """Send the recipient an Accept/Decline offer (DM first, in-channel fallback)."""
    offer_embed = obsidian_embed(
        "🎁 You've received a pet gift!",
        f"**{giver.display_name}** wants to gift you **{pet_name}** "
        f"({pet_type}) Lv.{pet_level} in **{guild.name}**.\n\n"
        "Tap **Accept** within 24 hours to take ownership, or **Decline** to refuse.",
        color=discord.Color.gold(),
        thumbnail=PET_ICONS.get(pet_type, DEFAULT_PET_ICON),
        client=btn_interaction.client,
    )
    view = _PetGiftAcceptView(
        guild_id=guild.id,
        giver_id=giver.id,
        recipient_id=recipient.id,
        pet_id=pet_id,
        pet_name=pet_name,
        pet_type=pet_type,
        pet_level=pet_level,
    )
    delivered = False
    try:
        await recipient.send(embed=offer_embed, view=view)
        delivered = True
    except (discord.Forbidden, discord.HTTPException):
        delivered = False

    if delivered:
        try:
            await btn_interaction.followup.send(
                embed=obsidian_embed(
                    "📬 Gift Sent",
                    f"Sent a gift offer to {recipient.mention} — they have 24 hours to accept.",
                    color=discord.Color.green(),
                    client=btn_interaction.client,
                ),
                ephemeral=True,
            )
        except Exception:
            pass
        return

    try:
        ch = btn_interaction.channel if hasattr(btn_interaction, "channel") else None
        if isinstance(ch, discord.TextChannel):
            await ch.send(
                content=recipient.mention,
                embed=offer_embed,
                view=view,
            )
            await btn_interaction.followup.send(
                "Couldn't DM them — posted the offer in this channel instead.",
                ephemeral=True,
            )
            return
    except Exception:
        pass
    try:
        await btn_interaction.followup.send(
            embed=obsidian_embed(
                "❌ Couldn't Deliver Gift",
                f"{recipient.mention} has DMs disabled and I couldn't post here either. Try again from a channel I can post in.",
                color=discord.Color.red(),
                client=btn_interaction.client,
            ),
            ephemeral=True,
        )
    except Exception:
        pass


async def _care_all_user_pets(guild_id: int, user_id: int, cost: int) -> tuple[list[dict], int]:
    """Apply feed+play to every pet owned by `user_id` in `guild_id`.

    Single-pet-per-user schema today, but written as a loop so the helper
    keeps working if multi-pet ownership lands later. Returns
    `(per_pet_results, total_cost_charged)`.
    """
    HUNGER_GAIN = 20
    HAPPINESS_GAIN = 15

    results: list[dict] = []
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT p.id, p.pet_name, p.pet_type, p.hunger, p.happiness, p.experience, p.level,
                   p.last_fed_at, p.last_played_at, p.created_at, pt.max_level
            FROM pets p
            JOIN pet_types pt ON p.pet_type = pt.pet_type
            WHERE p.guild_id=? AND p.user_id=?
        """, (guild_id, user_id))
        rows = await cur.fetchall()
        if not rows:
            return [], 0

        await remove_coins(guild_id, user_id, cost, "PET", "Care-all (feed + play)")
        now_str = now_utc().isoformat()

        for row in rows:
            pet_id, pet_name, pet_type, hunger, happiness, exp, level, last_fed, last_played, created_at, max_level = row
            hunger_eff = _apply_decay(hunger, last_fed, created_at, HUNGER_DECAY_PER_HOUR)
            happiness_eff = _apply_decay(happiness, last_played, created_at, HAPPINESS_DECAY_PER_HOUR)
            new_hunger = min(100, hunger_eff + HUNGER_GAIN)
            new_happiness = min(100, happiness_eff + HAPPINESS_GAIN)
            hunger_delta = new_hunger - hunger_eff
            happiness_delta = new_happiness - happiness_eff
            new_exp = exp + EXP_FEED + EXP_PLAY
            new_level = level
            while new_level < max_level and new_exp >= _exp_needed_for_level(new_level):
                new_exp -= _exp_needed_for_level(new_level)
                new_level += 1
            await db.execute(
                "UPDATE pets SET hunger=?, happiness=?, experience=?, level=?, "
                "last_fed_at=?, last_played_at=? WHERE id=?",
                (new_hunger, new_happiness, new_exp, new_level, now_str, now_str, pet_id),
            )
            results.append({
                "pet_id": pet_id,
                "pet_name": pet_name,
                "pet_type": pet_type,
                "hunger_delta": hunger_delta,
                "happiness_delta": happiness_delta,
                "old_level": level,
                "new_level": new_level,
                "leveled_up": new_level > level,
            })
        await db.commit()
    return results, cost
