# Bot.py Refactoring Plan

## Current Status
- `bot.py`: ~3232 lines (very large, slow to load)
- Goal: Split into modular files for better performance and maintainability

## Modules to Create

### ✅ Completed
1. **database.py** - All database functions (economy, XP, guild settings)
2. **warframe_api.py** - Warframe API functions
3. **channels.py** - Channel resolution and management

### 🔄 In Progress
4. **views.py** - All View classes (VCPanelView, ComplaintModView, RSVPView, etc.)
5. **modals.py** - All Modal classes (RenameVCModal, InviteModal, ComplaintModal, etc.)
6. **tasks.py** - Background tasks (baro_check_loop, cycle_check_loop, etc.)

### 📋 To Do
7. Update `bot.py` to import from new modules
8. Remove moved code from `bot.py`
9. Test that everything still works

## Expected Benefits
- Faster bot startup (smaller files load faster)
- Better code organization
- Easier to maintain and debug
- Reduced memory footprint
