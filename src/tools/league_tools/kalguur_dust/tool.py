"""
Kalguur Dust Tool - Find valuable uniques to disenchant for Thaumaturgic Dust.

Scans stash tabs for unique items and calculates their dust efficiency
(dust per chaos spent), helping identify items worth disenchanting.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QTextEdit, QSplitter, QFrame,
    QCheckBox, QScrollArea, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
import os
import shutil

from tools.base_tool import BaseTool
from core.valuation import NinjaPriceFetcher
from services.price_service import PriceService
from ui.components.stash_selector import StashTabSelector

from .dust_data import DustDataFetcher, DustEfficiencyAnalyzer, DustDataCache
from .scanner import (
    StashScanWorker, TabListWorker, UniqueItemInfo,
    fetch_tab_list_operation, scan_stash_operation,
    group_items_by_tab, items_to_highlights
)
from .tab_tracker import TabTracker, TabTrackerWorker, TabRegionConfig, MultiTabHighlighter
from ui.components.ocr_settings_dialog import OCRSettingsDialog
from utils.config import ConfigManager
from utils.workers import (
    WorkerRegistry,
    disconnect_qt_signals,
    discard_queued_meta_calls,
    stop_legacy_qthread,
)


class KalguurDustWidget(QWidget):
    """Main widget for Kalguur Dust tool."""
    
    overlay_update = pyqtSignal(list)  # Emits highlight data
    overlay_debug_rect_update = pyqtSignal(int, int, int, int, str)  # x, y, w, h, color
    overlay_debug_text_update = pyqtSignal(str, int, int)  # text, x, y
    overlay_guidance_update = pyqtSignal(str, int, int)  # text, x, y
    
    def __init__(self, config: dict, price_service=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.game_id = "poe1"
        league = ConfigManager.get_game_league(config, self.game_id)
        self._owns_price_service = price_service is None
        self.price_service = price_service or PriceService(self.game_id, league)
        self.dust_config = config.get("kalguur_dust", {})
        
        # Data components
        self.dust_fetcher: DustDataFetcher | None = None
        self.price_fetcher: NinjaPriceFetcher | None = None
        self.dust_analyzer: DustEfficiencyAnalyzer | None = None
        
        # Scan results (all_scan_results is unfiltered, scan_results is filtered)
        self.all_scan_results: list[UniqueItemInfo] = []
        self.scan_results: list[UniqueItemInfo] = []
        self.scan_stats: dict = {}
        self.items_by_tab: dict = {}
        self.tab_worker = None
        self.scan_worker = None
        self.worker_registry = WorkerRegistry(max_threads=3)
        self._pending_scan_args: dict | None = None
        self._price_service_signals_connected = False
        
        # Tab tracking
        self.tab_tracker: TabTracker = None
        self.tab_tracker_worker: TabTrackerWorker = None
        self.multi_tab_highlighter: MultiTabHighlighter = None
        
        # Debug mode
        # Debug mode - check global config first, fall back to tool-specific
        self.debug_mode = self.config.get("debug_mode", self.dust_config.get("debug_mode", False))
        
        self.setup_ui()
        self._connect_price_service_signals()
    
    def _connect_price_service_signals(self):
        if self._price_service_signals_connected:
            return
        try:
            self.price_service.refresh_completed.connect(self._on_price_refresh_completed)
            self.price_service.refresh_failed.connect(self._on_price_refresh_failed)
        except (AttributeError, TypeError, RuntimeError):
            return
        self._price_service_signals_connected = True

    def _disconnect_price_service_signals(self):
        if not self._price_service_signals_connected:
            return
        for signal_name, callback in (
            ("refresh_completed", self._on_price_refresh_completed),
            ("refresh_failed", self._on_price_refresh_failed),
        ):
            signal = getattr(self.price_service, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass
        self._price_service_signals_connected = False

    def set_debug_mode(self, enabled: bool):
        """Set debug mode (called from main window)."""
        self.debug_mode = enabled
        self.log_area.setMaximumHeight(200 if enabled else 100)
        self.log(f"Debug mode: {'ON' if enabled else 'OFF'}")
        if self.tab_tracker:
            self.tab_tracker.debug_mode = enabled

    def setup_ui(self):
        # Create main layout for the widget
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        # Create content widget
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        
        # Title
        title = QLabel("Kalguur Dust")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("Find valuable uniques to disenchant for Thaumaturgic Dust")
        subtitle.setStyleSheet("font-size: 12px; color: #888888; margin-bottom: 10px;")
        layout.addWidget(subtitle)
        
        # Account Section (shared with Settings)
        creds_group = QGroupBox("Account")
        creds_layout = QVBoxLayout(creds_group)
        
        creds_layout.addWidget(QLabel("Account/POESESSID are managed in Settings."))
        
        creds_row = QHBoxLayout()
        creds_row.addWidget(QLabel("Account:"))
        self.account_label = QLabel(ConfigManager.get_account_name(self.config) or "Not set")
        self.account_label.setStyleSheet("color: #cccccc;")
        creds_row.addWidget(self.account_label)

        creds_row.addWidget(QLabel("PoE 1 League:"))
        self.league_input = QComboBox()
        self.league_input.setEditable(False)
        for league in ConfigManager.get_game_league_options(self.config, self.game_id):
            self.league_input.addItem(league)
        selected_league = ConfigManager.get_game_league(self.config, self.game_id)
        if selected_league:
            idx = self.league_input.findText(selected_league)
            if idx < 0:
                self.league_input.insertItem(0, selected_league)
                idx = 0
            self.league_input.setCurrentIndex(idx)
        creds_row.addWidget(self.league_input)
        creds_layout.addLayout(creds_row)
        
        layout.addWidget(creds_group)
        
        # Fetch Tabs Button
        fetch_row = QHBoxLayout()
        self.fetch_tabs_btn = QPushButton("1. Fetch Tab List")
        self.fetch_tabs_btn.clicked.connect(self.fetch_tab_list)
        fetch_row.addWidget(self.fetch_tabs_btn)
        self.cancel_tabs_btn = QPushButton("Cancel")
        self.cancel_tabs_btn.clicked.connect(lambda: self.cancel_operation("tab-fetch"))
        self.cancel_tabs_btn.setEnabled(False)
        fetch_row.addWidget(self.cancel_tabs_btn)
        self.retry_tabs_btn = QPushButton("Retry")
        self.retry_tabs_btn.clicked.connect(self.fetch_tab_list)
        self.retry_tabs_btn.setEnabled(False)
        fetch_row.addWidget(self.retry_tabs_btn)
        layout.addLayout(fetch_row)
        self.phase_status = QLabel("Ready")
        self.phase_status.setStyleSheet("color: #cccccc;")
        layout.addWidget(self.phase_status)
        self.provenance_label = QLabel("Dust/price data not prepared")
        self.provenance_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.provenance_label)
        
        # Tab Selector
        layout.addWidget(QLabel("Select Tabs to Scan:"))
        self.tab_selector = StashTabSelector()
        layout.addWidget(self.tab_selector)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self._refresh_presets_combo()
        preset_row.addWidget(self.preset_combo)
        self.preset_name_input = QLineEdit()
        self.preset_name_input.setPlaceholderText("Preset name")
        preset_row.addWidget(self.preset_name_input)
        self.apply_preset_btn = QPushButton("Apply")
        self.apply_preset_btn.clicked.connect(self.apply_tab_preset)
        preset_row.addWidget(self.apply_preset_btn)
        self.save_preset_btn = QPushButton("Save")
        self.save_preset_btn.clicked.connect(self.save_tab_preset)
        preset_row.addWidget(self.save_preset_btn)
        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.clicked.connect(self.delete_tab_preset)
        preset_row.addWidget(self.delete_preset_btn)
        layout.addLayout(preset_row)
        
        # Scan Settings
        settings_row = QHBoxLayout()
        
        # Min Efficiency Slider (dust per chaos spent)
        settings_row.addWidget(QLabel("Min Dust/Chaos:"))
        self.efficiency_slider = QSlider(Qt.Orientation.Horizontal)
        self.efficiency_slider.setRange(0, 500)  # Represents 0 to 50,000 (x100)
        self.efficiency_slider.setValue(self.dust_config.get("min_efficiency", 10))  # Default 1000
        self.efficiency_label = QLabel(f"{self.efficiency_slider.value() * 100:,}")
        self.efficiency_slider.valueChanged.connect(
            lambda v: self.efficiency_label.setText(f"{v * 100:,}")
        )
        self.efficiency_slider.valueChanged.connect(self.apply_efficiency_filter)
        settings_row.addWidget(self.efficiency_slider)
        settings_row.addWidget(self.efficiency_label)

        self.include_unknown_prices = QCheckBox("Include unknown prices")
        self.include_unknown_prices.setChecked(
            self.dust_config.get("include_unknown_prices", False)
        )
        self.include_unknown_prices.stateChanged.connect(self.apply_efficiency_filter)
        settings_row.addWidget(self.include_unknown_prices)
        
        layout.addLayout(settings_row)
        
        # Scan Button
        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("2. Scan for Valuable Uniques")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setEnabled(False)
        scan_row.addWidget(self.scan_btn)
        self.cancel_scan_btn = QPushButton("Cancel")
        self.cancel_scan_btn.clicked.connect(lambda: self.cancel_operation("scan"))
        self.cancel_scan_btn.setEnabled(False)
        scan_row.addWidget(self.cancel_scan_btn)
        self.retry_scan_btn = QPushButton("Retry")
        self.retry_scan_btn.clicked.connect(self.start_scan)
        self.retry_scan_btn.setEnabled(False)
        scan_row.addWidget(self.retry_scan_btn)
        layout.addLayout(scan_row)
        
        # Results Table
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels([
            "Item", "Tab", "ilvl", "Dust", "Price (c)", "Dust/Chaos", "Corrupted"
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #252526;
                gridline-color: #3d3d3d;
            }
            QTableWidget::item:selected {
                background-color: #094771;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #cccccc;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #3d3d3d;
            }
        """)
        results_layout.addWidget(self.results_table)
        
        # Results summary
        self.results_summary = QLabel("No scan results yet")
        self.results_summary.setStyleSheet("color: #888888;")
        results_layout.addWidget(self.results_summary)
        
        layout.addWidget(results_group)
        
        # Highlighting Controls
        highlight_group = QGroupBox("Multi-Tab Highlighting")
        highlight_layout = QVBoxLayout(highlight_group)
        
        self.highlight_status = QLabel("Scan tabs first to enable highlighting")
        self.highlight_status.setStyleSheet("color: #888888;")
        highlight_layout.addWidget(self.highlight_status)
        
        highlight_btn_row = QHBoxLayout()
        
        self.start_highlight_btn = QPushButton("Start Highlighting")
        self.start_highlight_btn.clicked.connect(self.start_highlighting)
        self.start_highlight_btn.setEnabled(False)
        highlight_btn_row.addWidget(self.start_highlight_btn)
        
        self.stop_highlight_btn = QPushButton("Stop")
        self.stop_highlight_btn.clicked.connect(self.stop_highlighting)
        self.stop_highlight_btn.setEnabled(False)
        highlight_btn_row.addWidget(self.stop_highlight_btn)
        
        self.ocr_config_btn = QPushButton("Configure OCR")
        self.ocr_config_btn.clicked.connect(self.open_ocr_settings)
        highlight_btn_row.addWidget(self.ocr_config_btn)
        
        self.clear_btn = QPushButton("Clear Overlay")
        self.clear_btn.clicked.connect(self.clear_overlay)
        highlight_btn_row.addWidget(self.clear_btn)
        
        highlight_layout.addLayout(highlight_btn_row)
        
        # Current tab indicator
        self.current_tab_label = QLabel("")
        self.current_tab_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #4fc3f7; padding: 8px;"
        )
        highlight_layout.addWidget(self.current_tab_label)
        
        # Manual tab confirmation (OCR fallback)
        self.manual_tab_btn = QPushButton("I'm on the correct tab")
        self.manual_tab_btn.clicked.connect(self._on_manual_tab_confirm)
        self.manual_tab_btn.setEnabled(False)
        self.manual_tab_btn.setStyleSheet("background-color: #2d5a2d;")
        highlight_layout.addWidget(self.manual_tab_btn)
        
        layout.addWidget(highlight_group)
        
        # Log Area (debug mode controlled via Settings menu)
        log_label = QLabel("Log:")
        log_label.setStyleSheet("color: #888888;")
        layout.addWidget(log_label)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150 if self.debug_mode else 100)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #888888;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_area)
        
        layout.addStretch()
    
    def log(self, message: str, debug_only: bool = False):
        """Add message to log area.
        
        Args:
            message: Message to log
            debug_only: If True, only show when debug mode is enabled
        """
        if debug_only and not self.debug_mode:
            return
        self.log_area.append(message)
    
    
    def _set_phase_status(self, progress):
        if isinstance(progress, dict):
            phase = progress.get("phase", "work")
            message = progress.get("message") or phase.replace("_", " ")
            current = progress.get("current")
            total = progress.get("total")
            if phase == "rate_limit":
                message = f"Rate limited: retrying in {progress.get('retry_after', '?')}s"
            suffix = f" ({current}/{total})" if current is not None and total is not None else ""
            self.phase_status.setText(f"{phase}: {message}{suffix}")
            self.log(self.phase_status.text(), debug_only=phase not in {"rate_limit", "scan_log"})
        else:
            self.phase_status.setText(str(progress))

    def cancel_operation(self, operation: str):
        names = {"tab-fetch": ("kalguur-tab-fetch", self.cancel_tabs_btn), "scan": ("kalguur-prepare", self.cancel_scan_btn)}
        name, button = names.get(operation, (operation, None))
        if operation == "scan" and self._pending_scan_args is not None:
            self._pending_scan_args = None
            self.scan_btn.setEnabled(True)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "cancelled", "message": "Price preparation cancelled locally; shared refresh continues."})
            return
        if self.worker_registry.cancel(name):
            self._set_phase_status({"phase": "cancel", "message": f"Cancelling {operation}..."})
            if button is not None:
                button.setEnabled(False)

    def _selected_tab_refs(self):
        refs = []
        for tab in self.tab_selector.tabs_list:
            idx = tab.get('i')
            if idx in self.tab_selector.selected_indices:
                refs.append({"id": str(idx), "index": idx, "name": tab.get('n', f"Tab {idx}")})
        return refs

    def _selection_indices_from_config(self, tabs):
        saved = self.dust_config.get("selected_tabs", [])
        names = {str(entry.get("name")) for entry in saved if isinstance(entry, dict)}
        ids = {str(entry.get("id")) for entry in saved if isinstance(entry, dict)}
        indices = []
        for tab in tabs:
            idx = tab.get('i')
            if str(idx) in ids or str(tab.get('n', '')) in names:
                indices.append(idx)
        return indices

    def _refresh_presets_combo(self):
        if not hasattr(self, "preset_combo"):
            return
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        for name in sorted(self.dust_config.get("tab_presets", {})):
            self.preset_combo.addItem(name)
        if current:
            idx = self.preset_combo.findText(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def apply_tab_preset(self):
        name = self.preset_combo.currentText().strip()
        preset = self.dust_config.get("tab_presets", {}).get(name, [])
        self.dust_config["selected_tabs"] = preset
        indices = self._selection_indices_from_config(self.tab_selector.tabs_list)
        self.tab_selector.load_tabs(self.tab_selector.tabs_list, preselected_indices=indices)
        self.log(f"Applied tab preset '{name}' ({len(indices)} tabs)")

    def save_tab_preset(self):
        name = self.preset_name_input.text().strip() or self.preset_combo.currentText().strip()
        if not name:
            self.log("Enter a preset name before saving.")
            return
        self.dust_config.setdefault("tab_presets", {})[name] = self._selected_tab_refs()
        self._refresh_presets_combo()
        self.log(f"Saved tab preset '{name}'")

    def delete_tab_preset(self):
        name = self.preset_combo.currentText().strip()
        if name:
            self.dust_config.setdefault("tab_presets", {}).pop(name, None)
            self._refresh_presets_combo()
            self.log(f"Deleted tab preset '{name}'")

    def fetch_tab_list(self):
        """Fetch list of stash tabs in the shared worker registry."""
        session_id = ConfigManager.get_session_id(self.config)
        account = ConfigManager.get_account_name(self.config)
        league = self.league_input.currentText().strip()
        if not session_id or not account:
            self.log("Error: Credentials required. Set account and POESESSID in Settings, then retry.")
            return
        if "kalguur-tab-fetch" in self.worker_registry.active_names:
            self.log("Tab fetch is already running; wait or Cancel first.")
            return
        self.fetch_tabs_btn.setEnabled(False); self.cancel_tabs_btn.setEnabled(True); self.retry_tabs_btn.setEnabled(False)
        self._set_phase_status({"phase": "tab_fetch", "message": "Starting tab fetch"})
        def operation(context):
            return fetch_tab_list_operation(session_id, account, league, context=context)
        if not self.worker_registry.start("kalguur-tab-fetch", operation, on_progress=self._set_phase_status, on_result=self.on_tabs_fetched, on_error=self._on_tab_fetch_error, on_cancelled=lambda: self._on_operation_cancelled("tab_fetch"), on_finished=lambda: self._on_fetch_finished()):
            self.log("Tab fetch is already running; duplicate start ignored.")

    def _on_fetch_finished(self):
        self.fetch_tabs_btn.setEnabled(True); self.cancel_tabs_btn.setEnabled(False)

    def _on_tab_fetch_error(self, error):
        message = getattr(error, "message", str(error))
        self.retry_tabs_btn.setEnabled(True)
        self._set_phase_status({"phase": "error", "message": f"Tab fetch failed: {message}. Check credentials/league/network and Retry."})

    def _on_operation_cancelled(self, phase):
        self._set_phase_status({"phase": "cancelled", "message": f"{phase} cancelled"})
        self.retry_tabs_btn.setEnabled(True)
        self.retry_scan_btn.setEnabled(True)

    def on_tabs_fetched(self, tabs: list):
        """Handle fetched tab list."""
        if not tabs:
            self.retry_tabs_btn.setEnabled(True)
            self.scan_btn.setEnabled(False)
            self._set_phase_status({"phase": "error", "message": "No stash tabs were returned. Verify account/POESESSID/league and Retry."})
            return
        self.log(f"Fetched {len(tabs)} tabs.")
        preselected = self._selection_indices_from_config(tabs)
        self.tab_selector.load_tabs(tabs, preselected_indices=preselected)
        self.scan_btn.setEnabled(True)

    def start_scan(self):
        """Prepare dust/price data and scan selected tabs off the GUI thread."""
        selected_indices = tuple(self.tab_selector.get_selected_indices())
        if not selected_indices:
            self.log("No tabs selected!")
            return False
        session_id = ConfigManager.get_session_id(self.config)
        account = ConfigManager.get_account_name(self.config)
        league = self.league_input.currentText().strip()
        if "kalguur-prepare" in self.worker_registry.active_names or self._pending_scan_args is not None:
            self.log("Preparation/scan is already running; wait or Cancel first.")
            return False

        pending_args = {
            "session_id": session_id,
            "account": account,
            "league": league,
            "game": self.game_id,
            "selected_indices": selected_indices,
            "selected_tabs": tuple(tuple(sorted(ref.items())) for ref in self._selected_tab_refs()),
            "debug_mode": bool(self.debug_mode),
        }
        try:
            self.price_service.set_context(self.game_id, league)
            price_fetcher = self._current_price_fetcher()
        except Exception as error:
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "error", "message": f"Price preparation failed: {error}. Check league/network and Retry."})
            return False

        self.scan_btn.setEnabled(False)
        self.cancel_scan_btn.setEnabled(True)
        self.retry_scan_btn.setEnabled(False)
        self.dust_config["selected_tabs"] = [dict(entries) for entries in pending_args["selected_tabs"]]
        if price_fetcher is not None:
            return self._dispatch_scan_with_prices(pending_args, price_fetcher)

        self._pending_scan_args = pending_args
        self._set_phase_status({"phase": "price_prepare", "message": "Preparing prices in background; scan will start when ready"})
        try:
            started = self.price_service.refresh_prices(force=False)
        except Exception as error:
            self._pending_scan_args = None
            self.scan_btn.setEnabled(True)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "error", "message": f"Price preparation failed: {error}. Check league/network and Retry."})
            return False
        if not started:
            active_context = self._active_price_refresh_context()
            pending_context = (pending_args["game"], pending_args["league"])
            if active_context == pending_context:
                self._set_phase_status({"phase": "price_prepare", "message": "Waiting for shared price refresh already in progress"})
                return True
            self._pending_scan_args = None
            self.scan_btn.setEnabled(True)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "error", "message": "Previous context price refresh is still stopping; Retry once it finishes."})
            return False
        return True

    def _active_price_refresh_context(self):
        active_context = getattr(self.price_service, "active_refresh_context", None)
        if callable(active_context):
            return active_context()
        return None

    def _current_price_fetcher(self):
        current = getattr(self.price_service, "current_fetcher", None)
        if callable(current):
            return current()
        return None

    def _on_price_refresh_completed(self, result):
        pending_args = self._pending_scan_args
        if pending_args is None:
            return
        state = self.price_service.runtime_state()
        if (state.get("game"), state.get("league")) != (pending_args["game"], pending_args["league"]):
            return
        price_fetcher = self._current_price_fetcher()
        if price_fetcher is None:
            detail = getattr(result, "detail", None) or state.get("last_error") or "no usable price snapshot"
            self._pending_scan_args = None
            self.scan_btn.setEnabled(True)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "error", "message": f"Price preparation failed: {detail}. Check league/network and Retry."})
            return
        self._pending_scan_args = None
        self._dispatch_scan_with_prices(pending_args, price_fetcher)

    def _on_price_refresh_failed(self, error_message):
        if self._pending_scan_args is None:
            return
        self._pending_scan_args = None
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)
        self.retry_scan_btn.setEnabled(True)
        self._set_phase_status({"phase": "error", "message": f"Price preparation failed: {error_message}. Check league/network and Retry."})

    def _dispatch_scan_with_prices(self, pending_args, price_fetcher):
        if "kalguur-prepare" in self.worker_registry.active_names:
            self.log("Scan is already running; duplicate start ignored.")
            return False
        session_id = pending_args["session_id"]
        account = pending_args["account"]
        league = pending_args["league"]
        selected_indices = pending_args["selected_indices"]
        debug_mode = pending_args["debug_mode"]

        def operation(context):
            context.report_progress({"phase": "prepare", "message": "Preparing dust data and prices", "current": 0, "total": 2})
            dust_fetcher = self.dust_fetcher if self.dust_fetcher and self.dust_fetcher.league == league else DustDataFetcher(league)
            dust_fetcher.fetch_dust_data(context=context)
            context.report_progress({"phase": "prepare", "message": "Using prepared price snapshot", "current": 1, "total": 2})
            analyzer = DustEfficiencyAnalyzer(dust_fetcher, price_fetcher)
            context.report_progress({"phase": "scan", "message": f"Scanning {len(selected_indices)} tabs", "current": 0, "total": len(selected_indices)})
            items, stats = scan_stash_operation(session_id, account, league, list(selected_indices), analyzer, 0, debug_mode, context=context)
            return dust_fetcher, price_fetcher, analyzer, items, stats
        if not self.worker_registry.start("kalguur-prepare", operation, on_progress=self._set_phase_status, on_result=self._on_scan_payload, on_error=self._on_scan_error, on_cancelled=lambda: self._on_operation_cancelled("scan"), on_finished=lambda: self._on_scan_finished()):
            self.log("Scan is already running; duplicate start ignored.")
            return False
        return True

    def _on_scan_finished(self):
        self.scan_btn.setEnabled(True); self.cancel_scan_btn.setEnabled(False)

    def _on_scan_error(self, error):
        message = getattr(error, "message", str(error))
        self.retry_scan_btn.setEnabled(True)
        self._set_phase_status({"phase": "error", "message": f"Scan failed: {message}. Verify credentials/network/OCR settings and Retry."})

    def _on_scan_payload(self, payload):
        self.dust_fetcher, self.price_fetcher, self.dust_analyzer, items, stats = payload
        self._update_provenance()
        self.on_scan_complete(items, stats)

    def _update_provenance(self):
        dust = getattr(self.dust_fetcher, "provenance", {}) or {}
        price_state = self.price_service.runtime_state()
        dust_label = f"dust={dust.get('source', 'unknown')}"
        if dust.get("estimated"):
            dust_label += " (bundled fallback estimate)" if "built-in" in str(dust.get("source", "")) else " (estimate)"
        price_label = f"price={price_state.get('source')} status={price_state.get('status')} fetched={price_state.get('fetched_at') or 'n/a'}"
        if price_state.get("status") == "partial":
            price_label += " partial; last-known-good preserved"
        self.provenance_label.setText(f"{dust_label}; {price_label}")

    def on_scan_progress(self, current: int, total: int):
        """Update progress during scan."""
        self.results_summary.setText(f"Scanning... {current}/{total} tabs")
    
    def on_scan_complete(self, items: list, stats: dict):
        """Handle scan completion."""
        # Store ALL unfiltered results
        self.all_scan_results = items
        self.scan_stats = stats
        
        # Log scan completion once
        self.log(f"Scan complete. {len(items)} uniques found.")
        
        # Apply filter and update display
        self.apply_efficiency_filter()
    
    def apply_efficiency_filter(self):
        """Filter results by efficiency slider and update the table."""
        if not self.all_scan_results:
            return
        
        min_efficiency = self.efficiency_slider.value() * 100
        
        # Filter items by efficiency threshold
        filtered_items = [
            item for item in self.all_scan_results
            if (
                item.dust > 0
                and (
                    (
                        item.efficiency is not None
                        and item.efficiency >= min_efficiency
                    )
                    or (
                        self.include_unknown_prices.isChecked()
                        and item.chaos_price is None
                    )
                )
            )
        ]
        
        self.scan_results = filtered_items
        
        # Group items by tab for highlighting
        self.items_by_tab = group_items_by_tab(filtered_items)
        
        # Update results table
        self.results_table.setRowCount(len(filtered_items))
        
        for row, item in enumerate(filtered_items):
            self.results_table.setItem(row, 0, QTableWidgetItem(item.name))
            self.results_table.setItem(row, 1, QTableWidgetItem(item.tab_name))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(item.ilvl)))
            self.results_table.setItem(row, 3, QTableWidgetItem(str(item.dust)))
            price_text = "—" if item.chaos_price is None else f"{item.chaos_price:.1f}"
            efficiency_text = "—" if item.efficiency is None else f"{item.efficiency:.2f}"
            self.results_table.setItem(row, 4, QTableWidgetItem(price_text))
            self.results_table.setItem(row, 5, QTableWidgetItem(efficiency_text))
            
            corrupted_item = QTableWidgetItem("Yes" if item.corrupted else "No")
            if item.corrupted:
                corrupted_item.setForeground(QColor(255, 100, 100))
            self.results_table.setItem(row, 6, corrupted_item)
        
        # Update summary
        total_dust = sum(i.dust for i in filtered_items)
        tabs_count = len(self.items_by_tab)
        
        self.results_summary.setText(
            f"Found {len(filtered_items)} valuable uniques across {tabs_count} tabs | Total dust: {total_dust:,}"
        )
        
        # Enable highlighting
        if filtered_items:
            self.start_highlight_btn.setEnabled(True)
            self.highlight_status.setText(
                f"Ready to highlight {len(filtered_items)} items across {tabs_count} tabs"
            )
        else:
            self.start_highlight_btn.setEnabled(False)
            self.highlight_status.setText("No items to highlight")
    
    def get_guidance_y(self) -> int:
        """Get Y coordinate for guidance text (above tab bar)."""
        if self.tab_tracker and self.tab_tracker.is_calibrated:
            return self.tab_tracker.region_config.y
        # Fallback to calibration config
        calibration = self.config.get("calibration", {})
        tab_bar = calibration.get("tab_bar", {})
        return tab_bar.get("y", -1)

    def get_guidance_x(self) -> int:
        """Get X coordinate for guidance text (center of tab bar)."""
        if self.tab_tracker and self.tab_tracker.is_calibrated:
            return self.tab_tracker.region_config.x + (self.tab_tracker.region_config.width // 2)
        # Fallback
        calibration = self.config.get("calibration", {})
        tab_bar = calibration.get("tab_bar", {})
        x = tab_bar.get("x", -1)
        w = tab_bar.get("width", 0)
        if x > 0 and w > 0:
            return x + (w // 2)
        return -1

    def _tesseract_path_is_valid(self, tesseract_path: str) -> bool:
        """Return whether the configured Tesseract command/path can be executed."""
        if not tesseract_path:
            return False
        if os.path.isabs(tesseract_path) or os.path.sep in tesseract_path:
            return os.path.isfile(tesseract_path) and os.access(tesseract_path, os.X_OK)
        return shutil.which(tesseract_path) is not None

    def start_highlighting(self):
        """Start the multi-tab highlighting workflow."""
        if not self.scan_results:
            return
        
        # Get calibration settings
        calibration = self.config.get("calibration", {})
        tab_bar_calibration = calibration.get("tab_bar")
        
        tesseract_path = self.config.get("league_vision", {}).get(
            "tesseract_path", "tesseract"
        )
        if not self._tesseract_path_is_valid(tesseract_path):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Tesseract Not Found",
                f"Tesseract is configured as '{tesseract_path}', but it is not executable.\n\n"
                "Install Tesseract or update Settings > OCR/Tesseract path, then Retry highlighting.",
            )
            self._set_phase_status({"phase": "error", "message": "Tesseract path is invalid. Configure OCR settings before starting highlighting."})
            return
        
        # Check if tab bar is calibrated
        if not tab_bar_calibration:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self,
                "Tab Bar Not Calibrated",
                "The tab bar region has not been calibrated.\n\n"
                "Without calibration, automatic tab detection won't work.\n"
                "Use Settings > Calibration > Tab Bar Region to calibrate.\n\n"
                "Do you want to continue with manual tab confirmation only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            # Create empty config - will work with manual confirmation only
            region_config = TabRegionConfig()
        else:
            region_config = TabRegionConfig.from_calibration(tab_bar_calibration)
        
        self.tab_tracker = TabTracker(
            known_tabs=list(self.items_by_tab.keys()),
            region_config=region_config,
            tesseract_path=tesseract_path,
            debug_mode=self.debug_mode
        )
        self.tab_tracker.load_from_calibration(tab_bar_calibration)
        
        # Connect debug signal
        self.tab_tracker.debug_signal.connect(lambda msg: self.log(msg, debug_only=True))
        
        # Setup multi-tab highlighter
        self.multi_tab_highlighter = MultiTabHighlighter(
            self.tab_tracker,
            on_highlights_changed=self._update_highlights
        )
        
        # Convert items to highlight format
        highlights_by_tab = {}
        for tab_name, items in self.items_by_tab.items():
            highlights_by_tab[tab_name] = items_to_highlights(items)
        
        self.multi_tab_highlighter.set_items(highlights_by_tab)
        
        # Log tab summary
        tab_summary = ", ".join(
            f"{name}({len(items)})" for name, items in self.items_by_tab.items()
        )
        self.log(f"Highlighting across {len(self.items_by_tab)} tabs: {tab_summary}")
        
        # Start tab tracking
        self.tab_tracker_worker = TabTrackerWorker(self.tab_tracker, interval_ms=200)
        self.tab_tracker_worker.tab_changed.connect(self._on_tab_detected)
        self.tab_tracker_worker.status_signal.connect(self.log)
        self.tab_tracker_worker.ocr_debug_signal.connect(self._on_ocr_debug)
        self.tab_tracker_worker.start()
        
        # Update UI
        self.start_highlight_btn.setEnabled(False)
        self.stop_highlight_btn.setEnabled(True)
        self.manual_tab_btn.setEnabled(True)
        
        # Show debug rect if enabled
        if self.debug_mode and self.tab_tracker.is_calibrated:
            reg = self.tab_tracker.get_capture_region()
            self.log(f"DEBUG: Emitting debug rect: {reg}")
            self.overlay_debug_rect_update.emit(reg['left'], reg['top'], reg['width'], reg['height'], "cyan")
        else:
            self.log(f"DEBUG: Not showing debug rect. Mode={self.debug_mode}, Calibrated={self.tab_tracker.is_calibrated}")
        
        # Show first tab prompt - DON'T show highlights yet, wait for tab confirmation
        first_tab = self.multi_tab_highlighter.get_current_target_tab()
        if first_tab:
            items_in_tab = len(self.items_by_tab.get(first_tab, []))
            self.current_tab_label.setText(
                f"Go to tab: {first_tab} ({items_in_tab} items)"
            )
            
            # Update overlay guidance
            self.overlay_guidance_update.emit(f"Go to tab: {first_tab}", self.get_guidance_x(), self.get_guidance_y())
            
            if self.tab_tracker.is_calibrated:
                self.highlight_status.setText(
                    "Switch to the indicated tab - OCR will detect it automatically"
                )
            else:
                self.highlight_status.setText(
                    "Switch to the indicated tab, then click 'I'm on the correct tab'"
                )
            
            # Clear overlay until tab is confirmed
            self._update_highlights([])

    def _on_ocr_debug(self, raw_text: str, detected_tab: str):
        """Handle OCR debug updates for overlay."""
        if not self.debug_mode:
            return
        
        # Show raw text on overlay below the capture region
        reg = self.tab_tracker.get_capture_region()
        text_x = reg['left']
        text_y = reg['top'] + reg['height'] + 5
        
        display_text = f"OCR: '{raw_text}'"
        if detected_tab:
            display_text += f" -> MATCH: {detected_tab}"
        
        self.overlay_debug_text_update.emit(display_text, text_x, text_y)
    
    def _on_tab_detected(self, old_tab: str, new_tab: str):
        """Handle tab change detection from OCR."""
        if not self.multi_tab_highlighter:
            return
        
        self.log(f"OCR detected tab change: {old_tab or 'none'} -> {new_tab}")
        
        # Get items for new tab
        highlights = self.multi_tab_highlighter.get_highlights_for_tab(new_tab)
        items_count = len(highlights)
        
        if items_count > 0:
            self.log(f"Found {items_count} items to highlight in {new_tab}")
            self.current_tab_label.setText(f"Current: {new_tab} ({items_count} items)")
            self.overlay_guidance_update.emit(f"Current: {new_tab}", self.get_guidance_x(), self.get_guidance_y())
            self._update_highlights(highlights)
            
            # Show next tab hint
            remaining = self.multi_tab_highlighter.get_items_remaining()
            if remaining > items_count:
                self.highlight_status.setText(
                    f"Collect items, then switch to next tab ({remaining - items_count} more items)"
                )
            else:
                self.highlight_status.setText("Last tab! Collect items, then click Stop.")
        else:
            self.log(f"No items in detected tab: {new_tab}")
            self._update_highlights([]) # Clear highlights if no items in this tab
            # Check if there's a next tab with items
            remaining = self.multi_tab_highlighter.get_items_remaining()
            if remaining > 0:
                next_tab = self.multi_tab_highlighter.get_current_target_tab()
                if next_tab and next_tab != new_tab:
                    next_count = len(self.items_by_tab.get(next_tab, []))
                    self.current_tab_label.setText(
                        f"Switch to: {next_tab} ({next_count} items)"
                    )
                    self.overlay_guidance_update.emit(f"Go to: {next_tab}", self.get_guidance_x(), self.get_guidance_y())
                    self.highlight_status.setText(
                        f"Tab {new_tab} has no items - switch to {next_tab}"
                    )
            else:
                self.current_tab_label.setText("All tabs complete!")
                self.overlay_guidance_update.emit("All Complete!", self.get_guidance_x(), self.get_guidance_y())
                self.highlight_status.setText("All items highlighted! Click Stop when done.")
    
    def _update_highlights(self, highlights: list):
        """Update overlay with highlights."""
        # Always log highlight count for debugging "missing overlay" issues
        if self.debug_mode or (highlights and len(highlights) > 0):
            self.log(f"[Overlay] Emitting {len(highlights)} highlights", debug_only=self.debug_mode)
            
        self.overlay_update.emit(highlights)
    
    def stop_highlighting(self):
        """Stop the highlighting workflow and clear overlay."""
        if self.tab_tracker_worker:
            worker = self.tab_tracker_worker
            if not stop_legacy_qthread(worker, stop=worker.stop):
                return False
            disconnect_qt_signals(
                worker,
                ("tab_detected", "tab_changed", "status_signal", "ocr_debug_signal", "finished"),
            )
            self.tab_tracker_worker = None
            discard_queued_meta_calls(self)
        
        # Also clear the overlay when stopping
        self.overlay_update.emit([])
        # Clear debug overlay
        self.overlay_debug_text_update.emit("", 0, 0)
        self.overlay_debug_rect_update.emit(0, 0, 0, 0, "")
        self.overlay_guidance_update.emit("", 0, 0)
        
        self.start_highlight_btn.setEnabled(True)
        self.stop_highlight_btn.setEnabled(False)
        self.manual_tab_btn.setEnabled(False)
        self.current_tab_label.setText("")
        self.highlight_status.setText("Highlighting stopped")
        return True

    def _stop_worker(self, attribute: str) -> bool:
        worker = getattr(self, attribute, None)
        if stop_legacy_qthread(worker):
            signal_names = {
                "tab_worker": ("finished_signal", "error_signal", "finished"),
                "scan_worker": (
                    "log_signal", "debug_signal", "progress_signal",
                    "result_signal", "finished",
                ),
            }.get(attribute, ("finished",))
            if worker is not None:
                disconnect_qt_signals(worker, signal_names)
            setattr(self, attribute, None)
            return True
        return False
    
    def _on_manual_tab_confirm(self):
        """Handle manual tab confirmation (OCR fallback)."""
        self.log("Manual tab confirmation clicked")
        
        if not self.multi_tab_highlighter:
            self.log("ERROR: No multi_tab_highlighter")
            return
        
        target_tab = self.multi_tab_highlighter.get_current_target_tab()
        if not target_tab:
            self.log("No more tabs to process")
            return
        
        self.log(f"Target tab: {target_tab}")
        
        # Show highlights for current target tab
        highlights = self.multi_tab_highlighter.get_highlights_for_tab(target_tab)
        self.log(f"Got {len(highlights)} highlights for tab")
        
        if highlights:
            self._update_highlights(highlights)
            self.log(f"Showing {len(highlights)} items in tab: {target_tab}")
            self.current_tab_label.setText(f"Showing: {target_tab} ({len(highlights)} items)")
            self.overlay_guidance_update.emit(f"Current: {target_tab}", self.get_guidance_x(), self.get_guidance_y())
            
            # Advance to next tab for the next confirmation
            next_tab = self.multi_tab_highlighter.advance_to_next_tab()
            if next_tab:
                next_count = len(self.items_by_tab.get(next_tab, []))
                self.highlight_status.setText(
                    f"Collect items, then click tab: {next_tab} ({next_count} items)"
                )
            else:
                self.highlight_status.setText(
                    "Last tab! Collect items, then click Stop when done."
                )
        else:
            self.log(f"No items in tab: {target_tab}")
            self.overlay_guidance_update.emit(f"Skipping: {target_tab} (Empty)", self.get_guidance_x(), self.get_guidance_y())
            # Auto-advance if no items
            next_tab = self.multi_tab_highlighter.advance_to_next_tab()
            if next_tab:
                self._on_manual_tab_confirm()  # Recurse to show next tab
    
    def open_ocr_settings(self):
        """Open the OCR settings dialog."""
        # Get current settings
        calibration = self.config.get("calibration", {})
        tab_bar_cal = calibration.get("tab_bar", {})
        
        # If tracker is active, use its current config (which might have been tweaked)
        if self.tab_tracker:
            cfg = self.tab_tracker.region_config
            current_settings = {
                'threshold': cfg.threshold,
                'scale_factor': cfg.scale_factor,
                'psm': cfg.psm,
                'invert': cfg.invert
            }
        else:
            # Use saved config or defaults
            current_settings = {
                'threshold': tab_bar_cal.get('threshold', 150),
                'scale_factor': tab_bar_cal.get('scale_factor', 3.0),
                'psm': tab_bar_cal.get('psm', 0),
                'invert': tab_bar_cal.get('invert', True)
            }
            
        dlg = OCRSettingsDialog(current_settings, self)
        dlg.settings_changed.connect(self.update_ocr_settings)
        
        # Enable background scanning and connect preview
        if self.tab_tracker_worker:
            self.tab_tracker_worker.set_ignore_focus(True)
            self.tab_tracker_worker.ocr_debug_signal.connect(dlg.update_preview)
        
        dlg.exec()
        
        # Restore normal scanning
        if self.tab_tracker_worker:
            self.tab_tracker_worker.set_ignore_focus(False)
            # Signal automatically disconnected when dlg is destroyed
        
    def update_ocr_settings(self, settings: dict):
        """Update OCR settings from dialog."""
        self.log(f"Updating OCR settings: {settings}")
        
        # Update config dict (for next run / persistence)
        if "calibration" not in self.config:
            self.config["calibration"] = {}
        if "tab_bar" not in self.config["calibration"]:
            self.config["calibration"]["tab_bar"] = {}
            
        tab_bar_cal = self.config["calibration"]["tab_bar"]
        tab_bar_cal.update(settings)
        
        # Update active tracker
        if self.tab_tracker:
            self.tab_tracker.set_ocr_settings(
                threshold=settings['threshold'],
                scale=settings['scale_factor'],
                psm=settings['psm'],
                invert=settings['invert']
            )

    def clear_overlay(self):
        """Clear all highlights."""
        self.overlay_update.emit([])
        self.current_tab_label.setText("")
    
    def sync_config(self):
        """Persist tool-local filters; shared league belongs to Settings."""
        self.dust_config["min_efficiency"] = self.efficiency_slider.value()
        self.dust_config["include_unknown_prices"] = self.include_unknown_prices.isChecked()
        self.dust_config["selected_tabs"] = self._selected_tab_refs()
        self.config["kalguur_dust"] = self.dust_config

    def refresh_shared_settings(self):
        """Refresh mirrored account and league values from application Settings."""
        self.account_label.setText(f"Account: {ConfigManager.get_account_name(self.config)}")
        league = ConfigManager.get_game_league(self.config, self.game_id)
        if self.dust_fetcher is not None and self.dust_fetcher.league != league:
            self.dust_fetcher = None
            self.dust_analyzer = None
        if self.price_fetcher is not None and self.price_fetcher.league != league:
            self.price_fetcher = None
        self.price_service.set_context(self.game_id, league)
        index = self.league_input.findText(league)
        if league and index < 0:
            self.league_input.insertItem(0, league)
            index = 0
        if index >= 0:
            self.league_input.setCurrentIndex(index)

    def get_credentials(self):
        """Legacy save hook: account credentials now live in Settings."""
        self.sync_config()
        return {}
    
    def cleanup(self):
        """Cleanup resources."""
        success = self.stop_highlighting()
        success = self._stop_worker("tab_worker") and success
        success = self._stop_worker("scan_worker") and success
        registry = getattr(self, "worker_registry", None)
        if registry is not None:
            success = registry.close(timeout_ms=5000) and success
        if success:
            self._pending_scan_args = None
            self._disconnect_price_service_signals()
            discard_queued_meta_calls(self)
        self.clear_overlay()
        if success and getattr(self, "_owns_price_service", False):
            success = self.price_service.close()
        return success


class KalguurDustTool(BaseTool):
    """Kalguur Dust Tool plugin."""
    
    @property
    def name(self) -> str:
        return "Kalguur Dust"
    
    @property
    def icon(self) -> str:
        return "dust"
    
    @property
    def description(self) -> str:
        return "Find valuable uniques to disenchant for Thaumaturgic Dust"
    
    def __init__(self, config: dict, price_service=None):
        self.config = config
        self.price_service = price_service
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = KalguurDustWidget(
            self.config,
            price_service=self.price_service,
            parent=parent,
        )
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        if self.widget:
            self.widget.stop_highlighting()
    
    def cleanup(self):
        if self.widget:
            return self.widget.cleanup()
        return True

