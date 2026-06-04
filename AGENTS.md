# Agent instructions (Obsidian Clan Bot)

## Organization (required)

**Put new files in folders—do not add loose files at the repo root.**

Use [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for the full map. Quick reference:

- Commands → `commands/<category>/`
- Shared logic → `core/`
- Views / tasks / handlers / api / database → matching package
- Bot orchestration → `bot/`
- Env & gitignore → `config/`
- Data files → `data/`
- Deploy (requirements, Procfile, mise, railpack) → `deploy/`
- Markdown docs → `docs/`

Root is only for: `run.py`, `README.md`, `railway.toml`, `railpack.json`, and hard links (`requirements.txt`, `runtime.txt`, `mise.toml`, `.gitignore`) that point into `deploy/` or `config/`.

When editing requirements or ignore rules, change files under `deploy/` or `config/`, not duplicate at root.

## Code conventions

- Match existing import style (`from core.config import …`, `from database import …`).
- Keep changes minimal; do not refactor unrelated code.
- Railway builds with **Railpack** (`railway.toml` → `builder = "RAILPACK"`). Do not switch back to Nixpacks unless asked.

## Docs & commits

- Update `docs/` when setup or deploy steps change.
- Only commit or push when the user asks.
