"""
League Vision Tool - OCR-based screen scanning for league mechanics.
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QCheckBox, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt

from tools.base_tool import BaseTool
from tools.league_vision.scanner import ScannerWorker, ScanResult
from services.zone_monitor import ZoneMonitor


class LeagueVisionWidget(QWidget):
    """Main widget for League Vision tool."""
    
    def __init__(self, config: dict, overlay=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.vision_config = config.get("league_vision", {})
        self.overlay = overlay
        
        self.scanner = None
        self.zone_monitor = None
        
        self.setup_ui()
        self.setup_zone_monitor()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("League Vision")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("OCR-based screen scanning for league mechanics")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(subtitle)
        
        # Setup Group
        setup_group = QGroupBox("Setup")
        setup_layout = QVBoxLayout(setup_group)
        
        # Client Log Path
        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Client.txt Path:"))
        self.log_path_label = QLabel(self.vision_config.get("client_log_path", "Not Set"))
        self.log_path_label.setStyleSheet("color: #aaaaaa;")
        log_row.addWidget(self.log_path_label, 1)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_log_path)
        log_row.addWidget(browse_btn)
        setup_layout.addLayout(log_row)
        
        # Calibrate Button
        self.calibrate_btn = QPushButton("Calibrate Map Device Button")
        self.calibrate_btn.clicked.connect(self.calibrate_button)
        setup_layout.addWidget(self.calibrate_btn)
        
        layout.addWidget(setup_group)
        
        # Features Group
        features_group = QGroupBox("Features")
        features_layout = QVBoxLayout(features_group)
        
        # Feature checkboxes
        self.chk_map_safety = QCheckBox("Map Safety Check (blocks dangerous mods)")
        self.chk_map_safety.setChecked(self.vision_config.get("map_check", {}).get("enabled", True))
        features_layout.addWidget(self.chk_map_safety)
        
        self.chk_essence = QCheckBox("Essence Detection (Misery, Envy, Dread, Scorn)")
        self.chk_essence.setChecked(self.vision_config.get("essence", {}).get("enabled", True))
        features_layout.addWidget(self.chk_essence)
        
        self.chk_ritual = QCheckBox("Ritual Detection (Opulent, Apocalyptic, etc.)")
        self.chk_ritual.setChecked(self.vision_config.get("ritual", {}).get("enabled", True))
        features_layout.addWidget(self.chk_ritual)
        
        self.chk_altars = QCheckBox("Eldritch Altar Rewards")
        self.chk_altars.setChecked(self.vision_config.get("eldritch_altars", {}).get("enabled", True))
        features_layout.addWidget(self.chk_altars)
        
        self.chk_expedition = QCheckBox("Expedition Remnant Warnings")
        self.chk_expedition.setChecked(self.vision_config.get("expedition", {}).get("enabled", True))
        features_layout.addWidget(self.chk_expedition)
        
        layout.addWidget(features_group)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Scanner")
        self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold;")
        self.start_btn.clicked.connect(self.toggle_scanner)
        controls_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop Scanner")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scanner)
        controls_layout.addWidget(self.stop_btn)
        
        layout.addLayout(controls_layout)
        
        # Status
        self.zone_label = QLabel("Zone: Unknown")
        self.zone_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.zone_label)
        
        # Log Area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        layout.addWidget(self.log_area)
        
        layout.addStretch()
    
    def setup_zone_monitor(self):
        """Initialize zone monitoring."""
        log_path = self.vision_config.get("client_log_path", "")
        if log_path and os.path.exists(log_path):
            self.zone_monitor = ZoneMonitor(log_path)
            self.zone_monitor.zone_changed.connect(self.on_zone_changed)
            self.zone_monitor.start()
            self.log("Zone monitor started.")
    
    def on_zone_changed(self, zone: str):
        """Handle zone change."""
        self.zone_label.setText(f"Zone: {zone}")
        if self.scanner:
            self.scanner.set_zone(zone)
        self.log(f"Zone changed: {zone}")
    
    def log(self, message: str):
        self.log_area.append(message)
    
    def browse_log_path(self):
        """Browse for Client.txt file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Path of Exile Client.txt",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            self.vision_config["client_log_path"] = path
            self.log_path_label.setText(path)
            self.log(f"Client log path set: {path}")
            
            # Restart zone monitor
            if self.zone_monitor:
                self.zone_monitor.stop()
            self.zone_monitor = ZoneMonitor(path)
            self.zone_monitor.zone_changed.connect(self.on_zone_changed)
            self.zone_monitor.start()
    
    def calibrate_button(self):
        """Start calibration for map device button."""
        if not self.overlay:
            QMessageBox.warning(self, "Error", "Overlay not available.")
            return
        
        self.calibration_clicks = []
        self.overlay.set_calibration_mode(True, "Click TOP-LEFT of the 'Activate' button")
        self.overlay.calibration_clicked.connect(self.on_calibration_click)
        self.log("Calibration started. Click TOP-LEFT corner of Activate button.")
    
    def on_calibration_click(self, x: int, y: int):
        """Handle calibration click."""
        self.calibration_clicks.append((x, y))
        
        if len(self.calibration_clicks) == 1:
            self.overlay.set_calibration_mode(True, "Click BOTTOM-RIGHT of the 'Activate' button")
            self.log(f"Top-left: ({x}, {y}). Now click bottom-right.")
        elif len(self.calibration_clicks) == 2:
            self.overlay.set_calibration_mode(False)
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)
            
            x1, y1 = self.calibration_clicks[0]
            x2, y2 = self.calibration_clicks[1]
            
            rect = {
                "x": min(x1, x2),
                "y": min(y1, y2),
                "w": abs(x2 - x1),
                "h": abs(y2 - y1)
            }
            
            self.vision_config["map_device_button"] = rect
            self.log(f"Map device button calibrated: {rect}")
            QMessageBox.information(self, "Calibration Complete", 
                                  f"Button position saved!\nRect: {rect}")
    
    def get_scanner_config(self):
        """Build scanner config from current settings."""
        config = self.vision_config.copy()
        
        # Update enabled states from checkboxes
        if "map_check" not in config:
            config["map_check"] = {}
        config["map_check"]["enabled"] = self.chk_map_safety.isChecked()
        
        if "essence" not in config:
            config["essence"] = {"keywords": ["Misery", "Envy", "Dread", "Scorn"]}
        config["essence"]["enabled"] = self.chk_essence.isChecked()
        
        if "ritual" not in config:
            config["ritual"] = {"keywords": ["Opulent", "Apocalyptic", "Glacial", "Volatile"]}
        config["ritual"]["enabled"] = self.chk_ritual.isChecked()
        
        if "eldritch_altars" not in config:
            config["eldritch_altars"] = {}
        config["eldritch_altars"]["enabled"] = self.chk_altars.isChecked()
        
        if "expedition" not in config:
            config["expedition"] = {}
        config["expedition"]["enabled"] = self.chk_expedition.isChecked()
        
        return config
    
    def toggle_scanner(self):
        """Start the scanner."""
        if self.scanner and self.scanner.isRunning():
            return
        
        config = self.get_scanner_config()
        self.scanner = ScannerWorker(config)
        self.scanner.result_signal.connect(self.on_scan_result)
        self.scanner.status_signal.connect(self.log)
        
        if self.zone_monitor:
            self.scanner.set_zone(self.zone_monitor.get_current_zone())
        
        self.scanner.start()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log("Scanner started.")
    
    def stop_scanner(self):
        """Stop the scanner."""
        if self.scanner:
            self.scanner.stop()
            self.scanner.wait(2000)
            self.scanner = None
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log("Scanner stopped.")
    
    def on_scan_result(self, result: ScanResult):
        """Handle scan result."""
        self.log(f"[{result.color.upper()}] {result.message}")
        
        if self.overlay:
            self.overlay.show_alert(result.message, result.color)
            
            if result.is_blocking and result.blocker_rect:
                self.overlay.create_blocker(result.blocker_rect, "UNSAFE")
    
    def cleanup(self):
        """Clean up resources."""
        if self.scanner:
            self.scanner.stop()
            self.scanner.wait(2000)
        
        if self.zone_monitor:
            self.zone_monitor.stop()
        
        if self.overlay:
            self.overlay.clear_blockers()


class LeagueVisionTool(BaseTool):
    """League Vision Tool plugin."""
    
    @property
    def name(self) -> str:
        return "Vision"
    
    @property
    def icon(self) -> str:
        return "vision"
    
    @property
    def description(self) -> str:
        return "OCR-based screen scanning for league mechanics"
    
    def __init__(self, config: dict, overlay=None):
        self.config = config
        self.overlay = overlay
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = LeagueVisionWidget(self.config, self.overlay, parent)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            self.widget.cleanup()

