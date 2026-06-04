# Deploy / hosting files

Canonical copies of Python/deploy config live here. Root **`requirements.txt`**, **`runtime.txt`**, and **`mise.toml`** are hard links to these files so [Railpack](https://railpack.com) can auto-detect Python and install dependencies.

| File | Purpose |
|------|---------|
| `Procfile` | Heroku-style process (Worker: `python run.py` from repo root) |
| `requirements.txt` | Python dependencies |
| `runtime.txt` | Python version pin (3.11.11) |
| `mise.toml` | Mise/Railpack Python install settings |
| `nixpacks.toml` | Legacy Nixpacks plan only (if a service still uses Nixpacks) |

## Railway (Railpack)

Root **`railway.toml`** sets `builder = "RAILPACK"`. Root **`railpack.json`** pins Python 3.11.11 and `python run.py`.

Do not set `builder = "nixpacks"` or `nixpacksConfigPath` unless you intentionally use the legacy builder.

### mise attestation errors

If builds mention `MISE_PYTHON_GITHUB_ATTESTATIONS`, set:

```
MISE_PYTHON_GITHUB_ATTESTATIONS=false
```

(Railpack reads this from `mise.toml` in deploy/.)
