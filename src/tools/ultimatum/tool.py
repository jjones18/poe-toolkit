"""
Ultimatum Helper Tool - Scan stash tabs for profitable Inscribed Ultimatums.
"""

import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QSlider, QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect

from tools.base_tool import BaseTool
from api.auth import SessionAuthProvider
from api.client import PoEClient
from core.valuation import NinjaPriceFetcher
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


class ScanWorker(QThread):
    """Background worker for scanning stash tabs."""
    
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(list, dict, list, object)
    progress_signal = pyqtSignal(int, int)

    def __init__(self, session_id, account, league, config, tab_indices, debug_mode=False):
        super().__init__()
        self.session_id = session_id
        self.account = account
        self.league = league
        self.config = config
        self.tab_indices = tab_indices
        self.debug_mode = debug_mode
        DebugLogger.set_enabled(debug_mode)

    def run(self):
        self.log_signal.emit("Initializing API Client...")
        DebugLogger.log("Scan started.", "Worker")
        
        auth = SessionAuthProvider(self.session_id)
        client = PoEClient(auth, self.account, self.league)

        self.log_signal.emit("Fetching Prices...")
        price_fetcher = NinjaPriceFetcher(self.league)
        price_fetcher.fetch_all_prices()
        DebugLogger.log(f"Prices fetched: {len(price_fetcher.prices)} items.", "Prices")

        parser = UltimatumParser()
        engine = FilteringRuleEngine()
        
        min_profit = self.config.get("min_profit", 20)
        engine.add_rule(ValueRule(min_profit=min_profit))
        
        # Exclusion rules (standard rules - all must pass)
        if self.config.get("excluded_types"):
            engine.add_rule(EncounterRule(excluded_types=self.config.get("excluded_types")))

        if self.config.get("excluded_rewards"):
            engine.add_rule(RewardRule(excluded_rewards=self.config.get("excluded_rewards")))
            
        if self.config.get("excluded_tiers"):
            engine.add_rule(MonsterLifeRule(excluded_pcts=self.config.get("excluded_tiers")))
        
        # Include overrides (if any match, item is highlighted regardless of other rules)
        if self.config.get("included_types"):
            engine.add_override(EncounterIncludeOverride(included_types=self.config.get("included_types")))

        if self.config.get("included_rewards"):
            engine.add_override(RewardIncludeOverride(included_rewards=self.config.get("included_rewards")))
            
        if self.config.get("included_tiers"):
            engine.add_override(MonsterLifeIncludeOverride(included_pcts=self.config.get("included_tiers")))

        all_highlights = []
        all_parsed_items = []
        found_stats = {
            'types': set(),
            'rewards': set(),
            'tiers': set()
        }
        
        total_found = 0
        total_tabs = len(self.tab_indices)

        self.log_signal.emit(f"Scanning {total_tabs} tabs...")
        DebugLogger.log(f"Scanning tabs: {self.tab_indices}", "Worker")

        for i, tab_idx in enumerate(self.tab_indices):
            self.log_signal.emit(f"Fetching Tab Index {tab_idx} ({i+1}/{total_tabs})...")
            
            if i > 0:
                time.sleep(1.5) 
            
            data = client.get_stash_items(tab_idx)
            if not data or 'items' not in data:
                self.log_signal.emit(f"Failed to fetch tab {tab_idx}.")
                DebugLogger.log(f"Failed fetch for tab {tab_idx}", "API")
                continue
            
            is_quad = data.get('quadLayout', False)
            items = data.get('items', [])
            DebugLogger.log(f"Tab {tab_idx} contains {len(items)} items. Quad: {is_quad}", "API")
            
            for item in items:
                parsed = parser.parse_item(item)
                if parsed:
                    found_stats['types'].add(parsed.get('type', 'Unknown'))
                    # Store reward as tuple: (reward_name, reward_count, sacrifice_name, sacrifice_count)
                    reward_tuple = (
                        parsed.get('reward', 'Unknown'),
                        parsed.get('reward_count', 1),
                        parsed.get('sacrifice', None),
                        parsed.get('sacrifice_count', 1)
                    )
                    found_stats['rewards'].add(reward_tuple)
                    found_stats['tiers'].add(parsed.get('monster_life_pct', 0))
                    
                    all_parsed_items.append({
                        'parsed': parsed,
                        'item': item,
                        'tab_index': tab_idx,
                        'is_quad': is_quad
                    })

                    if engine.evaluate(parsed, price_fetcher):
                        DebugLogger.log("-> Highlighted (Passed Filters)", "Engine")
                        
                        all_highlights.append({
                            'tab_index': tab_idx,
                            'x': item['x'], 
                            'y': item['y'], 
                            'w': item.get('w', 1), 
                            'h': item.get('h', 1),
                            'name': parsed.get('reward', 'Unknown'),
                            'is_quad': is_quad
                        })
                        total_found += 1

            self.progress_signal.emit(i+1, total_tabs)

        self.log_signal.emit(f"Scan Complete. Found {total_found} items.")
        DebugLogger.log(f"Scan complete. Total found: {total_found}", "Worker")
        
        if hasattr(price_fetcher, 'session'):
            try:
                price_fetcher.session.close()
            except:
                pass
            del price_fetcher.session

        self.result_signal.emit(all_highlights, found_stats, all_parsed_items, price_fetcher)


class TabListWorker(QThread):
    """Fetches list of tabs only."""
    
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, session_id, account, league):
        super().__init__()
        self.session_id = session_id
        self.account = account
        self.league = league

    def run(self):
        try:
            auth = SessionAuthProvider(self.session_id)
            client = PoEClient(auth, self.account, self.league)
            tabs = client.get_stash_tab_list()
            self.finished_signal.emit(tabs)
        except Exception as e:
            self.error_signal.emit(str(e))


class UltimatumWidget(QWidget):
    """Main widget for Ultimatum tool."""
    
    overlay_update = pyqtSignal(list)  # Emits highlight rects
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.ultimatum_config = config.get("ultimatum", {})
        self.cached_scan_data = None
        self.price_fetcher = None
        self.found_stats = {'types': set(), 'rewards': set(), 'tiers': set()}
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Ultimatum Helper")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # Credentials Section
        creds_layout = QVBoxLayout()
        creds_layout.addWidget(QLabel("POESESSID:"))
        self.sess_id_input = QLineEdit()
        self.sess_id_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.sess_id_input.setText(self.config.get("credentials", {}).get("session_id", ""))
        creds_layout.addWidget(self.sess_id_input)

        creds_row = QHBoxLayout()
        creds_row.addWidget(QLabel("Account:"))
        self.account_input = QLineEdit()
        self.account_input.setText(self.config.get("credentials", {}).get("account_name", ""))
        creds_row.addWidget(self.account_input)
        
        creds_row.addWidget(QLabel("League:"))
        self.league_input = QLineEdit()
        self.league_input.setText(self.config.get("credentials", {}).get("league", "Settlers"))
        creds_row.addWidget(self.league_input)
        creds_layout.addLayout(creds_row)
        layout.addLayout(creds_layout)

        # Fetch Tabs Button
        self.fetch_tabs_btn = QPushButton("1. Fetch Tab List")
        self.fetch_tabs_btn.clicked.connect(self.fetch_tab_list)
        layout.addWidget(self.fetch_tabs_btn)

        # Tab Selector
        layout.addWidget(QLabel("Select Tabs to Scan:"))
        self.tab_selector = StashTabSelector()
        layout.addWidget(self.tab_selector)

        # Scan Action
        self.scan_btn = QPushButton("2. Scan Selected Tabs")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setEnabled(False)
        layout.addWidget(self.scan_btn)

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

    def fetch_tab_list(self):
        session_id = self.sess_id_input.text().strip()
        account = self.account_input.text().strip()
        league = self.league_input.text().strip()
        
        if not session_id or not account:
            self.log("Error: Credentials required.")
            return

        self.fetch_tabs_btn.setEnabled(False)
        self.log("Fetching tab list...")
        
        self.tab_worker = TabListWorker(session_id, account, league)
        self.tab_worker.finished_signal.connect(self.on_tabs_fetched)
        self.tab_worker.error_signal.connect(lambda e: self.log(f"Error: {e}"))
        self.tab_worker.finished.connect(lambda: self.fetch_tabs_btn.setEnabled(True))
        self.tab_worker.start()

    def on_tabs_fetched(self, tabs):
        self.log(f"Fetched {len(tabs)} tabs.")
        self.tab_selector.load_tabs(tabs)
        self.scan_btn.setEnabled(True)

    def start_scan(self):
        selected_indices = self.tab_selector.get_selected_indices()
        if not selected_indices:
            self.log("No tabs selected!")
            return

        session_id = self.sess_id_input.text().strip()
        account = self.account_input.text().strip()
        league = self.league_input.text().strip()
        
        self.scan_btn.setEnabled(False)
        
        scan_config = {
            "min_profit": self.ultimatum_config.get("min_profit", 20),
            "excluded_types": self.ultimatum_config.get("excluded_types", []),
            "included_types": self.ultimatum_config.get("included_types", []),
            "excluded_rewards": self.ultimatum_config.get("excluded_rewards", []),
            "included_rewards": self.ultimatum_config.get("included_rewards", []),
            "excluded_tiers": self.ultimatum_config.get("excluded_tiers", []),
            "included_tiers": self.ultimatum_config.get("included_tiers", []),
        }
        
        self.worker = ScanWorker(session_id, account, league, scan_config, selected_indices)
        self.worker.log_signal.connect(self.log)
        self.worker.result_signal.connect(self.on_scan_result)
        self.worker.finished.connect(lambda: self.scan_btn.setEnabled(True))
        self.worker.start()

    def on_scan_result(self, highlights, stats, all_items, price_fetcher):
        self.cached_scan_data = all_items
        self.price_fetcher = price_fetcher
        self.found_stats = stats
        self.overlay_update.emit(highlights)

    def apply_filters_and_update(self):
        if not self.cached_scan_data:
            return

        engine = FilteringRuleEngine()
        min_profit = self.ultimatum_config.get("min_profit", 20)
        engine.add_rule(ValueRule(min_profit=min_profit))
        
        # Exclusion rules (standard rules - all must pass)
        if self.ultimatum_config.get("excluded_types"):
            engine.add_rule(EncounterRule(excluded_types=self.ultimatum_config.get("excluded_types")))

        if self.ultimatum_config.get("excluded_rewards"):
            engine.add_rule(RewardRule(excluded_rewards=self.ultimatum_config.get("excluded_rewards")))
            
        if self.ultimatum_config.get("excluded_tiers"):
            engine.add_rule(MonsterLifeRule(excluded_pcts=self.ultimatum_config.get("excluded_tiers")))
        
        # Include overrides (if any match, item is highlighted regardless of other rules)
        if self.ultimatum_config.get("included_types"):
            engine.add_override(EncounterIncludeOverride(included_types=self.ultimatum_config.get("included_types")))

        if self.ultimatum_config.get("included_rewards"):
            engine.add_override(RewardIncludeOverride(included_rewards=self.ultimatum_config.get("included_rewards")))
            
        if self.ultimatum_config.get("included_tiers"):
            engine.add_override(MonsterLifeIncludeOverride(included_pcts=self.ultimatum_config.get("included_tiers")))

        if not self.price_fetcher:
            self.price_fetcher = NinjaPriceFetcher(self.league_input.text().strip())
            self.price_fetcher.fetch_all_prices()

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

    def get_credentials(self):
        """Return current credentials for saving."""
        return {
            "session_id": self.sess_id_input.text().strip(),
            "account_name": self.account_input.text().strip(),
            "league": self.league_input.text().strip()
        }


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
    
    def __init__(self, config: dict):
        self.config = config
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = UltimatumWidget(self.config, parent)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            self.widget.clear_overlay()

