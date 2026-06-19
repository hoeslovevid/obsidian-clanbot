"""
Background tasks package.

All periodic task loops are defined in tasks/_core.py as closures inside
setup_tasks(bot). Call setup_tasks(bot) once after the bot is ready to
start all background loops.

Domain grouping (future: split _core.py further into sub-modules):
  warframe   baro_check_loop, baro_live_update_loop, cycle_check_loop,
             invasion_check_loop, archon_check_loop, warframe_achievement_roles_loop,
             alert_check_loop, devstream_check_loop, lfg_expire_loop
             (Baro arrival notify: tasks/wf_notify.py)
  economy    giveaway_check_loop, voice_reward_loop, daily_streak_reminder_loop,
             pet_decay_reminder_loop
  xp         (XP tasks are embedded inside voice_reward_loop)
  moderation stale_ticket_reminder_loop
  events     event_reminder_loop, recurring_event_loop, event_end_loop,
             reminder_check_loop, scheduled_messages_loop, forum_check_loop,
             youtube_check_loop, twitch_check_loop, member_count_update_loop,
             server_stats_update_loop, temp_vc_cleanup
"""
from tasks._core import setup_tasks  # noqa: F401
