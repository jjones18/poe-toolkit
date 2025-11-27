"""
Main application window with sidebar navigation.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFrame, QMessageBox,
    QMenuBar, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction

from ui.overlay_manager import OverlayManager
from ui.theme import apply_dark_theme
from ui.calibration import (
    CalibrationManager, CalibrationType, CALIBRATION_CONFIGS,
    get_calibration_status_text
)
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
        
        # Ensure window is visible on screen (prevent off-screen title bar)
        x = win_config.get("x", 100)
        y = max(30, win_config.get("y", 100))  # Force at least 30px from top
        
        self.setGeometry(
            x, y,
            win_config.get("width", 1100),
            win_config.get("height", 800)
        )
        
        # Create overlay
        self.overlay = OverlayManager()
        
        # Create mapper for overlay
        overlay_config = self.config.get("overlay", {})
        self.mapper = StashGridMapper(
            offset_x=overlay_config.get("x_offset", 18),
            offset_y=overlay_config.get("y_offset", 160),
            cell_size=overlay_config.get("cell_size", 53)
        )
        
        # Create calibration manager
        self.calibration_manager = CalibrationManager(
            self.config,
            save_callback=lambda: ConfigManager.save(self.config)
        )
        self.calibration_manager.on_complete = self.on_calibration_complete
        
        # Apply dark theme
        apply_dark_theme(self.parent() if self.parent() else self)
        
        # Create menu bar
        self.create_menu_bar()
        
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
        self.overlay_btn = SidebarButton("Show Overlay")
        self.overlay_btn.clicked.connect(self.toggle_overlay)
        layout.addWidget(self.overlay_btn)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666666; font-size: 10px; padding: 8px;")
        layout.addWidget(self.status_label)
        
        return sidebar
    
    def create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # Settings menu
        settings_menu = menubar.addMenu("Settings")
        
        # Calibration submenu
        calibration_menu = settings_menu.addMenu("Calibration")
        
        # Add action for each calibration type
        for cal_type in CalibrationType:
            config = CALIBRATION_CONFIGS[cal_type]
            action = QAction(f"{config.name}...", self)
            action.setStatusTip(config.description)
            # Use lambda with default arg to capture cal_type
            action.triggered.connect(
                lambda checked, ct=cal_type: self.start_calibration(ct)
            )
            calibration_menu.addAction(action)
        
        # Add separator and status action
        calibration_menu.addSeparator()
        status_action = QAction("Show Calibration Status", self)
        status_action.triggered.connect(self.show_calibration_status)
        calibration_menu.addAction(status_action)
        
        # Separator before debug mode
        settings_menu.addSeparator()
        
        # Global debug mode toggle
        self.debug_mode_action = QAction("Debug Mode", self)
        self.debug_mode_action.setCheckable(True)
        self.debug_mode_action.setChecked(self.config.get("debug_mode", False))
        self.debug_mode_action.setStatusTip("Enable verbose debug logging for all tools")
        self.debug_mode_action.triggered.connect(self.toggle_debug_mode)
        settings_menu.addAction(self.debug_mode_action)
    
    def toggle_debug_mode(self, checked: bool):
        """Toggle global debug mode."""
        self.config["debug_mode"] = checked
        self.status_label.setText(f"Debug Mode: {'ON' if checked else 'OFF'}")
        
        # Notify all tools of debug mode change
        for tool in self.tools:
            if hasattr(tool, 'set_debug_mode'):
                tool.set_debug_mode(checked)
            if hasattr(tool, 'widget') and tool.widget:
                if hasattr(tool.widget, 'set_debug_mode'):
                    tool.widget.set_debug_mode(checked)
    
    def is_debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return self.config.get("debug_mode", False)
    
    def load_tools(self):
        """Load and initialize tool modules."""
        from tools.league_tools import LeagueToolsTool
        from tools.league_vision import LeagueVisionTool
        from tools.trade_sniper import TradeSniperTool
        
        # Create tool instances
        tool_classes = [
            (LeagueToolsTool, {"config": self.config}),
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
                
                # Connect debug overlay updates
                if hasattr(widget, 'overlay_debug_text_update'):
                    widget.overlay_debug_text_update.connect(self.overlay.set_debug_text)
                if hasattr(widget, 'overlay_debug_rect_update'):
                    widget.overlay_debug_rect_update.connect(self.overlay.set_debug_rect)
                if hasattr(widget, 'overlay_guidance_update'):
                    widget.overlay_guidance_update.connect(self.overlay.set_guidance_text)
                
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
            self.overlay.clear_calibration_preview()  # Clear preview when showing real highlights
            self.overlay.set_highlights_from_items(
                highlights, 
                self.mapper, 
                self.mapper.cell_size,
                calibrated_is_quad
            )
            self.overlay.show()
            self.overlay_btn.setChecked(True)
        else:
            self.overlay.set_highlights([])
            self.overlay.clear_calibration_preview()
            self.overlay.hide()
            self.overlay_btn.setChecked(False)
    
    def toggle_overlay(self):
        """Toggle overlay visibility."""
        if self.overlay.isVisible():
            self.overlay.hide()
            self.overlay.clear_calibration_preview()
            self.overlay_btn.setChecked(False)
        else:
            # Show calibration preview corners when no highlights are active
            overlay_config = self.config.get("overlay", {})
            is_quad = overlay_config.get("is_quad_calibrated", False)
            self.overlay.set_calibration_preview(
                self.mapper.offset_x,
                self.mapper.offset_y,
                self.mapper.cell_size,
                is_quad
            )
            self.overlay.show()
            self.overlay_btn.setChecked(True)
    
    def start_calibration(self, cal_type: CalibrationType = CalibrationType.STASH_GRID):
        """Start calibration for a specific region type."""
        # Start calibration and get first instruction
        msg = self.calibration_manager.start_calibration(cal_type)
        
        # Enable calibration mode in overlay
        self.overlay.set_calibration_mode(True, msg)
        self.overlay.calibration_clicked.connect(self.on_calibration_click)
        
        config = CALIBRATION_CONFIGS[cal_type]
        self.status_label.setText(f"Calibrating: {config.name}")
    
    def on_calibration_click(self, x: int, y: int):
        """Handle calibration clicks using CalibrationManager."""
        next_msg = self.calibration_manager.handle_click(x, y)
        
        if next_msg:
            # More steps needed
            self.overlay.set_calibration_mode(True, next_msg)
        else:
            # Calibration step 2 completed - now SHOW PREVIEW
            # The calibration manager logic was modified to wait for confirmation
            # But on_calibration_complete is called from inside the manager.
            # We need to show preview BEFORE the confirmation dialog.
            
            # Since on_calibration_complete is called with the result:
            pass

    def on_calibration_complete(self, cal_type: CalibrationType, result: dict):
        """Handle calibration completion."""
        config = CALIBRATION_CONFIGS[cal_type]
        
        # Show preview on overlay
        if cal_type == CalibrationType.STASH_GRID:
            is_quad = result.get('is_quad_calibrated', False)
            self.overlay.set_calibration_preview(
                result.get('x_offset', result.get('x', 0)),
                result.get('y_offset', result.get('y', 0)),
                result.get('cell_size', 52),
                is_quad
            )
        else:
            # For other regions, show a simple rect preview
            self.overlay.set_calibration_region_preview(
                result['x'], result['y'], result['width'], result['height']
            )
        
        self.overlay.set_calibration_mode(False)
        
        # Update mapper if this was stash grid calibration (so the preview works if we use set_calibration_preview)
        if cal_type == CalibrationType.STASH_GRID:
            self.mapper.offset_x = result.get('x_offset', result.get('x', 0))
            self.mapper.offset_y = result.get('y_offset', result.get('y', 0))
            self.mapper.cell_size = result.get('cell_size', 52)
            
            tab_type = "QUAD" if result.get('is_quad_calibrated', False) else "STANDARD"
            status_msg = (f"Offset: ({self.mapper.offset_x}, {self.mapper.offset_y})\n"
                          f"Cell Size: {self.mapper.cell_size}\n"
                          f"Tab Type: {tab_type}")
        else:
            status_msg = (f"Region: ({result['x']}, {result['y']}) - "
                          f"({result['x2']}, {result['y2']})\n"
                          f"Size: {result['width']} x {result['height']}")

        # Show blocking dialog
        reply = QMessageBox.question(
            self,
            "Confirm Calibration",
            f"{config.name} calibrated!\n\n{status_msg}\n\n"
            "Is the highlighted region correct?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        # Clear preview
        self.overlay.clear_calibration_preview()
        
        if reply == QMessageBox.StandardButton.Yes:
            # Confirm and save
            self.calibration_manager.confirm_calibration(result)
            self.status_label.setText(f"Calibrated: {config.name}")
        else:
            # Cancel
            self.calibration_manager.cancel()
            self.status_label.setText("Calibration cancelled")
            
        try:
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)
        except TypeError:
            pass
    
    def show_calibration_status(self):
        """Show current calibration status for all regions."""
        status = get_calibration_status_text(self.calibration_manager)
        QMessageBox.information(
            self,
            "Calibration Status",
            f"Current calibration status:\n\n{status}"
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
