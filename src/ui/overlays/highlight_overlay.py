from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtCore import QRect, Qt, QPoint, QTimer
from .base_overlay import BaseOverlay

try:
    import win32api
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class HighlightOverlay(BaseOverlay):
    """Overlay for highlighting stash items."""
    
    def __init__(self):
        super().__init__()
        self.highlights = []
        self.highlight_states = []
        
        # Colors
        self.pen_green = QPen(QColor(0, 255, 0, 200))
        self.pen_green.setWidth(3)
        self.brush_green = QColor(0, 255, 0, 50)
        
        self.pen_gray = QPen(QColor(150, 150, 150, 200))
        self.pen_gray.setWidth(3)
        self.brush_gray = QColor(150, 150, 150, 50)
        
        # Keep overlay click-through (don't call set_clickable)
        # Use a timer to poll for clicks instead of intercepting them
        self._last_mouse_state = False
        self._click_poll_timer = QTimer()
        self._click_poll_timer.timeout.connect(self._poll_mouse_clicks)
        self._click_poll_timer.start(50)  # Poll every 50ms

    def _poll_mouse_clicks(self):
        """Poll for mouse clicks to mark items as collected without blocking."""
        if not HAS_WIN32 or not self.highlights or not self.isVisible():
            return
        
        # Check left mouse button state (0x8000 means pressed)
        mouse_down = win32api.GetAsyncKeyState(0x01) & 0x8000
        
        # Detect click (transition from not-pressed to pressed)
        if mouse_down and not self._last_mouse_state:
            # Get cursor position
            cursor_pos = win32gui.GetCursorPos()
            click_pos = QPoint(cursor_pos[0], cursor_pos[1])
            
            # Check if click is within any highlight rect
            for i, rect in enumerate(self.highlights):
                if rect.contains(click_pos):
                    # Mark as collected (gray)
                    self.highlight_states[i] = True
                    self.update()
                    break
        
        self._last_mouse_state = bool(mouse_down)

    def set_highlights(self, rects: list):
        """Set the list of highlight rectangles."""
        self.highlights = [QRect(*r) if isinstance(r, tuple) else r for r in rects]
        self.highlight_states = [False] * len(self.highlights)
        self.update()
        
        if self.highlights:
            self.show()
        else:
            self.hide()

    def paintEvent(self, event):
        if not self.highlights:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if len(self.highlight_states) != len(self.highlights):
            self.highlight_states = [False] * len(self.highlights)

        for i, rect in enumerate(self.highlights):
            if self.highlight_states[i]:
                painter.setPen(self.pen_gray)
                painter.setBrush(self.brush_gray)
            else:
                painter.setPen(self.pen_green)
                painter.setBrush(self.brush_green)
            painter.drawRect(rect)

