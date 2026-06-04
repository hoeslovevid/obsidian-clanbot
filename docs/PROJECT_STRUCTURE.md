# Project structure

Keep the repo organized by **folder**, not loose files at the root. When adding something new, put it in the matching directory below instead of creating another top-level file.

## Where to put new files

| You are adding… | Put it in… | Examples |
|-----------------|------------|----------|
| Slash command | `commands/<category>/` | `commands/general/foo.py` |
| Shared bot logic | `core/` | helpers, config, loaders, modals |
| Discord UI (views) | `views/` | buttons, panels |
| Background loops | `tasks/` | scheduled checks |
| Event / interaction handlers | `handlers/` | startup, modals, components |
| HTTP / external APIs | `api/` | Warframe API client |
| Database tables / queries | `database/` | schema, accessors |
| Bot class & events | `bot/` | `bot/app.py` |
| Secrets & ignore rules | `config/` | `.env`, `.gitignore` |
| SQLite / exports | `data/` | `.db`, `.gitkeep` |
| Deploy / hosting | `deploy/` | `requirements.txt`, `Procfile`, `mise.toml`, `railpack.json` |
| Documentation | `docs/` | guides, plans, this file |

## Root directory (keep minimal)

Only these should live at the repo root. Everything else belongs in a folder above.

| File | Why it stays at root |
|------|----------------------|
| `run.py` | Process entry point (`python run.py`) |
| `README.md` | Short pointer to `docs/README.md` |
| `railway.toml` | Railway config-as-code (must be at repo root) |
| `railpack.json` | Railpack config (must be at repo root unless `RAILPACK_CONFIG_FILE` is set) |
| `requirements.txt` | Hard link → `deploy/requirements.txt` (Railpack detection) |
| `runtime.txt` | Hard link → `deploy/runtime.txt` |
| `mise.toml` | Hard link → `deploy/mise.toml` |
| `.gitignore` | Hard link → `config/.gitignore` (Git only applies root ignore rules globally) |

**Edit the real file** in `deploy/` or `config/` when changing requirements, Python version, mise, or ignore rules—the root names are links for tooling, not a second copy.

## Adding deploy or config files

1. Create or edit under `deploy/` or `config/`.
2. If Railpack/Mise/Git need a root name, add or refresh a **hard link** at the root (do not duplicate content).
3. Update `docs/DEPLOYMENT.md` or `deploy/README.md` if Railway/env behavior changes.

## Adding Python modules

- Prefer an existing package (`core`, `commands`, `handlers`, …).
- New command categories: `commands/<new_category>/` with `__init__.py`.
- Avoid new top-level `.py` files next to `run.py`.

## Layout reference

```
obsidian_clanbot/
├── run.py                 # entry only
├── README.md
├── railway.toml
├── railpack.json
├── bot/                   # ClanBot + events (bot/app.py)
├── commands/              # slash commands by category
├── core/                  # config, utils, loaders, modals, …
├── database/
├── handlers/
├── tasks/
├── views/
├── api/
├── config/                # .env, .gitignore (canonical)
├── data/                  # SQLite default path
├── deploy/                # requirements, Procfile, mise, nixpacks (canonical)
└── docs/                  # all markdown guides
```
