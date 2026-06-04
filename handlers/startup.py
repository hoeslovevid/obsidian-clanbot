"""
Bot startup logic extracted from bot.py on_ready.

Call run_startup(bot) from on_ready to execute all startup tasks.
"""
from __future__ import annotations
import asyncio
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Any

from core.config import DB_PATH
from database import init_db
from core.channels import ensure_core_channels, ensure_join_to_create_channel
from views import VCPanelView, ComplaintPanel, ComplaintModView, RSVPView

logger = logging.getLogger(__name__)


def _channel_name_safe(channel: Any) -> str:
    """Return a printable channel name (mirror of bot._channel_name_safe)."""
    name = getattr(channel, "name", None)
    return str(name) if name else f"<id:{getattr(channel, 'id', '?')}>"


def _update_status_presence(bot: discord.Client) -> discord.Activity:
    """Build a presence Activity reflecting website, /help, and guild count."""
    from core.presence import build_bot_activity
    return build_bot_activity(bot)


async def run_startup(bot: discord.Client) -> None:
    """Execute all bot startup tasks. Called from on_ready."""
    bu = bot.user
    print(f"[ready] Logged in as {bu} ({bu.id if bu else '?'})")

    activity = _update_status_presence(bot)
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"[ready] Status set: Watching {activity.name}")

    guild_list = sorted(bot.guilds, key=lambda g: (g.name or "").lower())
    guild_count = len(guild_list)
    print(f"[ready] Servers ({guild_count}):")
    for i, g in enumerate(guild_list, start=1):
        print(f"[ready]   {i:>3}. {g.name} ({g.id})")

    # Parallelize startup tasks for faster initialization
    async def setup_guild_channels():
        """Setup channels for all guilds in parallel."""
        tasks = []
        for g in bot.guilds:
            tasks.append(ensure_core_channels(g))
            tasks.append(ensure_join_to_create_channel(g))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                guild_idx = i // 2
                if guild_idx < len(bot.guilds):
                    print(f"[startup] Ensure failed in {bot.guilds[guild_idx].name}: {result}")

    async def setup_background_tasks():
        """Setup background tasks (lazy-import defers tasks.py ~1700 lines until ready)."""
        try:
            from tasks import setup_tasks
            tasks_dict = setup_tasks(bot)
            print(f"[ready] Background tasks initialized: {len(tasks_dict)} tasks")
        except Exception as e:
            print(f"[ready] ERROR: Failed to setup background tasks: {e}")
            import traceback
            traceback.print_exc()

    async def register_persistent_views():
        """Register all persistent views in parallel."""
        # Basic views
        bot.add_view(ComplaintPanel())
        bot.add_view(RSVPView())
        try:
            from commands.general.console import ConsoleHubView
            bot.add_view(ConsoleHubView())
        except Exception as e:
            logger.debug(f"[ready] ConsoleHubView registration skipped: {e}")

        # Item 47: re-register pending VC revival vote buttons.
        try:
            from commands.voice.vc import RevivalView
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT token FROM vc_revivals WHERE resolved=0"
                )
                tokens = [r[0] for r in await cur.fetchall()]
            for tok in tokens:
                try:
                    bot.add_view(RevivalView(token=str(tok)))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[ready] could not register vc_revival views: {e}")

        # Warframe self-subscribe panel (Item 21) — static custom_ids so a
        # single instance is enough to route every panel's buttons.
        try:
            from commands.warframe.notify_panel import NotifyPanelView
            bot.add_view(NotifyPanelView())
        except Exception as e:
            logger.debug(f"[ready] Could not register NotifyPanelView: {e}")

        # Collect all view data in parallel
        async def get_all_view_data():
            """Fetch all view data in a single query batch."""
            async with aiosqlite.connect(DB_PATH) as db:
                # Fetch all data in parallel queries
                vc_cur = await db.execute("SELECT guild_id, channel_id FROM temp_vcs")
                vc_data = await vc_cur.fetchall()

                lfg_cur = await db.execute("SELECT id FROM lfg_posts WHERE status='OPEN'")
                lfg_data = await lfg_cur.fetchall()

                complaint_cur = await db.execute("SELECT case_id FROM complaints WHERE status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')")
                complaint_data = await complaint_cur.fetchall()

                suggestion_cur = await db.execute("SELECT id FROM suggestions WHERE status='PENDING'")
                suggestion_data = await suggestion_cur.fetchall()

                app_cur = await db.execute("SELECT id FROM applications WHERE status='PENDING'")
                app_data = await app_cur.fetchall()

                panel_cur = await db.execute("SELECT guild_id, panel_message_id FROM application_settings WHERE panel_message_id IS NOT NULL")
                panel_data = await panel_cur.fetchall()

                giveaway_cur = await db.execute("SELECT id FROM giveaways WHERE ended = 0")
                giveaway_data = await giveaway_cur.fetchall()

                trading_cur = await db.execute("SELECT id, user_id FROM trading_posts WHERE status='ACTIVE'")
                trading_data = await trading_cur.fetchall()

                ticket_cur = await db.execute(
                    "SELECT id, ticket_id, control_message_id FROM tickets WHERE status='open' AND control_message_id IS NOT NULL"
                )
                ticket_data = await ticket_cur.fetchall()

                return {
                    'vc': vc_data,
                    'lfg': lfg_data,
                    'complaints': complaint_data,
                    'suggestions': suggestion_data,
                    'applications': app_data,
                    'panels': panel_data,
                    'giveaways': giveaway_data,
                    'trading': trading_data,
                    'tickets': ticket_data,
                }

        view_data = await get_all_view_data()

        # Register views (non-blocking)
        for (guild_id, channel_id) in view_data['vc']:
            try:
                bot.add_view(VCPanelView(int(channel_id)))
            except Exception:
                pass

        for (lfg_id,) in view_data['lfg']:
            try:
                from commands.warframe.lfg import LFGView
                bot.add_view(LFGView(int(lfg_id)))
            except Exception:
                pass

        for (case_id,) in view_data['complaints']:
            try:
                bot.add_view(ComplaintModView(str(case_id)))
            except Exception:
                pass

        for (suggestion_id,) in view_data['suggestions']:
            try:
                from commands.suggestions.manage_suggestions import SuggestionView
                bot.add_view(SuggestionView(int(suggestion_id)))
            except Exception:
                pass
            try:
                from commands.suggestions.suggest import SuggestionVoteView
                bot.add_view(SuggestionVoteView(int(suggestion_id)))
            except Exception:
                pass

        for (application_id,) in view_data['applications']:
            try:
                from views import ApplicationManageView
                bot.add_view(ApplicationManageView(int(application_id)))
            except Exception:
                pass

        for (guild_id, panel_message_id) in view_data['panels']:
            try:
                from views import ApplicationPanelView
                bot.add_view(ApplicationPanelView(guild_id))
            except Exception:
                pass

        for (giveaway_id,) in view_data['giveaways']:
            try:
                from views import GiveawayView
                bot.add_view(GiveawayView(giveaway_id))
            except Exception as e:
                logger.debug(f"[ready] Error re-registering giveaway view {giveaway_id}: {e}")

        for (listing_id, user_id) in view_data['trading']:
            try:
                from views import TradingPostView
                bot.add_view(TradingPostView(int(listing_id), int(user_id)))
            except Exception:
                pass

        # Ticket control panels (per-ticket persistent views)
        for (ticket_db_id, ticket_id, control_message_id) in view_data.get('tickets', []):
            try:
                from commands.tickets.ticket import TicketControlView
                if control_message_id:
                    bot.add_view(TicketControlView(int(ticket_db_id), str(ticket_id)), message_id=int(control_message_id))
            except Exception:
                pass

        # Self-assign role panels (#10) — bind each persistent view to its message id
        # so Discord routes button clicks back to the correct panel after a restart.
        try:
            from commands.moderation.role_panel import RolePanelView, fetch_all_panels
            for panel in await fetch_all_panels():
                try:
                    bot.add_view(
                        RolePanelView(panel_id=panel["panel_id"], roles=panel["roles"]),
                        message_id=panel["message_id"],
                    )
                except Exception as exc:
                    logger.debug(f"[ready] role_panel re-register failed for {panel.get('panel_id')}: {exc}")
        except Exception as exc:
            logger.debug(f"[ready] Could not register role_panel views: {exc}")

    # Run setup tasks in parallel
    await asyncio.gather(
        setup_guild_channels(),
        setup_background_tasks(),
        register_persistent_views(),
        return_exceptions=True
    )


    # Verify update log settings and version tracking (parallel)
    async def verify_settings():
        """Verify update log settings and version tracking."""
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT guild_id, channel_id FROM update_log_settings WHERE channel_id IS NOT NULL
            """)
            settings = list(await cur.fetchall())
            if settings:
                logger.info(f"[ready] Loaded {len(settings)} update log channel setting(s) from database")
                for guild_id, channel_id in settings:
                    guild = bot.get_guild(guild_id)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            logger.info(f"[ready] Update log channel configured: {guild.name} -> #{_channel_name_safe(channel)}")
                        else:
                            logger.warning(f"[ready] Update log channel not found: guild {guild.name}, channel_id {channel_id}")
            else:
                logger.info("[ready] No update log channels configured")

            # Canonical version is BOT_VERSION (env / core.config); DB row is for change detection only.
            from core.config import BOT_VERSION

            bot._bot_version = BOT_VERSION or "unknown"
            cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
            version_row = await cur.fetchone()
            if version_row:
                logger.info(
                    "[ready] BOT_VERSION=%s (tracking DB: %s)",
                    bot._bot_version,
                    version_row[0],
                )
            else:
                logger.info("[ready] BOT_VERSION=%s (no tracking row yet)", bot._bot_version)

    async def init_achievements():
        """Initialize achievement definitions (cached)."""
        global _achievement_definitions_initialized
        try:
            from database import initialize_achievement_definitions, initialize_badge_definitions, initialize_title_definitions
            await initialize_achievement_definitions()
            await initialize_badge_definitions()
            await initialize_title_definitions()
            _achievement_definitions_initialized = True
            logger.info("[ready] Achievement definitions initialized")
        except Exception as e:
            logger.error(f"[ready] Error initializing achievements: {e}", exc_info=True)

    async def run_one_time_migrations():
        """Run cheap, idempotent migrations once at startup."""
        try:
            from commands.warframe.alerts_notify import _migrate_alerts_channel_key
            await _migrate_alerts_channel_key()
        except Exception as e:
            logger.debug(f"[ready] alerts channel key migration skipped: {e}")
        try:
            from commands.warframe.devstream_notify import _migrate_devstream_channel_key
            await _migrate_devstream_channel_key()
        except Exception as e:
            logger.debug(f"[ready] devstream channel key migration skipped: {e}")

    # Update application profile (description, tags) for bot profile display
    async def update_app_profile():
        try:
            from core.app_profile import update_app_profile_metadata
            await update_app_profile_metadata()
        except Exception as e:
            logger.debug(f"[ready] App profile update skipped: {e}")

    # Run verification tasks in parallel
    await asyncio.gather(
        verify_settings(),
        init_achievements(),
        update_app_profile(),
        run_one_time_migrations(),
        return_exceptions=True
    )

    # Wait a bit for commands to fully sync, then check and post automatic update logs (non-blocking)
    async def check_updates():
        """Check for updates in background (lazy-import defers version_tracking until ready)."""
        try:
            from core.version_tracking import check_and_post_updates
            logger.info("[ready] Waiting for commands to sync, then checking for automatic updates...")
            await asyncio.sleep(5)  # Give commands more time to fully register and sync with Discord
            logger.info("[ready] Starting update check...")
            await check_and_post_updates(bot)
            logger.info("[ready] Automatic update check completed")
        except Exception as e:
            logger.error(f"[ready] Error during automatic update check: {e}", exc_info=True)

    # Run update check in background (non-blocking)
    asyncio.create_task(check_updates())

    async def announce_release():
        try:
            from core.release_announce import announce_release_if_needed
            await asyncio.sleep(6)
            await announce_release_if_needed(bot)
        except Exception as e:
            logger.debug(f"[ready] release announce skipped: {e}")

    asyncio.create_task(announce_release())

    # Re-register reaction roles for all messages (optimized - batch fetch reactions)
    async def restore_reaction_roles():
        """Restore reaction roles in background (non-blocking)."""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Get all reaction role messages with their emojis in one query
                cur = await db.execute("""
                    SELECT DISTINCT message_id, channel_id, 
                           GROUP_CONCAT(emoji, ',') as emojis
                    FROM reaction_roles
                    GROUP BY message_id, channel_id
                """)
                reaction_messages = await cur.fetchall()

            # Process in batches to avoid rate limits
            for message_id, channel_id, emojis_str in reaction_messages:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        try:
                            message = await channel.fetch_message(message_id)
                            emojis = emojis_str.split(',') if emojis_str else []

                            # Re-add reactions if they're missing (batch)
                            for emoji_str in emojis:
                                try:
                                    if not any(str(r.emoji) == emoji_str for r in message.reactions):
                                        await message.add_reaction(emoji_str)
                                except Exception:
                                    pass
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except Exception as e:
                            logger.debug(f"[ready] Error restoring reaction roles for message {message_id}: {e}")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[ready] Error in reaction role restoration: {e}")

    # Run reaction role restoration in background (non-blocking)
    asyncio.create_task(restore_reaction_roles())


