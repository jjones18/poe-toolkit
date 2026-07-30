# Windows setup and packaging notes for POE Toolkit 1.8.0

## Prerequisites

- Windows 10/11 with `winget` for automatic prerequisite installation.
- Python 3.10+ (the setup script prefers 3.12).
- Node.js 18+ for Trade Sniper.
- Brave Browser for Trade Sniper DevTools automation.
- Tesseract OCR for League Vision and Kalguur tab OCR.

The setup script installs missing external prerequisites through `winget`; it does not download unsigned executables directly.

## Fresh checkout install

```powershell
git clone https://github.com/jjones18/poe-toolkit.git
cd poe-toolkit
.\setup.ps1
```

No Administrator PowerShell window is required. The script creates `.venv`, installs the bounded `.[full]` runtime set, runs `npm ci`, and creates the private config at `%APPDATA%\poe-toolkit\user_config.json`. Existing user config is preserved unless `-Force` is explicitly supplied.

The checkout remains read-only at runtime. Do not put POESESSID, account names, Brave profiles, cache files, or `node_modules` into the repository tree.

## Optional feature groups

- Core app: `pip install -e .`
- OCR/capture: `pip install -e .[capture]` plus Tesseract executable.
- Overlay/input hooks: `pip install -e .[overlay-input]`.
- Platform integration: `pip install -e .[platform]`.
- Full runtime: `pip install -e .[full]`.
- Packaging: `pip install -e .[packaging]`.

If an optional module is absent, affected tools remain represented in navigation and show an actionable missing-extra message instead of preventing basic startup.

## Locked development and release environment

The checked-in `uv.lock` is the reproducible Python dependency source used by local development and release builds:

```powershell
uv sync --locked --extra full --extra test --extra packaging
```

Node dependencies are independently locked by `trade_service\package-lock.json` and installed with `npm ci`.

## Smoke and release checks

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
uv run --locked python -m unittest discover -s tests
uv run --locked python -m compileall -q src tests scripts
uv run --locked python scripts/check_version_consistency.py
uv run --locked python scripts/check_packaging_assets.py
uv run --locked python scripts/check_no_mutable_checkout_data.py
uv run --locked python src/main.py --package-smoke
cd trade_service
npm ci
npm test
npm run check
npm audit --audit-level=high
```

## Building and exercising the app

```powershell
cd ..
uv run --locked pyinstaller --noconfirm --clean packaging/poe_toolkit.spec
uv run --locked python scripts/run_frozen_smoke.py dist
```

The one-directory build contains immutable defaults/templates/data and trade-service JavaScript/package files. It excludes legacy `config/config.json`, mutable user config, caches, Brave profiles, secrets, and `node_modules`. Run the frozen smoke check before sharing the generated build.
