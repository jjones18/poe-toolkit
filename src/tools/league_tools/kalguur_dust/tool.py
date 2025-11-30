"""
Kalguur Dust Tool - Find valuable uniques to disenchant for Thaumaturgic Dust.

Scans stash tabs for unique items and calculates their dust efficiency
(dust per chaos spent), helping identify items worth disenchanting.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QTextEdit, QSplitter, QFrame,
    QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from tools.base_tool import BaseTool
from core.valuation import NinjaPriceFetcher
from ui.components.stash_selector import StashTabSelector

from .dust_data import DustDataFetcher, DustEfficiencyAnalyzer, DustDataCache
from .scanner import (
    StashScanWorker, TabListWorker, UniqueItemInfo, 
    group_items_by_tab, items_to_highlights
)
from .tab_tracker import TabTracker, TabTrackerWorker, TabRegionConfig, MultiTabHighlighter
from ui.components.ocr_settings_dialog import OCRSettingsDialog


class KalguurDustWidget(QWidget):
    """Main widget for Kalguur Dust tool."""
    
    overlay_update = pyqtSignal(list)  # Emits highlight data
    overlay_debug_rect_update = pyqtSignal(int, int, int, int, str)  # x, y, w, h, color
    overlay_debug_text_update = pyqtSignal(str, int, int)  # text, x, y
    overlay_guidance_update = pyqtSignal(str, int, int)  # text, x, y
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.dust_config = config.get("kalguur_dust", {})
        
        # Data components
        self.dust_fetcher: DustDataFetcher = None
        self.price_fetcher: NinjaPriceFetcher = None
        self.dust_analyzer: DustEfficiencyAnalyzer = None
        
        # Scan results (all_scan_results is unfiltered, scan_results is filtered)
        self.all_scan_results: list[UniqueItemInfo] = []
        self.scan_results: list[UniqueItemInfo] = []
        self.scan_stats: dict = {}
        self.items_by_tab: dict = {}
        
        # Tab tracking
        self.tab_tracker: TabTracker = None
        self.tab_tracker_worker: TabTrackerWorker = None
        self.multi_tab_highlighter: MultiTabHighlighter = None
        
        # Debug mode
        # Debug mode - check global config first, fall back to tool-specific
        self.debug_mode = self.config.get("debug_mode", self.dust_config.get("debug_mode", False))
        
        self.setup_ui()
    
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
        
        # Credentials Section (reuse from parent config)
        creds_group = QGroupBox("API Credentials")
        creds_layout = QVBoxLayout(creds_group)
        
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
        
        layout.addWidget(creds_group)
        
        # Fetch Tabs Button
        self.fetch_tabs_btn = QPushButton("1. Fetch Tab List")
        self.fetch_tabs_btn.clicked.connect(self.fetch_tab_list)
        layout.addWidget(self.fetch_tabs_btn)
        
        # Tab Selector
        layout.addWidget(QLabel("Select Tabs to Scan:"))
        self.tab_selector = StashTabSelector()
        layout.addWidget(self.tab_selector)
        
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
        
        layout.addLayout(settings_row)
        
        # Scan Button
        self.scan_btn = QPushButton("2. Scan for Valuable Uniques")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setEnabled(False)
        layout.addWidget(self.scan_btn)
        
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
    
    
    def fetch_tab_list(self):
        """Fetch list of stash tabs."""
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
    
    def on_tabs_fetched(self, tabs: list):
        """Handle fetched tab list."""
        self.log(f"Fetched {len(tabs)} tabs.")
        self.tab_selector.load_tabs(tabs)
        self.scan_btn.setEnabled(True)
    
    def start_scan(self):
        """Start scanning selected tabs for valuable uniques."""
        selected_indices = self.tab_selector.get_selected_indices()
        if not selected_indices:
            self.log("No tabs selected!")
            return
        
        session_id = self.sess_id_input.text().strip()
        account = self.account_input.text().strip()
        league = self.league_input.text().strip()
        
        self.scan_btn.setEnabled(False)
        self.log("Initializing dust data...")
        
        # Initialize data fetchers
        if not self.dust_fetcher:
            self.dust_fetcher = DustDataFetcher(league)
            success = self.dust_fetcher.fetch_dust_data()
            dust_count = len(self.dust_fetcher.dust_values)
            self.log(f"Dust data: {dust_count} items loaded", debug_only=True)
            if dust_count < 50:
                self.log("WARNING: Low dust data - many items will show 0 dust!")
                if self.debug_mode:
                    # Show which items we have data for
                    items_list = list(self.dust_fetcher.dust_values.keys())[:10]
                    self.log(f"  Known items: {', '.join(items_list)}...", debug_only=True)
        
        if not self.price_fetcher:
            self.price_fetcher = NinjaPriceFetcher(league)
            self.price_fetcher.fetch_all_prices()
            self.log(f"Price data: {len(self.price_fetcher.prices)} items loaded", debug_only=True)
        
        self.dust_analyzer = DustEfficiencyAnalyzer(
            self.dust_fetcher, self.price_fetcher
        )
        
        min_efficiency = self.efficiency_slider.value() * 100  # Slider is scaled x100
        
        self.log(f"Scanning {len(selected_indices)} tabs (min efficiency: {min_efficiency:,})...")
        
        # Scanner returns ALL items (min_efficiency=0), filtering happens in UI for real-time updates
        
        self.scan_worker = StashScanWorker(
            session_id, account, league,
            selected_indices, self.dust_analyzer,
            0,  # Return ALL items, filtering done in UI for real-time slider
            self.debug_mode
        )
        self.scan_worker.log_signal.connect(self.log)
        self.scan_worker.debug_signal.connect(lambda msg: self.log(msg, debug_only=True))
        self.scan_worker.progress_signal.connect(self.on_scan_progress)
        self.scan_worker.result_signal.connect(self.on_scan_complete)
        self.scan_worker.finished.connect(lambda: self.scan_btn.setEnabled(True))
        self.scan_worker.start()
    
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
            if item.dust > 0 and item.efficiency >= min_efficiency
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
            self.results_table.setItem(row, 4, QTableWidgetItem(f"{item.chaos_price:.1f}"))
            self.results_table.setItem(row, 5, QTableWidgetItem(f"{item.efficiency:.2f}"))
            
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

    def start_highlighting(self):
        """Start the multi-tab highlighting workflow."""
        if not self.scan_results:
            return
        
        # Get calibration settings
        calibration = self.config.get("calibration", {})
        tab_bar_calibration = calibration.get("tab_bar")
        
        tesseract_path = self.config.get("league_vision", {}).get(
            "tesseract_path", "C:/Program Files/Tesseract-OCR/tesseract.exe"
        )
        
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
            self.tab_tracker_worker.stop()
            self.tab_tracker_worker.wait()
            self.tab_tracker_worker = None
        
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
    
    def get_credentials(self):
        """Return current credentials for saving."""
        return {
            "session_id": self.sess_id_input.text().strip(),
            "account_name": self.account_input.text().strip(),
            "league": self.league_input.text().strip()
        }
    
    def cleanup(self):
        """Cleanup resources."""
        self.stop_highlighting()
        self.clear_overlay()


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
    
    def __init__(self, config: dict):
        self.config = config
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = KalguurDustWidget(self.config, parent)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        if self.widget:
            self.widget.stop_highlighting()
    
    def cleanup(self):
        if self.widget:
            self.widget.cleanup()

