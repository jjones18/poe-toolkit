"""
Unified overlay system for POE Toolkit.
Supports item highlighting, calibration, and safety blockers.
"""

from PyQt6.QtWidgets import QMainWindow, QWidget, QApplication, QLabel
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

try:
    from pynput import mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    print("Warning: pynput not found. Overlay click detection will be disabled.")


class BlockerWindow(QMainWindow):
    """
    A semi-transparent blocking overlay that prevents clicks on dangerous buttons.
    Used by League Vision for map safety checks.
    """
    
    dismissed = pyqtSignal()
    
    def __init__(self, rect: dict, message: str = "BLOCKED"):
        super().__init__()
        
        x, y, w, h = rect.get('x', 0), rect.get('y', 0), rect.get('w', 100), rect.get('h', 50)
        
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        self.setGeometry(x, y, w, h)
        
        # Red semi-transparent background - use setWindowOpacity for proper semi-transparency
        self.setWindowOpacity(0.6)
        self.setStyleSheet("background-color: red;")
        
        # Create central widget to receive mouse events
        central = QWidget(self)
        central.setStyleSheet("background-color: red;")
        self.setCentralWidget(central)
        
        # Warning message window (separate, centered on screen) - CLICK-THROUGH
        self.warning_window = QMainWindow()
        self.warning_window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput  # Click-through!
        )
        self.warning_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.warning_window.setStyleSheet("background-color: rgba(200, 0, 0, 200);")
        
        screen = QApplication.primaryScreen().geometry()
        self.warning_window.setGeometry(
            screen.width() // 2 - 200,
            screen.height() // 3,
            400, 80
        )
        
        warning_label = QLabel("UNSAFE MAP DETECTED\nShift+Click Red Box to Dismiss", self.warning_window)
        warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warning_label.setStyleSheet("color: white; font-weight: bold; font-size: 16px; background-color: red;")
        warning_label.setGeometry(0, 0, 400, 80)
        self.warning_window.show()
    
    def mousePressEvent(self, event):
        """Shift+Click to dismiss."""
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.dismissed.emit()
            self.close()
    
    def closeEvent(self, event):
        """Also close the warning window."""
        if hasattr(self, 'warning_window') and self.warning_window:
            self.warning_window.close()
        super().closeEvent(event)


class OverlayWindow(QMainWindow):
    """
    Main overlay window for highlighting items and calibration.
    Supports multiple modes:
    - Highlight mode: Shows semi-transparent boxes over items
    - Calibration mode: Allows clicking to set calibration points
    - Alert mode: Shows text alerts on screen
    """
    
    toggle_signal = pyqtSignal(int)
    calibration_clicked = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POE Toolkit Overlay")
        
        # Start as transparent for input (click-through)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool | 
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Fullscreen geometry
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        
        self.highlights = []
        self.highlight_states = []
        
        # Alert state
        self.alert_text = ""
        self.alert_color = QColor(255, 0, 0)
        self.alert_visible = False
        
        # Calibration state
        self.calibration_mode = False
        self.calibration_msg = ""
        
        # Blockers
        self.blockers = []
        
        # Debug scan region
        self.debug_rect = None
        self.debug_color = QColor(255, 255, 0, 200)  # Yellow
        
        # Debug keyword boxes (list of (QRect, QColor))
        self.debug_boxes = []
        
        # Calibration preview (corner markers showing stash grid position)
        self.calibration_preview = None  # Will be dict with corner rects
        
        # Global click listener
        self.listener = None
        if HAS_PYNPUT:
            self.listener = mouse.Listener(on_click=self.on_global_click)
            self.listener.start()
            
        self.toggle_signal.connect(self.toggle_highlight_state)
    
    def closeEvent(self, event):
        if self.listener:
            self.listener.stop()
        self.clear_blockers()
        super().closeEvent(event)

    def on_global_click(self, x, y, button, pressed):
        """Handle global clicks for toggling highlights."""
        if not pressed or button != mouse.Button.left:
            return
            
        if self.calibration_mode:
            return
        
        geo = self.geometry()
        local_x = x - geo.x()
        local_y = y - geo.y()
        
        for i, rect in enumerate(self.highlights):
            if rect.contains(local_x, local_y):
                self.toggle_signal.emit(i)
                break

    def set_calibration_mode(self, active: bool, step_msg: str = ""):
        """Enable/disable calibration mode."""
        self.calibration_mode = active
        self.calibration_msg = step_msg
        
        if active:
            # Make window clickable
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.show()
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            # Restore click-through
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool | 
                Qt.WindowType.WindowTransparentForInput
            )
            self.show()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            
        self.update()

    def mousePressEvent(self, event):
        """Handle clicks during calibration."""
        if self.calibration_mode:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self.calibration_clicked.emit(int(event.pos().x()), int(event.pos().y()))

    def toggle_highlight_state(self, index):
        """Toggle a highlight between active and dismissed."""
        if 0 <= index < len(self.highlight_states):
            self.highlight_states[index] = not self.highlight_states[index]
            self.update()

    def set_highlights(self, rects: list):
        """Set the list of highlight rectangles."""
        self.highlights = [QRect(*r) if isinstance(r, tuple) else r for r in rects]
        self.highlight_states = [False] * len(self.highlights)
        
        if not self.calibration_mode:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool | 
                Qt.WindowType.WindowTransparentForInput
            )
            self.show()
        
        self.update()
    
    def set_highlights_from_items(self, items: list, mapper, base_cell_size: int, calibrated_is_quad: bool = False):
        """
        Convert item data to screen rectangles using the coordinate mapper.
        Handles quad vs standard tab size differences.
        """
        rects = []
        
        for item in items:
            item_is_quad = item.get('is_quad', False)
            current_cell_size = base_cell_size
            
            if calibrated_is_quad and not item_is_quad:
                current_cell_size = base_cell_size * 2
            elif not calibrated_is_quad and item_is_quad:
                current_cell_size = base_cell_size / 2
            
            pixel_x = mapper.offset_x + (item['x'] * current_cell_size)
            pixel_y = mapper.offset_y + (item['y'] * current_cell_size)
            pixel_w = item.get('w', 1) * current_cell_size
            pixel_h = item.get('h', 1) * current_cell_size
            
            rects.append(QRect(int(pixel_x), int(pixel_y), int(pixel_w), int(pixel_h)))
        
        self.set_highlights(rects)

    def show_alert(self, message: str, color: str = "red", duration_ms: int = 2000):
        """Show a temporary alert message."""
        self.alert_text = message
        self.alert_color = QColor(color)
        self.alert_visible = True
        self.update()
        
        # Auto-hide after duration
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(duration_ms, self.hide_alert)
    
    def hide_alert(self):
        """Hide the alert message."""
        self.alert_visible = False
        self.update()

    def create_blocker(self, rect: dict, message: str = "UNSAFE"):
        """Create a blocking overlay at the specified location."""
        if rect.get('w', 0) <= 0 or rect.get('h', 0) <= 0:
            return
        
        # Don't create duplicate blockers - if one already exists, skip
        if self.blockers:
            return
        
        blocker = BlockerWindow(rect, message)
        blocker.dismissed.connect(lambda: self.remove_blocker(blocker))
        blocker.show()
        self.blockers.append(blocker)
    
    def remove_blocker(self, blocker):
        """Remove a specific blocker."""
        if blocker in self.blockers:
            self.blockers.remove(blocker)
            blocker.close()
    
    def clear_blockers(self):
        """Remove all blockers."""
        for blocker in self.blockers:
            blocker.close()
        self.blockers.clear()
    
    def set_debug_rect(self, x: int, y: int, w: int, h: int, color: str = "yellow"):
        """Set the debug scan region rectangle."""
        self.debug_rect = QRect(x, y, w, h)
        if color == "yellow":
            self.debug_color = QColor(255, 255, 0, 200)
        elif color == "cyan":
            self.debug_color = QColor(0, 255, 255, 200)
        elif color == "red":
            self.debug_color = QColor(255, 0, 0, 200)
        else:
            self.debug_color = QColor(255, 255, 0, 200)
        self.update()
    
    def clear_debug(self):
        """Clear the debug scan region rectangle and all debug boxes."""
        self.debug_rect = None
        self.debug_boxes = []
        self.update()
    
    def add_debug_box(self, x: int, y: int, w: int, h: int, color: str = "red"):
        """Add a debug box (for highlighting found keywords)."""
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
        self.update()
    
    def set_calibration_preview(self, offset_x: int, offset_y: int, cell_size: int, is_quad: bool = False):
        """
        Set the calibration preview showing the stash grid boundaries.
        Shows 4 corner markers to indicate where the overlay is calibrated.
        """
        grid_size = 24 if is_quad else 12
        total_size = grid_size * cell_size
        corner_size = cell_size  # Each corner marker is 1 cell
        
        # Four corners of the stash grid
        self.calibration_preview = {
            'top_left': QRect(offset_x, offset_y, corner_size, corner_size),
            'top_right': QRect(offset_x + total_size - corner_size, offset_y, corner_size, corner_size),
            'bottom_left': QRect(offset_x, offset_y + total_size - corner_size, corner_size, corner_size),
            'bottom_right': QRect(offset_x + total_size - corner_size, offset_y + total_size - corner_size, corner_size, corner_size),
            'grid_size': grid_size,
            'total_size': total_size,
            'offset_x': offset_x,
            'offset_y': offset_y
        }
        self.update()
    
    def clear_calibration_preview(self):
        """Clear the calibration preview."""
        self.calibration_preview = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Calibration background
        if self.calibration_mode:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        
        # Draw highlights
        pen_green = QPen(QColor(0, 255, 0, 200))
        pen_green.setWidth(3)
        brush_green = QColor(0, 255, 0, 50)
        
        pen_gray = QPen(QColor(150, 150, 150, 200))
        pen_gray.setWidth(3)
        brush_gray = QColor(150, 150, 150, 50)

        if self.highlights:
            if len(self.highlight_states) != len(self.highlights):
                self.highlight_states = [False] * len(self.highlights)

            for i, rect in enumerate(self.highlights):
                if self.highlight_states[i]:
                    painter.setPen(pen_gray)
                    painter.setBrush(brush_gray)
                else:
                    painter.setPen(pen_green)
                    painter.setBrush(brush_green)
                painter.drawRect(rect)
        
        # Draw debug scan region
        if self.debug_rect:
            pen_debug = QPen(self.debug_color)
            pen_debug.setWidth(2)
            painter.setPen(pen_debug)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.debug_rect)
        
        # Draw debug keyword boxes
        for rect, color in self.debug_boxes:
            pen_box = QPen(color)
            pen_box.setWidth(2)
            painter.setPen(pen_box)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        
        # Draw calibration preview (corner markers)
        if self.calibration_preview and not self.highlights:
            pen_corner = QPen(QColor(0, 255, 0, 200))
            pen_corner.setWidth(3)
            brush_corner = QColor(0, 255, 0, 30)
            
            painter.setPen(pen_corner)
            painter.setBrush(brush_corner)
            
            # Draw the 4 corner boxes
            painter.drawRect(self.calibration_preview['top_left'])
            painter.drawRect(self.calibration_preview['top_right'])
            painter.drawRect(self.calibration_preview['bottom_left'])
            painter.drawRect(self.calibration_preview['bottom_right'])
            
            # Draw connecting lines (dashed) to show the full grid boundary
            pen_line = QPen(QColor(0, 255, 0, 100))
            pen_line.setWidth(1)
            pen_line.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen_line)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            ox = self.calibration_preview['offset_x']
            oy = self.calibration_preview['offset_y']
            ts = self.calibration_preview['total_size']
            
            # Draw full grid outline
            painter.drawRect(QRect(ox, oy, ts, ts))
        
        # Draw calibration message
        if self.calibration_mode and self.calibration_msg:
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.calibration_msg)
        
        # Draw alert
        if self.alert_visible and self.alert_text:
            # Background box
            font = QFont("Arial", 32, QFont.Weight.Bold)
            painter.setFont(font)
            
            text_rect = painter.fontMetrics().boundingRect(self.alert_text)
            padding = 20
            
            box_x = (self.width() - text_rect.width()) // 2 - padding
            box_y = self.height() // 4 - padding
            box_w = text_rect.width() + padding * 2
            box_h = text_rect.height() + padding * 2
            
            painter.fillRect(box_x, box_y, box_w, box_h, QColor(32, 32, 32, 220))
            painter.setPen(self.alert_color)
            painter.drawText(
                QRect(box_x, box_y, box_w, box_h),
                Qt.AlignmentFlag.AlignCenter,
                self.alert_text
            )

