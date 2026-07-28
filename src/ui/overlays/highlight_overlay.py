from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtCore import QRect, Qt, QPoint, QTimer
from .base_overlay import BaseOverlay

try:
    import win32api
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from pynput import mouse as pynput_mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


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
        
        self._pynput_listener = None

        if HAS_WIN32:
            # Windows: poll mouse state via timer
            self._last_mouse_state = False
            self._click_poll_timer = QTimer()
            self._click_poll_timer.timeout.connect(self._poll_mouse_clicks)
            self._click_poll_timer.start(50)
        elif HAS_PYNPUT:
            # Linux: use pynput listener for click detection
            self._pynput_listener = pynput_mouse.Listener(on_click=self._on_pynput_click)
            self._pynput_listener.start()

    def _on_pynput_click(self, x, y, button, pressed):
        """Handle mouse clicks via pynput (Linux)."""
        if not pressed or button != pynput_mouse.Button.left:
            return
        if not self.highlights or not self.isVisible():
            return
        click_pos = QPoint(x, y)
        for i, rect in enumerate(self.highlights):
            if rect.contains(click_pos):
                self.highlight_states[i] = True
                self.update()
                break

    def _poll_mouse_clicks(self):
        """Poll for mouse clicks to mark items as collected (Windows only)."""
        if not HAS_WIN32 or not self.highlights or not self.isVisible():
            return
        
        # Check left mouse button state (0x8000 means pressed)
        mouse_down = win32api.GetAsyncKeyState(0x01) & 0x8000
        
        # Detect click (transition from not-pressed to pressed)
        if mouse_down and not self._last_mouse_state:
            cursor_pos = win32gui.GetCursorPos()
            click_pos = QPoint(cursor_pos[0], cursor_pos[1])
            
            for i, rect in enumerate(self.highlights):
                if rect.contains(click_pos):
                    self.highlight_states[i] = True
                    self.update()
                    break
        
        self._last_mouse_state = bool(mouse_down)

    def closeEvent(self, event):
        if self._pynput_listener is not None:
            self._pynput_listener.stop()
        super().closeEvent(event)


    def set_highlights(self, rects: list):
        """Set the list of highlight rectangles."""
        self.highlights = [QRect(*r) if isinstance(r, tuple) else r for r in rects]
        self.highlight_states = [False] * len(self.highlights)
        self.update()

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

