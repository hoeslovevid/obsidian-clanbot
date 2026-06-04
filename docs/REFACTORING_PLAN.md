# Bot.py Refactoring Plan

## Current Status
- `bot/app.py`: event handlers inline; command loading extracted
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
8. **commands_loader.py** - Command loading and group registration (~260 lines extracted)

### ✅ Load/Deploy Optimizations
9. **Deferred imports** - tasks, version_tracking lazy-loaded in on_ready
10. **Single config source** - database.py uses config.DB_PATH

### 📋 Structure (clean)

See **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** for the full layout and rules for new files.

## What Stays in bot/app.py (by design)
- ClanBot class + bot instance
- Event handlers (@bot.event) - require bot reference
- Helpers used by events: check_auto_mod, post_vc_panel, log_complaint_action, format_thread_name
- incident_mode_check + install
- main() entry point

## Future (optional)
- Extract handlers to handlers/ with lazy-load wrappers for faster cold start
- Extract helpers to core/ package
