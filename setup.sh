#!/usr/bin/env bash
# POE Toolkit - Linux Setup Script
# Run once after cloning: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[-]${NC} $1"; }
info() { echo -e "${CYAN}[*]${NC} $1"; }

echo ""
echo "========================================"
echo "      POE Toolkit - Linux Setup        "
echo "========================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Detect package manager ────────────────────────────────────────────────────
if command -v paru &>/dev/null; then
    PKG="paru -S"
elif command -v pacman &>/dev/null; then
    PKG="sudo pacman -S"
elif command -v apt &>/dev/null; then
    PKG="sudo apt install"
elif command -v dnf &>/dev/null; then
    PKG="sudo dnf install"
else
    PKG="<your package manager>"
fi

install_hint() { echo -e "    ${CYAN}$PKG $1${NC}"; }

# ── Python ────────────────────────────────────────────────────────────────────
info "Checking Python..."
if ! command -v python3 &>/dev/null; then
    err "Python 3 not found. Install it:"
    install_hint "python"
    exit 1
fi
PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PYTHON_VER found"

# ── Tesseract ─────────────────────────────────────────────────────────────────
info "Checking Tesseract OCR..."
if command -v tesseract &>/dev/null; then
    ok "Tesseract found: $(tesseract --version 2>&1 | head -1)"
else
    warn "Tesseract not found. Install it:"
    install_hint "tesseract"
    warn "League Vision and Kalguur Dust OCR features will not work without it."
fi

# ── Node.js ───────────────────────────────────────────────────────────────────
info "Checking Node.js (required for Trade Sniper)..."
if command -v node &>/dev/null; then
    ok "Node.js found: $(node --version)"
else
    warn "Node.js not found. Trade Sniper will not work without it."
    install_hint "nodejs npm"
fi

# ── Brave browser ─────────────────────────────────────────────────────────────
info "Checking Brave browser (required for Trade Sniper)..."
BRAVE_FOUND=0
for path in /usr/bin/brave-browser /usr/bin/brave /opt/brave.com/brave/brave-browser /snap/bin/brave ~/.local/bin/brave-browser; do
    if [ -f "$path" ]; then
        ok "Brave found at $path"
        BRAVE_FOUND=1
        break
    fi
done
if [ "$BRAVE_FOUND" -eq 0 ]; then
    warn "Brave not found. Trade Sniper will not work without it."
    install_hint "brave-bin"   # AUR name; apt: brave-browser
    warn "Or install from https://brave.com/linux/"
fi

# ── xdotool (optional, window detection fallback) ─────────────────────────────
info "Checking xdotool (optional, improves window detection)..."
if command -v xdotool &>/dev/null; then
    ok "xdotool found"
else
    warn "xdotool not found. Window auto-detection will rely on python-xlib only."
    install_hint "xdotool"
fi

# ── Virtual environment ───────────────────────────────────────────────────────
info "Setting up Python virtual environment..."
if [ ! -f "venv/bin/activate" ]; then
    [ -d "venv" ] && rm -rf venv  # Remove broken/incomplete venv if present
    python3 -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

source venv/bin/activate

# ── pip dependencies ──────────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt
ok "Python dependencies installed"

# ── npm dependencies ──────────────────────────────────────────────────────────
if [ -d "trade_service" ] && command -v npm &>/dev/null; then
    info "Installing npm dependencies for Trade Sniper..."
    cd trade_service
    npm install --silent
    cd ..
    ok "npm dependencies installed"
fi

# ── User config ───────────────────────────────────────────────────────────────
if [ ! -f "config/user_config.json" ]; then
    cp config/user_config.template.json config/user_config.json
    ok "Created config/user_config.json from template"
    warn "Edit config/user_config.json and fill in your POESESSID and account name."
    warn "Set 'client_log_path' to your PoE Client.txt path (check your Wine/Proton prefix)."
else
    ok "config/user_config.json already exists (not overwritten)"
fi

echo ""
echo "========================================"
ok "Setup complete!"
echo ""
info "To run the toolkit:"
echo "    source venv/bin/activate"
echo "    python src/main.py"
echo ""
info "Notes:"
echo "  - Shift+Esc hotkey uses pynput automatically (no root needed)."
echo "  - Screen capture requires X11. Use XWayland if on Wayland."
echo "  - Set PoE to 'Windowed Fullscreen' for best screen capture compatibility."
echo "========================================"
echo ""
