"""
Ultimatum Helper Tool - Scan stash tabs for profitable Inscribed Ultimatums.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QSlider, QTextEdit, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from tools.base_tool import BaseTool
from api.auth import SessionAuthProvider
from api.client import PoEClient
from services.price_service import PriceService
from core.parser import UltimatumParser
from core.filters import (
    FilteringRuleEngine, ValueRule, 
    EncounterRule, EncounterIncludeOverride,
    RewardRule, RewardIncludeOverride,
    MonsterLifeRule, MonsterLifeIncludeOverride
)
from ui.components.stash_selector import StashTabSelector
from ui.components.filter_dialog import FilterConfigDialog
from utils.logger import DebugLogger
from utils.config import ConfigManager
from utils.workers import (
    disconnect_qt_signals,
    discard_queued_meta_calls,
    stop_legacy_qthread,
    WorkerRegistry,
    CancelledError,
)


def build_ultimatum_filter_engine(config):
    """Build the explicit Ultimatum filter engine.

    Include lists are positive overrides: if an include override matches, the
    item is highlighted even when excluded or below the value threshold.
    Exclude lists are normal fail rules evaluated only when no include override
    matched. Unknown prices fail value filtering unless an include override
    matched.
    """
    engine = FilteringRuleEngine()
    engine.add_rule(ValueRule(min_profit=config.get("min_profit", 20)))
    if config.get("excluded_types"):
        engine.add_rule(EncounterRule(excluded_types=config.get("excluded_types")))
    if config.get("excluded_rewards"):
        engine.add_rule(RewardRule(excluded_rewards=config.get("excluded_rewards")))
    if config.get("excluded_tiers"):
        engine.add_rule(MonsterLifeRule(excluded_pcts=config.get("excluded_tiers")))
    if config.get("included_types"):
        engine.add_override(EncounterIncludeOverride(included_types=config.get("included_types")))
    if config.get("included_rewards"):
        engine.add_override(RewardIncludeOverride(included_rewards=config.get("included_rewards")))
    if config.get("included_tiers"):
        engine.add_override(MonsterLifeIncludeOverride(included_pcts=config.get("included_tiers")))
    return engine


def fetch_ultimatum_tab_list_operation(session_id, account, league, *, context=None):
    auth = SessionAuthProvider(session_id)
    client = PoEClient(auth, account, league)
    try:
        tabs = client.get_stash_tab_list(context=context, rate_limit_callback=context.report_progress if context is not None else None)
        if not tabs:
            raise RuntimeError("No stash tabs were returned. Verify account/POESESSID/league and Retry.")
        return tabs
    finally:
        client.close()


def scan_ultimatum_operation(session_id, account, league, config, tab_indices, price_fetcher, debug_mode=False, *, context=None):
    if context is not None:
        context.report_progress({"phase": "prepare", "message": "Initializing API client", "current": 0, "total": len(tab_indices)})
    DebugLogger.set_enabled(debug_mode)
    auth = SessionAuthProvider(session_id)
    client = PoEClient(auth, account, league)
    parser = UltimatumParser()
    engine = build_ultimatum_filter_engine(config)
    all_highlights = []
    all_parsed_items = []
    found_stats = {'types': set(), 'rewards': set(), 'tiers': set()}
    failed_tabs = []
    total_tabs = len(tab_indices)
    try:
        for i, tab_idx in enumerate(tab_indices):
            if context is not None:
                context.report_progress({"phase": "scan", "message": f"Fetching tab {tab_idx}", "current": i, "total": total_tabs})
                if i > 0:
                    context.sleep(1.5)
            try:
                data = client.get_stash_items(tab_idx, context=context, rate_limit_callback=context.report_progress if context is not None else None)
            except CancelledError:
                raise
            except Exception as error:
                failed_tabs.append((tab_idx, str(error)))
                DebugLogger.log(f"Failed fetch for tab {tab_idx}: {error}", "API")
                continue
            if not data or 'items' not in data:
                failed_tabs.append((tab_idx, "API response did not include items"))
                continue
            is_quad = data.get('quadLayout', False)
            for item in data.get('items', []):
                parsed = parser.parse_item(item)
                if not parsed:
                    continue
                found_stats['types'].add(parsed.get('type', 'Unknown'))
                found_stats['rewards'].add((parsed.get('reward', 'Unknown'), parsed.get('reward_count', 1), parsed.get('sacrifice', None), parsed.get('sacrifice_count', 1)))
                found_stats['tiers'].add(parsed.get('monster_life_pct', 0))
                all_parsed_items.append({'parsed': parsed, 'item': item, 'tab_index': tab_idx, 'is_quad': is_quad})
                if engine.evaluate(parsed, price_fetcher):
                    all_highlights.append({'tab_index': tab_idx, 'x': item['x'], 'y': item['y'], 'w': item.get('w', 1), 'h': item.get('h', 1), 'name': parsed.get('reward', 'Unknown'), 'is_quad': is_quad})
            if context is not None:
                context.report_progress({"phase": "scan", "message": f"Scanned tab {tab_idx}", "current": i + 1, "total": total_tabs})
        if failed_tabs and len(failed_tabs) == total_tabs:
            details = "; ".join(f"{idx}: {msg}" for idx, msg in failed_tabs[:3])
            raise RuntimeError(f"Every selected stash tab fetch failed ({details}). Check credentials/league/network and Retry.")
        return all_highlights, found_stats, all_parsed_items, price_fetcher
    finally:
        client.close()


class UltimatumWidget(QWidget):
    """Main widget for Ultimatum tool."""
    
    overlay_update = pyqtSignal(list)  # Emits highlight rects
    
    def __init__(self, config: dict, price_service=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.game_id = "poe1"
        league = ConfigManager.get_game_league(config, self.game_id)
        self._owns_price_service = price_service is None
        self.price_service = price_service or PriceService(self.game_id, league)
        self.ultimatum_config = config.get("ultimatum", {})
        self.cached_scan_data = None
        self.price_fetcher = None
        self.worker = None
        self.tab_worker = None
        self.worker_registry = WorkerRegistry(max_threads=2)
        self._pending_scan_args = None
        self._active_scan_context = None
        self._active_tab_fetch_context = None
        self._tab_list_context = None
        self._price_service_signals_connected = False
        self.found_stats = {'types': set(), 'rewards': set(), 'tiers': set()}
        
        self._connect_price_service_signals()
        self.setup_ui()
    
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
        if not getattr(self, "_price_service_signals_connected", False):
            return
        for signal_name, callback in (("refresh_completed", self._on_price_refresh_completed), ("refresh_failed", self._on_price_refresh_failed)):
            signal = getattr(self.price_service, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass
        self._price_service_signals_connected = False

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Ultimatum Helper")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # Shared account settings
        creds_layout = QVBoxLayout()
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
        self.league_input.setEnabled(False)
        creds_row.addWidget(self.league_input)
        creds_layout.addLayout(creds_row)
        layout.addLayout(creds_layout)

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

        # Tab Selector
        layout.addWidget(QLabel("Select Tabs to Scan:"))
        self.tab_selector = StashTabSelector()
        layout.addWidget(self.tab_selector)

        # Scan Action
        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("2. Scan Selected Tabs")
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

        # Min Profit Slider
        layout.addWidget(QLabel("Min Profit (Chaos):"))
        self.profit_slider = QSlider(Qt.Orientation.Horizontal)
        self.profit_slider.setRange(0, 200)
        self.profit_slider.setValue(self.ultimatum_config.get("min_profit", 20))
        self.profit_label = QLabel(f"{self.profit_slider.value()}c")
        self.profit_slider.valueChanged.connect(self.on_profit_slider_changed)
        
        profit_layout = QHBoxLayout()
        profit_layout.addWidget(self.profit_slider)
        profit_layout.addWidget(self.profit_label)
        layout.addLayout(profit_layout)

        # Filter Button
        self.filter_btn = QPushButton("Configure Filters...")
        self.filter_btn.clicked.connect(self.open_filter_dialog)
        layout.addWidget(self.filter_btn)
        
        # Clear Button
        self.clear_btn = QPushButton("Clear Overlay")
        self.clear_btn.clicked.connect(self.clear_overlay)
        layout.addWidget(self.clear_btn)

        # Log Area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        layout.addWidget(self.log_area)
        
        layout.addStretch()

    def log(self, message):
        self.log_area.append(message)

    def on_profit_slider_changed(self, value):
        self.profit_label.setText(f"{value}c")
        self.ultimatum_config["min_profit"] = value
        if self.cached_scan_data:
            self.apply_filters_and_update()

    def _set_phase_status(self, progress):
        if isinstance(progress, dict):
            phase = progress.get("phase", "work")
            message = progress.get("message") or phase.replace("_", " ")
            if phase == "rate_limit":
                message = f"Rate limited: retrying in {progress.get('retry_after', '?')}s"
            current = progress.get("current")
            total = progress.get("total")
            suffix = f" ({current}/{total})" if current is not None and total is not None else ""
            self.phase_status.setText(f"{phase}: {message}{suffix}")
            self.log(self.phase_status.text())
        else:
            self.phase_status.setText(str(progress))

    def cancel_operation(self, operation: str):
        names = {"tab-fetch": ("ultimatum-tab-fetch", self.cancel_tabs_btn), "scan": ("ultimatum-scan", self.cancel_scan_btn)}
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

    def fetch_tab_list(self):
        session_id = ConfigManager.get_session_id(self.config)
        account = ConfigManager.get_account_name(self.config)
        league = ConfigManager.get_game_league(self.config, self.game_id)
        if not session_id or not account:
            self.log("Error: Credentials required. Set account and POESESSID in Settings, then retry.")
            return False
        if "ultimatum-tab-fetch" in self.worker_registry.active_names:
            self.log("Tab fetch is already running; wait or Cancel first.")
            return False
        self.fetch_tabs_btn.setEnabled(False)
        self.cancel_tabs_btn.setEnabled(True)
        self.retry_tabs_btn.setEnabled(False)
        self._set_phase_status({"phase": "tab_fetch", "message": "Starting tab fetch"})
        def operation(context):
            return fetch_ultimatum_tab_list_operation(session_id, account, league, context=context)
        fetch_context = (account, league)
        started = self.worker_registry.start("ultimatum-tab-fetch", operation, on_progress=self._set_phase_status, on_result=lambda tabs, expected=fetch_context: self._on_tabs_fetched_for_context(expected, tabs), on_error=self._on_tab_fetch_error, on_cancelled=lambda: self._on_operation_cancelled("tab_fetch"), on_finished=self._on_fetch_finished)
        if not started:
            self.log("Tab fetch is already running; duplicate start ignored.")
        else:
            self._active_tab_fetch_context = fetch_context
        return started

    def _on_fetch_finished(self):
        self._active_tab_fetch_context = None
        self.fetch_tabs_btn.setEnabled(True)
        self.cancel_tabs_btn.setEnabled(False)

    def _on_tab_fetch_error(self, error):
        message = getattr(error, "message", str(error))
        self.retry_tabs_btn.setEnabled(True)
        self.scan_btn.setEnabled(False)
        self._set_phase_status({"phase": "error", "message": f"Tab fetch failed: {message}. Check credentials/league/network and Retry."})

    def _on_operation_cancelled(self, phase):
        self._set_phase_status({"phase": "cancelled", "message": f"{phase} cancelled"})
        self.retry_tabs_btn.setEnabled(True)
        self.retry_scan_btn.setEnabled(True)

    def _on_tabs_fetched_for_context(self, expected_context, tabs):
        current_context = (
            ConfigManager.get_account_name(self.config) or "",
            ConfigManager.get_game_league(self.config, self.game_id),
        )
        if expected_context != current_context:
            self.retry_tabs_btn.setEnabled(True)
            self.scan_btn.setEnabled(False)
            self._set_phase_status({"phase": "cancelled", "message": "Discarded stale tab results after Settings changed. Fetch tabs again."})
            return
        self._tab_list_context = expected_context
        self.on_tabs_fetched(tabs)

    def on_tabs_fetched(self, tabs):
        if not tabs:
            self.retry_tabs_btn.setEnabled(True)
            self.scan_btn.setEnabled(False)
            self._set_phase_status({"phase": "error", "message": "No stash tabs were returned. Verify account/POESESSID/league and Retry."})
            return
        self.log(f"Fetched {len(tabs)} tabs.")
        self._tab_list_context = self._active_tab_fetch_context or (
            ConfigManager.get_account_name(self.config) or "",
            ConfigManager.get_game_league(self.config, self.game_id),
        )
        self.tab_selector.load_tabs(tabs)
        self.scan_btn.setEnabled(True)

    def start_scan(self):
        selected_indices = tuple(self.tab_selector.get_selected_indices())
        if not selected_indices:
            self.log("No tabs selected!")
            return False
        if "ultimatum-scan" in self.worker_registry.active_names or self._pending_scan_args is not None:
            self.log("Preparation/scan is already running; wait or Cancel first.")
            return False
        session_id = ConfigManager.get_session_id(self.config)
        account = ConfigManager.get_account_name(self.config)
        league = ConfigManager.get_game_league(self.config, self.game_id)
        if not session_id or not account:
            self.log("Error: Credentials required. Set account and POESESSID in Settings, then retry.")
            return False
        scan_config = {
            "min_profit": self.ultimatum_config.get("min_profit", 20),
            "excluded_types": self.ultimatum_config.get("excluded_types", []),
            "included_types": self.ultimatum_config.get("included_types", []),
            "excluded_rewards": self.ultimatum_config.get("excluded_rewards", []),
            "included_rewards": self.ultimatum_config.get("included_rewards", []),
            "excluded_tiers": self.ultimatum_config.get("excluded_tiers", []),
            "included_tiers": self.ultimatum_config.get("included_tiers", []),
        }
        pending_args = {"session_id": session_id, "account": account, "league": league, "game": self.game_id, "scan_config": scan_config, "selected_indices": selected_indices, "debug_mode": self.config.get("debug_mode", False)}
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

    def _current_price_fetcher(self):
        current = getattr(self.price_service, "current_fetcher", None)
        if callable(current):
            return current()
        return None

    def _active_price_refresh_context(self):
        active_context = getattr(self.price_service, "active_refresh_context", None)
        if callable(active_context):
            return active_context()
        return None

    def _on_price_refresh_completed(self, result):
        pending_args = self._pending_scan_args
        if pending_args is None:
            return
        state_getter = getattr(self.price_service, "runtime_state", None)
        state = state_getter() if callable(state_getter) else {"game": self.game_id, "league": ConfigManager.get_game_league(self.config, self.game_id)}
        if (state.get("game"), state.get("league")) != (pending_args["game"], pending_args["league"]):
            self._pending_scan_args = None
            self.scan_btn.setEnabled(True)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
            self._set_phase_status({"phase": "error", "message": "Price context changed while preparing; Retry scan with the current Settings account and league."})
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
        if "ultimatum-scan" in self.worker_registry.active_names:
            self.log("Scan is already running; duplicate start ignored.")
            return False
        def operation(context):
            return scan_ultimatum_operation(pending_args["session_id"], pending_args["account"], pending_args["league"], pending_args["scan_config"], list(pending_args["selected_indices"]), price_fetcher, pending_args["debug_mode"], context=context)
        scan_context = (pending_args["account"], pending_args["league"])
        started = self.worker_registry.start("ultimatum-scan", operation, on_progress=self._set_phase_status, on_result=lambda payload, expected=scan_context: self._on_scan_result_for_context(expected, payload), on_error=self._on_scan_error, on_cancelled=lambda: self._on_operation_cancelled("scan"), on_finished=self._on_scan_finished)
        if not started:
            self.log("Scan is already running; duplicate start ignored.")
        else:
            self._active_scan_context = scan_context
        return started

    def _on_scan_finished(self):
        self._active_scan_context = None
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)

    def _on_scan_error(self, error):
        message = getattr(error, "message", str(error))
        self.retry_scan_btn.setEnabled(True)
        self._set_phase_status({"phase": "error", "message": f"Scan failed: {message}. Check credentials/league/network and Retry."})

    def _on_scan_result_for_context(self, expected_context, payload):
        current_context = (
            ConfigManager.get_account_name(self.config) or "",
            ConfigManager.get_game_league(self.config, self.game_id),
        )
        if expected_context != current_context:
            self.retry_tabs_btn.setEnabled(True)
            self.retry_scan_btn.setEnabled(True)
            self.scan_btn.setEnabled(False)
            self._set_phase_status({"phase": "cancelled", "message": "Discarded stale scan results after Settings changed. Fetch tabs again."})
            return
        self.on_scan_result(*payload)

    def on_scan_result(self, highlights, stats, all_items, price_fetcher):
        self.cached_scan_data = all_items
        self.price_fetcher = price_fetcher
        self.found_stats = stats
        self.overlay_update.emit(highlights)
        self._set_phase_status({"phase": "complete", "message": f"Scan complete. Found {len(highlights)} highlighted items."})

    def apply_filters_and_update(self):
        if not self.cached_scan_data:
            return

        engine = build_ultimatum_filter_engine(self.ultimatum_config)

        if not self.price_fetcher:
            self.price_fetcher = self._current_price_fetcher()
            if not self.price_fetcher:
                self.retry_scan_btn.setEnabled(True)
                self._set_phase_status({"phase": "error", "message": "No price snapshot is loaded yet; Retry scan to prepare prices in background."})
                return

        valid_highlights = []
        
        for item_data in self.cached_scan_data:
            parsed = item_data['parsed']
            raw_item = item_data['item']
            tab_idx = item_data['tab_index']
            is_quad = item_data['is_quad']
            
            if engine.evaluate(parsed, self.price_fetcher):
                valid_highlights.append({
                    'tab_index': tab_idx,
                    'x': raw_item['x'], 
                    'y': raw_item['y'], 
                    'w': raw_item.get('w', 1), 
                    'h': raw_item.get('h', 1),
                    'name': parsed.get('reward', 'Unknown'),
                    'is_quad': is_quad
                })
        
        self.overlay_update.emit(valid_highlights)

    def open_filter_dialog(self):
        dlg = FilterConfigDialog(
            self, 
            self.found_stats, 
            self.ultimatum_config,
            self.price_fetcher
        )
        if dlg.exec():
            updates = dlg.get_config_updates()
            self.ultimatum_config.update(updates)
            self.log("Filter configuration updated.")
            if self.cached_scan_data:
                self.apply_filters_and_update()

    def clear_overlay(self):
        self.overlay_update.emit([])
        self.cached_scan_data = None
        self.log("Overlay cleared.")

    def cleanup(self):
        """Stop active workers or fail closed while they remain active."""
        success = True
        registry = getattr(self, "worker_registry", None)
        if registry is not None:
            success = bool(registry.close())
        worker_signals = {
            "worker": ("log_signal", "result_signal", "progress_signal", "finished"),
            "tab_worker": ("finished_signal", "error_signal", "finished"),
        }
        for attribute, signal_names in worker_signals.items():
            worker = getattr(self, attribute, None)
            stopped = stop_legacy_qthread(worker)
            if stopped:
                if worker is not None:
                    disconnect_qt_signals(worker, signal_names)
                setattr(self, attribute, None)
            else:
                success = False
        if success:
            self._pending_scan_args = None
            disconnect_price_signals = getattr(self, "_disconnect_price_service_signals", None)
            if callable(disconnect_price_signals):
                disconnect_price_signals()
            discard_queued_meta_calls(self)
        self.clear_overlay()
        if success and getattr(self, "_owns_price_service", False):
            success = self.price_service.close()
        return success

    def sync_config(self):
        """Synchronize tool-local filters before the main window persists config."""
        self.ultimatum_config["min_profit"] = self.profit_slider.value()
        self.config["ultimatum"] = self.ultimatum_config

    def refresh_shared_settings(self):
        """Refresh mirrored settings and fail closed on stale scan contexts."""
        account = ConfigManager.get_account_name(self.config) or ""
        league = ConfigManager.get_game_league(self.config, self.game_id)
        self.account_label.setText(account or "Not set")
        current_context = (account, league)

        tabs_stale = self._tab_list_context is not None and self._tab_list_context != current_context
        if tabs_stale:
            self._tab_list_context = None
            self.tab_selector.load_tabs([])
            self.scan_btn.setEnabled(False)
            self.retry_tabs_btn.setEnabled(True)

        pending = self._pending_scan_args
        pending_stale = pending is not None and (pending["account"], pending["league"]) != current_context
        active_scan_stale = self._active_scan_context is not None and self._active_scan_context != current_context
        active_tab_stale = self._active_tab_fetch_context is not None and self._active_tab_fetch_context != current_context
        if pending_stale:
            self._pending_scan_args = None
            self.scan_btn.setEnabled(not tabs_stale)
            self.cancel_scan_btn.setEnabled(False)
            self.retry_scan_btn.setEnabled(True)
        if active_scan_stale:
            self.worker_registry.cancel("ultimatum-scan")
            self.retry_scan_btn.setEnabled(True)
        if active_tab_stale:
            self.worker_registry.cancel("ultimatum-tab-fetch")
            self.retry_tabs_btn.setEnabled(True)
        if tabs_stale or pending_stale or active_scan_stale or active_tab_stale:
            self._set_phase_status({"phase": "cancelled", "message": "Settings account or league changed; stale tabs/work cleared. Fetch tabs again and Retry with the current context."})

        if self.price_fetcher is not None and getattr(self.price_fetcher, "league", league) != league:
            self.price_fetcher = None
            self.cached_scan_data = None
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


class UltimatumTool(BaseTool):
    """Ultimatum Helper Tool plugin."""
    
    @property
    def name(self) -> str:
        return "Ultimatum"
    
    @property
    def icon(self) -> str:
        return "ultimatum"
    
    @property
    def description(self) -> str:
        return "Scan stash tabs for profitable Inscribed Ultimatums"
    
    def __init__(self, config: dict, price_service=None):
        self.config = config
        self.price_service = price_service
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = UltimatumWidget(
            self.config,
            price_service=self.price_service,
            parent=parent,
        )
        return self.widget
    
    def on_activated(self):
        if self.widget:
            self.widget.refresh_shared_settings()
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            return self.widget.cleanup()
        return True

