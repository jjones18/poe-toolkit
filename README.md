# POE Toolkit

A unified Path of Exile helper application combining multiple tools into a single, extensible interface.

## Features

- **Ultimatum Helper**: Scan stash tabs for profitable Inscribed Ultimatums with poe.ninja pricing
- **League Vision**: OCR-based screen scanning for Map Safety, Syndicate, Altars, Expedition, and more
- **Trade Sniper**: Control panel for automated live search monitoring

## Architecture

This project uses a modular plugin architecture where each tool is a self-contained module:

```
poe-toolkit/
├── src/
│   ├── main.py                 # Application entry point
│   ├── api/                    # POE API client, authentication
│   ├── core/                   # Pricing, parsing, shared logic
│   ├── services/               # Background services (zone monitor, price cache)
│   ├── ui/
│   │   ├── main_window.py      # Main application shell with sidebar
│   │   ├── overlay.py          # Unified overlay system
│   │   └── components/         # Reusable UI widgets
│   ├── tools/                  # Tool modules (plugins)
│   │   ├── base_tool.py        # Base class for tools
│   │   ├── ultimatum/          # Ultimatum helper
│   │   ├── league_vision/      # OCR vision tool
│   │   └── trade_sniper/       # Trade automation control
│   └── utils/                  # Config, logging, helpers
├── trade_service/              # Node.js trade automation service
├── config/                     # Configuration files
└── tests/                      # Unit tests
```

## Installation

1. **Python 3.10+** required
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. For League Vision OCR features, Tesseract must be installed
4. For Trade Sniper, Node.js 18+ is required

## Usage

```powershell
python src/main.py
```

## Source Projects

This toolkit consolidates functionality from:
- [poe-stash-merchant-helper](../poe-stash-merchant-helper) - Ultimatum stash scanning
- [poe-league-helper](../poe-league-helper) - OCR vision tool
- [poe-trade-automation](../poe-trade-automation) - Trade live search automation

## Development

Each tool module follows the `BaseTool` interface defined in `src/tools/base_tool.py`.
To add a new tool, create a new folder under `src/tools/` and implement the required interface.

