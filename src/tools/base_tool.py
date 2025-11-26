"""
Base class for POE Toolkit tool modules.

Each tool (Ultimatum, League Vision, Trade Sniper, etc.) should inherit from BaseTool
and implement the required interface methods.
"""

from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QIcon


class BaseTool(ABC):
    """Abstract base class for tool modules."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Display name for the tool (shown in sidebar)."""
        pass
    
    @property
    @abstractmethod
    def icon(self) -> str:
        """Icon identifier or path for the sidebar."""
        pass
    
    @property
    def description(self) -> str:
        """Brief description shown in tooltips."""
        return ""
    
    @abstractmethod
    def create_widget(self, parent: QWidget = None) -> QWidget:
        """
        Create and return the main widget for this tool.
        This widget will be displayed when the tool is selected in the sidebar.
        """
        pass
    
    def on_activated(self):
        """Called when this tool is selected/activated in the sidebar."""
        pass
    
    def on_deactivated(self):
        """Called when switching away from this tool."""
        pass
    
    def on_overlay_update(self, overlay):
        """
        Called to allow the tool to update the shared overlay.
        
        Args:
            overlay: The shared OverlayWindow instance
        """
        pass
    
    def cleanup(self):
        """Called when the application is closing. Clean up resources."""
        pass

