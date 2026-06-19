# Command tree budget

Discord limits each **slash command group** to **25 subcommands** and roughly **8000 bytes** of serialized payload per group. This bot registers most commands globally (`guild=None`).

## Before adding a command

1. Run **`/admin health`** (mods) and check the command-tree field, or inspect startup logs after deploy.
2. Count subcommands for the target group — stay **≤ 23** when possible (headroom for the next feature).
3. Prefer a **top-level shortcut** (`/daily`, `/menu`, `/search`) when the parent group is at cap — see `core/command_shortcuts.py`.
4. Do **not** add to `/general` when it is at 25 — use shortcuts or a dedicated top-level group.

## Where new commands go

| Use case | Placement |
|----------|-----------|
| Member-facing, high traffic | Top-level shortcut + optional group subcommand |
| Themed bundle (economy, warframe) | Matching `app_commands.Group` if under 23 subcommands |
| Mod-only tool | `/mod`, `/admin`, `/warn`, etc. — never in member help defaults |
| Rare contextual action | Context menu (`commands/context_menus.py`) |
| Warframe notify UX | `/wfnotify` — prefer **`/wfnotify configure`** or `post_panel` over many one-off subs |

## Groups at cap (historical)

- **`/general`** — at 25; `/status` and several tools are top-level only.
- **`/tools`** — at 25; favorites are `/favorite_add`, `/favorites`, etc.

## Implementation references

Run before deploy or in CI:

```bash
python tools/check_command_tree.py
```

Exits non-zero if any group exceeds Discord's 25-subcommand cap.
- Stats: `core/command_tree_stats.py` — `collect_command_tree_stats(bot)`.
- Discovery filters: `core/command_search.py` — feature toggles and mod-only groups for `/search` and `/help`.

## Release checklist

- [ ] No group over 25 subcommands
- [ ] `py_compile` / import smoke on touched command modules
- [ ] Bump `BOT_VERSION` + `core/changelog.py` when user-visible
