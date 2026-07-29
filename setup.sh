#!/usr/bin/env bash
# Reproducible Linux source-checkout setup for POE Toolkit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

info() { printf '[*] %s\n' "$*"; }
ok() { printf '[+] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
fail() { printf '[-] %s\n' "$*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null 2>&1 || fail "Python 3.10+ is required."
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10+ is required."
command -v node >/dev/null 2>&1 || fail "Node.js 18+ is required for Trade Sniper."
node -e 'const major=Number(process.versions.node.split(".")[0]); process.exit(major >= 18 ? 0 : 1)' \
  || fail "Node.js 18+ is required for Trade Sniper."
command -v npm >/dev/null 2>&1 || fail "npm is required for Trade Sniper."

VENV="$ROOT/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  info "Creating $VENV"
  "$PYTHON" -m venv "$VENV"
fi
info "Installing locked-compatible Python runtime dependencies"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -e '.[full]'

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/poe-toolkit"
USER_CONFIG="$CONFIG_HOME/user_config.json"
mkdir -p "$CONFIG_HOME"
chmod 700 "$CONFIG_HOME"
if [[ ! -f "$USER_CONFIG" ]]; then
  install -m 600 "$ROOT/config/user_config.template.json" "$USER_CONFIG"
  ok "Created private config: $USER_CONFIG"
else
  ok "Preserved existing config: $USER_CONFIG"
fi

info "Installing Node dependencies from package-lock.json"
(
  cd "$ROOT/trade_service"
  npm ci
)

command -v tesseract >/dev/null 2>&1 \
  || warn "Tesseract is not installed; OCR features will show an actionable unavailable state."
if ! command -v brave-browser >/dev/null 2>&1 && ! command -v brave >/dev/null 2>&1; then
  warn "Brave was not found; install it before using Trade Sniper."
fi

ok "Setup complete"
printf 'Run: %q %q\n' "$VENV/bin/python" "$ROOT/src/main.py"
