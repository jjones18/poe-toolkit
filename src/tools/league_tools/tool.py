"""
League Tools - Container tool with sub-tabs for different league mechanics.

Each league mechanic (Ultimatum, etc.) gets its own tab within this container.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTabBar
)
from PyQt6.QtCore import pyqtSignal

from tools.base_tool import BaseTool
from .ultimatum.tool import UltimatumWidget
from .kalguur_dust.tool import KalguurDustWidget


class LeagueToolsWidget(QWidget):
    """Container widget with tabs for each league tool."""
    
    overlay_update = pyqtSignal(list)
    overlay_debug_rect_update = pyqtSignal(int, int, int, int, str)
    overlay_debug_text_update = pyqtSignal(str, int, int)
    overlay_guidance_update = pyqtSignal(str, int, int)
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.league_widgets = []
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Tab widget for different league tools
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #888888;
                padding: 10px 20px;
                margin-right: 2px;
                border: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d3d;
                color: #cccccc;
            }
        """)
        
        layout.addWidget(self.tab_widget)
        
        # Add Ultimatum tab
        self.add_ultimatum_tab()
        
        # Add Kalguur Dust tab
        self.add_kalguur_dust_tab()
    
    def add_ultimatum_tab(self):
        """Add the Ultimatum helper as a tab."""
        ultimatum_widget = UltimatumWidget(self.config)
        ultimatum_widget.overlay_update.connect(self.overlay_update.emit)
        self.league_widgets.append(ultimatum_widget)
        self.tab_widget.addTab(ultimatum_widget, "Ultimatum")
    
    def add_kalguur_dust_tab(self):
        """Add the Kalguur Dust helper as a tab."""
        dust_widget = KalguurDustWidget(self.config)
        dust_widget.overlay_update.connect(self.overlay_update.emit)
        
        # Connect debug signals
        if hasattr(dust_widget, 'overlay_debug_rect_update'):
            dust_widget.overlay_debug_rect_update.connect(self.overlay_debug_rect_update.emit)
        if hasattr(dust_widget, 'overlay_debug_text_update'):
            dust_widget.overlay_debug_text_update.connect(self.overlay_debug_text_update.emit)
        if hasattr(dust_widget, 'overlay_guidance_update'):
            dust_widget.overlay_guidance_update.connect(self.overlay_guidance_update.emit)
            
        self.league_widgets.append(dust_widget)
        self.tab_widget.addTab(dust_widget, "Kalguur Dust")
    
    def set_debug_mode(self, enabled: bool):
        """Propagate debug mode to children."""
        for widget in self.league_widgets:
            if hasattr(widget, 'set_debug_mode'):
                widget.set_debug_mode(enabled)
    
    def add_league_tab(self, name: str, widget: QWidget):
        """Add a new league tool tab.
        
        Args:
            name: Display name for the tab
            widget: The widget to show for this league
        """
        if hasattr(widget, 'overlay_update'):
            widget.overlay_update.connect(self.overlay_update.emit)
        self.league_widgets.append(widget)
        self.tab_widget.addTab(widget, name)
    
    def get_credentials(self):
        """Return credentials from the active tab if available."""
        current_widget = self.tab_widget.currentWidget()
        if hasattr(current_widget, 'get_credentials'):
            return current_widget.get_credentials()
        
        # Fallback: check all widgets
        for widget in self.league_widgets:
            if hasattr(widget, 'get_credentials'):
                return widget.get_credentials()
        
        return {}
    
    def cleanup(self):
        """Clean up all league widgets."""
        for widget in self.league_widgets:
            if hasattr(widget, 'cleanup'):
                widget.cleanup()
            elif hasattr(widget, 'clear_overlay'):
                widget.clear_overlay()


class LeagueToolsTool(BaseTool):
    """League Tools - Container for league-specific helpers."""
    
    @property
    def name(self) -> str:
        return "League Tools"
    
    @property
    def icon(self) -> str:
        return "league"
    
    @property
    def description(self) -> str:
        return "Tools for various league mechanics (Ultimatum, Kalguur Dust, etc.)"
    
    def __init__(self, config: dict):
        self.config = config
        self.widget = None
    
    def create_widget(self, parent=None) -> QWidget:
        self.widget = LeagueToolsWidget(self.config, parent)
        return self.widget
    
    def on_activated(self):
        pass
    
    def on_deactivated(self):
        pass
    
    def cleanup(self):
        if self.widget:
            self.widget.cleanup()

