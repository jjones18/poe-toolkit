"""
Trade Sniper Tool - Control panel for trade automation service.
"""

import os
import socket
import subprocess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QCheckBox, QSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

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
        self.check_brave_status()
        
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
        """Check if Node.js is available."""
        node_ver, npm_ver = self.service.check_dependencies()
        
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
    
    def update_start_button_state(self):
        """Enable Start button only when all requirements are met."""
        all_ok = getattr(self, 'node_ok', False) and getattr(self, 'deps_ok', False)
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
        """Install npm dependencies."""
        self.install_deps_btn.setEnabled(False)
        self.install_deps_btn.setText("Installing...")
        self.deps_status.setText("Dependencies: Installing...")
        self.deps_status.setStyleSheet("color: #ffaa66;")
        self.log("Installing npm dependencies...")
        self.log(f"Working directory: {self.service.service_dir}")
        
        # Run npm install using shell=True to access PATH
        try:
            result = subprocess.run(
                "npm install",
                cwd=self.service.service_dir,
                capture_output=True,
                text=True,
                timeout=120,
                shell=True  # Use shell to access PATH
            )
            
            if result.returncode == 0:
                self.log("Dependencies installed successfully!")
                if result.stdout:
                    self.log(result.stdout)
                self.check_npm_dependencies()
            else:
                self.log(f"npm install failed:")
                if result.stderr:
                    self.log(result.stderr)
                if result.stdout:
                    self.log(result.stdout)
                self.deps_status.setText("Dependencies: INSTALL FAILED")
                self.deps_status.setStyleSheet("color: #ff6666;")
        except subprocess.TimeoutExpired:
            self.log("npm install timed out after 120 seconds")
            self.deps_status.setText("Dependencies: INSTALL TIMEOUT")
            self.deps_status.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.log(f"Error installing dependencies: {e}")
            self.deps_status.setText("Dependencies: ERROR")
            self.deps_status.setStyleSheet("color: #ff6666;")
        
        self.install_deps_btn.setEnabled(True)
        self.install_deps_btn.setText("Install")
    
    def check_brave_status(self):
        """Check if Brave is running with remote debugging on port 9222."""
        if self.is_brave_debug_running():
            self.brave_status.setText("Brave: Connected (Debug Mode)")
            self.brave_status.setStyleSheet("color: #66ff66;")
            self.launch_brave_btn.setText("Brave Already Running")
            self.launch_brave_btn.setEnabled(False)
        else:
            self.brave_status.setText("Brave: Not Running")
            self.brave_status.setStyleSheet("color: #ff6666;")
            self.launch_brave_btn.setText("1. Launch Brave (Debug Mode)")
            self.launch_brave_btn.setEnabled(True)
            self.launch_brave_btn.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 8px;")
    
    def is_brave_debug_running(self) -> bool:
        """Check if something is listening on port 9222 (Brave debug port)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', 9222))
            sock.close()
            return result == 0
        except:
            return False
    
    def launch_brave(self):
        """Launch Brave browser with remote debugging enabled."""
        # Common Brave paths
        brave_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
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
        
        # Create profile directory in trade_service folder
        profile_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
                                    "..", "trade_service", "brave-profile")
        profile_dir = os.path.abspath(profile_dir)
        os.makedirs(profile_dir, exist_ok=True)
        
        try:
            # Launch Brave with remote debugging and open trade site
            cmd = [
                brave_exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={profile_dir}",
                "https://www.pathofexile.com/trade"
            ]
            
            # Use subprocess.Popen to launch without blocking
            subprocess.Popen(cmd, shell=False)
            
            self.brave_status.setText("Brave: Launched (Debug Mode)")
            self.brave_status.setStyleSheet("color: #66ff66;")
            self.log("Brave launched with remote debugging on port 9222")
            self.log("Opening pathofexile.com/trade...")
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
        self.log_area.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_start_resume_click(self):
        """Handle start/resume button click based on current state."""
        if self.is_service_running:
            # Service is running, send resume signal
            self.service.resume()
        else:
            # Service not running, start it
            auto_resume = self.chk_auto_resume.isChecked()
            self.service.start(auto_resume=auto_resume)
    
    def stop_service(self):
        """Stop the trade service."""
        self.service.stop()
    
    def on_status_changed(self, status: str):
        """Handle status changes."""
        if status == "running":
            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet("font-size: 14px; color: #66ff66;")
            self.is_service_running = True
            # Swap to Resume button
            self.start_btn.setText("Resume (Enter)")
            self.start_btn.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 10px;")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        elif status == "stopped":
            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet("font-size: 14px; color: #ff6666;")
            self.is_service_running = False
            # Swap back to Start button
            self.start_btn.setText("Start Service")
            self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
            self.update_start_button_state()  # Re-check if deps are OK
            self.stop_btn.setEnabled(False)
        else:
            self.status_label.setText(f"Status: {status}")
            self.status_label.setStyleSheet("font-size: 14px; color: #ffaa66;")
    
    def cleanup(self):
        """Clean up resources."""
        if hasattr(self, 'brave_check_timer'):
            self.brave_check_timer.stop()
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

