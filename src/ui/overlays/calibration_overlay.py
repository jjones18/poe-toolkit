from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from .base_overlay import BaseOverlay

class CalibrationOverlay(BaseOverlay):
    """Overlay for calibration interaction."""
    
    calibration_clicked = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        self.message = ""
        self.preview_rects = None # For showing grid preview
        self.region_preview = None # For showing simple region (Rect)
    
    def set_mode(self, active: bool, message: str = ""):
        self.message = message
        if active:
            self.set_clickable(True)
            self.show()
        else:
            self.set_clickable(False)
            # Only hide if no preview is showing
            if not self.preview_rects and not self.region_preview:
                self.hide()
        self.update()

    def set_region_preview(self, rect: QRect):
        """Set a simple region rectangle to preview."""
        self.region_preview = rect
        if rect:
            self.show()
        # If clearing preview and no active mode, hide
        elif not self.message:
            self.hide()
        self.update()

    def set_preview(self, rects: dict):
        """Set calibration preview rectangles (corners)."""
        self.preview_rects = rects
        if rects:
            self.show()
        # If clearing preview and no active mode, hide
        elif not self.message:
            self.hide()
        self.update()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.calibration_clicked.emit(int(event.pos().x()), int(event.pos().y()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Darken background during active calibration
        if self.message:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
            
            # Draw message
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)

        # Draw region preview
        if self.region_preview:
            pen = QPen(QColor(0, 255, 255, 200)) # Cyan
            pen.setWidth(3)
            brush = QColor(0, 255, 255, 30)
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawRect(self.region_preview)

        # Draw preview
        if self.preview_rects:
            pen = QPen(QColor(0, 255, 0, 200))
            pen.setWidth(3)
            brush = QColor(0, 255, 0, 30)
            painter.setPen(pen)
            painter.setBrush(brush)
            
            for key in ['top_left', 'top_right', 'bottom_left', 'bottom_right']:
                if key in self.preview_rects:
                    painter.drawRect(self.preview_rects[key])
            
            # Outline
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            if 'offset_x' in self.preview_rects:
                painter.drawRect(QRect(
                    self.preview_rects['offset_x'],
                    self.preview_rects['offset_y'],
                    self.preview_rects['total_size'],
                    self.preview_rects['total_size']
                ))

