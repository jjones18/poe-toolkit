"""
Main application window with sidebar navigation.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.overlay import OverlayWindow
from ui.theme import apply_dark_theme
from utils.config import ConfigManager
from utils.coordinate_mapper import StashGridMapper


class SidebarButton(QPushButton):
    """Custom button for sidebar navigation."""
    
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setMinimumHeight(50)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 12px;
                text-align: left;
                font-size: 13px;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QPushButton:checked {
                background-color: #4a4a4a;
                color: #ffffff;
                font-weight: bold;
            }
        """)


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POE Toolkit")
        self.setMinimumSize(900, 700)
        
        # Load config
        self.config = ConfigManager.load()
        
        # Restore window geometry
        win_config = self.config.get("window", {})
        self.setGeometry(
            win_config.get("x", 100),
            win_config.get("y", 100),
            win_config.get("width", 1100),
            win_config.get("height", 800)
        )
        
        # Create overlay
        self.overlay = OverlayWindow()
        
        # Create mapper for overlay
        overlay_config = self.config.get("overlay", {})
        self.mapper = StashGridMapper(
            offset_x=overlay_config.get("x_offset", 18),
            offset_y=overlay_config.get("y_offset", 160),
            cell_size=overlay_config.get("cell_size", 53)
        )
        
        # Apply dark theme
        apply_dark_theme(self.parent() if self.parent() else self)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main layout: sidebar + content
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar
        sidebar = self.create_sidebar()
        main_layout.addWidget(sidebar)
        
        # Content area
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background-color: #1e1e1e;")
        main_layout.addWidget(self.content_stack, 1)
        
        # Load tools
        self.tools = []
        self.load_tools()
        
        # Select first tool by default
        if self.sidebar_buttons:
            self.sidebar_buttons[0].setChecked(True)
            self.on_tool_selected(0)
    
    def create_sidebar(self) -> QWidget:
        """Create the sidebar navigation panel."""
        sidebar = QFrame()
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border-right: 1px solid #3d3d3d;
            }
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)
        
        # Logo/Title
        title = QLabel("POE Toolkit")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0e0; padding: 8px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3d3d3d;")
        layout.addWidget(sep)
        layout.addSpacing(12)
        
        # Tool buttons (will be populated by load_tools)
        self.sidebar_buttons = []
        self.tool_button_container = QVBoxLayout()
        layout.addLayout(self.tool_button_container)
        
        # Spacer
        layout.addStretch()
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #3d3d3d;")
        layout.addWidget(sep2)
        layout.addSpacing(8)
        
        # Overlay controls
        overlay_btn = SidebarButton("Show Overlay")
        overlay_btn.clicked.connect(self.toggle_overlay)
        layout.addWidget(overlay_btn)
        
        calibrate_btn = SidebarButton("Calibrate")
        calibrate_btn.clicked.connect(self.start_calibration)
        layout.addWidget(calibrate_btn)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666666; font-size: 10px; padding: 8px;")
        layout.addWidget(self.status_label)
        
        return sidebar
    
    def load_tools(self):
        """Load and initialize tool modules."""
        from tools.ultimatum import UltimatumTool
        from tools.league_vision import LeagueVisionTool
        from tools.trade_sniper import TradeSniperTool
        
        # Create tool instances
        tool_classes = [
            (UltimatumTool, {"config": self.config}),
            (LeagueVisionTool, {"config": self.config, "overlay": self.overlay}),
            (TradeSniperTool, {"config": self.config}),
        ]
        
        for tool_class, kwargs in tool_classes:
            try:
                tool = tool_class(**kwargs)
                self.tools.append(tool)
                
                # Create sidebar button
                btn = SidebarButton(tool.name)
                btn.setToolTip(tool.description)
                idx = len(self.sidebar_buttons)
                btn.clicked.connect(lambda checked, i=idx: self.on_tool_selected(i))
                self.tool_button_container.addWidget(btn)
                self.sidebar_buttons.append(btn)
                
                # Create widget and add to stack
                widget = tool.create_widget()
                self.content_stack.addWidget(widget)
                
                # Connect Ultimatum overlay updates
                if hasattr(widget, 'overlay_update'):
                    widget.overlay_update.connect(self.on_overlay_update)
                
            except Exception as e:
                print(f"Error loading tool {tool_class.__name__}: {e}")
    
    def on_tool_selected(self, index: int):
        """Handle tool selection from sidebar."""
        # Update button states
        for i, btn in enumerate(self.sidebar_buttons):
            btn.setChecked(i == index)
        
        # Deactivate previous tool
        current_idx = self.content_stack.currentIndex()
        if 0 <= current_idx < len(self.tools):
            self.tools[current_idx].on_deactivated()
        
        # Switch content
        self.content_stack.setCurrentIndex(index)
        
        # Activate new tool
        if 0 <= index < len(self.tools):
            self.tools[index].on_activated()
    
    def on_overlay_update(self, highlights: list):
        """Handle overlay updates from tools."""
        if highlights:
            calibrated_is_quad = self.config.get("overlay", {}).get("is_quad_calibrated", False)
            self.overlay.set_highlights_from_items(
                highlights, 
                self.mapper, 
                self.mapper.cell_size,
                calibrated_is_quad
            )
            self.overlay.show()
        else:
            self.overlay.set_highlights([])
            self.overlay.hide()
    
    def toggle_overlay(self):
        """Toggle overlay visibility."""
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()
    
    def start_calibration(self):
        """Start overlay calibration."""
        self.calibration_step = 1
        self.calibration_p1 = None
        self.overlay.set_calibration_mode(True, "Click TOP-LEFT corner of stash grid")
        self.overlay.calibration_clicked.connect(self.on_calibration_click)
        self.status_label.setText("Calibrating...")
    
    def on_calibration_click(self, x: int, y: int):
        """Handle calibration clicks."""
        if self.calibration_step == 1:
            self.calibration_p1 = (x, y)
            self.calibration_step = 2
            self.overlay.set_calibration_mode(True, "Click BOTTOM-RIGHT corner of stash grid")
        elif self.calibration_step == 2:
            self.overlay.set_calibration_mode(False)
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)
            
            # Calculate calibration
            p2 = (x, y)
            ox, oy, cell = self.mapper.calculate_from_points(self.calibration_p1, p2, False)
            
            # Save to config
            self.config["overlay"]["x_offset"] = ox
            self.config["overlay"]["y_offset"] = oy
            self.config["overlay"]["cell_size"] = cell
            
            self.status_label.setText(f"Calibrated: ({ox}, {oy}), cell={cell}")
            self.calibration_step = 0
            
            QMessageBox.information(
                self, 
                "Calibration Complete",
                f"Offset: ({ox}, {oy})\nCell Size: {cell}"
            )
    
    def save_config(self):
        """Save current configuration."""
        # Update window position
        self.config["window"] = {
            "x": self.x(),
            "y": self.y(),
            "width": self.width(),
            "height": self.height()
        }
        
        # Save credentials from Ultimatum tool if available
        if self.tools and hasattr(self.tools[0], 'widget') and self.tools[0].widget:
            widget = self.tools[0].widget
            if hasattr(widget, 'get_credentials'):
                self.config["credentials"] = widget.get_credentials()
        
        ConfigManager.save(self.config)
    
    def closeEvent(self, event):
        """Handle application close."""
        # Cleanup tools
        for tool in self.tools:
            try:
                tool.cleanup()
            except Exception as e:
                print(f"Error cleaning up tool: {e}")
        
        # Close overlay
        self.overlay.close()
        
        # Save config
        self.save_config()
        
        super().closeEvent(event)
