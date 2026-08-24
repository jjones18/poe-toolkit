"""Click-through labeled target previews for safe input diagnostics."""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from .base_overlay import BaseOverlay


class TargetPreviewOverlay(BaseOverlay):
    """Render intended input locations without intercepting or injecting input."""

    def __init__(self):
        super().__init__()
        self.targets = []
        # This layer must never capture clicks, even if another caller tries to
        # reuse BaseOverlay's calibration interactivity API.
        super().set_clickable(False)

    def set_clickable(self, clickable: bool):
        super().set_clickable(False)

    def set_targets(self, targets):
        self.targets = [dict(target) for target in (targets or [])]
        self.update()

    def clear(self):
        self.targets = []
        self.update()

    def has_visible_content(self) -> bool:
        return bool(self.targets)

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))

        for index, target in enumerate(self.targets, start=1):
            x = int(target.get("x", 0))
            y = int(target.get("y", 0))
            color = QColor(target.get("color", "#00e5ff"))
            color.setAlpha(245)
            pen = QPen(color)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 55))
            painter.drawEllipse(x - 13, y - 13, 26, 26)
            painter.drawLine(x - 20, y, x + 20, y)
            painter.drawLine(x, y - 20, x, y + 20)

            label = str(target.get("label") or f"Target {index}")
            label_rect = painter.fontMetrics().boundingRect(label)
            label_x = x + 18
            label_y = y - label_rect.height() - 8
            background = QRect(
                label_x,
                label_y,
                label_rect.width() + 12,
                label_rect.height() + 6,
            )
            painter.fillRect(background, QColor(0, 0, 0, 205))
            painter.setPen(QColor(255, 255, 255, 250))
            painter.drawText(background, Qt.AlignmentFlag.AlignCenter, label)
