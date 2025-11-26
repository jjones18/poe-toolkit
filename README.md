# POE Toolkit

A unified Path of Exile helper application combining multiple tools into a single, modern interface.

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
└── requirements.txt
```

---

## 🚀 Installation

### Prerequisites
- **Python 3.10+**
- **Node.js 18+** (for Trade Sniper)
- **Tesseract OCR** (for League Vision) - [Download](https://github.com/UB-Mannheim/tesseract/wiki)
- **Brave Browser** (for Trade Sniper)

### Setup

1. **Clone the repository**
   ```powershell
   git clone https://github.com/jjones18/poe-toolkit.git
   cd poe-toolkit
   ```

2. **Install Python dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Create your user config**
   ```powershell
   copy config\user_config.template.json config\user_config.json
   ```

4. **Edit `config/user_config.json`** with your settings:
   - `session_id` - Your POESESSID cookie from pathofexile.com
   - `account_name` - Your PoE account name
   - `league` - Current league name
   - `client_log_path` - Path to your PoE Client.txt log file

5. **For Trade Sniper** - Install Node.js dependencies:
   ```powershell
   cd trade_service
   npm install
   cd ..
   ```

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

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Credits

This toolkit consolidates and improves upon:
- Ultimatum stash scanning logic
- OCR-based league mechanic detection
- Trade live search automation
