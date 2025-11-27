from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import Qt

class BaseOverlay(QMainWindow):
    """Base class for all overlay windows."""
    
    def __init__(self):
        super().__init__()
        
        # Standard overlay flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Default to fullscreen
        if self.screen():
            self.setGeometry(self.screen().geometry())
            
    def set_clickable(self, clickable: bool):
        """Toggle between click-through and clickable."""
        flags = self.windowFlags()
        if clickable:
            flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            flags |= Qt.WindowType.WindowTransparentForInput
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setWindowFlags(flags)
        self.show()

