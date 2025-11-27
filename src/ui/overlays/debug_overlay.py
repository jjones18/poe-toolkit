from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import QRect, Qt
from .base_overlay import BaseOverlay

class DebugOverlay(BaseOverlay):
    """Overlay for debug visualization (OCR regions, text)."""
    
    def __init__(self):
        super().__init__()
        self.debug_rect = None
        self.debug_color = QColor(255, 255, 0, 200)
        self.debug_text = ""
        self.debug_text_pos = (0, 0)
        self.debug_boxes = []

    def set_rect(self, x, y, w, h, color_name="yellow"):
        self.debug_rect = QRect(x, y, w, h)
        if color_name == "cyan":
            self.debug_color = QColor(0, 255, 255, 200)
        else:
            self.debug_color = QColor(255, 255, 0, 200)
        self.show()
        self.update()

    def set_text(self, text, x, y):
        self.debug_text = text
        self.debug_text_pos = (x, y)
        if text:
            self.show()
        self.update()

    def clear(self):
        self.debug_rect = None
        self.debug_text = ""
        self.debug_boxes = []
        self.hide()

    def add_debug_box(self, x: int, y: int, w: int, h: int, color="red"):
        rect = QRect(x, y, w, h)
        if color == "red":
            qcolor = QColor(255, 0, 0, 200)
        elif color == "blue":
            qcolor = QColor(0, 100, 255, 200)
        elif color == "purple":
            qcolor = QColor(150, 0, 255, 200)
        elif color == "green":
            qcolor = QColor(0, 255, 0, 200)
        else:
            qcolor = QColor(255, 0, 0, 200)
        self.debug_boxes.append((rect, qcolor))
        self.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw debug scan region
        if self.debug_rect:
            pen = QPen(self.debug_color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.debug_rect)
            
        # Draw debug boxes
        for rect, color in self.debug_boxes:
            pen = QPen(color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        
        # Draw debug text
        if self.debug_text:
            painter.setPen(QColor(255, 255, 0))
            painter.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
            
            text_rect = painter.fontMetrics().boundingRect(self.debug_text)
            padding = 5
            bg_rect = QRect(
                self.debug_text_pos[0], 
                self.debug_text_pos[1],
                text_rect.width() + padding * 2,
                text_rect.height() + padding * 2
            )
            painter.fillRect(bg_rect, QColor(0, 0, 0, 180))
            painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, self.debug_text)

