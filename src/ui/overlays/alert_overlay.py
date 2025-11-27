from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import QRect, Qt, QTimer
from .base_overlay import BaseOverlay

class AlertOverlay(BaseOverlay):
    """Overlay for showing temporary alerts."""
    
    def __init__(self):
        super().__init__()
        self.message = ""
        self.color = QColor(255, 0, 0)
        self.guidance_text = ""
        self.guidance_x = -1
        self.guidance_y = -1
        
    def show_alert(self, message: str, color: str = "red", duration_ms: int = 2000):
        self.message = message
        if color == "red":
            self.color = QColor(255, 0, 0)
        elif color == "green":
            self.color = QColor(0, 255, 0)
        else:
            self.color = QColor(color)
            
        self.show()
        self.update()
        QTimer.singleShot(duration_ms, self._clear_alert)

    def set_guidance(self, text: str, x: int = -1, y: int = -1):
        """Set persistent guidance text. If x/y > 0, text is anchored there."""
        self.guidance_text = text
        self.guidance_x = x
        self.guidance_y = y
        if text:
            self.show()
        elif not self.message:
            self.hide()
        self.update()

    def _clear_alert(self):
        self.message = ""
        self.update()
        if not self.guidance_text:
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw alert (centered)
        if self.message:
            font = QFont("Arial", 32, QFont.Weight.Bold)
            painter.setFont(font)
            
            text_rect = painter.fontMetrics().boundingRect(self.message)
            padding = 20
            
            box_x = (self.width() - text_rect.width()) // 2 - padding
            box_y = self.height() // 4 - padding
            box_w = text_rect.width() + padding * 2
            box_h = text_rect.height() + padding * 2
            
            painter.fillRect(box_x, box_y, box_w, box_h, QColor(32, 32, 32, 220))
            painter.setPen(self.color)
            painter.drawText(
                QRect(box_x, box_y, box_w, box_h),
                Qt.AlignmentFlag.AlignCenter,
                self.message
            )
            
        # Draw guidance
        if self.guidance_text:
            font = QFont("Arial", 20, QFont.Weight.Bold)
            painter.setFont(font)
            
            text_rect = painter.fontMetrics().boundingRect(self.guidance_text)
            padding = 15
            
            box_w = text_rect.width() + padding * 2
            box_h = text_rect.height() + padding * 2
            
            # Calculate Position
            if self.guidance_x > 0:
                # Center on specific X
                box_x = self.guidance_x - (box_w // 2)
            else:
                # Center on screen
                box_x = (self.width() - box_w) // 2
                
            if self.guidance_y > 0:
                # Position above the specified Y with some padding
                box_y = max(0, self.guidance_y - box_h - 10)
            else:
                # Default top
                box_y = 50 
            
            # Semi-transparent blue background
            painter.fillRect(box_x, box_y, box_w, box_h, QColor(0, 0, 50, 200))
            painter.setPen(QColor(100, 200, 255)) # Light blue text
            painter.drawText(
                QRect(box_x, box_y, box_w, box_h),
                Qt.AlignmentFlag.AlignCenter,
                self.guidance_text
            )

