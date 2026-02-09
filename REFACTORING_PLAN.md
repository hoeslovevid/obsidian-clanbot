# Bot.py Refactoring Plan

## Current Status
- `bot.py`: ~3300 lines (event handlers still inline; config + deferred imports done)
- Goal: Split into modular files for better performance and maintainability

## Modules Created

### ✅ Completed
1. **config.py** - All env vars (TOKEN, GUILD_ID, economy, channels, etc.)
2. **database.py** - All database functions (economy, XP, guild settings)
3. **warframe_api.py** - Warframe API functions
4. **channels.py** - Channel resolution and management
5. **views.py** - All View classes (VCPanelView, ComplaintModView, RSVPView, etc.)
6. **modals.py** - All Modal classes (RenameVCModal, InviteModal, ComplaintModal, etc.)
7. **tasks.py** - Background tasks (baro_check_loop, cycle_check_loop, etc.)

### ✅ Load/Deploy Optimizations (Jan 2025)
8. **Deferred imports**
   - `tasks.py` and `version_tracking.check_and_post_updates` are lazy-imported in `on_ready` (saves ~2k lines at startup)
   - `warframe_api` removed from bot.py (only used by tasks/commands)
   - `detect_and_update_version` wrapped so `version_tracking` loads only when `/force_version_update` runs
9. **Single config source** - `database.py` uses `config.DB_PATH`; `bot.py` imports from `config`

## Expected Benefits
- Faster bot startup (tasks/version_tracking load after connect)
- Lower memory at cold start
- Better code organization
- Easier to maintain and debug
