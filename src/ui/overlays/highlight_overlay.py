from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtCore import QRect, Qt
from .base_overlay import BaseOverlay

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

