"""Warframe trivia command — answer questions, earn coins."""
import random
import time
from typing import Optional

import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS, format_number, ECONOMY_ENABLED
from database import add_coins, get_guild_setting, set_guild_setting

# Cooldown in seconds (4 hours)
_TRIVIA_COOLDOWN = 4 * 3600

# ── Question bank ────────────────────────────────────────────────────────────
# Format: (question, [A, B, C, D], correct_index 0-3, difficulty, fun_fact)
# difficulty: "easy" | "medium" | "hard"

_QUESTIONS = [
    # ── Warframes ──────────────────────────────────────────────────────────
    (
        "Which Warframe is known as the 'Goddess of War' and is the starting frame for many players?",
        ["Excalibur", "Volt", "Mag", "Ember"],
        0, "easy",
        "Excalibur is often considered the 'starter' Warframe and is balanced for all playstyles.",
    ),
    (
        "What is the name of Warframe's prime version of Excalibur available only to founders?",
        ["Excalibur Umbra", "Excalibur Prime", "Excalibur Jade", "Excalibur Unbound"],
        1, "medium",
        "Excalibur Prime was a founders-exclusive reward and is one of the rarest items in the game.",
    ),
    (
        "Which Warframe has the ability 'Wormhole', allowing teleportation?",
        ["Nova", "Ash", "Loki", "Vauban"],
        0, "medium",
        "Nova's Wormhole creates a portal that lets the whole squad teleport across the map.",
    ),
    (
        "Which Warframe can turn invisible using their second ability 'Invisibility'?",
        ["Ash", "Loki", "Ivara", "Octavia"],
        1, "easy",
        "Loki's Invisibility is one of the most iconic stealth tools in Warframe.",
    ),
    (
        "Mesa's 'Peacemaker' ability is analogous to which real-world gunslinger archetype?",
        ["Viking", "Samurai", "Gunslinger / Cowboy", "Ninja"],
        2, "easy",
        "Mesa's entire design is built around the Wild West gunslinger aesthetic.",
    ),
    (
        "Which Warframe's passive lets them revive fallen allies without going down?",
        ["Trinity", "Wisp", "Oberon", "Nidus"],
        0, "medium",
        "Trinity's passive lets her channel energy into a healing well when teammates are downed.",
    ),
    (
        "Nekros' 'Desecrate' ability causes enemies to drop extra loot. What type of frame is Nekros?",
        ["Tank", "Damage", "Support / Loot", "Stealth"],
        2, "easy",
        "Nekros is the premier loot-farming frame, paired with 'Pilfering Swarm' Hydroid for double-loot.",
    ),
    (
        "Which Warframe is built using components obtained from the Sacrifice quest?",
        ["Harrow", "Octavia", "Gara", "Excalibur Umbra"],
        3, "medium",
        "The Sacrifice quest is one of the most story-rich quests in Warframe and rewards Excalibur Umbra.",
    ),
    (
        "What is the name of the void entity that possesses Warframes and is controlled by the player?",
        ["Cephalon", "Operator", "Sentient", "Corpus"],
        1, "easy",
        "The Operator is revealed during The Second Dream quest — a major story twist.",
    ),
    (
        "Which Warframe has the ability 'Spellbind' that causes enemies to float helplessly?",
        ["Titania", "Zephyr", "Gara", "Khora"],
        0, "medium",
        "Titania is a fairy-themed Warframe whose Spellbind makes enemies drift into the air.",
    ),
    (
        "Hydroid's rework gave him a unique passive. What does it do?",
        ["Auto-revive teammates", "Generate energy on kill", "Extra loot from enemies under Undertow", "Shield gating on damage"],
        2, "hard",
        "After his rework, Hydroid's Undertow directly causes enemies to drop extra loot, replacing Nekros in many farming builds.",
    ),
    (
        "Which Warframe is obtained by defeating the Ropalolyst boss fight?",
        ["Wisp", "Baruuk", "Hildryn", "Gauss"],
        0, "medium",
        "Wisp's main blueprint drops from the Ropalolyst on Jupiter.",
    ),
    (
        "Nidus has a unique mechanic called 'Mutation Stacks'. What is the maximum number of stacks?",
        ["50", "100", "150", "200"],
        1, "hard",
        "Nidus can stack up to 100 Mutation stacks, powering up abilities and granting pseudo-immortality.",
    ),
    (
        "What is the name of the quest that introduces the Drifter character?",
        ["The New War", "Angels of the Zariman", "Whispers in the Walls", "The Sacrifice"],
        0, "medium",
        "The New War is a massive cinematic quest that introduces the Drifter as a playable character.",
    ),
    (
        "Which Warframe can wall-latch indefinitely without any mods?",
        ["Ash", "Zephyr", "Inaros", "Wukong"],
        1, "hard",
        "Zephyr's passive grants greatly reduced gravity and the ability to cling to walls indefinitely.",
    ),

    # ── Weapons ────────────────────────────────────────────────────────────
    (
        "What is the name of Excalibur's signature exalted blade weapon?",
        ["Skana Prime", "Exalted Blade", "Broken Scepter", "Skiajati"],
        1, "easy",
        "Exalted Blade is summoned by Excalibur's 4th ability and fires energy waves at higher combo.",
    ),
    (
        "The Ignis Wraith is a popular weapon. What damage type does it primarily deal?",
        ["Cold", "Electricity", "Heat / Fire", "Toxin"],
        2, "easy",
        "The Ignis Wraith is a flame thrower that deals Heat damage, excellent for stripping armour.",
    ),
    (
        "Which sniper rifle is known for its extreme critical chance and the 'Punch Through' inherent?",
        ["Rubico Prime", "Vectis Prime", "Lanka", "Snipetron Vandal"],
        0, "medium",
        "Rubico Prime has one of the highest critical multipliers among snipers and is a staple for Eidolon hunts.",
    ),
    (
        "What is the name of the Corpus laser rifle obtained from Baro Ki'Teer?",
        ["Quanta", "Dera Vandal", "Supra Vandal", "Convectrix"],
        2, "medium",
        "Supra Vandal is a Baro exclusive, upgraded version of the Supra with better stats.",
    ),
    (
        "The Orthos Prime is a type of which melee weapon category?",
        ["Sword", "Staff / Polearm", "Hammer", "Dual Swords"],
        1, "easy",
        "The Orthos Prime is a polearm with wide sweeping attacks, great for clearing groups.",
    ),
    (
        "Which Zaw strike is used to craft the popular Zaw known as 'Dokrahm'?",
        ["Plague Keewar", "Balla", "Dokrahm", "Cyath"],
        2, "medium",
        "Dokrahm is a Zaw strike that creates a heavy scythe — a favourite for melee builds.",
    ),
    (
        "The Acceltra is the signature weapon of which Warframe?",
        ["Gauss", "Volt", "Octavia", "Wisp"],
        0, "medium",
        "Gauss and the Acceltra are both speed-themed — the rocket rifle pairs perfectly with the frame.",
    ),
    (
        "What is the riven disposition scale range in Warframe?",
        ["1 to 3", "1 to 5", "0.5 to 2", "1 to 10"],
        1, "hard",
        "Riven dispositions run from 1 (weakest, popular weapons) to 5 (strongest, obscure weapons).",
    ),

    # ── Factions & Lore ────────────────────────────────────────────────────
    (
        "What is the name of the ancient enemy that drained the Orokin of their power during the Orokin Era?",
        ["Grineer", "Infested", "Sentients", "Corpus"],
        2, "easy",
        "Sentients were created by the Orokin to terraform the Tau system, but they turned against their makers.",
    ),
    (
        "Which faction is known for their profit-driven philosophy and use of robots and proxies?",
        ["Grineer", "Corpus", "Infested", "Ostron"],
        1, "easy",
        "The Corpus are a mega-corporation who worship profit, using robotic proxies to avoid human casualties.",
    ),
    (
        "What is the Tenno's primary base of operations called?",
        ["Relay", "Orbiter", "Liset", "Dojo"],
        1, "easy",
        "The Orbiter is the Tenno's personal ship, navigated by Ordis the Cephalon.",
    ),
    (
        "Who is the Cephalon that assists the Tenno aboard the Orbiter?",
        ["Simaris", "Suda", "Ordis", "Samodeus"],
        2, "easy",
        "Ordis is a quirky, slightly unstable Cephalon who serves as your ship's AI.",
    ),
    (
        "The Quills are a Cetus-based syndicate. What do they primarily deal in?",
        ["Eidolon shards", "Gems", "Standing", "Amp blueprints"],
        0, "medium",
        "Quills rank up using Eidolon shards earned from Teralyst hunts on the Plains of Eidolon.",
    ),
    (
        "What is the name of the Orokin tower that can be found in the Void?",
        ["Orokin Derelict", "Tower", "Sanctuary", "Entrati Lab"],
        1, "medium",
        "Orokin Towers in the Void are ancient structures rich in rare resources and Void relics.",
    ),
    (
        "The Zariman Ten Zero was a ship carrying colonists and Tenno children. What happened to it?",
        ["It crashed on Earth", "It passed through the Void", "It was destroyed by Sentients", "It docked at Cetus"],
        1, "hard",
        "The Zariman passed through a Void anomaly, killing all adults but granting the children Void powers — the origin of the Tenno.",
    ),
    (
        "Which syndicate is dedicated to hunting and cataloguing Warframe abilities?",
        ["Red Veil", "Arbiters of Hexis", "Cephalon Simaris", "Steel Meridian"],
        2, "medium",
        "Cephalon Simaris operates the Sanctuary and sends Tenno on Synthesis missions to scan targets.",
    ),
    (
        "Duviri is a realm ruled by which emotional entity?",
        ["Praghasa", "Dominus Thrax", "Orowyrm", "The Drifter"],
        1, "medium",
        "Dominus Thrax is a childlike tyrant whose emotions shape the ever-changing Duviri landscape.",
    ),
    (
        "The Entrati family resides in which open world zone?",
        ["Cetus", "Fortuna", "Deimos", "Zariman"],
        2, "medium",
        "The Entrati are a partially Infested Orokin family living on Deimos — the Cambion Drift.",
    ),

    # ── Game Mechanics ─────────────────────────────────────────────────────
    (
        "What is the maximum rank (Mastery Rank) a player can achieve in Warframe?",
        ["30", "35", "40", "50"],
        2, "medium",
        "Mastery Rank 40 is the current cap, requiring players to master a huge number of items and challenges.",
    ),
    (
        "What are Void Relics used for in Warframe?",
        ["Crafting Warframes", "Unlocking Prime parts", "Trading with NPCs", "Ranking up Syndicates"],
        1, "easy",
        "Void Relics are opened in Void Fissure missions to unlock Prime Warframe parts and weapons.",
    ),
    (
        "What resource is required to build a Dojo room?",
        ["Credits", "Orokin Cells", "Credits and Resources", "Platinum"],
        2, "easy",
        "Dojo rooms require Credits along with various crafting resources depending on the room type.",
    ),
    (
        "What is 'Condition Overload' in Warframe?",
        ["A gun mod that buffs reload speed", "A melee mod that boosts damage per status on the target", "A passive ability of Valkyr", "An Arcane that triggers on status"],
        1, "medium",
        "Condition Overload is one of the most powerful melee mods — each unique status on the enemy multiplies melee damage.",
    ),
    (
        "In Warframe, what does 'SP' commonly stand for in the community?",
        ["Special Power", "Steel Path", "Secondary Pistol", "Sentinel Passive"],
        1, "easy",
        "Steel Path is the endgame difficulty mode that adds +100 to enemy levels across all missions.",
    ),
    (
        "What is the primary currency used for trading between players?",
        ["Credits", "Ducats", "Platinum", "Aya"],
        2, "easy",
        "Platinum is Warframe's premium currency, but players can earn it by selling items to other players.",
    ),
    (
        "Which game mode has players defending excavation drills for power cells?",
        ["Survival", "Interception", "Excavation", "Mobile Defense"],
        2, "easy",
        "Excavation missions require players to run Excavators to dig up rare resources, powered by energy cells dropped by enemies.",
    ),
    (
        "What does 'forma' do when applied to a Warframe or weapon?",
        ["Increases max rank by 10", "Adds a polarity slot and resets rank to 0", "Unlocks a new ability", "Grants bonus Mastery XP"],
        1, "easy",
        "Forma adds or changes a polarity on any mod slot, allowing more powerful mods at lower drain — at the cost of resetting the item.",
    ),
    (
        "What is the name of Warframe's PvP mode?",
        ["Conclave", "Tribunal", "Rift", "Clash"],
        0, "medium",
        "Conclave is Warframe's PvP mode — it's not popular, but has unique mods obtainable only there.",
    ),
    (
        "What is an 'Arcane Enhancement' in Warframe?",
        ["A mod for Companions", "A passive buff applied to a Warframe or weapon via special slots", "A type of Riven mod", "An Operator ability"],
        1, "medium",
        "Arcane Enhancements go into dedicated Arcane slots and provide unique conditional bonuses.",
    ),
    (
        "Which open-world zone was the first added to Warframe?",
        ["Fortuna (Orb Vallis)", "Cambion Drift (Deimos)", "Plains of Eidolon", "Duviri Paradox"],
        2, "easy",
        "Plains of Eidolon launched in 2017, introducing open-world gameplay and Eidolon hunts to Warframe.",
    ),
    (
        "Baro Ki'Teer visits Relays every two weeks. What currency does he accept?",
        ["Credits only", "Ducats and Credits", "Platinum", "Standing"],
        1, "easy",
        "Baro accepts Ducats (converted from Prime parts) and Credits. Ducats can only be traded at Ducat kiosks in Relays.",
    ),
    (
        "What is the name of Warframe's player-vs-environment game mode where you fight increasingly difficult enemies?",
        ["Arbitrations", "Nightwave", "The Circuit", "Disruption"],
        0, "hard",
        "Arbitrations are elite alert missions with a single revive limit, rewarding exclusive mods and Ayatan sculptures.",
    ),
    (
        "What weekly content system replaced the Alert system and introduced a seasonal story?",
        ["Syndicate Missions", "Nightwave", "Steel Path", "The Circuit"],
        1, "medium",
        "Nightwave replaced the old Alert system with an episodic story-driven challenge system offering unique rewards.",
    ),
    (
        "What is the maximum number of Warframe slots available by default (without purchase)?",
        ["1", "2", "3", "5"],
        2, "hard",
        "New accounts start with 3 Warframe slots. Additional slots must be purchased with Platinum.",
    ),

    # ── Eidolons & Bosses ──────────────────────────────────────────────────
    (
        "What is the weakest of the three Eidolon types on the Plains of Eidolon?",
        ["Gantulyst", "Teralyst", "Hydrolyst", "Profit-Taker"],
        1, "easy",
        "The Teralyst is the first and weakest Eidolon — defeating it is required to summon the Gantulyst.",
    ),
    (
        "The Profit-Taker Orb is a boss fight located on which open-world map?",
        ["Plains of Eidolon", "Cambion Drift", "Orb Vallis", "Duviri"],
        2, "medium",
        "Profit-Taker is a massive Corpus spider-mech on Orb Vallis that requires hitting rotating elemental weaknesses.",
    ),
    (
        "Which weapon type is most effective at destroying Eidolon Synovias?",
        ["Shotgun", "Sniper Rifle", "Melee", "Pistol"],
        1, "medium",
        "Eidolon Synovias are weak to Void damage; sniper rifles with Void amp support from the Operator deal the most damage.",
    ),

    # ── Companions ─────────────────────────────────────────────────────────
    (
        "Kubrows are a type of companion. Which Kubrow breed passively generates loot?",
        ["Raksa", "Huras", "Sahasa", "Chesa"],
        3, "hard",
        "Chesa Kubrow will automatically retrieve loot from nearby enemies, making it a passive farming companion.",
    ),
    (
        "What is the name of the Sentient-type companion introduced in The New War?",
        ["Kavat", "Helminth Charger", "Hound", "Predasite"],
        2, "hard",
        "Hounds are Corpus-made Sentient-style companions that Tenno can craft using Parvos Granum's designs.",
    ),
    (
        "Sentinels are robotic companions. Which Sentinel is known for reviving its owner once per mission?",
        ["Wyrm", "Carrier", "Dethcube", "Taxon"],
        1, "medium",
        "Carrier is a popular Sentinel due to its Ammo Case precept, but Taxon and Guardian Sentinel mods can also revive.",
    ),
]

# Coin rewards by difficulty
_REWARDS = {
    "easy":   (50,  150),
    "medium": (150, 350),
    "hard":   (350, 750),
}

_DIFFICULTY_EMOJI = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
_ANSWER_LABELS = ["🇦", "🇧", "🇨", "🇩"]


# ── UI ───────────────────────────────────────────────────────────────────────

class TriviaView(discord.ui.View):
    """Four answer buttons for a trivia question."""

    def __init__(
        self,
        question: str,
        choices: list[str],
        correct: int,
        difficulty: str,
        fact: str,
        coin_reward: int,
        interaction_user: discord.User | discord.Member,
    ):
        super().__init__(timeout=30)
        self.question = question
        self.choices = choices
        self.correct = correct
        self.difficulty = difficulty
        self.fact = fact
        self.coin_reward = coin_reward
        self.interaction_user = interaction_user
        self.answered = False

        for i, choice in enumerate(choices):
            btn = discord.ui.Button(
                label=f"{_ANSWER_LABELS[i]} {choice}",
                style=discord.ButtonStyle.secondary,
                custom_id=str(i),
                row=i // 2,
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.interaction_user.id:
                return await interaction.response.send_message(
                    "This trivia isn't for you!", ephemeral=True
                )
            if self.answered:
                return await interaction.response.send_message(
                    "You've already answered!", ephemeral=True
                )
            self.answered = True
            self.stop()

            correct = index == self.correct
            reward = self.coin_reward if correct else 0
            emoji = "✅" if correct else "❌"
            diff_emoji = _DIFFICULTY_EMOJI[self.difficulty]
            color = "success" if correct else "error"

            if correct and interaction.guild:
                await add_coins(
                    interaction.guild.id,
                    interaction.user.id,
                    reward,
                    "TRIVIA",
                    f"Trivia correct ({self.difficulty})",
                )

            desc_lines = [
                f"**{emoji} {'Correct!' if correct else 'Wrong!'}**",
                "",
                f"> **Q:** {self.question}",
                f"> **Correct answer:** {_ANSWER_LABELS[self.correct]} {self.choices[self.correct]}",
            ]
            if not correct:
                desc_lines.append(f"> **Your answer:** {_ANSWER_LABELS[index]} {self.choices[index]}")
            desc_lines += [
                "",
                f"💡 **Did you know?** {self.fact}",
            ]
            if correct:
                desc_lines += ["", f"🪙 **+{format_number(reward)} coins** added to your balance!"]

            embed = obsidian_embed(
                f"{emoji} Trivia — {diff_emoji} {self.difficulty.title()}",
                "\n".join(desc_lines),
                category=color,
                client=interaction.client,
            )

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
                    btn_idx = int(item.custom_id)
                    if btn_idx == self.correct:
                        item.style = discord.ButtonStyle.success
                    elif btn_idx == index and not correct:
                        item.style = discord.ButtonStyle.danger

            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
                if int(item.custom_id) == self.correct:
                    item.style = discord.ButtonStyle.success


# ── Command ──────────────────────────────────────────────────────────────────

def setup(bot, group=None):
    command_decorator = (
        group.command(name="trivia", description="Answer a Warframe trivia question and earn coins!")
        if group
        else bot.tree.command(name="trivia", description="Answer a Warframe trivia question and earn coins!")
    )

    @command_decorator
    @app_commands.describe(difficulty="Choose a difficulty tier (default: random)")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="🟢 Easy (50–150 coins)", value="easy"),
        app_commands.Choice(name="🟡 Medium (150–350 coins)", value="medium"),
        app_commands.Choice(name="🔴 Hard (350–750 coins)", value="hard"),
    ])
    async def trivia_callback(
        interaction: discord.Interaction,
        difficulty: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild:
            return

        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                "The economy is currently disabled.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=False)

        # ── Cooldown check ──────────────────────────────────────────────────
        cooldown_key = f"trivia_last:{interaction.user.id}"
        last_str = await get_guild_setting(interaction.guild.id, cooldown_key)
        now = int(time.time())
        if last_str:
            last_ts = int(last_str)
            remaining = _TRIVIA_COOLDOWN - (now - last_ts)
            if remaining > 0:
                hours, rem = divmod(remaining, 3600)
                minutes = rem // 60
                time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
                embed = obsidian_embed(
                    "⏳ Trivia on Cooldown",
                    f"You've already answered a trivia question recently.\n\n"
                    f"> Next question available in **{time_str}**.",
                    category="warning",
                    client=interaction.client,
                )
                return await interaction.followup.send(embed=embed, ephemeral=True)

        # ── Pick question ───────────────────────────────────────────────────
        chosen_diff = difficulty.value if difficulty else None
        pool = [q for q in _QUESTIONS if chosen_diff is None or q[3] == chosen_diff]
        if not pool:
            pool = _QUESTIONS

        q_text, choices, correct_idx, diff, fact = random.choice(pool)
        # Shuffle choices while tracking the correct answer
        indexed = list(enumerate(choices))
        random.shuffle(indexed)
        new_correct = next(i for i, (orig, _) in enumerate(indexed) if orig == correct_idx)
        shuffled_choices = [c for _, c in indexed]

        min_r, max_r = _REWARDS[diff]
        coin_reward = random.randint(min_r, max_r)

        # ── Set cooldown ────────────────────────────────────────────────────
        await set_guild_setting(interaction.guild.id, cooldown_key, str(now))

        # ── Build question embed ────────────────────────────────────────────
        diff_emoji = _DIFFICULTY_EMOJI[diff]
        choice_lines = "\n".join(
            f"> {_ANSWER_LABELS[i]} {c}" for i, c in enumerate(shuffled_choices)
        )
        desc = (
            f"{diff_emoji} **{diff.title()} • {format_number(min_r)}–{format_number(max_r)} coins**\n\n"
            f"**{q_text}**\n\n"
            f"{choice_lines}\n\n"
            f"-# ⏱️ You have 30 seconds to answer."
        )
        embed = obsidian_embed(
            "🧠 Warframe Trivia",
            desc,
            category="general",
            footer=f"Correct answer earns {format_number(min_r)}–{format_number(max_r)} coins",
            client=interaction.client,
        )

        view = TriviaView(
            question=q_text,
            choices=shuffled_choices,
            correct=new_correct,
            difficulty=diff,
            fact=fact,
            coin_reward=coin_reward,
            interaction_user=interaction.user,
        )
        await interaction.followup.send(embed=embed, view=view)
