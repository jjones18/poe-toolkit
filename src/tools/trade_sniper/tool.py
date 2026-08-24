"""
Trade Sniper Tool - Control panel for trade automation service.
"""

import copy
import json
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QCheckBox, QSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from tools.base_tool import BaseTool
from services.trade_service import TradeService
from utils.config import ConfigManager, ConfigSaveError
from utils.workers import WorkerRegistry


ZONE_STATE_PREFIX = "__POE_TOOLKIT_ZONE_STATE__:"
AREA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def get_trade_profile_dir(platform_name=None, environ=None, home=None):
    """Return the per-user data directory for Trade Sniper's browser profile."""
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)

    if platform_name.startswith("win"):
        base = Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    elif platform_name == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "poe-toolkit" / "brave-profile"


def get_legacy_trade_profile_dir():
    """Return the pre-1.2 profile directory inside the repository checkout."""
    return Path(__file__).resolve().parents[3] / "trade_service" / "brave-profile"


def prepare_trade_profile_dir(target_dir=None, legacy_dir=None):
    """Create/migrate the profile, preserving the legacy path if a move is unsafe."""
    target = Path(target_dir) if target_dir is not None else get_trade_profile_dir()
    legacy = Path(legacy_dir) if legacy_dir is not None else get_legacy_trade_profile_dir()

    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if legacy.is_dir():
        try:
            shutil.move(str(legacy), str(target))
            return target
        except OSError:
            # A running browser can lock profile files on Windows. Never risk a
            # partial copy or a fresh logged-out profile; retry on a later launch.
            return legacy
    target.mkdir(parents=True, exist_ok=True)
    return target


def _is_pathofexile_trade_host(hostname: str) -> bool:
    """Strict host boundary shared with trade_monitor.js/page_worker.js.

    Accepts pathofexile.com, www.pathofexile.com, and subdomains; rejects
    suffix impostors like evilpathofexile.com and pathofexile.com.evil.io.
    """
    host = (hostname or "").lower()
    return (
        host == "pathofexile.com"
        or host == "www.pathofexile.com"
        or host.endswith(".pathofexile.com")
    )


def evaluate_devtools_readiness(version: dict, targets: list, trade_url: str):
    """Validate CDP identity and find a page under the selected game's trade path."""
    if not isinstance(version, dict) or not version.get("webSocketDebuggerUrl"):
        return False, "Port 9222 is not a DevTools browser endpoint"

    expected = urlparse(trade_url)
    expected_path = expected.path.rstrip("/")
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        candidate = urlparse(target.get("url", ""))
        path_matches = (
            candidate.path == expected_path
            or candidate.path.startswith(f"{expected_path}/")
        )
        # Host check mirrors the Node service so a tab accepted here is also
        # accepted by the monitor (and vice versa).
        if _is_pathofexile_trade_host(candidate.hostname) and path_matches:
            browser = version.get("Browser", "Chromium")
            return True, f"{browser}: compatible trade tab ready"

    return False, "DevTools connected; open a compatible trade tab for this game"


class TradeSniperWidget(QWidget):
    """Main widget for Trade Sniper tool."""
    
    def __init__(self, config: dict, parent=None, service: TradeService = None):
        super().__init__(parent)
        self.config = config
        self.trade_config = config.setdefault("trade_sniper", {})
        self.game_id = ConfigManager.get_active_game(config)
        self.game_profile = ConfigManager.get_game_profile(self.game_id)
        self.trade_url = ConfigManager.get_trade_url(config, self.game_id)
        self.brave_ready = False
        self.current_zone_id = ""
        self.current_zone_safe = False
        self.current_zone_kind = "unknown"
        self._worker_registry = WorkerRegistry(max_threads=3)

        self.service = service or TradeService()
        self.service.status_changed.connect(self.on_status_changed)
        self.service.log_output.connect(self.log)
        
        self.setup_ui()
        self.check_setup()
        self.check_brave_status()
        self.on_status_changed("running" if self.service.is_running else "stopped")
        
        # Periodically check Brave status every 5 seconds
        self.brave_check_timer = QTimer()
        self.brave_check_timer.timeout.connect(self.check_brave_status)
        self.brave_check_timer.start(5000)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Trade Sniper")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel(f"Automated live search monitoring ({self.game_profile['label']})")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(subtitle)
        
        # Status
        self.status_label = QLabel("Status: Stopped")
        self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
        layout.addWidget(self.status_label)
        
        # Requirements
        req_group = QGroupBox("Requirements")
        req_layout = QVBoxLayout(req_group)
        
        self.node_status = QLabel("Checking Node.js...")
        req_layout.addWidget(self.node_status)
        
        # NPM dependencies status
        deps_row = QHBoxLayout()
        self.deps_status = QLabel("Dependencies: Checking...")
        deps_row.addWidget(self.deps_status)
        
        self.install_deps_btn = QPushButton("Install")
        self.install_deps_btn.setFixedWidth(80)
        self.install_deps_btn.clicked.connect(self.install_dependencies)
        self.install_deps_btn.hide()  # Hidden until needed
        deps_row.addWidget(self.install_deps_btn)
        deps_row.addStretch()
        req_layout.addLayout(deps_row)
        
        self.brave_status = QLabel("Brave: Not Running")
        self.brave_status.setStyleSheet("color: #ff6666;")
        req_layout.addWidget(self.brave_status)
        
        # Launch Brave button
        brave_row = QHBoxLayout()
        self.launch_brave_btn = QPushButton("1. Launch Brave (Debug Mode)")
        self.launch_brave_btn.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 8px;")
        self.launch_brave_btn.clicked.connect(self.launch_brave)
        brave_row.addWidget(self.launch_brave_btn)
        brave_row.addStretch()
        req_layout.addLayout(brave_row)
        
        req_layout.addWidget(QLabel(f"2. Login to {self.trade_url} in Brave"))
        req_layout.addWidget(QLabel("3. Open live search tab(s)"))
        req_layout.addWidget(QLabel(f"4. Start {self.game_profile['full_name']} game"))
        
        layout.addWidget(req_group)
        
        # Configuration
        config_group = QGroupBox("Configuration")
        config_layout = QVBoxLayout(config_group)
        
        # Auto-resume checkbox and adjustable delay
        auto_resume_row = QHBoxLayout()
        self.chk_auto_resume = QCheckBox("Auto-resume after:")
        self.chk_auto_resume.setChecked(self.trade_config.get("auto_resume", True))
        self.chk_auto_resume.toggled.connect(self.on_auto_resume_toggled)
        auto_resume_row.addWidget(self.chk_auto_resume)

        self.auto_resume_delay_spin = QSpinBox()
        self.auto_resume_delay_spin.setRange(1, 600)
        self.auto_resume_delay_spin.setSingleStep(1)
        self.auto_resume_delay_spin.setSuffix(" s")
        auto_resume_delay_ms = self.trade_config.get("auto_resume_delay_ms", 30000)
        self.auto_resume_delay_spin.setValue(max(1, auto_resume_delay_ms // 1000))
        self.auto_resume_delay_spin.valueChanged.connect(self.on_auto_resume_delay_changed)
        auto_resume_row.addWidget(self.auto_resume_delay_spin)
        auto_resume_row.addStretch()
        config_layout.addLayout(auto_resume_row)
        
        # Cooldown (in seconds)
        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(QLabel("Wait time after teleport click (s):"))
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(1, 30)
        self.cooldown_spin.setSingleStep(1)
        cooldown_ms = self.trade_config.get("cooldown_ms", 5000)
        self.cooldown_spin.setValue(cooldown_ms // 1000)
        self.cooldown_spin.valueChanged.connect(self.on_cooldown_changed)
        cooldown_row.addWidget(self.cooldown_spin)
        cooldown_row.addStretch()
        config_layout.addLayout(cooldown_row)

        self.chk_zone_gate = QCheckBox("Only click while in a town or hideout")
        self.chk_zone_gate.setChecked(self.trade_config.get("zone_gate_enabled", True))
        self.chk_zone_gate.setToolTip(
            "Uses the selected game's Client.txt. Unknown areas or a missing log "
            "block Travel and Teleport anyway clicks.\n\n"
            "When unchecked, Trade Sniper still monitors and logs new listings, "
            "but auto-clicking is disabled - clicks require zone verification."
        )
        self.chk_zone_gate.toggled.connect(self.on_zone_gate_toggled)
        config_layout.addWidget(self.chk_zone_gate)

        self.zone_gate_warning = QLabel(
            "⚠ Zone verification is OFF - monitoring only, auto-clicking disabled."
        )
        self.zone_gate_warning.setStyleSheet("color: #ffaa66; font-weight: bold;")
        self.zone_gate_warning.setVisible(not self.trade_config.get("zone_gate_enabled", True))
        self.chk_zone_gate.toggled.connect(self.zone_gate_warning.setVisible)
        config_layout.addWidget(self.zone_gate_warning)

        zone_row = QHBoxLayout()
        self.current_zone_label = QLabel("Current zone: Unknown")
        zone_row.addWidget(self.current_zone_label)
        self.allow_current_zone_btn = QPushButton("Allow Current Zone")
        self.allow_current_zone_btn.setEnabled(False)
        self.allow_current_zone_btn.setToolTip(
            "Start Trade Sniper to detect the exact current area ID."
        )
        self.allow_current_zone_btn.clicked.connect(self.allow_current_zone)
        zone_row.addWidget(self.allow_current_zone_btn)
        self.remove_current_zone_btn = QPushButton("Remove Current Zone")
        self.remove_current_zone_btn.setEnabled(False)
        self.remove_current_zone_btn.setToolTip(
            "Only custom zones added for the active game can be removed."
        )
        self.remove_current_zone_btn.clicked.connect(self.remove_current_zone)
        zone_row.addWidget(self.remove_current_zone_btn)
        zone_row.addStretch()
        config_layout.addLayout(zone_row)
        
        layout.addWidget(config_group)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Service")
        self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
        self.start_btn.clicked.connect(self.on_start_resume_click)
        controls_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop Service")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("padding: 10px;")
        self.stop_btn.clicked.connect(self.stop_service)
        controls_layout.addWidget(self.stop_btn)
        
        layout.addLayout(controls_layout)
        
        # Track if service is running (for button swap)
        self.is_service_running = False
        
        # Log Area
        layout.addWidget(QLabel("Service Output:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)
    
    def check_setup(self):
        """Check Node/npm availability without blocking the GUI thread."""
        self.node_status.setText("Node.js: Checking...")
        self.node_ok = False
        self.deps_ok = False
        self.update_start_button_state()
        self._start_background_task(
            "dependency-check",
            self.service.check_dependencies,
            self._on_dependencies_checked,
        )

    def _on_dependencies_checked(self, versions):
        node_ver, _npm_ver = versions
        if node_ver:
            self.node_status.setText(f"Node.js: {node_ver} (OK)")
            self.node_status.setStyleSheet("color: #66ff66;")
            self.node_ok = True
        else:
            self.node_status.setText("Node.js: NOT FOUND - Please install Node.js")
            self.node_status.setStyleSheet("color: #ff6666;")
            self.node_ok = False
        
        # Check npm dependencies (this will also call update_start_button_state)
        self.check_npm_dependencies()

    def _start_background_task(self, name, operation, on_result):
        """Submit one named cancellable operation; reject duplicate task names."""
        return self._worker_registry.start(
            name,
            lambda context: operation(context.token),
            on_result=on_result,
            on_error=lambda failure, task_name=name: self._on_background_error(
                task_name, failure.message
            ),
        )

    def _on_background_error(self, name: str, message: str):
        self.log(f"{name} failed: {message}")
        if name == "dependency-check":
            self.node_status.setText("Node.js: CHECK FAILED")
            self.node_status.setStyleSheet("color: #ff6666;")
        elif name == "npm-install":
            self._on_install_finished(False)
        elif name == "service-stop":
            self._on_stop_finished(False)
    
    def update_start_button_state(self):
        """Enable Start button only when all requirements are met."""
        all_ok = (
            getattr(self, 'node_ok', False)
            and getattr(self, 'deps_ok', False)
            and self.brave_ready
        )
        self.start_btn.setEnabled(all_ok)
    
    def check_npm_dependencies(self):
        """Check if npm dependencies are installed."""
        node_modules_path = os.path.join(self.service.service_dir, "node_modules")
        puppeteer_path = os.path.join(node_modules_path, "puppeteer-core")
        
        if os.path.exists(puppeteer_path):
            self.deps_status.setText("Dependencies: Installed (OK)")
            self.deps_status.setStyleSheet("color: #66ff66;")
            self.install_deps_btn.hide()
            self.deps_ok = True
        elif os.path.exists(node_modules_path):
            # node_modules exists but puppeteer-core might be missing
            self.deps_status.setText("Dependencies: Incomplete")
            self.deps_status.setStyleSheet("color: #ffaa66;")
            self.install_deps_btn.show()
            self.deps_ok = False
        else:
            self.deps_status.setText("Dependencies: NOT INSTALLED")
            self.deps_status.setStyleSheet("color: #ff6666;")
            self.install_deps_btn.show()
            self.deps_ok = False
        
        self.update_start_button_state()
    
    def install_dependencies(self):
        """Install npm dependencies outside the GUI thread."""
        self.install_deps_btn.setEnabled(False)
        self.install_deps_btn.setText("Installing...")
        self.deps_status.setText("Dependencies: Installing...")
        self.deps_status.setStyleSheet("color: #ffaa66;")
        self.log("Installing npm dependencies...")
        self.log(f"Working directory: {self.service.service_dir}")
        
        self._start_background_task(
            "npm-install",
            self.service.install_dependencies,
            self._on_install_finished,
        )

    def _on_install_finished(self, installed: bool):
        if installed:
            self.check_npm_dependencies()
        else:
            self.deps_status.setText("Dependencies: INSTALL FAILED")
            self.deps_status.setStyleSheet("color: #ff6666;")
        self.install_deps_btn.setEnabled(True)
        self.install_deps_btn.setText("Install")
    
    def check_brave_status(self):
        """Verify the local DevTools endpoint and a compatible trade page."""
        self.brave_ready, detail = self.probe_devtools_readiness()
        if self.brave_ready:
            self.brave_status.setText(f"Browser: {detail}")
            self.brave_status.setStyleSheet("color: #66ff66;")
            self.launch_brave_btn.setText("Brave Already Running")
            self.launch_brave_btn.setEnabled(False)
        else:
            self.brave_status.setText(f"Browser: {detail}")
            self.brave_status.setStyleSheet("color: #ffaa66;")
            self.launch_brave_btn.setText("1. Launch Brave (Debug Mode)")
            self.launch_brave_btn.setEnabled(True)
            self.launch_brave_btn.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 8px;")
        self.update_start_button_state()

    def probe_devtools_readiness(self):
        """Read bounded localhost CDP metadata without trusting an open port."""
        try:
            with urlopen("http://127.0.0.1:9222/json/version", timeout=0.5) as response:
                version = json.load(response)
            with urlopen("http://127.0.0.1:9222/json/list", timeout=0.5) as response:
                targets = json.load(response)
            return evaluate_devtools_readiness(version, targets, self.trade_url)
        except (OSError, ValueError, TypeError):
            return False, "DevTools unavailable on 127.0.0.1:9222"
    
    def is_brave_debug_running(self) -> bool:
        """Return whether a valid CDP endpoint and matching trade tab are ready."""
        ready, _detail = self.probe_devtools_readiness()
        return ready
    
    def launch_brave(self):
        """Launch Brave browser with remote debugging enabled."""
        # Common Brave paths per platform
        if sys.platform == "win32":
            brave_paths = [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ]
        else:
            brave_paths = [
                "/usr/bin/brave-browser",
                "/usr/bin/brave",
                "/opt/brave.com/brave/brave-browser",
                "/snap/bin/brave",
                os.path.expanduser("~/.local/bin/brave-browser"),
            ]
        
        brave_exe = None
        for path in brave_paths:
            if os.path.exists(path):
                brave_exe = path
                break
        
        if not brave_exe:
            QMessageBox.warning(
                self,
                "Brave Not Found",
                "Could not find Brave browser.\n\n"
                "Please install Brave from https://brave.com\n"
                "or update the path in the config."
            )
            return
        
        # Keep mutable cookies/cache outside the source checkout. Migration only
        # happens when the user explicitly launches Brave and no CDP browser is ready.
        profile_dir = prepare_trade_profile_dir()
        
        try:
            # Launch Brave with remote debugging and open trade site
            cmd = [
                brave_exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={profile_dir}",
                self.trade_url
            ]
            
            # Use subprocess.Popen to launch without blocking
            subprocess.Popen(cmd, shell=False)
            
            self.brave_status.setText("Brave: Launched (Debug Mode)")
            self.brave_status.setStyleSheet("color: #66ff66;")
            self.log("Brave launched with remote debugging on port 9222")
            self.log(f"Opening {self.trade_url}...")
            self.log("")
            self.log("Next steps:")
            self.log("  - Login if needed")
            self.log("  - Open/create your live search")
            self.log("  - Click 'Start Service' when ready")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Launch Failed",
                f"Failed to launch Brave:\n{str(e)}"
            )
            self.log(f"ERROR: Failed to launch Brave: {e}")
    
    def log(self, message: str):
        if message.startswith(ZONE_STATE_PREFIX):
            try:
                state = json.loads(message[len(ZONE_STATE_PREFIX):])
            except (TypeError, ValueError, json.JSONDecodeError):
                return
            self._handle_zone_state(state)
            return
        self.log_area.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _save_trade_setting(self, key: str, value):
        """Persist a Trade Sniper setting in the shared configuration."""
        self.trade_config[key] = value
        try:
            ConfigManager.save(self.config)
        except ConfigSaveError as error:
            self.status_label.setText(f"Status: Config save failed: {error}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.log(f"ERROR: Config save failed: {error}")
            return False
        return True

    def on_auto_resume_toggled(self, checked: bool):
        """Persist and send the auto-resume toggle to the running service."""
        if not self._save_trade_setting("auto_resume", checked):
            return
        if self.is_service_running:
            self.service.send_input(f"__auto_resume__:{'on' if checked else 'off'}\n")

    def on_auto_resume_delay_changed(self, seconds: int):
        """Persist and live-update the auto-resume delay."""
        if not self._save_trade_setting("auto_resume_delay_ms", seconds * 1000):
            return
        if self.is_service_running:
            self.service.send_input(f"__auto_resume_delay__:{seconds}\n")

    def on_cooldown_changed(self, seconds: int):
        """Persist and live-update the post-teleport click cooldown."""
        if not self._save_trade_setting("cooldown_ms", seconds * 1000):
            return
        if self.is_service_running:
            self.service.send_input(f"__cooldown__:{seconds}\n")

    def on_zone_gate_toggled(self, checked: bool):
        """Persist zone gating; a running service keeps its startup policy."""
        self._save_trade_setting("zone_gate_enabled", checked)

    def _get_custom_allowed_zones(self) -> list[str]:
        """Return validated custom area IDs for the active game."""
        by_game = self.trade_config.get("custom_allowed_zones", {})
        if not isinstance(by_game, dict):
            return []
        zones = by_game.get(self.game_id, [])
        if not isinstance(zones, list):
            return []
        return list(dict.fromkeys(
            zone for zone in zones
            if isinstance(zone, str) and AREA_ID_PATTERN.fullmatch(zone)
        ))

    def _handle_zone_state(self, state: dict):
        """Update the UI from the Node gate's exact machine-readable state."""
        if not isinstance(state, dict):
            return
        area_id = state.get("areaId", "")
        if not isinstance(area_id, str) or not AREA_ID_PATTERN.fullmatch(area_id):
            area_id = ""
        self.current_zone_id = area_id
        self.current_zone_safe = state.get("safe") is True
        kind = state.get("kind", "unknown")
        self.current_zone_kind = kind if isinstance(kind, str) else "unknown"
        self.current_zone_label.setText(
            f"Current zone: {area_id}" if area_id else "Current zone: Unknown"
        )
        self._update_zone_action_buttons()

    def _update_zone_action_buttons(self):
        already_custom = self.current_zone_id in self._get_custom_allowed_zones()
        can_allow = bool(
            self.is_service_running
            and self.current_zone_id
            and not self.current_zone_safe
            and not already_custom
        )
        self.allow_current_zone_btn.setEnabled(can_allow)
        if self.current_zone_safe or already_custom:
            tooltip = "The current zone is already allowed."
        elif self.current_zone_id:
            tooltip = "Persist this exact area ID for the active game and allow it now."
        else:
            tooltip = "Start Trade Sniper to detect the exact current area ID."
        self.allow_current_zone_btn.setToolTip(tooltip)

        can_remove = bool(
            self.is_service_running
            and self.current_zone_id
            and already_custom
            and self.current_zone_kind == "custom"
        )
        self.remove_current_zone_btn.setEnabled(can_remove)
        if can_remove:
            remove_tooltip = (
                "Remove this exact area ID from the active game's custom allowlist "
                "and block it now."
            )
        elif self.current_zone_kind in {"town", "hideout"}:
            remove_tooltip = "Built-in towns and hideouts cannot be removed."
        else:
            remove_tooltip = "Only custom zones added for the active game can be removed."
        self.remove_current_zone_btn.setToolTip(remove_tooltip)

    def allow_current_zone(self):
        """Persist and immediately allow the exact currently detected area ID."""
        area_id = self.current_zone_id
        if (
            not self.is_service_running
            or not AREA_ID_PATTERN.fullmatch(area_id)
            or self.current_zone_safe
            or area_id in self._get_custom_allowed_zones()
        ):
            self._update_zone_action_buttons()
            return

        candidate = copy.deepcopy(self.config)
        candidate_trade = candidate.setdefault("trade_sniper", {})
        by_game = candidate_trade.setdefault(
            "custom_allowed_zones", {"poe1": [], "poe2": []}
        )
        if not isinstance(by_game, dict):
            by_game = {"poe1": [], "poe2": []}
            candidate_trade["custom_allowed_zones"] = by_game
        zones = by_game.setdefault(self.game_id, [])
        if not isinstance(zones, list):
            zones = []
            by_game[self.game_id] = zones
        if area_id not in zones:
            zones.append(area_id)

        try:
            ConfigManager.save(candidate)
        except ConfigSaveError as error:
            self.status_label.setText(f"Status: Config save failed: {error}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.log(f"ERROR: Could not allow {area_id}: {error}")
            return

        self.config.clear()
        self.config.update(candidate)
        self.trade_config = self.config.setdefault("trade_sniper", {})
        self.current_zone_safe = True
        self.current_zone_kind = "custom"
        self._update_zone_action_buttons()
        self.log(f"Allowed zone for {self.game_profile['label']}: {area_id}")
        if self.is_service_running:
            if not self.service.send_input(f"__allow_zone__:{area_id}\n"):
                self.log("Runtime update failed; the zone will be allowed on next service start.")

    def remove_current_zone(self):
        """Remove and immediately block the exact current custom area ID."""
        area_id = self.current_zone_id
        if (
            not self.is_service_running
            or not AREA_ID_PATTERN.fullmatch(area_id)
            or self.current_zone_kind != "custom"
            or area_id not in self._get_custom_allowed_zones()
        ):
            self._update_zone_action_buttons()
            return

        candidate = copy.deepcopy(self.config)
        candidate_trade = candidate.get("trade_sniper", {})
        by_game = candidate_trade.get("custom_allowed_zones", {})
        zones = by_game.get(self.game_id, []) if isinstance(by_game, dict) else []
        if not isinstance(zones, list) or area_id not in zones:
            self._update_zone_action_buttons()
            return
        by_game[self.game_id] = [zone for zone in zones if zone != area_id]

        try:
            ConfigManager.save(candidate)
        except ConfigSaveError as error:
            self.status_label.setText(f"Status: Config save failed: {error}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.log(f"ERROR: Could not remove {area_id}: {error}")
            return

        self.config.clear()
        self.config.update(candidate)
        self.trade_config = self.config.setdefault("trade_sniper", {})
        self.current_zone_safe = False
        self.current_zone_kind = "unsafe-area"
        self._update_zone_action_buttons()
        self.log(f"Removed zone for {self.game_profile['label']}: {area_id}")
        if not self.service.send_input(f"__remove_zone__:{area_id}\n"):
            self.log("Runtime removal failed; stopping Trade Sniper to fail closed.")
            self.stop_service()
    
    def on_start_resume_click(self):
        """Handle start/resume button click based on current state."""
        if self.is_service_running:
            # Service is running, send resume signal
            self.service.resume()
        else:
            # Service not running, start it
            auto_resume = self.chk_auto_resume.isChecked()
            auto_resume_delay_s = self.auto_resume_delay_spin.value()
            cooldown_s = self.cooldown_spin.value()
            poll_interval_ms = self.trade_config.get("check_interval_ms", 10)
            confirmation_retry_ms = self.trade_config.get("confirmation_retry_ms", 20)
            zone_gate_enabled = self.chk_zone_gate.isChecked()
            client_log_path = ConfigManager.get_client_log_path(self.config, self.game_id)
            allowed_zones = self._get_custom_allowed_zones()
            self.service.start(
                auto_resume=auto_resume,
                auto_resume_delay_s=auto_resume_delay_s,
                cooldown_s=cooldown_s,
                poll_interval_ms=poll_interval_ms,
                confirmation_retry_ms=confirmation_retry_ms,
                game_id=self.game_id,
                zone_gate_enabled=zone_gate_enabled,
                client_log_path=client_log_path,
                allowed_zones=allowed_zones,
            )
    
    def stop_service(self):
        """Stop the trade service without blocking the GUI thread."""
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping...")
        self.status_label.setText("Status: Stopping")
        self._start_background_task(
            "service-stop",
            self.service.stop,
            self._on_stop_finished,
        )

    def _on_stop_finished(self, stopped: bool):
        self.stop_btn.setText("Stop Service")
        if not stopped and self.service.is_running:
            self.stop_btn.setEnabled(True)
            self.status_label.setText("Status: Stop failed")
    
    def on_status_changed(self, status: str):
        """Handle status changes."""
        if status == "running":
            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet("font-size: 14px; color: #66ff66;")
            self.is_service_running = True
            self.chk_zone_gate.setEnabled(False)
            # Swap to Resume button
            self.start_btn.setText("Resume (Enter)")
            self.start_btn.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 10px;")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        elif status == "stopped":
            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.is_service_running = False
            self.chk_zone_gate.setEnabled(True)
            self.current_zone_id = ""
            self.current_zone_safe = False
            self.current_zone_kind = "unknown"
            self.current_zone_label.setText("Current zone: Unknown")
            self._update_zone_action_buttons()
            # Swap back to Start button
            self.start_btn.setText("Start Service")
            self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
            self.update_start_button_state()  # Re-check if deps are OK
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Stop Service")
        else:
            self.status_label.setText(f"Status: {status}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ffaa66;")
    
    def cleanup(self):
        """Cancel and verify view-owned work without stopping the app-owned service."""
        timer_was_active = False
        if hasattr(self, 'brave_check_timer'):
            timer_was_active = self.brave_check_timer.isActive()
            self.brave_check_timer.stop()
        workers_stopped = self._worker_registry.close(timeout_ms=20_000)
        if not workers_stopped:
            if timer_was_active:
                self.brave_check_timer.start()
            self.log("Background work did not stop before cleanup timeout.")
            return False
        try:
            self.service.status_changed.disconnect(self.on_status_changed)
        except TypeError:
            pass
        try:
            self.service.log_output.disconnect(self.log)
        except TypeError:
            pass
        return True


class TradeSniperTool(BaseTool):
    """Trade Sniper Tool plugin."""
    
    @property
    def name(self) -> str:
        return "Trade"
    
    @property
    def icon(self) -> str:
        return "trade"
    
    @property
    def description(self) -> str:
        return "Automated live search monitoring"
    
    def __init__(self, config: dict, service: TradeService = None):
        self.config = config
        self.service = service
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = TradeSniperWidget(self.config, parent, service=self.service)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            return self.widget.cleanup()
        return True

