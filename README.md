# POE Toolkit

A unified Path of Exile helper application combining multiple tools into a single, modern interface.

![Version](https://img.shields.io/badge/Version-1.6.0-blue.svg)
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
- **Unique Tab Workflow**: Guided clipboard-based workflow for unique stash tabs

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
- Fail-closed controller lease and verified browser-worker cleanup on Stop

### 🩺 Diagnostics & Data Freshness
Inspect application health without displaying account names, session tokens, or
cached item contents:
- Active game/league, shared services, workers, Client.txt, and zone monitor
- Explicit Node/npm, Tesseract, and local DevTools readiness tests
- Price/dust cache source, league, schema, age, and item count
- Open runtime directories, clear only per-user caches, and export redacted JSON
- Dependency probes run only when requested and use cancellable bounded workers

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
│   └── utils/                  # Config, logging, helpers
├── trade_service/              # Node.js trade service
├── config/
│   ├── config.json             # Shareable settings (presets, keywords)
│   └── user_config.template.json  # Template for new users
├── setup.bat                   # Easy setup launcher (double-click)
├── setup.ps1                   # PowerShell setup script
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

2. **Run the setup script** (as Administrator)
   ```powershell
   # Double-click setup.bat, or run:
   .\setup.bat
   ```
   
   The setup script will automatically:
   - ✅ Check for Python 3.10+, Node.js 18+, Tesseract OCR, Brave Browser
   - ✅ Install any missing prerequisites via winget
   - ✅ Create your private per-user `user_config.json` from template (won't overwrite existing)
   - ✅ Install Python dependencies (`pip install`)
   - ✅ Install Node.js dependencies (`npm install`)
   
   > **Note:** Safe to run multiple times - only installs what's missing!

3. **Use the toolkit Settings page**, or edit the per-user config path listed under Configuration:
   - `session_id` - Your POESESSID cookie from pathofexile.com
   - `account_name` - Your PoE account name  
   - `league` - Current league name
   - `client_log_path` - Path to your PoE Client.txt log file

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
pip install -r requirements.txt

# Install Node.js dependencies (for Trade Sniper)
cd trade_service
npm install
cd ..
```

</details>

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
| `config/config.json` | Shipped defaults and shareable presets | ✅ Tracked and never rewritten at runtime |
| Per-user `user_config.json` | All mutable settings, credentials, paths, and calibration | Outside the checkout |

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

The app version is defined in `src/utils/__init__.py` as `APP_VERSION` and displayed in the UI sidebar. Every commit that changes application behavior must include a version bump following semver (MAJOR.MINOR.PATCH).

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Credits

This toolkit consolidates and improves upon:
- Ultimatum stash scanning logic
- OCR-based league mechanic detection
- Trade live search automation
