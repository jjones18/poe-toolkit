# POE Toolkit

A unified Path of Exile helper application combining multiple tools into a single, modern interface.

![Version](https://img.shields.io/badge/Version-1.1.0-blue.svg)
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
│   ├── user_config.json        # Your PC-specific settings (gitignored)
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
   - ✅ Create your `user_config.json` from template (won't overwrite existing)
   - ✅ Install Python dependencies (`pip install`)
   - ✅ Install Node.js dependencies (`npm install`)
   
   > **Note:** Safe to run multiple times - only installs what's missing!

3. **Edit `config/user_config.json`** with your settings:
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

# Create user config
copy config\user_config.template.json config\user_config.json

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

Settings are split into two files:

| File | Purpose | Git Status |
|------|---------|------------|
| `config.json` | Shareable presets, keywords, thresholds | ✅ Tracked |
| `user_config.json` | Personal settings (credentials, paths, calibration) | ❌ Gitignored |

Your personal settings stay private while filter presets can be shared.

---

## 🛠️ Development

Each tool follows the `BaseTool` interface in `src/tools/base_tool.py`.

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
