# Deploy / hosting files

| File | Purpose |
|------|---------|
| `Procfile` | Heroku-style process (Worker: `python run.py` from repo root) |
| `requirements.txt` | Python dependencies |
| `runtime.txt` | Python version pin (3.11.11) |
| `mise.toml` | Mise/Railpack Python install settings |
| `nixpacks.toml` | Nixpacks build plan (install + env vars) |

Railway reads **`railway.toml`** at the repo root, which points here via `nixpacksConfigPath` and `startCommand`.

If Railpack does not pick up `mise.toml`, set a Railway variable:

`MISE_OVERRIDE_CONFIG_FILENAMES=deploy/mise.toml`
