import copy
import importlib.machinery
import os
import sys
import types
import unittest
from unittest.mock import ANY, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def optional_module_stub(name):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return module


for optional_module in ("cv2", "mss", "pynput", "keyboard"):
    optional_module_stub(optional_module)
cv2_stub = optional_module_stub("cv2")
cv2_stub.COLOR_BGR2GRAY = 1
cv2_stub.COLOR_BGR2HSV = 2
cv2_stub.THRESH_BINARY = 0
cv2_stub.ADAPTIVE_THRESH_GAUSSIAN_C = 0
cv2_stub.cvtColor = Mock(side_effect=lambda image, _code: image)
cv2_stub.threshold = Mock(side_effect=lambda image, *_args: (None, image))
cv2_stub.adaptiveThreshold = Mock(side_effect=lambda image, *_args: image)
cv2_stub.inRange = Mock(side_effect=lambda *_args: 1)
cv2_stub.bitwise_or = Mock(side_effect=lambda left, _right: left)
numpy_stub = Mock()
numpy_stub.array.side_effect = lambda value, *_args, **_kwargs: value
sys.modules.setdefault("numpy", numpy_stub)
pytesseract_stub = optional_module_stub("pytesseract")
pytesseract_stub.Output = Mock()
pytesseract_stub.Output.DICT = "DICT"
pytesseract_stub.pytesseract = Mock()
pytesseract_stub.pytesseract.tesseract_cmd = "tesseract"
pytesseract_stub.image_to_data = Mock()
pytesseract_stub.image_to_string = Mock()

from PyQt6.QtCore import QObject, QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from tools.league_vision.tool import LeagueVisionWidget
from ui.calibration import (
    CalibrationManager,
    CalibrationType,
    StashGridProfile,
    calculate_stash_grid_calibration,
    get_calibration_status_text,
)
from ui.geometry_utils import RectSpec, clamp_window_geometry
from ui.main_window import MainWindow
from ui.overlay_manager import OverlayManager
from ui.overlays.calibration_overlay import CalibrationOverlay
from ui.overlays.target_preview_overlay import TargetPreviewOverlay
from utils.config import ConfigManager


class CalibrationProfileTests(unittest.TestCase):
    def test_stash_grid_math_uses_explicit_standard_profile_not_width_inference(self):
        result = calculate_stash_grid_calibration((100, 200), (1300, 1400), StashGridProfile.STANDARD)
        self.assertEqual(result["profile"], "standard")
        self.assertEqual(result["grid_cols"], 12)
        self.assertEqual(result["grid_rows"], 12)
        self.assertEqual(result["cell_size"], 100)
        self.assertFalse(result["is_quad_calibrated"])

    def test_stash_grid_math_uses_explicit_quad_profile_for_same_points(self):
        result = calculate_stash_grid_calibration((100, 200), (1300, 1400), StashGridProfile.QUAD)
        self.assertEqual(result["profile"], "quad")
        self.assertEqual(result["grid_cols"], 24)
        self.assertEqual(result["grid_rows"], 24)
        self.assertEqual(result["cell_size"], 50)
        self.assertTrue(result["is_quad_calibrated"])

    def test_profiles_are_saved_separately_and_only_after_confirmation(self):
        config = {}
        save = Mock()
        manager = CalibrationManager(config, save_callback=save)

        manager.start_calibration(CalibrationType.STASH_GRID, StashGridProfile.STANDARD)
        manager.handle_click(0, 0)
        manager.handle_click(120, 120)
        self.assertEqual(save.call_count, 0)
        self.assertNotIn("calibration", config)
        manager.confirm_calibration(calculate_stash_grid_calibration((0, 0), (120, 120), StashGridProfile.STANDARD))

        manager.start_calibration(CalibrationType.STASH_GRID, StashGridProfile.QUAD)
        manager.confirm_calibration(calculate_stash_grid_calibration((10, 20), (250, 260), StashGridProfile.QUAD))

        profiles = config["calibration"]["stash_grid_profiles"]
        self.assertEqual(set(profiles), {"standard", "quad"})
        self.assertEqual(profiles["standard"]["cell_size"], 10)
        self.assertEqual(profiles["quad"]["cell_size"], 10)
        self.assertEqual(config["calibration"]["active_stash_profile"], "quad")
        self.assertEqual(save.call_count, 2)

    def test_legacy_overlay_calibration_is_migrated_in_memory_without_save(self):
        config = {"overlay": {"x_offset": 18, "y_offset": 160, "cell_size": 53, "is_quad_calibrated": True}}
        save = Mock()
        manager = CalibrationManager(config, save_callback=save)

        migrated = manager.get_calibration(CalibrationType.STASH_GRID, StashGridProfile.QUAD)

        self.assertEqual(migrated["profile"], "quad")
        self.assertTrue(migrated["migrated_from_overlay"])
        save.assert_not_called()
        self.assertIn("Quad (24x24): Done", get_calibration_status_text(manager))


class OverlayManagerVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QApplication.processEvents()

    def test_layers_remain_hidden_when_overlay_disabled(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)

        manager.set_highlights([(1, 2, 3, 4)])
        manager.set_debug_rect(1, 2, 3, 4)
        manager.set_calibration_mode(True, "Click")
        manager.set_calibration_preview(0, 0, 10, False)
        manager.show_alert("Unsafe", duration_ms=1)
        manager.create_blocker({"x": 0, "y": 0, "w": 10, "h": 10})
        QApplication.processEvents()

        self.assertFalse(manager.isVisible())
        self.assertFalse(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())
        self.assertTrue(all(not blocker.isVisible() for blocker in manager.blockers))

    def test_enable_and_disable_controls_all_layers(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        manager.set_highlights([(1, 2, 3, 4)])
        manager.set_debug_text("debug")
        manager.set_calibration_preview(0, 0, 10, False)
        manager.set_guidance_text("guidance")

        manager.show()
        QApplication.processEvents()
        self.assertTrue(manager.highlight_layer.isVisible())
        self.assertTrue(manager.debug_layer.isVisible())
        self.assertTrue(manager.calibration_layer.isVisible())
        self.assertTrue(manager.alert_layer.isVisible())

        manager.hide()
        QApplication.processEvents()
        self.assertFalse(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())

    def test_direct_layer_updates_do_not_override_disabled_manager_visibility(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)

        manager.highlight_layer.set_highlights([(1, 2, 3, 4)])
        manager.debug_layer.set_rect(1, 2, 3, 4)
        manager.debug_layer.set_text("debug", 5, 6)
        manager.debug_layer.add_debug_box(7, 8, 9, 10)
        manager.calibration_layer.set_mode(True, "Click")
        manager.calibration_layer.set_preview({"grid": QRect(0, 0, 10, 10), "cols": 1, "rows": 1})
        manager.alert_layer.show_alert("Unsafe")
        manager.alert_layer.set_guidance("guidance")
        QApplication.processEvents()

        self.assertFalse(manager.isVisible())
        self.assertFalse(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())

    def test_direct_layer_clears_do_not_hide_until_manager_reapplies_visibility(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        manager.set_highlights([(1, 2, 3, 4)])
        manager.set_debug_rect(1, 2, 3, 4)
        manager.set_calibration_preview(0, 0, 10, False)
        manager.set_guidance_text("guidance")
        manager.show()
        QApplication.processEvents()

        manager.highlight_layer.set_highlights([])
        manager.debug_layer.clear()
        manager.calibration_layer.set_preview(None)
        manager.alert_layer.set_guidance("")
        QApplication.processEvents()

        self.assertTrue(manager.highlight_layer.isVisible())
        self.assertTrue(manager.debug_layer.isVisible())
        self.assertTrue(manager.calibration_layer.isVisible())
        self.assertTrue(manager.alert_layer.isVisible())

        manager.set_highlights([])
        manager.clear_debug()
        manager.clear_calibration_preview()
        manager.set_guidance_text("")
        QApplication.processEvents()

        self.assertFalse(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())

    def test_enabled_manager_shows_only_layers_with_content_and_expires_alerts(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        manager.show()
        QApplication.processEvents()
        self.assertFalse(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())

        manager.set_highlights([(1, 2, 3, 4)])
        manager.show_alert("Unsafe", duration_ms=60_000)
        QApplication.processEvents()
        self.assertTrue(manager.highlight_layer.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertFalse(manager.calibration_layer.isVisible())
        self.assertTrue(manager.alert_layer.isVisible())
        self.assertTrue(manager._alert_timer.isActive())

        manager._alert_timer.timeout.emit()
        QApplication.processEvents()
        self.assertTrue(manager.highlight_layer.isVisible())
        self.assertFalse(manager.alert_layer.isVisible())

    def test_calibration_target_uses_game_window_and_preview_translates_global_coordinates(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        target = QRect(1920, 100, 1280, 720)

        manager.enable_for_calibration(target)
        manager.set_calibration_mode(True, "Click")
        manager.set_calibration_preview(2000, 180, 10, cols=12, rows=12)

        self.assertEqual(manager.calibration_layer.geometry(), target)
        self.assertEqual(manager.calibration_layer.preview_rects["grid"], QRect(80, 80, 120, 120))

        manager.finish_calibration()
        self.assertIsNone(manager.calibration_target_geometry)


class CalibrationOverlayInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mouse_click_emits_global_desktop_coordinates(self):
        overlay = CalibrationOverlay()
        self.addCleanup(overlay.close)
        received = []
        overlay.calibration_clicked.connect(lambda x, y: received.append((x, y)))
        event = Mock()
        event.button.return_value = Qt.MouseButton.LeftButton
        event.globalPosition.return_value = QPointF(2010, 320)
        event.pos.return_value = QPointF(10, 20)

        overlay.mousePressEvent(event)

        self.assertEqual(received, [(2010, 320)])


class TargetPreviewOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_target_preview_is_permanently_click_through(self):
        overlay = TargetPreviewOverlay()
        self.addCleanup(overlay.close)
        overlay.set_targets([{"x": 80, "y": 90, "label": "Currency"}])

        self.assertTrue(
            bool(overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        )
        self.assertTrue(
            bool(overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        )
        self.assertTrue(
            bool(overlay.windowFlags() & Qt.WindowType.X11BypassWindowManagerHint)
        )
        self.assertTrue(overlay.has_visible_content())

    def test_manager_translates_global_targets_into_exact_game_window(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        target = QRect(1440, 1595, 3440, 1440)

        manager.enable_target_preview(
            target,
            [{"x": 1540, "y": 1795, "label": "Crafting Item"}],
        )

        self.assertEqual(manager.target_preview_layer.geometry(), target)
        self.assertEqual(
            manager.target_preview_layer.targets[0]["x"], 100
        )
        self.assertEqual(
            manager.target_preview_layer.targets[0]["y"], 200
        )
        self.assertTrue(
            bool(
                manager.target_preview_layer.windowFlags()
                & Qt.WindowType.WindowTransparentForInput
            )
        )

        manager.clear_target_preview()
        self.assertFalse(manager.target_preview_layer.has_visible_content())


class FakeScannerWorker(QObject):
    debug_rect_signal = pyqtSignal(int, int, int, int, str)
    debug_box_signal = pyqtSignal(int, int, int, int, str)
    clear_debug_signal = pyqtSignal()
    result_signal = pyqtSignal(object)
    status_signal = pyqtSignal(str)
    mode_signal = pyqtSignal(str)
    stop_requested_signal = pyqtSignal()

    last_instance = None

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.debug_mode = config.get("debug_mode", False)
        self.started = False
        FakeScannerWorker.last_instance = self

    def isRunning(self):
        return self.started

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def wait(self, _timeout):
        return True

    def set_zone(self, _zone):
        pass


class LeagueVisionDebugOverlayGatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_widget(self, overlay):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        config["debug_mode"] = True
        widget = LeagueVisionWidget(config, overlay)
        self.addCleanup(widget.cleanup)
        return widget

    def test_starting_and_updating_debug_does_not_show_overlay_when_disabled(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        widget = self.make_widget(manager)

        with (
            patch("tools.league_vision.tool.ScannerWorker", FakeScannerWorker),
            patch.object(LeagueVisionWidget, "validate_tesseract_path", return_value=True),
        ):
            widget.toggle_scanner()
            FakeScannerWorker.last_instance.debug_rect_signal.emit(1, 2, 3, 4, "yellow")
            FakeScannerWorker.last_instance.debug_box_signal.emit(5, 6, 7, 8, "red")
            QApplication.processEvents()

        self.assertFalse(manager.isVisible())
        self.assertFalse(manager.debug_layer.isVisible())
        self.assertIsNotNone(manager.debug_layer.debug_rect)
        self.assertEqual(len(manager.debug_layer.debug_boxes), 1)

    def test_debug_updates_are_visible_when_show_overlay_is_enabled(self):
        manager = OverlayManager()
        self.addCleanup(manager.close)
        widget = self.make_widget(manager)
        manager.show()

        with (
            patch("tools.league_vision.tool.ScannerWorker", FakeScannerWorker),
            patch.object(LeagueVisionWidget, "validate_tesseract_path", return_value=True),
        ):
            widget.toggle_scanner()
            FakeScannerWorker.last_instance.debug_rect_signal.emit(1, 2, 3, 4, "yellow")
            QApplication.processEvents()

        self.assertTrue(manager.isVisible())
        self.assertTrue(manager.debug_layer.isVisible())


class GeometryHelperTests(unittest.TestCase):
    def test_negative_coordinate_monitor_is_valid_target(self):
        screens = [RectSpec(-1920, 0, 1920, 1080), RectSpec(0, 0, 2560, 1440)]
        result = clamp_window_geometry({"x": -1800, "y": 40, "width": 1000, "height": 700}, screens)
        self.assertEqual(result, RectSpec(-1800, 40, 1000, 700))

    def test_disconnected_monitor_geometry_is_clamped_to_connected_screen(self):
        screens = [RectSpec(0, 0, 1920, 1040)]
        result = clamp_window_geometry({"x": 5000, "y": -2000, "width": 1100, "height": 800}, screens)
        self.assertEqual(result, RectSpec(820, 0, 1100, 800))

    def test_oversized_saved_window_is_reduced_to_available_screen(self):
        screens = [RectSpec(0, 0, 1280, 720)]
        result = clamp_window_geometry({"x": -50, "y": -50, "width": 4000, "height": 3000}, screens)
        self.assertEqual(result, RectSpec(0, 0, 1280, 720))


class MainWindowCalibrationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _close_without_persisting(window):
        with patch.object(ConfigManager, "save", return_value=True):
            window.close()


    def test_overlay_updates_do_not_force_show_overlay_on(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False
        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch.object(ConfigManager, "save", return_value=True),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)
        self.addCleanup(self._close_without_persisting, window)

        window.on_overlay_update([{"x": 0, "y": 0, "w": 1, "h": 1}])
        QApplication.processEvents()

        self.assertFalse(window.overlay.isVisible())
        self.assertFalse(window.overlay_btn.isChecked())
        self.assertFalse(window.overlay.highlight_layer.isVisible())

    def test_start_calibration_uses_single_enable_path_and_status_names_profile(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False
        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch.object(ConfigManager, "save", return_value=True),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)
        self.addCleanup(self._close_without_persisting, window)

        game_rect = {"left": 1920, "top": 100, "width": 1280, "height": 720}
        with patch("ui.main_window.platform_utils.find_window_rect", return_value=game_rect) as find_window:
            started = window.start_calibration(CalibrationType.STASH_GRID, StashGridProfile.QUAD)

        self.assertTrue(started)
        find_window.assert_called_once_with(
            "Path of Exile 2",
            exact_title=True,
            process_names=("PathOfExile2.exe", "PathOfExile2Steam.exe"),
            title_matcher=ANY,
        )
        self.assertTrue(window.overlay.isVisible())
        self.assertTrue(window.overlay_btn.isChecked())
        self.assertEqual(window.overlay.calibration_layer.geometry(), QRect(1920, 100, 1280, 720))
        self.assertIn("Quad (24x24)", window.status_label.text())
        self.assertIn("Quad (24x24)", window.overlay.calibration_layer.message)

    def test_start_calibration_fails_closed_when_active_game_window_is_missing(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe1")
        service = Mock()
        service.is_running = False
        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch.object(ConfigManager, "save", return_value=True),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)
        self.addCleanup(self._close_without_persisting, window)

        with (
            patch("ui.main_window.platform_utils.find_window_rect", return_value=None),
            patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok) as warning,
        ):
            started = window.start_calibration(CalibrationType.STASH_GRID, StashGridProfile.STANDARD)

        self.assertFalse(started)
        self.assertFalse(window.calibration_manager.is_active())
        self.assertFalse(window.overlay.isVisible())
        self.assertFalse(window.overlay.calibration_layer.has_visible_content())
        self.assertIn("Path of Exile 1", warning.call_args.args[2])
        self.assertEqual(window.status_label.text(), "Calibration unavailable: game window not found")

    def test_confirm_dialog_saves_only_on_yes_after_preview(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False
        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch.object(ConfigManager, "save", return_value=True) as save,
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)
            with patch(
                "ui.main_window.platform_utils.find_window_rect",
                return_value={"left": 0, "top": 0, "width": 1920, "height": 1080},
            ):
                window.start_calibration(CalibrationType.STASH_GRID, StashGridProfile.STANDARD)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window.on_calibration_click(0, 0)
                window.on_calibration_click(120, 120)
        self.addCleanup(self._close_without_persisting, window)

        self.assertIn("standard", window.config["calibration"]["stash_grid_profiles"])
        self.assertGreaterEqual(save.call_count, 1)
        self.assertFalse(window.overlay.calibration_layer.preview_rects)


if __name__ == "__main__":
    unittest.main()
