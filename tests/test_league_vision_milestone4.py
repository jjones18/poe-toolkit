import copy
import importlib.machinery
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtWidgets import QApplication

# Keep League Vision unit tests independent of optional OCR/screen-capture wheels.
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

from utils.config import ConfigManager, ConfigSaveError


class LeagueVisionMilestone4WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_widget(self):
        from tools.league_vision.tool import LeagueVisionWidget

        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        return LeagueVisionWidget(config), config

    def test_feature_checkbox_persists_immediately_and_updates_running_scanner(self):
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        scanner = Mock()
        scanner.isRunning.return_value = True
        widget.scanner = scanner

        with patch("tools.league_vision.tool.ConfigManager.save", return_value=True) as save:
            widget.chk_map_safety.setChecked(False)

        save.assert_called_once_with(config)
        self.assertFalse(config["league_vision"]["map_check"]["enabled"])
        scanner.update_config.assert_called_once()
        scanner_config = scanner.update_config.call_args.args[0]
        self.assertFalse(scanner_config["map_check"]["enabled"])
        self.assertEqual(scanner_config["active_game"], "poe2")
        self.assertIn("screen_geometry", scanner_config)

    def test_calibration_rolls_back_previous_button_when_persistence_fails(self):
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        overlay = Mock()
        widget.overlay = overlay
        previous = {"x": 1, "y": 2, "w": 3, "h": 4}
        config["league_vision"]["map_device_button"] = previous.copy()
        widget.calibration_clicks = [(10, 20)]

        with (
            patch("tools.league_vision.tool.ConfigManager.save", side_effect=ConfigSaveError("disk full")),
            patch("tools.league_vision.tool.QMessageBox.information") as info,
            patch("tools.league_vision.tool.QMessageBox.warning") as warning,
        ):
            widget.on_calibration_click(30, 60)

        self.assertEqual(config["league_vision"]["map_device_button"], previous)
        info.assert_not_called()
        warning.assert_called_once()
        self.assertIn("was not saved", widget.log_area.toPlainText())

    def test_calibration_deletes_button_key_when_new_unsaved_value_had_no_prior_key(self):
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        overlay = Mock()
        widget.overlay = overlay
        config["league_vision"].pop("map_device_button", None)
        widget.calibration_clicks = [(10, 20)]

        with (
            patch("tools.league_vision.tool.ConfigManager.save", side_effect=ConfigSaveError("disk full")),
            patch("tools.league_vision.tool.QMessageBox.information") as info,
            patch("tools.league_vision.tool.QMessageBox.warning") as warning,
        ):
            widget.on_calibration_click(30, 60)

        self.assertNotIn("map_device_button", config["league_vision"])
        info.assert_not_called()
        warning.assert_called_once()

    def test_tesseract_warning_is_logged_before_scanner_is_constructed(self):
        widget, _ = self.make_widget()
        self.addCleanup(widget.cleanup)
        widget.vision_config["tesseract_path"] = "/definitely/missing/tesseract"
        with (
            patch("tools.league_vision.tool.ScannerWorker") as worker_cls,
            patch("tools.league_vision.tool.QMessageBox.warning") as warning,
        ):
            result = widget.toggle_scanner()

        self.assertFalse(result)
        worker_cls.assert_not_called()
        warning.assert_called_once()
        self.assertIn("Tesseract not found", widget.log_area.toPlainText())
        self.assertIsNone(widget.scanner)
    def test_ocr_preview_uses_active_game_exact_window_matching(self):
        widget, _config = self.make_widget()
        self.addCleanup(widget.cleanup)
        vision_instance = Mock()
        vision_instance.get_window_rect.return_value = None

        with patch("tools.league_vision.vision_core.VisionCore", return_value=vision_instance) as vision_cls:
            widget.test_ocr()

        _, kwargs = vision_cls.call_args
        self.assertEqual(kwargs["window_title"], "Path of Exile 2")
        self.assertTrue(kwargs["exact_title"])
        self.assertIn("PathOfExile2.exe", kwargs["process_names"])
        self.assertFalse(kwargs["title_matcher"]("Path of Exile"))
        self.assertIn("Could not find", widget.log_area.toPlainText())


    def test_live_setting_rolls_back_config_and_control_when_save_fails(self):
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        old_value = config["league_vision"].get("ocr_threshold", 70)
        new_value = 123 if old_value != 123 else 124

        with patch("tools.league_vision.tool.ConfigManager.save", side_effect=ConfigSaveError("readonly")):
            widget.threshold_spin.setValue(new_value)

        self.assertEqual(config["league_vision"].get("ocr_threshold", 70), old_value)
        self.assertEqual(widget.threshold_spin.value(), old_value)
        self.assertIn("Could not save", widget.log_area.toPlainText())

    def import_payload(self, widget, payload):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            import_path = handle.name
        self.addCleanup(lambda: os.path.exists(import_path) and os.unlink(import_path))
        return patch("tools.league_vision.tool.QFileDialog.getOpenFileName", return_value=(import_path, "JSON"))

    def test_import_rejects_invalid_scalars_before_save_or_mutation(self):
        invalid_payloads = [
            ({"ocr_threshold": "70"}, "ocr_threshold"),
            ({"ocr_threshold": 0}, "ocr_threshold"),
            ({"ocr_timeout": "slow"}, "ocr_timeout"),
            ({"scan_interval_mouse": 10}, "scan_interval_mouse"),
            ({"ocr_profile": "turbo"}, "ocr_profile"),
            ({"syndicate_enabled": "yes"}, "syndicate_enabled"),
            ({"map_device_button": {"x": 1, "y": 2, "w": "3", "h": 4}}, "map_device_button.w"),
        ]
        for payload, field in invalid_payloads:
            with self.subTest(field=field):
                widget, config = self.make_widget()
                self.addCleanup(widget.cleanup)
                original = copy.deepcopy(config["league_vision"])
                original_profile = widget.profile_combo.currentText()
                original_threshold = widget.threshold_spin.value()

                with (
                    self.import_payload(widget, payload),
                    patch("tools.league_vision.tool.ConfigManager.save") as save,
                    patch("tools.league_vision.tool.QMessageBox.warning") as warning,
                ):
                    self.assertFalse(widget.import_settings())

                save.assert_not_called()
                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[1], "Import Failed")
                self.assertIn(field.split(".")[0], warning.call_args.args[2])
                self.assertEqual(config["league_vision"], original)
                self.assertEqual(widget.profile_combo.currentText(), original_profile)
                self.assertEqual(widget.threshold_spin.value(), original_threshold)

    def test_import_rejects_invalid_nested_collections_before_save_or_mutation(self):
        invalid_payloads = [
            ({"map_check": []}, "map_check"),
            ({"map_check": {"enabled": "false"}}, "map_check.enabled"),
            ({"map_check": {"bad_mods": ["safe", 1]}}, "map_check.bad_mods"),
            ({"eldritch_altars": {"tiers": {"bad": ["Divine Orb"]}}}, "eldritch_altars.tiers.bad"),
            ({"eldritch_altars": {"tiers": {"1": "Divine Orb"}}}, "eldritch_altars.tiers.1"),
            ({"expedition": {"immune_warning": ["fire", None]}}, "expedition.immune_warning"),
            ({"scan_region": {"width_pct": 2.0}}, "scan_region.width_pct"),
            ({"resolution_override": {"enabled": True}}, "resolution_override.width"),
            ({"resolution_override": {"enabled": True, "width": 1920}}, "resolution_override.height"),
        ]
        for payload, field in invalid_payloads:
            with self.subTest(field=field):
                widget, config = self.make_widget()
                self.addCleanup(widget.cleanup)
                original = copy.deepcopy(config["league_vision"])
                original_map_checked = widget.chk_map_safety.isChecked()

                with (
                    self.import_payload(widget, payload),
                    patch("tools.league_vision.tool.ConfigManager.save") as save,
                    patch("tools.league_vision.tool.QMessageBox.warning") as warning,
                ):
                    self.assertFalse(widget.import_settings())

                save.assert_not_called()
                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[1], "Import Failed")
                self.assertIn(field.split(".")[0], warning.call_args.args[2])
                self.assertEqual(config["league_vision"], original)
                self.assertEqual(widget.chk_map_safety.isChecked(), original_map_checked)

    def test_import_success_persists_once_and_applies_live(self):
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        scanner = Mock()
        scanner.isRunning.return_value = True
        widget.scanner = scanner
        payload = {
            "ocr_profile": "fast",
            "ocr_threshold": 111,
            "ocr_advanced": True,
            "scan_interval_mouse": 75,
            "scan_interval_center": 250,
            "ocr_timeout": 2.5,
            "map_check": {"enabled": False, "bad_mods": ["reflect"], "required_context": ["map"]},
            "unknown_future_key": {"preserved": True},
        }

        with (
            self.import_payload(widget, payload),
            patch("tools.league_vision.tool.ConfigManager.save", return_value=True) as save,
        ):
            self.assertTrue(widget.import_settings())

        save.assert_called_once_with(config)
        self.assertEqual(config["league_vision"]["unknown_future_key"], {"preserved": True})
        self.assertEqual(widget.profile_combo.currentText(), "fast")
        self.assertEqual(widget.threshold_spin.value(), 111)
        self.assertFalse(widget.chk_map_safety.isChecked())
        scanner.update_config.assert_called_once()
        self.assertEqual(scanner.update_config.call_args.args[0]["ocr_timeout"], 2.5)

    def test_league_vision_cleanup_false_propagates_to_main_window_cleanup_gate(self):
        from PyQt6.QtWidgets import QLabel
        from tools.league_vision.tool import LeagueVisionTool
        from ui.main_window import MainWindow

        tool = LeagueVisionTool(copy.deepcopy(ConfigManager.DEFAULTS))
        tool.widget = Mock()
        tool.widget.cleanup.return_value = False

        self.assertFalse(tool.cleanup())

        window = MainWindow.__new__(MainWindow)
        window.tools = [tool]
        window.status_label = QLabel()

        self.assertFalse(MainWindow._cleanup_tools_verified(window))
        self.assertIn("aborted", window.status_label.text())

    def test_import_rolls_back_unsaved_replacement_on_save_failure(self):
        import tempfile
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        original = copy.deepcopy(config["league_vision"])
        payload = {"ocr_profile": "fast", "ocr_threshold": 111, "map_check": {"enabled": False}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            import json
            json.dump(payload, handle)
            import_path = handle.name
        self.addCleanup(lambda: os.path.exists(import_path) and os.unlink(import_path))

        with (
            patch("tools.league_vision.tool.QFileDialog.getOpenFileName", return_value=(import_path, "JSON")),
            patch("tools.league_vision.tool.ConfigManager.save", side_effect=ConfigSaveError("readonly")),
        ):
            self.assertFalse(widget.import_settings())

        self.assertEqual(config["league_vision"], original)
        self.assertEqual(widget.profile_combo.currentText(), original.get("ocr_profile", "balanced"))
        self.assertEqual(widget.threshold_spin.value(), original.get("ocr_threshold", 70))

    def test_import_success_synchronizes_controls(self):
        import tempfile
        widget, config = self.make_widget()
        self.addCleanup(widget.cleanup)
        payload = {"ocr_profile": "fast", "ocr_threshold": 111, "map_check": {"enabled": False}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            import json
            json.dump(payload, handle)
            import_path = handle.name
        self.addCleanup(lambda: os.path.exists(import_path) and os.unlink(import_path))

        with (
            patch("tools.league_vision.tool.QFileDialog.getOpenFileName", return_value=(import_path, "JSON")),
            patch("tools.league_vision.tool.ConfigManager.save", return_value=True),
        ):
            self.assertTrue(widget.import_settings())

        self.assertEqual(config["league_vision"]["ocr_profile"], "fast")
        self.assertEqual(widget.profile_combo.currentText(), "fast")
        self.assertEqual(widget.threshold_spin.value(), 111)
        self.assertFalse(widget.chk_map_safety.isChecked())


class LeagueVisionMilestone4ScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_worker(self, config=None):
        from tools.league_vision import scanner as scanner_module

        base = {
            "tesseract_path": "tesseract",
            "active_game": "poe1",
            "ocr_timeout": 1.25,
            "ocr_advanced": True,
            "essence": {"enabled": False},
            "ritual": {"enabled": False},
            "map_check": {"enabled": False},
            "eldritch_altars": {"enabled": True},
            "expedition": {"enabled": False},
            "screen_geometry": {"width": 640, "height": 480},
        }
        if config:
            base.update(config)
        with patch.object(scanner_module, "HAS_KEYBOARD", False), patch.object(scanner_module, "HAS_PYNPUT_KB", False):
            return scanner_module.ScannerWorker(base)

    def test_all_scanner_ocr_calls_use_bounded_timeout_argument(self):
        from tools.league_vision import scanner as scanner_module

        worker = self.make_worker({"ocr_timeout": 2.5})
        image = [[0]]
        scanner_module.pytesseract.Output.DICT = "DICT"
        data = {"text": [""], "left": [0], "top": [0], "width": [1], "height": [1]}

        with patch.object(scanner_module.pytesseract, "image_to_data", return_value=data) as image_to_data:
            worker.process_image(image)
            worker.process_syndicate_ocr(image, image)

        self.assertGreaterEqual(image_to_data.call_count, 5)
        for call in image_to_data.call_args_list:
            self.assertEqual(call.kwargs.get("timeout"), 2.5)

    def test_malformed_altar_tier_keys_are_ignored_not_crashes(self):
        worker = self.make_worker({
            "eldritch_altars": {
                "enabled": True,
                "min_tier_to_highlight": 2,
                "tiers": {"bad": ["Divine Orb"], "1": ["Exalted Orb"], "2": "not-list"},
            }
        })
        warnings = []
        worker.status_signal.connect(warnings.append)

        result = worker.check_eldritch("The altar offers an Exalted Orb and a Divine Orb")

        self.assertEqual(result.message, "ALTAR T1: Exalted Orb")
        self.assertTrue(any("invalid altar tier key" in warning for warning in warnings))
        self.assertTrue(any("rewards must be a list" in warning for warning in warnings))

    def test_exact_game_window_and_process_matching_are_separate(self):
        from tools.league_vision.scanner import (
            exact_window_title_for_game,
            is_exact_poe_process_name,
            is_exact_poe_window_title,
        )

        self.assertEqual(exact_window_title_for_game("poe1"), "Path of Exile")
        self.assertEqual(exact_window_title_for_game("poe2"), "Path of Exile 2")
        self.assertTrue(is_exact_poe_window_title("Path of Exile", "poe1"))
        self.assertFalse(is_exact_poe_window_title("Path of Exile 2", "poe1"))
        self.assertFalse(is_exact_poe_window_title("Path of Exile - broad suffix", "poe1"))
        self.assertTrue(is_exact_poe_process_name("PathOfExile2.exe", "poe2"))
        self.assertFalse(is_exact_poe_process_name("PathOfExile2.exe", "poe1"))


    def test_focus_gate_requires_exact_title_and_process_and_fails_closed(self):
        from tools.league_vision import scanner as scanner_module

        worker = self.make_worker({"active_game": "poe2"})

        with patch.object(
            scanner_module.platform_utils,
            "get_foreground_window_identity",
            return_value={"title": "Path of Exile 2", "process_name": "PathOfExile2.exe", "pid": "123"},
        ):
            self.assertTrue(worker.is_poe_focused())

        bad_identities = [
            {"title": "Path of Exile", "process_name": "PathOfExile2.exe", "pid": "123"},
            {"title": "Path of Exile 2", "process_name": "PathOfExile.exe", "pid": "123"},
            {"title": "", "process_name": "PathOfExile2.exe", "pid": "123"},
            {"title": "Path of Exile 2", "process_name": "", "pid": "123"},
        ]
        for identity in bad_identities:
            with self.subTest(identity=identity), patch.object(
                scanner_module.platform_utils, "get_foreground_window_identity", return_value=identity
            ):
                self.assertFalse(worker.is_poe_focused())

        with patch.object(scanner_module.platform_utils, "get_foreground_window_identity", side_effect=RuntimeError("boom")):
            self.assertFalse(worker.is_poe_focused())

    def test_profiles_and_live_update_apply_expected_intervals(self):
        worker = self.make_worker({"ocr_profile": "low_cpu"})
        self.assertEqual(worker.config["scan_interval_center"], 1000)
        worker.update_config({"ocr_profile": "fast", "active_game": "poe2"})
        self.assertEqual(worker.config["scan_interval_mouse"], 75)
        self.assertEqual(worker.vision.window_title, "Path of Exile 2")

    def test_scanner_cancellation_and_widget_cleanup_request_bounded_shutdown(self):
        worker = self.make_worker()
        worker.running = True
        worker.stop()
        self.assertFalse(worker.running)

        from tools.league_vision.tool import LeagueVisionWidget
        widget = LeagueVisionWidget(copy.deepcopy(ConfigManager.DEFAULTS))
        fake_scanner = Mock()
        fake_scanner.isRunning.return_value = True
        fake_scanner.wait.return_value = True
        widget.scanner = fake_scanner
        self.assertTrue(widget.cleanup())
        fake_scanner.stop.assert_called_once()
        fake_scanner.requestInterruption.assert_called_once()
        fake_scanner.wait.assert_called_once_with(5000)
        self.assertIsNone(widget.scanner)

    def test_widget_stop_scanner_preserves_ownership_on_shutdown_failure(self):
        from tools.league_vision.tool import LeagueVisionWidget
        widget = LeagueVisionWidget(copy.deepcopy(ConfigManager.DEFAULTS))
        self.addCleanup(widget.cleanup)
        fake_scanner = Mock()
        fake_scanner.isRunning.return_value = True
        fake_scanner.wait.return_value = False
        widget.scanner = fake_scanner

        self.assertFalse(widget.stop_scanner())

        self.assertIs(widget.scanner, fake_scanner)
        self.assertFalse(widget.start_btn.isEnabled())
        self.assertTrue(widget.stop_btn.isEnabled())
        self.assertIn("did not stop", widget.log_area.toPlainText())


if __name__ == "__main__":
    unittest.main()
