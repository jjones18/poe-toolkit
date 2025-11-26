"""
Trade Sniper Tool - Control panel for trade automation service.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt

from tools.base_tool import BaseTool
from services.trade_service import TradeService


class TradeSniperWidget(QWidget):
    """Main widget for Trade Sniper tool."""
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.trade_config = config.get("trade_sniper", {})
        
        self.service = TradeService()
        self.service.status_changed.connect(self.on_status_changed)
        self.service.log_output.connect(self.log)
        
        self.setup_ui()
        self.check_setup()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Trade Sniper")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        subtitle = QLabel("Automated live search monitoring")
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
        
        req_layout.addWidget(QLabel("1. Run start_brave_debugging.bat first"))
        req_layout.addWidget(QLabel("2. Login to pathofexile.com/trade in Brave"))
        req_layout.addWidget(QLabel("3. Open live search tab(s)"))
        req_layout.addWidget(QLabel("4. Start Path of Exile game"))
        
        layout.addWidget(req_group)
        
        # Configuration
        config_group = QGroupBox("Configuration")
        config_layout = QVBoxLayout(config_group)
        
        # Auto-resume
        self.chk_auto_resume = QCheckBox("Auto-resume after 60 seconds")
        self.chk_auto_resume.setChecked(self.trade_config.get("auto_resume", False))
        config_layout.addWidget(self.chk_auto_resume)
        
        # Cooldown
        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(QLabel("Click cooldown (ms):"))
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(1000, 30000)
        self.cooldown_spin.setSingleStep(1000)
        self.cooldown_spin.setValue(self.trade_config.get("cooldown_ms", 5000))
        cooldown_row.addWidget(self.cooldown_spin)
        cooldown_row.addStretch()
        config_layout.addLayout(cooldown_row)
        
        layout.addWidget(config_group)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Service")
        self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
        self.start_btn.clicked.connect(self.start_service)
        controls_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop Service")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("padding: 10px;")
        self.stop_btn.clicked.connect(self.stop_service)
        controls_layout.addWidget(self.stop_btn)
        
        self.resume_btn = QPushButton("Resume (Enter)")
        self.resume_btn.setEnabled(False)
        self.resume_btn.setStyleSheet("padding: 10px;")
        self.resume_btn.clicked.connect(self.resume_service)
        controls_layout.addWidget(self.resume_btn)
        
        layout.addLayout(controls_layout)
        
        # Log Area
        layout.addWidget(QLabel("Service Output:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)
    
    def check_setup(self):
        """Check if Node.js is available."""
        node_ver, npm_ver = self.service.check_dependencies()
        
        if node_ver:
            self.node_status.setText(f"Node.js: {node_ver} (OK)")
            self.node_status.setStyleSheet("color: #66ff66;")
        else:
            self.node_status.setText("Node.js: NOT FOUND - Please install Node.js")
            self.node_status.setStyleSheet("color: #ff6666;")
            self.start_btn.setEnabled(False)
    
    def log(self, message: str):
        self.log_area.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def start_service(self):
        """Start the trade service."""
        auto_resume = self.chk_auto_resume.isChecked()
        self.service.start(auto_resume=auto_resume)
    
    def stop_service(self):
        """Stop the trade service."""
        self.service.stop()
    
    def resume_service(self):
        """Resume the paused service."""
        self.service.resume()
    
    def on_status_changed(self, status: str):
        """Handle status changes."""
        if status == "running":
            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet("font-size: 14px; color: #66ff66;")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.resume_btn.setEnabled(True)
        elif status == "stopped":
            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
        else:
            self.status_label.setText(f"Status: {status}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ffaa66;")
    
    def cleanup(self):
        """Clean up resources."""
        if self.service.is_running:
            self.service.stop()


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
    
    def __init__(self, config: dict):
        self.config = config
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = TradeSniperWidget(self.config, parent)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            self.widget.cleanup()

