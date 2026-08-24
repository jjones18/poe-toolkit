from .overlays.highlight_overlay import HighlightOverlay
from .overlays.debug_overlay import DebugOverlay
from .overlays.calibration_overlay import CalibrationOverlay
from .overlays.target_preview_overlay import TargetPreviewOverlay
from .overlays.alert_overlay import AlertOverlay
from .overlay import BlockerWindow # Reuse existing blocker window logic
from PyQt6.QtCore import QObject, QPoint, QRect, QTimer, pyqtSignal


class OverlayManager(QObject):
    """
    Manages multiple overlay layers and owns the single Show Overlay state.
    """

    calibration_clicked = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.overlay_enabled = False
        self.calibration_target_geometry = None
        self.target_preview_geometry = None
        self.highlight_layer = HighlightOverlay()
        self.debug_layer = DebugOverlay()
        self.calibration_layer = CalibrationOverlay()
        self.target_preview_layer = TargetPreviewOverlay()
        self.alert_layer = AlertOverlay()
        self._alert_timer = QTimer(self)
        self._alert_timer.setSingleShot(True)
        self._alert_timer.timeout.connect(self._expire_alert)
        self.blockers = []
        self.calibration_layer.calibration_clicked.connect(self.calibration_clicked)
        self._all_layers = [
            self.highlight_layer,
            self.debug_layer,
            self.calibration_layer,
            self.target_preview_layer,
            self.alert_layer,
        ]
        self._sync_layer_geometries()
        self._hide_all_layers()

    def _sync_layer_geometries(self):
        try:
            from PyQt6.QtGui import QGuiApplication
            geometry = QGuiApplication.primaryScreen().virtualGeometry()
        except Exception:
            geometry = None
        if geometry:
            for layer in self._all_layers:
                layer.setGeometry(geometry)
        if self.calibration_target_geometry is not None:
            self.calibration_layer.setGeometry(self.calibration_target_geometry)
        if self.target_preview_geometry is not None:
            self.target_preview_layer.setGeometry(self.target_preview_geometry)

    def _hide_all_layers(self):
        for layer in self._all_layers:
            layer.hide()
        for blocker in self.blockers:
            blocker.hide()

    def _raise_visible_layers(self):
        self.debug_layer.raise_()
        self.calibration_layer.raise_()
        self.target_preview_layer.raise_()
        self.alert_layer.raise_()

    def _apply_visibility(self):
        if not self.overlay_enabled:
            self._hide_all_layers()
            return
        if getattr(self.highlight_layer, "highlights", None):
            self.highlight_layer.show()
        else:
            self.highlight_layer.hide()
        if getattr(self.debug_layer, "debug_rect", None) or getattr(self.debug_layer, "debug_text", "") or getattr(self.debug_layer, "debug_boxes", None):
            self.debug_layer.show()
        else:
            self.debug_layer.hide()
        if self.calibration_layer.has_visible_content():
            self.calibration_layer.show()
        else:
            self.calibration_layer.hide()
        if self.target_preview_layer.has_visible_content():
            self.target_preview_layer.show()
        else:
            self.target_preview_layer.hide()
        if self.alert_layer.has_visible_content():
            self.alert_layer.show()
        else:
            self.alert_layer.hide()
        for blocker in self.blockers:
            blocker.show()
        self._raise_visible_layers()

    def set_overlay_enabled(self, enabled: bool):
        self.overlay_enabled = bool(enabled)
        self._sync_layer_geometries()
        self._apply_visibility()

    def enable_for_calibration(self, target_geometry: QRect):
        """Enable calibration over the exact game window on any monitor."""
        self.calibration_target_geometry = QRect(target_geometry)
        self.set_overlay_enabled(True)

    def finish_calibration(self):
        """Release the game-window target after preview confirmation/cancellation."""
        self.calibration_target_geometry = None
        self._sync_layer_geometries()

    def enable_target_preview(self, target_geometry: QRect, targets):
        """Show labeled global targets over one exact game window without input."""
        self.target_preview_geometry = QRect(target_geometry)
        self._sync_layer_geometries()
        local_targets = []
        for target in targets or []:
            local = dict(target)
            local["x"] = int(target["x"]) - self.target_preview_geometry.x()
            local["y"] = int(target["y"]) - self.target_preview_geometry.y()
            local_targets.append(local)
        self.target_preview_layer.set_targets(local_targets)
        self.set_overlay_enabled(True)

    def clear_target_preview(self):
        self.target_preview_layer.clear()
        self.target_preview_geometry = None
        self._sync_layer_geometries()
        self._apply_visibility()

    def create_blocker(self, rect: dict, message: str = "UNSAFE"):
        if rect.get('w', 0) <= 0 or rect.get('h', 0) <= 0:
            return
        if self.blockers:
            return
        blocker = BlockerWindow(rect, message)
        blocker.dismissed.connect(lambda: self.remove_blocker(blocker))
        self.blockers.append(blocker)
        if self.overlay_enabled:
            blocker.show()
        else:
            blocker.hide()

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
        self._apply_visibility()

    def set_highlights_from_items(self, items, mapper, base_cell_size, is_quad=False):
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
        self.set_highlights(rects)

    def show_alert(self, message: str, color: str = "red", duration_ms: int = 2000):
        self.alert_layer.show_alert(message, color, duration_ms)
        if duration_ms > 0:
            self._alert_timer.start(duration_ms)
        else:
            self._alert_timer.stop()
        self._apply_visibility()

    def _expire_alert(self):
        self.alert_layer.clear_alert()
        self._apply_visibility()

    def set_guidance_text(self, text: str, x: int = -1, y: int = -1):
        self.alert_layer.set_guidance(text, x, y)
        self._apply_visibility()

    def add_debug_box(self, x, y, w, h, color="red"):
        if hasattr(self.debug_layer, 'add_debug_box'):
            self.debug_layer.add_debug_box(x, y, w, h, color)
        self._apply_visibility()

    def set_debug_rect(self, x, y, w, h, color="yellow"):
        self.debug_layer.set_rect(x, y, w, h, color)
        self._apply_visibility()

    def set_debug_text(self, text, x=10, y=10):
        self.debug_layer.set_text(text, x, y)
        self._apply_visibility()

    def clear_debug(self):
        self.debug_layer.clear()
        self._apply_visibility()

    def set_calibration_mode(self, active, message=""):
        self.calibration_layer.set_mode(active, message)
        # setWindowFlags() may let the window manager reset a tool window's
        # position, so always restore the exact game target afterward.
        self._sync_layer_geometries()
        self._apply_visibility()

    def set_calibration_preview(self, ox, oy, cell, is_quad=False, cols=None, rows=None, cell_width=None, cell_height=None):
        grid_cols = int(cols or (24 if is_quad else 12))
        grid_rows = int(rows or grid_cols)
        cw = float(cell_width if cell_width is not None else cell)
        ch = float(cell_height if cell_height is not None else cell)
        total_w = int(round(grid_cols * cw))
        total_h = int(round(grid_rows * ch))
        local_origin = QPoint(
            int(ox) - self.calibration_layer.geometry().x(),
            int(oy) - self.calibration_layer.geometry().y(),
        )
        rects = {
            'grid': QRect(local_origin.x(), local_origin.y(), total_w, total_h),
            'offset_x': int(ox), 'offset_y': int(oy),
            'cell_width': cw, 'cell_height': ch,
            'cols': grid_cols, 'rows': grid_rows,
            'total_size': total_w,
            'total_width': total_w, 'total_height': total_h,
        }
        self.calibration_layer.set_preview(rects)
        self._apply_visibility()

    def set_calibration_region_preview(self, x, y, w, h):
        geometry = self.calibration_layer.geometry()
        self.calibration_layer.set_region_preview(QRect(x - geometry.x(), y - geometry.y(), w, h))
        self._apply_visibility()

    def set_calibration_point_previews(self, points):
        """Preview labeled global crafting points in calibration-local coordinates."""
        geometry = self.calibration_layer.geometry()
        local_points = []
        for point in points or []:
            local = dict(point)
            local["x"] = int(point["x"]) - geometry.x()
            local["y"] = int(point["y"]) - geometry.y()
            local_points.append(local)
        self.calibration_layer.set_point_previews(local_points)
        self._apply_visibility()

    def clear_calibration_preview(self):
        self.calibration_layer.set_preview(None)
        self.calibration_layer.set_region_preview(None)
        self.calibration_layer.set_point_previews([])
        self._apply_visibility()

    def close(self):
        self._alert_timer.stop()
        for layer in self._all_layers:
            layer.close()
        self.clear_blockers()

    def isVisible(self):
        return self.overlay_enabled

    def hide(self):
        self.set_overlay_enabled(False)

    def show(self):
        self.set_overlay_enabled(True)
