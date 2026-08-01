# POE Toolkit

A unified Path of Exile helper application combining multiple tools into a single, modern interface.

![Version](https://img.shields.io/badge/Version-1.8.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Node.js](https://img.shields.io/badge/Node.js-18+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ Features

### 🎰 Ultimatum Helper
Scan your stash tabs for profitable Inscribed Ultimatums with real-time poe.ninja pricing.
- Automatic profit calculation
- Configurable filters (encounter types, rewards, monster life tiers)
- Visual overlay highlighting profitable items in your stash

### 🏺 Kalguur Dust Helper
Optimize your Thaumaturgic Dust disenchanting:
- Scan stash tabs for high-value unique items (Dust/Chaos ratio)
- **Multi-Tab Support**: Automatically highlights items across multiple tabs
- **OCR Tab Detection**: Smart detection of your current stash tab

### 👁️ League Vision
OCR-based screen scanning for various league mechanics:
- **Map Safety Check** - Detect dangerous map mods
- **Syndicate Board** - Track member positions and goals
- **Eldritch Altars** - Highlight valuable altar rewards
- **Expedition** - Warn about dangerous remnant mods
- **Ritual/Essence** - Detect valuable encounters

### 🎯 Trade Sniper
Automated live search monitoring with browser integration:
- Connects to your existing Brave browser session
- Auto-clicks "Travel to Hideout" on new listings
- Supports multiple live search tabs simultaneously
- Pause/resume functionality
- Adjustable auto-resume delay and teleport cooldown, both live-updated while running
- Client.txt zone safety blocks Travel and confirmation clicks outside allowed towns/hideouts
- Unknown areas and missing logs fail closed; neighboring **Allow Current Zone** / **Remove Current Zone** buttons manage newly verified hubs for the active game while Trade Sniper is running
- Built-in and custom zone details: [Trade Sniper zone safety](docs/TRADE_SNIPER_ZONE_SAFETY.md)
- Fail-closed controller lease and verified browser-worker cleanup on Stop

### 🩺 Diagnostics & Data Freshness
Inspect application health without displaying account names, session tokens, or
cached item contents:
- Active game/league, shared services, workers, Client.txt, and zone monitor
- Explicit Node/npm, Tesseract, and local DevTools readiness tests
- Price/dust cache game, league, source, schema, status, age, and item count
- Open runtime directories, clear only per-user caches, and export redacted JSON
- Dependency probes run only when requested and use cancellable bounded workers

### 📊 Shared Price & Dust Data
- One application-owned, game/league-aware price service is shared by valuation tools
- Price entries are keyed by game, league, source, endpoint set, and schema
- Cache read/modify/write is serialized across threads/processes and written atomically
- Refreshes use bounded requests and report cache, success, partial, or failure outcomes
- Partial/failed refreshes retain the active and on-disk last-known-good snapshot
- Unknown prices remain distinct from known zero values, render as `—`, and are excluded by default
- Explicit include overrides still win; Kalguur Dust can optionally display unknown-price items
- Bundled 2025 dust estimates are explicitly labeled stale and estimated
- Reload/close fails closed if a legacy league-tool thread does not stop within its bounded wait

---

## 📁 Project Structure

```
poe-toolkit/
├── src/
│   ├── main.py                 # Application entry point
│   ├── api/                    # POE API client
│   ├── core/                   # Pricing, parsing, filters
│   ├── services/               # Background services
│   ├── ui/
│   │   ├── main_window.py      # Main application shell
│   │   ├── overlay.py          # Transparent overlay system
│   │   └── components/         # Reusable UI widgets
│   ├── tools/                  # Tool modules (plugins)
│   │   ├── ultimatum/          # Ultimatum helper
│   │   ├── league_vision/      # OCR vision tool
│   │   └── trade_sniper/       # Trade automation
│   └── utils/                  # Config, logging, helpers + immutable defaults
├── trade_service/              # Node.js trade service
├── config/
│   └── user_config.template.json  # Template for new users
├── setup.bat                   # Easy setup launcher (double-click)
├── packaging/                  # PyInstaller spec
├── docs/WINDOWS_SETUP.md        # Fresh Windows install/release setup
├── setup.ps1                   # PowerShell setup script
├── pyproject.toml              # Install metadata and optional extras
└── requirements.txt
```

---

## 🚀 Installation

### Quick Setup (Recommended)

1. **Clone the repository**
   ```powershell
   git clone https://github.com/jjones18/poe-toolkit.git
   cd poe-toolkit
   ```

2. **Run the setup script**
   ```powershell
   # Double-click setup.bat, or run from a normal PowerShell session:
   .\setup.bat
   ```
   
   The setup script will automatically:
   - ✅ Check for Python 3.10+, Node.js 18+, Tesseract OCR, and Brave Browser
   - ✅ Install missing prerequisites through winget
   - ✅ Create a private `.venv`
   - ✅ Create your private per-user `user_config.json` from the template without overwriting it
   - ✅ Install Python dependencies into `.venv`
   - ✅ Install exact Node dependencies with `npm ci`
   
   > **Note:** The script is safe to rerun and does not require an Administrator PowerShell window.

3. **Use the toolkit Settings page**, or edit the per-user config path listed under Configuration:
   - `credentials.session_id` and `credentials.account_name` - shared by PoE 1 and PoE 2
   - `game_settings.<game>.league` - current league for that game
   - `game_settings.<game>.client_log_path` - that game's own Client.txt log

   The Settings page's **Active toolkit** selector switches the league and
   Client.txt fields together. Unsaved edits are retained while switching, and
   saving persists the independent PoE 1 and PoE 2 values.

### Manual Setup

If you prefer manual installation:

<details>
<summary>Click to expand manual steps</summary>

**Prerequisites:**
- [Python 3.10+](https://python.org)
- [Node.js 18+](https://nodejs.org) (for Trade Sniper)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (for League Vision)
- [Brave Browser](https://brave.com) (for Trade Sniper)

**Steps:**
```powershell
# Install Python dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[full]

# Install Node.js dependencies (for Trade Sniper)
cd trade_service
npm ci
cd ..
```

</details>

### Packaging and local verification

POE Toolkit 1.8.0 includes install metadata and a checked-in `uv.lock`. Use `uv sync --locked` for the core UI/API environment, or `uv sync --locked --extra full` for all runtime OCR/capture, overlay/input, and platform integrations. Packaging and test dependencies remain explicit extras; the Node service is independently locked by `trade_service/package-lock.json`. `requirements.txt` remains a bounded full-runtime compatibility list for existing pip workflows.

Optional features degrade loudly and actionably: missing OCR/capture/input/platform modules are reported with the relevant extra (for example `pip install .[capture]`) instead of blocking basic app startup.

Release smoke checks:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests
python -m compileall -q src tests scripts
python scripts/check_version_consistency.py
python scripts/check_packaging_assets.py
python scripts/check_no_mutable_checkout_data.py
python src/main.py --package-smoke
cd trade_service; npm ci; npm test; npm run check
```

PyInstaller builds use `packaging/poe_toolkit.spec`, bundle immutable defaults/templates/assets/data and trade-service JS/package files, and exclude mutable user data/secrets (`config/config.json`, `user_config.json`, caches, Brave profile, and `node_modules`). Run the frozen binary smoke check locally before sharing a build. See `docs/WINDOWS_SETUP.md` and `docs/RELEASE.md`.

---

## 💻 Usage

```powershell
python src/main.py
```

### First-Time Setup

1. **Calibrate Stash Overlay**: Settings menu → "Calibrate Stash"
   - Click the top-left corner of your stash grid
   - Click the bottom-right corner
   
2. **Configure Filters**: Use the "Configure Filters" button in Ultimatum tab

3. **Trade Sniper Setup**:
   - Click "Launch Brave (Debug Mode)"
   - Login to pathofexile.com/trade
   - Open your live search tabs
   - Click "Start Service"

---

## ⚙️ Configuration

Configuration has a read-only checked-in base and a private per-user override:

| File | Purpose | Git Status |
|------|---------|------------|
| `src/utils/default_config.json` | Immutable package defaults and shareable presets | ✅ Tracked and read-only at runtime |
| `config/config.json` | Legacy checkout-local file; never packaged or read by 1.8.0 | ✅ Preserved for compatibility only |
| Per-user `user_config.json` | All mutable settings, credentials, paths, and calibration | Outside the checkout |

Stash grid calibration uses explicit named profiles: Standard (12x12) and Quad (24x24). The app previews the full grid and only persists calibration after confirmation.

Per-user locations:

- Windows: `%APPDATA%\poe-toolkit\user_config.json`
- Linux: `$XDG_CONFIG_HOME/poe-toolkit/user_config.json`, or `~/.config/poe-toolkit/user_config.json`
- macOS: `~/Library/Application Support/poe-toolkit/user_config.json`

Existing `config/user_config.json` files are migrated automatically only when no new-location config exists. A successful migration verifies the new file before removing the legacy copy. Linux files use mode `0600` inside a `0700` directory; the Windows installer restricts the directory ACL to the current user.

Saves use a same-directory temporary file, `fsync`, and atomic replacement. Before replacing a valid config, the toolkit stores `user_config.json.bak` as the last-known-good copy. If the primary is malformed, the backup is loaded with a visible warning; if neither is valid, saves remain blocked so application shutdown cannot overwrite the damaged file with defaults.

Mutable runtime data also stays outside the checkout:

- Windows: caches/logs under `%LOCALAPPDATA%\poe-toolkit`
- Linux: caches under `$XDG_CACHE_HOME/poe-toolkit` and logs under `$XDG_STATE_HOME/poe-toolkit/logs`
- macOS: caches under `~/Library/Caches/poe-toolkit` and logs under `~/Library/Logs/poe-toolkit`

Legacy checkout-local price and dust caches are migrated once. A valid existing
per-user destination wins; otherwise the newest valid legacy cache is copied
atomically and verified before checkout duplicates are removed. Debug logs and
opt-in screenshots use the per-user log/cache directories, and screenshot
retention is bounded. If the per-user cache is malformed but a valid legacy
cache exists, the malformed file is preserved with a `.invalid` suffix before
recovery.

Price and dust caches use schema-v2 provenance. Before the first schema-v2
replacement, a valid unversioned cache is preserved byte-for-byte as
`.legacy-v1`. Cache and compatibility-backup writes use same-directory atomic
replacement plus file and directory durability barriers.

---

## 🛠️ Development

Each tool follows the `BaseTool` interface in `src/tools/base_tool.py`.

Background operations use `src/utils/workers.py`. Operations receive a
`WorkerContext`, report progress through it, use its interruptible `sleep`, and
must not call GUI APIs directly. External HTTP, OCR, and subprocess work must
use the bounded adapters. Tool cleanup returns `False` only when worker
shutdown could not be verified; reload/close then aborts before deleting the
widget.

To add a new tool:
1. Create a folder under `src/tools/`
2. Implement the `BaseTool` interface
3. Register it in `main_window.py`

### Versioning

The app version is defined in `src/utils/__init__.py` as `APP_VERSION` and displayed in the UI sidebar. Update it, the README badge, and the checked release markers together when preparing a release, following semantic versioning (MAJOR.MINOR.PATCH). Routine commits within the same planned release do not each require a separate version bump.

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Credits

This toolkit consolidates and improves upon:
- Ultimatum stash scanning logic
- OCR-based league mechanic detection
- Trade live search automation
