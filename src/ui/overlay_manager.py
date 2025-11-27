from .overlays.highlight_overlay import HighlightOverlay
from .overlays.debug_overlay import DebugOverlay
from .overlays.calibration_overlay import CalibrationOverlay
from .overlays.alert_overlay import AlertOverlay
from .overlay import BlockerWindow # Reuse existing blocker window logic
from PyQt6.QtCore import QObject, pyqtSignal

class OverlayManager(QObject):
    """
    Manages multiple overlay layers.
    Replacement for the monolithic OverlayWindow.
    """
    
    calibration_clicked = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        
        # Create layers
        self.highlight_layer = HighlightOverlay()
        self.debug_layer = DebugOverlay()
        self.calibration_layer = CalibrationOverlay()
        self.alert_layer = AlertOverlay()
        
        self.blockers = []
        
        # Connect signals
        self.calibration_layer.calibration_clicked.connect(self.calibration_clicked)
        
        # Stack layers (Debug and Alert on top)
        self.highlight_layer.show()
        self.debug_layer.show()
        self.calibration_layer.hide()
        self.alert_layer.hide()
        
        # Raise to top
        self.debug_layer.raise_()
        self.calibration_layer.raise_()
        self.alert_layer.raise_()

    def create_blocker(self, rect: dict, message: str = "UNSAFE"):
        """Create a blocking overlay at the specified location."""
        if rect.get('w', 0) <= 0 or rect.get('h', 0) <= 0:
            return
        
        # Don't create duplicate blockers
        if self.blockers:
            return
        
        blocker = BlockerWindow(rect, message)
        blocker.dismissed.connect(lambda: self.remove_blocker(blocker))
        blocker.show()
        self.blockers.append(blocker)
    
    def remove_blocker(self, blocker):
        if blocker in self.blockers:
            self.blockers.remove(blocker)
            blocker.close()
    
    def clear_blockers(self):
        for blocker in self.blockers:
            blocker.close()
        self.blockers.clear()

    def set_highlights(self, rects):
        self.highlight_layer.set_highlights(rects)

    def set_highlights_from_items(self, items, mapper, base_cell_size, is_quad=False):
        # Helper logic moved here or kept in layer? 
        # Let's implement the rect calculation here to keep layer dumb
        rects = []
        for item in items:
            item_is_quad = item.get('is_quad', False)
            current_cell_size = base_cell_size
            
            if is_quad and not item_is_quad:
                current_cell_size = base_cell_size * 2
            elif not is_quad and item_is_quad:
                current_cell_size = base_cell_size / 2
            
            pixel_x = mapper.offset_x + (item['x'] * current_cell_size)
            pixel_y = mapper.offset_y + (item['y'] * current_cell_size)
            pixel_w = item.get('w', 1) * current_cell_size
            pixel_h = item.get('h', 1) * current_cell_size
            
            rects.append((int(pixel_x), int(pixel_y), int(pixel_w), int(pixel_h)))
        
        self.highlight_layer.set_highlights(rects)

    def show_alert(self, message: str, color: str = "red", duration_ms: int = 2000):
        self.alert_layer.show_alert(message, color, duration_ms)
        self.alert_layer.raise_()

    def set_guidance_text(self, text: str, x: int = -1, y: int = -1):
        """Set persistent guidance text on the overlay."""
        self.alert_layer.set_guidance(text, x, y)
        self.alert_layer.raise_()

    def add_debug_box(self, x, y, w, h, color="red"):
        # DebugOverlay doesn't implement add_debug_box yet, need to add it there too
        # For now, pass it if supported, or ignore
        if hasattr(self.debug_layer, 'add_debug_box'):
            self.debug_layer.add_debug_box(x, y, w, h, color)
    
    def set_debug_rect(self, x, y, w, h, color="yellow"):
        self.debug_layer.set_rect(x, y, w, h, color)
        self.debug_layer.raise_() # Ensure top

    def set_debug_text(self, text, x=10, y=10):
        self.debug_layer.set_text(text, x, y)
        self.debug_layer.raise_()

    def clear_debug(self):
        self.debug_layer.clear()

    def set_calibration_mode(self, active, message=""):
        self.calibration_layer.set_mode(active, message)
        if active:
            self.calibration_layer.raise_()

    def set_calibration_preview(self, ox, oy, cell, is_quad=False):
        # Logic to calculate preview rects
        grid_size = 24 if is_quad else 12
        total_size = grid_size * cell
        corner = cell
        
        from PyQt6.QtCore import QRect
        rects = {
            'top_left': QRect(ox, oy, corner, corner),
            'top_right': QRect(ox + total_size - corner, oy, corner, corner),
            'bottom_left': QRect(ox, oy + total_size - corner, corner, corner),
            'bottom_right': QRect(ox + total_size - corner, oy + total_size - corner, corner, corner),
            'offset_x': ox, 'offset_y': oy, 'total_size': total_size
        }
        self.calibration_layer.set_preview(rects)

    def set_calibration_region_preview(self, x, y, w, h):
        from PyQt6.QtCore import QRect
        self.calibration_layer.set_region_preview(QRect(x, y, w, h))

    def clear_calibration_preview(self):
        self.calibration_layer.set_preview(None)
        self.calibration_layer.set_region_preview(None)

    def close(self):
        self.highlight_layer.close()
        self.debug_layer.close()
        self.calibration_layer.close()
        self.alert_layer.close()
        self.clear_blockers()
    
    def isVisible(self):
        return self.highlight_layer.isVisible() or self.calibration_layer.isVisible()
    
    def hide(self):
        self.highlight_layer.hide()
        # self.debug_layer.hide() # Keep debug active?
        self.calibration_layer.hide()
    
    def show(self):
        self.highlight_layer.show()

