"""Database schema: all CREATE TABLE, migrations, and index creation.
Call init_db() once at startup to initialise all tables and indexes.
"""
import logging
import os

import aiosqlite  # type: ignore
from core.config import DB_PATH
from core.db import configure_sqlite

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Initialize all database tables."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # WAL + busy_timeout: concurrent readers/writers wait instead of failing locked.
        await configure_sqlite(db)
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=-32000")   # 32 MB page cache
        await db.execute("PRAGMA temp_store=MEMORY")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_vcs (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_nonempty_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS vc_panels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            details TEXT NOT NULL,
            evidence TEXT,
            status TEXT NOT NULL,
            staff_thread_id INTEGER,
            last_update_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, case_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaint_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER,
            description TEXT NOT NULL,
            role_id INTEGER,
            created_at TEXT NOT NULL,
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            ended INTEGER NOT NULL DEFAULT 0,
            recap_posted INTEGER NOT NULL DEFAULT 0,
            recap_message_id INTEGER,
            thread_id INTEGER,
            PRIMARY KEY (guild_id, message_id)
        )""")

        # Event automation (columns on existing table)
        try:
            cur = await db.execute("PRAGMA table_info(events)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "end_ts" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN end_ts INTEGER")
            if "ended" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN ended INTEGER NOT NULL DEFAULT 0")
            if "recap_posted" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN recap_posted INTEGER NOT NULL DEFAULT 0")
            if "recap_message_id" not in column_names:
                await db.execute("ALTER TABLE events ADD COLUMN recap_message_id INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding event automation columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_rsvps (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            PRIMARY KEY (guild_id, message_id, user_id)
        )""")

        # Economy tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_balances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            total_earned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS economy_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_activity (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            last_reward_at TEXT,
            total_minutes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS message_cooldowns (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_message_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            total_xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_claims (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_claim_date TEXT NOT NULL,
            streak_days INTEGER NOT NULL DEFAULT 1,
            freeze_used_month TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")
        # Migration: add freeze_used_month if missing (existing DBs)
        try:
            cur = await db.execute("PRAGMA table_info(daily_claims)")
            cols = [row[1] for row in await cur.fetchall()]
            if "freeze_used_month" not in cols:
                await db.execute("ALTER TABLE daily_claims ADD COLUMN freeze_used_month TEXT")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] daily_claims freeze_used_month migration: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arrival_time TEXT NOT NULL,
            departure_time TEXT NOT NULL,
            location TEXT NOT NULL,
            inventory_json TEXT,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_live_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            expiry_time TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, channel_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            mission_type TEXT NOT NULL,
            player_count INTEGER NOT NULL,
            max_players INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            thread_id INTEGER
        )""")

        # LFG enhancements (optional ping role + close metadata)
        try:
            cur = await db.execute("PRAGMA table_info(lfg_posts)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "ping_role_id" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN ping_role_id INTEGER")
            if "closed_at" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN closed_at TEXT")
            if "closed_by" not in column_names:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN closed_by INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding LFG enhancement columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lfg_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (lfg_id) REFERENCES lfg_posts(id) ON DELETE CASCADE,
            UNIQUE(lfg_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            cetus_enabled INTEGER NOT NULL DEFAULT 0,
            fortuna_enabled INTEGER NOT NULL DEFAULT 0,
            deimos_enabled INTEGER NOT NULL DEFAULT 0,
            ping_role_id INTEGER,
            PRIMARY KEY (guild_id)
        )""")
        # Migration: add ping_role_id if missing (existing DBs)
        try:
            cur = await db.execute("PRAGMA table_info(cycle_notification_settings)")
            cols = [row[1] for row in await cur.fetchall()]
            if "ping_role_id" not in cols:
                await db.execute("ALTER TABLE cycle_notification_settings ADD COLUMN ping_role_id INTEGER")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] cycle_notification_settings ping_role_id migration: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            cycle_type TEXT NOT NULL,
            cycle_state TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, cycle_type, cycle_state, notified_at)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_live_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(guild_id, channel_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notification_settings (
            guild_id INTEGER NOT NULL,
            reward_lower TEXT NOT NULL,
            reward_display TEXT NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            invasion_id TEXT NOT NULL,
            reward_lower TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, invasion_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            archon_boss TEXT NOT NULL,
            expiry_time TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, archon_boss, expiry_time)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_count_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            channel_type TEXT NOT NULL DEFAULT 'voice',
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_event_settings (
            guild_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_discord_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            warframe_event_id TEXT NOT NULL,
            discord_event_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, warframe_event_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            suggestion_text TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            status TEXT NOT NULL DEFAULT 'PENDING',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT
        )""")

        # Add category column to suggestions if missing (migration)
        try:
            cur = await db.execute("PRAGMA table_info(suggestions)")
            cols = await cur.fetchall()
            col_names = [c[1] for c in cols]
            if "category" not in col_names:
                await db.execute("ALTER TABLE suggestions ADD COLUMN category TEXT NOT NULL DEFAULT 'other'")
                await db.commit()
                logger.info("[db] Added category column to suggestions table")
        except Exception as e:
            logger.warning(f"[db] Error adding category to suggestions: {e}")

        # Suggestion votes table (one row per user-per-suggestion, value 1=up -1=down)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS suggestion_votes (
            suggestion_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            vote INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (suggestion_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            panel_channel_id INTEGER,
            panel_message_id INTEGER,
            panel_description TEXT,
            panel_image_url TEXT
        )""")
        
        # Add panel columns if they don't exist (for existing databases)
        try:
            cur = await db.execute("PRAGMA table_info(application_settings)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            
            if "panel_channel_id" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_channel_id INTEGER")
                logger.info("[db] Added panel_channel_id column to application_settings table")
            
            if "panel_message_id" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_message_id INTEGER")
                logger.info("[db] Added panel_message_id column to application_settings table")
            
            if "panel_description" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_description TEXT")
                logger.info("[db] Added panel_description column to application_settings table")
            
            if "panel_image_url" not in column_names:
                await db.execute("ALTER TABLE application_settings ADD COLUMN panel_image_url TEXT")
                logger.info("[db] Added panel_image_url column to application_settings table")
            
            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding panel columns: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            question_order INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            UNIQUE(guild_id, question_order)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
            current_question_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            submitted_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT,
            message_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            response_text TEXT NOT NULL,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES application_questions(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_posted_versions (
            guild_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, version)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_version_tracking (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_version TEXT NOT NULL,
            feature_hash TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            previous_commands TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id, emoji)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS welcome_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS leave_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT NOT NULL,
            winner_count INTEGER NOT NULL DEFAULT 1,
            end_time TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            ended INTEGER NOT NULL DEFAULT 0,
            ended_at TEXT,
            required_role_id INTEGER,
            min_level INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            entered_at TEXT NOT NULL,
            UNIQUE(giveaway_id, user_id),
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            spam_enabled INTEGER NOT NULL DEFAULT 1,
            spam_threshold INTEGER NOT NULL DEFAULT 5,
            spam_interval INTEGER NOT NULL DEFAULT 10,
            caps_enabled INTEGER NOT NULL DEFAULT 1,
            caps_threshold INTEGER NOT NULL DEFAULT 70,
            caps_min_length INTEGER NOT NULL DEFAULT 10,
            links_enabled INTEGER NOT NULL DEFAULT 0,
            links_whitelist TEXT,
            mention_enabled INTEGER NOT NULL DEFAULT 1,
            mention_limit INTEGER NOT NULL DEFAULT 5,
            punishment_action TEXT NOT NULL DEFAULT 'delete',
            punishment_duration INTEGER,
            log_channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            message_content TEXT,
            action_taken TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_spam_tracking (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 1,
            first_message_time TEXT NOT NULL,
            last_message_time TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS self_assignable_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            category TEXT,
            description TEXT,
            max_roles INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, role_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS level_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, level)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS afk_users (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            set_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_stats_channels (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            stats_type TEXT NOT NULL DEFAULT 'members',
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS alert_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            alert_id TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, alert_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS devstream_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            devstream_date TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, devstream_date, notification_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            interest_rate REAL NOT NULL DEFAULT 0.05,
            invested_at TEXT NOT NULL,
            maturity_date TEXT NOT NULL,
            collected INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, invested_at)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_stash (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            stashed INTEGER NOT NULL DEFAULT 0,
            last_interest_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS log_channels (
            guild_id INTEGER NOT NULL,
            log_type TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, log_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS deleted_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT,
            author_name TEXT,
            author_avatar TEXT,
            attachments TEXT,
            embeds TEXT,
            deleted_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS edited_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            old_content TEXT,
            new_content TEXT,
            author_name TEXT,
            edited_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            milestone_type TEXT NOT NULL,
            milestone_value INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, milestone_type, milestone_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            UNIQUE(guild_id, user_id, achievement_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievement_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            requirement TEXT,
            reward_coins INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0,
            unlock_title_id TEXT,
            UNIQUE(achievement_id)
        )""")
        # Item 107 — older DBs may not have unlock_title_id yet
        try:
            cur = await db.execute("PRAGMA table_info(achievement_definitions)")
            cols = [row[1] for row in await cur.fetchall()]
            if "unlock_title_id" not in cols:
                await db.execute("ALTER TABLE achievement_definitions ADD COLUMN unlock_title_id TEXT")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] achievement_definitions.unlock_title_id migration: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS music_queues (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            voice_channel_id INTEGER NOT NULL,
            current_track TEXT,
            queue_json TEXT,
            is_playing INTEGER NOT NULL DEFAULT 0,
            volume INTEGER NOT NULL DEFAULT 50,
            updated_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            endpoint_name TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            event_types TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, endpoint_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            price INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_value TEXT,
            stock INTEGER DEFAULT -1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, item_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            price_paid INTEGER NOT NULL,
            purchased_at TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES shop_items(id)
        )""")
        
        # Add previous_commands column if it doesn't exist (for existing databases)
        # Check if column exists first to avoid errors
        try:
            cur = await db.execute("PRAGMA table_info(bot_version_tracking)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            if "previous_commands" not in column_names:
                await db.execute("ALTER TABLE bot_version_tracking ADD COLUMN previous_commands TEXT")
                await db.commit()
                logger.info("[db] Added previous_commands column to bot_version_tracking table")
        except Exception as e:
            logger.warning(f"[db] Error checking/adding previous_commands column: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            listing_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            price INTEGER,
            quantity INTEGER DEFAULT 1,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            platform TEXT NOT NULL DEFAULT 'pc'
        )""")

        try:
            cur = await db.execute("PRAGMA table_info(trading_posts)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            if "expires_at" not in column_names:
                await db.execute("ALTER TABLE trading_posts ADD COLUMN expires_at TEXT")
                await db.commit()
                logger.info("[db] Added expires_at column to trading_posts table")
            if "channel_id" not in column_names:
                await db.execute("ALTER TABLE trading_posts ADD COLUMN channel_id INTEGER")
                await db.commit()
                logger.info("[db] Added channel_id column to trading_posts table")
        except Exception as e:
            logger.warning(f"[db] Error checking/adding trading_posts.expires_at: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_channel_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            commands_used INTEGER NOT NULL DEFAULT 0,
            events_attended INTEGER NOT NULL DEFAULT 0,
            voice_minutes INTEGER NOT NULL DEFAULT 0,
            messages_sent INTEGER NOT NULL DEFAULT 0,
            last_activity_date TEXT NOT NULL,
            weekly_score INTEGER NOT NULL DEFAULT 0,
            monthly_score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            activity_date TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )""")

        # Ticket system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            ticket_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT,
            closed_by INTEGER,
            UNIQUE(guild_id, ticket_id)
        )""")

        # Ticket enhancements (columns on existing table)
        # - assigned_to: who claimed/owns the ticket (mod id)
        # - claimed_at: when it was claimed
        # - first_response_at: first staff response time
        # - last_activity_at: last message time (user or staff)
        # - sla_minutes: per-ticket SLA target (minutes)
        # - control_message_id: message id of the ticket control panel in the ticket channel
        # - satisfaction_rating/feedback: post-close feedback
        # - transcript_channel_id/transcript_message_id: where transcript was posted
        try:
            cur = await db.execute("PRAGMA table_info(tickets)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]

            if "assigned_to" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN assigned_to INTEGER")
            if "claimed_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN claimed_at TEXT")
            if "first_response_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN first_response_at TEXT")
            if "last_activity_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN last_activity_at TEXT")
            if "sla_minutes" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN sla_minutes INTEGER DEFAULT 60")
            if "control_message_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN control_message_id INTEGER")
            if "satisfaction_rating" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN satisfaction_rating INTEGER")
            if "satisfaction_feedback" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN satisfaction_feedback TEXT")
            if "transcript_channel_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN transcript_channel_id INTEGER")
            if "transcript_message_id" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN transcript_message_id INTEGER")
            if "tag" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN tag TEXT")
            if "stale_reminder_sent" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN stale_reminder_sent INTEGER DEFAULT 0")
            if "priority" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN priority TEXT DEFAULT 'normal'")
            if "escalated" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN escalated INTEGER DEFAULT 0")
            if "escalated_at" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN escalated_at TEXT")
            if "escalated_by" not in column_names:
                await db.execute("ALTER TABLE tickets ADD COLUMN escalated_by INTEGER")

            await db.commit()
        except Exception as e:
            logger.warning(f"[db] Error checking/adding ticket enhancement columns: {e}")

        # Ticket notes (internal staff notes)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
        )""")

        # Ticket canned responses (quick replies)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_canned_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, name)
        )""")

        # Gambling tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS gambling_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game_type TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            win_amount INTEGER NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # Server rules tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            rule_number INTEGER NOT NULL,
            rule_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, rule_number)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS rules_channel_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            message_id INTEGER
        )""")

        # Poll system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            ends_at TEXT,
            created_at TEXT NOT NULL,
            closed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, message_id)
        )""")
        try:
            cur = await db.execute("PRAGMA table_info(polls)")
            poll_cols = [row[1] for row in await cur.fetchall()]
            if "closed" not in poll_cols:
                await db.execute("ALTER TABLE polls ADD COLUMN closed INTEGER NOT NULL DEFAULT 0")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] polls closed migration: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            poll_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            option_index INTEGER NOT NULL,
            voted_at TEXT NOT NULL,
            PRIMARY KEY (poll_id, user_id),
            FOREIGN KEY (poll_id) REFERENCES polls(id)
        )""")

        # Warn system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warn_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            max_warnings INTEGER NOT NULL DEFAULT 3,
            action_after_max TEXT NOT NULL DEFAULT 'mute',
            mute_duration INTEGER,
            log_channel_id INTEGER
        )""")

        # Reminder system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            reminder_text TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        )""")
        try:
            cur = await db.execute("PRAGMA table_info(reminders)")
            cols = [row[1] for row in await cur.fetchall()]
            if "recurrence_rule" not in cols:
                await db.execute("ALTER TABLE reminders ADD COLUMN recurrence_rule TEXT")
                await db.commit()
        except Exception as e:
            logger.warning(f"[db] reminders recurrence_rule migration: {e}")

        # Scheduled messages (one-time)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_content TEXT NOT NULL,
            send_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS integration_seen (
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (source, item_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS mod_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS economy_bounties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            bounty_type TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            target INTEGER NOT NULL,
            reward INTEGER NOT NULL,
            claimed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, user_id, bounty_type)
        )""")

        # Starboard tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            threshold INTEGER NOT NULL DEFAULT 5,
            emoji TEXT NOT NULL DEFAULT '⭐'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_messages (
            guild_id INTEGER NOT NULL,
            original_message_id INTEGER NOT NULL,
            starboard_message_id INTEGER NOT NULL,
            stars INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, original_message_id)
        )""")

        # Reputation system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reputation_points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            giver_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )""")

        # Twitch integration tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 0,
            ping_role_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_streamers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            streamer_name TEXT NOT NULL,
            twitch_user_id TEXT,
            last_live_status INTEGER NOT NULL DEFAULT 0,
            last_notified_at TEXT,
            UNIQUE(guild_id, streamer_name)
        )""")

        # Role menu tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            max_roles INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menu_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            emoji TEXT,
            description TEXT,
            FOREIGN KEY (menu_id) REFERENCES role_menus(id) ON DELETE CASCADE
        )""")

        # Clan Dojo tracker tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            research_name TEXT NOT NULL,
            research_type TEXT NOT NULL,
            required_resources TEXT,
            current_resources TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(guild_id, research_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_decorations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            decoration_name TEXT NOT NULL,
            room_location TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL
        )""")

        # Pet system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pet_name TEXT NOT NULL,
            pet_type TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            experience INTEGER NOT NULL DEFAULT 0,
            hunger INTEGER NOT NULL DEFAULT 100,
            happiness INTEGER NOT NULL DEFAULT 100,
            last_fed_at TEXT,
            last_played_at TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_type TEXT NOT NULL UNIQUE,
            base_price INTEGER NOT NULL,
            max_level INTEGER NOT NULL DEFAULT 100,
            description TEXT
        )""")
        # Seed default pets if shop is empty
        cur = await db.execute("SELECT COUNT(*) FROM pet_types")
        row = await cur.fetchone()
        if row is None or row[0] == 0:
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
            for pet_type, base_price, max_level, description in default_pets:
                await db.execute(
                    "INSERT OR IGNORE INTO pet_types (pet_type, base_price, max_level, description) VALUES (?, ?, ?, ?)",
                    (pet_type, base_price, max_level, description),
                )
            await db.commit()

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_evolutions (
            base_type TEXT NOT NULL,
            evolved_type TEXT NOT NULL,
            required_level INTEGER NOT NULL,
            PRIMARY KEY (base_type)
        )""")

        # Seed pet evolutions (base_type -> evolved_type at required_level)
        cur = await db.execute("SELECT COUNT(*) FROM pet_evolutions")
        row = await cur.fetchone()
        if row is None or row[0] == 0:
            evolutions = [
                ("Dog", "Golden Retriever", 25),
                ("Cat", "Shadow Cat", 30),
                ("Bird", "Phoenix Chick", 20),
                ("Rabbit", "Moon Rabbit", 25),
                ("Fox", "Arctic Fox", 35),
                ("Robot", "Mech Prime", 40),
                ("Wolf", "Alpha Wolf", 45),
                ("Dragon", "Elder Dragon", 50),
                ("Phoenix", "Inferno Phoenix", 55),
            ]
            for base, evolved, lvl in evolutions:
                await db.execute(
                    "INSERT OR IGNORE INTO pet_evolutions (base_type, evolved_type, required_level) VALUES (?, ?, ?)",
                    (base, evolved, lvl),
                )
            # Add evolved types to pet_types if not present
            for _, evolved, _ in evolutions:
                await db.execute(
                    "INSERT OR IGNORE INTO pet_types (pet_type, base_price, max_level, description) VALUES (?, 0, 100, 'Evolved form')",
                    (evolved,),
                )
            await db.commit()

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_battle_cooldowns (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_battle_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_battle_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            pet_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            listed_at TEXT NOT NULL,
            FOREIGN KEY (pet_id) REFERENCES pets(id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_abandonments (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            abandoned_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Add evolution_tier to pets if missing
        try:
            cur = await db.execute("PRAGMA table_info(pets)")
            cols = [row[1] for row in await cur.fetchall()]
            if "evolution_tier" not in cols:
                await db.execute("ALTER TABLE pets ADD COLUMN evolution_tier INTEGER NOT NULL DEFAULT 0")
                await db.commit()
        except Exception:
            pass

        # Prestige system tables
        # Warframe in-game achievement roles (Steam playtime, etc.)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS linked_steam_accounts (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            steam_id_64 TEXT NOT NULL,
            warframe_ign TEXT,
            linked_at TEXT NOT NULL,
            last_playtime_hours INTEGER,
            last_checked_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")
        # Migration: add warframe_ign if missing
        try:
            cur = await db.execute("PRAGMA table_info(linked_steam_accounts)")
            cols = [row[1] for row in await cur.fetchall()]
            if "warframe_ign" not in cols:
                await db.execute("ALTER TABLE linked_steam_accounts ADD COLUMN warframe_ign TEXT")
                await db.commit()
        except Exception:
            pass
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_achievement_roles (
            guild_id INTEGER NOT NULL,
            achievement_type TEXT NOT NULL,
            threshold_value INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, achievement_type, threshold_value)
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_achievement_unlocks (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_type TEXT NOT NULL,
            threshold_value INTEGER NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, achievement_type, threshold_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_prestige (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            prestige_level INTEGER NOT NULL DEFAULT 0,
            total_prestige_xp INTEGER NOT NULL DEFAULT 0,
            last_prestige_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Badge/Title system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            badge_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            is_equipped INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, badge_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS badge_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            icon_emoji TEXT,
            rarity TEXT NOT NULL DEFAULT 'common',
            requirement TEXT,
            reward_coins INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_titles (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS title_definitions (
            id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            unlock_type TEXT NOT NULL DEFAULT 'purchase',
            unlock_value TEXT,
            cost_coins INTEGER NOT NULL DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_unlocked_titles (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, title_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_badge_showcase (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            slot INTEGER NOT NULL CHECK (slot >= 1 AND slot <= 5),
            badge_id TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, slot)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS recurring_event_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            day_of_week INTEGER NOT NULL,
            hour_utc INTEGER NOT NULL,
            minute_utc INTEGER NOT NULL DEFAULT 0,
            duration_hours INTEGER NOT NULL DEFAULT 2,
            role_id INTEGER,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            last_created_week TEXT
        )""")

        # Scheduled announcements tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            embed_json TEXT,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # Server milestones tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            milestone_type TEXT NOT NULL,
            milestone_value INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            announced INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, milestone_type, milestone_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_milestone_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            member_count_enabled INTEGER NOT NULL DEFAULT 1,
            anniversary_enabled INTEGER NOT NULL DEFAULT 1,
            announcement_channel_id INTEGER
        )""")

        # Raid protection tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS raid_protection_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            join_threshold INTEGER NOT NULL DEFAULT 10,
            time_window_seconds INTEGER NOT NULL DEFAULT 60,
            action TEXT NOT NULL DEFAULT 'lockdown',
            lockdown_duration_minutes INTEGER NOT NULL DEFAULT 30,
            alert_channel_id INTEGER,
            alert_role_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS recent_joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            account_age_days INTEGER,
            joined_at TEXT NOT NULL
        )""")

        # Raid protection: add gate_role_id and verify_role_id for auto-verify
        try:
            cur = await db.execute("PRAGMA table_info(raid_protection_settings)")
            cols = [row[1] for row in await cur.fetchall()]
            if "gate_role_id" not in cols:
                await db.execute("ALTER TABLE raid_protection_settings ADD COLUMN gate_role_id INTEGER")
            if "verify_role_id" not in cols:
                await db.execute("ALTER TABLE raid_protection_settings ADD COLUMN verify_role_id INTEGER")
            await db.commit()
        except Exception:
            pass

        await db.execute("""
        CREATE TABLE IF NOT EXISTS raid_restricted_users (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            restricted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Cross-server communication tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_alliances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            allied_guild_id INTEGER NOT NULL,
            alliance_name TEXT,
            created_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            UNIQUE(guild_id, allied_guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cross_server_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_guild_id INTEGER NOT NULL,
            to_guild_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            message_content TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cross_server_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            alliance_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (alliance_id) REFERENCES server_alliances(id) ON DELETE CASCADE
        )""")

        # Voice activity leaderboard tables (enhancement)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_leaderboard_cache (
            guild_id INTEGER NOT NULL,
            period_type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            voice_minutes INTEGER NOT NULL DEFAULT 0,
            rank INTEGER,
            last_updated TEXT NOT NULL,
            PRIMARY KEY (guild_id, period_type, user_id)
        )""")

        # Per-user slash command usage counters powering /tools my_stats.
        # We aggregate (rather than logging every single invocation) so the
        # table stays tiny — one row per (guild, user, command, weekday).
        await db.execute("""
        CREATE TABLE IF NOT EXISTS command_usage_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            command_name TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, command_name, weekday)
        )""")

        # Self-assignable role panels persisted across restarts (#10).
        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            roles_json TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # v1.94 — Baro wishlist, LFG interest, mentorship, IGN verification
        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_wishlist (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, item_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_interest_subscriptions (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id, tag)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS mentorship_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            mentor_id INTEGER NOT NULL,
            mentee_id INTEGER NOT NULL,
            thread_id INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, mentee_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS ign_verifications (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            ign TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            verified_by INTEGER,
            verified_at TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        try:
            cur = await db.execute("PRAGMA table_info(lfg_posts)")
            lfg_cols = [col[1] for col in await cur.fetchall()]
            if "role_tags" not in lfg_cols:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN role_tags TEXT")
            if "scheduled_at" not in lfg_cols:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN scheduled_at TEXT")
            if "reminder_sent" not in lfg_cols:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN reminder_sent INTEGER DEFAULT 0")
            if "squad_vc_id" not in lfg_cols:
                await db.execute("ALTER TABLE lfg_posts ADD COLUMN squad_vc_id INTEGER")
            await db.commit()
        except Exception as e:
            logger.warning(f"[db] LFG v1.94 column migration: {e}")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lfg_presets (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                preset_name TEXT NOT NULL,
                mission_type TEXT NOT NULL,
                max_players INTEGER NOT NULL DEFAULT 4,
                description TEXT,
                radio_query TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, preset_name)
            )
            """
        )
        await db.commit()

        try:
            cur = await db.execute("PRAGMA table_info(applications)")
            app_cols = [col[1] for col in await cur.fetchall()]
            if "pipeline_stage" not in app_cols:
                await db.execute(
                    "ALTER TABLE applications ADD COLUMN pipeline_stage TEXT DEFAULT 'applied'"
                )
            await db.commit()
        except Exception as e:
            logger.warning(f"[db] applications pipeline_stage migration: {e}")

        # Create indexes for common queries to improve performance
        logger.info("[db] Creating indexes for performance optimization...")
        
        # Indexes for frequently queried columns
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_balances_guild_user ON user_balances(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_xp_guild_user ON user_xp(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_activity_stats_guild_user ON activity_stats(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_transactions_guild_user ON economy_transactions(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_transactions_created ON economy_transactions(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_voice_activity_guild_user ON voice_activity(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_recent_joins_guild_time ON recent_joins(guild_id, joined_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_next_run ON scheduled_announcements(next_run_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_polls_guild_message ON polls(guild_id, message_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_applications_guild_status ON applications(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_complaints_guild_status ON complaints(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_ended ON giveaways(ended)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trading_posts_guild_status ON trading_posts(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trading_posts_status_expires ON trading_posts(status, expires_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_log_channels_guild_type ON log_channels(guild_id, log_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_auto_mod_settings_guild ON auto_mod_settings(guild_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_command_usage_user ON command_usage_stats(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_role_panels_msg ON role_panels(guild_id, message_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_auto_mod_spam_tracking_guild_user ON auto_mod_spam_tracking(guild_id, user_id)")

            # Tickets
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_channel_status ON tickets(channel_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_guild_user ON tickets(guild_id, user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket ON ticket_notes(ticket_id)")

            # Events
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_guild_start ON events(guild_id, start_ts)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_guild_end ON events(guild_id, end_ts)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_rsvps_message ON event_rsvps(guild_id, message_id)")

            # LFG
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lfg_posts_status_expires ON lfg_posts(status, expires_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lfg_rsvps_lfg ON lfg_rsvps(lfg_id)")
            
            await db.commit()
            logger.info("[db] Indexes created successfully")
        except Exception as e:
            logger.warning(f"[db] Error creating indexes (may already exist): {e}")
        
        await db.commit()
        logger.info("[db] Database tables initialized successfully")
