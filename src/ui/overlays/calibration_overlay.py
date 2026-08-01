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

    def has_visible_content(self) -> bool:
        return bool(self.message or self.preview_rects or self.region_preview)

    def set_mode(self, active: bool, message: str = ""):
        self.message = message if active else ""
        self.set_clickable(active)
        self.update()

    def set_region_preview(self, rect: QRect):
        self.region_preview = rect
        self.update()

    def set_preview(self, rects: dict):
        self.preview_rects = rects
        self.update()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            position = event.globalPosition()
            self.calibration_clicked.emit(int(position.x()), int(position.y()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.message:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)

        if self.region_preview:
            pen = QPen(QColor(0, 255, 255, 200))
            pen.setWidth(3)
            brush = QColor(0, 255, 255, 30)
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawRect(self.region_preview)

        if self.preview_rects:
            grid = self.preview_rects.get('grid')
            if grid is None and 'offset_x' in self.preview_rects:
                grid = QRect(
                    self.preview_rects['offset_x'],
                    self.preview_rects['offset_y'],
                    self.preview_rects.get('total_width', self.preview_rects.get('total_size', 0)),
                    self.preview_rects.get('total_height', self.preview_rects.get('total_size', 0)),
                )
            if grid is None:
                return
            pen = QPen(QColor(0, 255, 0, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 0, 24))
            painter.drawRect(grid)

            cols = int(self.preview_rects.get('cols', 12))
            rows = int(self.preview_rects.get('rows', cols))
            cw = float(self.preview_rects.get('cell_width', grid.width() / max(cols, 1)))
            ch = float(self.preview_rects.get('cell_height', grid.height() / max(rows, 1)))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for col in range(1, cols):
                x = int(round(grid.x() + col * cw))
                painter.drawLine(x, grid.y(), x, grid.y() + grid.height())
            for row in range(1, rows):
                y = int(round(grid.y() + row * ch))
                painter.drawLine(grid.x(), y, grid.x() + grid.width(), y)
