import copy
import os
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from tools.crafting.controller import CraftingController
from tools.crafting.hotkeys import CraftingHotkeys
from tools.crafting.layout import (
    derive_currency_points,
    resolve_currency_points,
    resolve_currency_targets,
)
from tools.crafting.models import CraftingGoal, CraftingMode, ScreenPoint
from tools.crafting.tool import CraftingWidget
from tools.crafting.parser import (
    ClipboardParseError,
    goal_is_met,
    parse_poe1_currency_stack,
    parse_poe1_socket_state,
)
from ui.calibration import CalibrationManager, CalibrationType
from utils.config import ConfigManager
from services.game_input_service import InputCapability, WindowRelativePoint


ITEM_4L_6S = """Item Class: Body Armours
Rarity: Rare
Dragon Hide
Bronze Plate
--------
Sockets: W-W-W-W W W 
--------
Item Level: 55
"""
ITEM_5L = """Item Class: Body Armours
Rarity: Rare
Test Plate
--------
Sockets: R-R-R-R-R G
--------
"""
ITEM_6L = """Item Class: Body Armours
Rarity: Rare
Test Plate
--------
Sockets: R-R-R-R-R-R
--------
"""
JEWELLERS_840 = """Item Class: Stackable Currency
Rarity: Currency
Jeweller's Orb
--------
Stack Size: 840/20
--------
Reforges the number of sockets on an item
"""


class CraftingHotkeyTests(unittest.TestCase):
    def test_exact_evdev_keypad_codes_do_not_match_main_keyboard_symbols(self):
        self.assertTrue(
            CraftingHotkeys._matches_evdev("KEY_KPPLUS", "Numpad Plus")
        )
        self.assertTrue(
            CraftingHotkeys._matches_evdev("KEY_KPMINUS", "Numpad Minus")
        )
        self.assertFalse(
            CraftingHotkeys._matches_evdev("KEY_EQUAL", "Numpad Plus")
        )
        self.assertFalse(
            CraftingHotkeys._matches_evdev("KEY_MINUS", "Numpad Minus")
        )

    def test_evdev_keypad_press_emits_configured_action_only(self):
        hotkeys = CraftingHotkeys()
        actions = []
        hotkeys.triggered.connect(actions.append)

        hotkeys._on_evdev_press("KEY_EQUAL")
        hotkeys._on_evdev_press("KEY_KPPLUS")
        hotkeys._on_evdev_press("KEY_KPMINUS")

        self.assertEqual(actions, ["start", "stop"])

    def test_wayland_uses_exact_evdev_listener(self):
        hotkeys = CraftingHotkeys()
        listener = Mock()
        listener.start.return_value = None
        availability = []
        hotkeys.availability_changed.connect(
            lambda available, detail: availability.append((available, detail))
        )

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}), patch(
            "tools.crafting.hotkeys.EvdevKeyboardListener",
            return_value=listener,
        ) as listener_class:
            self.assertTrue(hotkeys.start())

        listener_class.assert_called_once()
        listener.start.assert_called_once_with()
        self.assertTrue(availability[-1][0])
        self.assertIn("evdev", availability[-1][1])

        hotkeys.stop()
        listener.stop.assert_called_once_with()


class CraftingParserTests(unittest.TestCase):
    def test_real_six_socket_four_link_fixture(self):
        state = parse_poe1_socket_state(ITEM_4L_6S)
        self.assertEqual(state.socket_count, 6)
        self.assertEqual(state.max_link_group, 4)
        self.assertEqual(state.raw_sockets_line, "W-W-W-W W W")

    def test_five_and_six_link_groups(self):
        five = parse_poe1_socket_state(ITEM_5L)
        six = parse_poe1_socket_state(ITEM_6L)
        self.assertEqual((five.socket_count, five.max_link_group), (6, 5))
        self.assertEqual((six.socket_count, six.max_link_group), (6, 6))
        self.assertTrue(goal_is_met(six, CraftingMode.LINKS, 5))
        self.assertTrue(goal_is_met(five, CraftingMode.LINKS, 5))
        self.assertFalse(goal_is_met(five, CraftingMode.LINKS, 6))

    def test_real_jewellers_stack_fixture(self):
        state = parse_poe1_currency_stack(JEWELLERS_840, "Jeweller's Orb")
        self.assertEqual(state.stack_count, 840)
        self.assertEqual(state.stack_limit, 20)

    def test_wrong_currency_and_missing_sockets_fail_closed(self):
        with self.assertRaises(ClipboardParseError):
            parse_poe1_currency_stack(JEWELLERS_840, "Orb of Fusing")
        with self.assertRaises(ClipboardParseError):
            parse_poe1_socket_state("Item Class: Body Armours\nRarity: Rare")


class CurrencyLayoutTests(unittest.TestCase):
    def test_bounds_scale_all_points_and_override_one(self):
        bounds = {"x": 100, "y": 200, "width": 1000, "height": 800}
        points = derive_currency_points(bounds)
        self.assertEqual(points["jewellers_orb"], ScreenPoint(261, 534))
        self.assertEqual(points["orb_of_fusing"], ScreenPoint(351, 534))
        self.assertEqual(points["crafting_item"], ScreenPoint(620, 613))

        points = derive_currency_points(bounds, {"orb_of_fusing": {"x": 999, "y": 777}})
        self.assertEqual(points["orb_of_fusing"], ScreenPoint(999, 777))
        self.assertEqual(points["jewellers_orb"], ScreenPoint(261, 534))

    def test_missing_or_too_small_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            resolve_currency_points({}, "poe1")
        with self.assertRaises(ValueError):
            derive_currency_points({"x": 0, "y": 0, "width": 200, "height": 200})


class CraftingCalibrationTests(unittest.TestCase):
    def test_bounds_and_point_override_save_in_poe1_profile(self):
        config = {}
        save = Mock()
        manager = CalibrationManager(config, save_callback=save)

        manager.start_calibration(CalibrationType.CURRENCY_TAB_BOUNDS, game_id="poe1")
        manager.handle_click(1010, 520)
        manager.handle_click(1810, 1420)
        result = {
            "x": 1010, "y": 520, "x2": 1810, "y2": 1420,
            "width": 800, "height": 900,
            "game_id": "poe1", "layout_id": "poe1_currency_general_v1",
            "window_rect": {"left": 1000, "top": 500, "width": 3440, "height": 1440},
        }
        manager.confirm_calibration(result)

        manager.start_calibration(
            CalibrationType.CRAFTING_POINT,
            game_id="poe1",
            point_role="jewellers_orb",
            point_label="Jeweller's Orb",
        )
        manager.confirm_calibration({
            "x": 1123, "y": 956, "game_id": "poe1",
            "point_role": "jewellers_orb", "point_label": "Jeweller's Orb",
            "window_rect": {"left": 1000, "top": 500, "width": 3440, "height": 1440},
        })

        profile = config["calibration"]["currency_tab_profiles"]["poe1"]
        self.assertEqual(profile["bounds"]["width"], 800)
        self.assertEqual(profile["overrides"]["jewellers_orb"], {"x": 123, "y": 456})
        self.assertEqual(profile["coordinate_space"], "game_window")
        self.assertEqual(profile["reference_window"], {"width": 3440, "height": 1440})
        self.assertEqual(save.call_count, 2)

        manager.start_calibration(CalibrationType.CURRENCY_TAB_BOUNDS, game_id="poe1")
        manager.confirm_calibration({
            "x": 1020, "y": 530, "x2": 1820, "y2": 1430,
            "width": 800, "height": 900,
            "game_id": "poe1", "layout_id": "poe1_currency_general_v1",
            "window_rect": {"left": 1000, "top": 500, "width": 3440, "height": 1440},
        })
        self.assertEqual(profile["overrides"], {})
        self.assertEqual(save.call_count, 3)

    def test_failed_save_rolls_back_currency_calibration(self):
        config = {"unchanged": {"value": 1}}
        manager = CalibrationManager(config, save_callback=lambda: False)
        manager.start_calibration(
            CalibrationType.CURRENCY_TAB_BOUNDS,
            game_id="poe1",
        )
        result = {
            "x": 1020,
            "y": 530,
            "x2": 1820,
            "y2": 1430,
            "width": 800,
            "height": 900,
            "game_id": "poe1",
            "layout_id": "poe1_currency_general_v1",
            "window_rect": {
                "left": 1000,
                "top": 500,
                "width": 3440,
                "height": 1440,
            },
        }

        self.assertFalse(manager.confirm_calibration(result))
        self.assertEqual(config, {"unchanged": {"value": 1}})
        self.assertFalse(manager.is_active())

    def test_window_relative_targets_keep_reference_resolution(self):
        config = {
            "calibration": {
                "currency_tab_profiles": {
                    "poe1": {
                        "coordinate_space": "game_window",
                        "reference_window": {"width": 3440, "height": 1440},
                        "bounds": {"x": 100, "y": 200, "width": 1000, "height": 800},
                        "overrides": {},
                    }
                }
            }
        }
        targets = resolve_currency_targets(config, "poe1")
        self.assertEqual(
            targets["jewellers_orb"],
            WindowRelativePoint(261, 534, 3440, 1440),
        )

    def test_single_point_click_completes_in_one_step(self):
        manager = CalibrationManager({})
        complete = Mock()
        manager.on_complete = complete
        manager.start_calibration(
            CalibrationType.CRAFTING_POINT,
            game_id="poe1",
            point_role="crafting_item",
            point_label="Crafting Item",
        )
        self.assertIsNone(manager.handle_click(500, 600))
        complete.assert_called_once()
        self.assertEqual(complete.call_args.args[1]["point_role"], "crafting_item")


class FakeInput:
    def __init__(self):
        self.calls = []

    def move_to(self, point): self.calls.append(("move", point))
    def right_click(self, point): self.calls.append(("right", point))
    def shift_left_click(self, point): self.calls.append(("shift-left", point))
    def copy(self): self.calls.append(("copy",))
    def copy_at(self, point): self.calls.append(("copy-at", point))
    def cancel_selection(self): self.calls.append(("escape",))
    def release_all(self): self.calls.append(("release",))


class CraftingWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_poe2_page_is_visible_but_all_input_controls_are_disabled(self):
        widget = CraftingWidget({"app": {"active_game": "poe2"}})
        self.assertFalse(widget.setup_toggle.isEnabled())
        self.assertFalse(widget.advanced_toggle.isEnabled())
        self.assertFalse(widget.calibrate_bounds_button.isEnabled())
        self.assertFalse(widget.action_combo.isEnabled())
        self.assertFalse(widget.start_hotkey.isEnabled())
        self.assertFalse(widget.verify_only.isEnabled())
        self.assertIn("PoE 2 crafting is not enabled", widget.status_label.text())
        widget.activate()
        self.assertIsNone(widget.hotkeys.listener)
        widget.cleanup()

    def test_preview_targets_does_not_prepare_or_request_input(self):
        config = {
            "app": {"active_game": "poe1"},
            "calibration": {
                "currency_tab_profiles": {
                    "poe1": {
                        "coordinate_space": "game_window",
                        "reference_window": {"width": 3440, "height": 1440},
                        "bounds": {"x": 100, "y": 200, "width": 1000, "height": 800},
                        "overrides": {},
                    }
                }
            },
        }
        input_service = Mock()
        input_service.capability.return_value = InputCapability(True, "kwin-eis", "available")
        received = []
        widget = CraftingWidget(config, game_input_service=input_service)
        widget.target_preview_requested.connect(
            lambda game_id, targets: received.append((game_id, targets))
        )

        widget._preview_targets()

        self.assertEqual(received[0][0], "poe1")
        self.assertIsInstance(received[0][1]["crafting_item"], WindowRelativePoint)
        input_service.prepare.assert_not_called()
        input_service.session.assert_not_called()
        widget.cleanup()

    def test_currency_layout_buttons_are_readable_at_narrow_tool_width(self):
        input_service = Mock()
        input_service.capability.return_value = InputCapability(
            True, "kwin-eis", "available"
        )
        widget = CraftingWidget(
            {"app": {"active_game": "poe1"}},
            game_input_service=input_service,
        )
        widget.setFixedWidth(700)
        widget.resize(700, 800)
        widget.show()
        widget.setup_toggle.setChecked(True)
        self.app.processEvents()
        self.assertEqual(widget.width(), 700)

        buttons = [
            widget.calibrate_bounds_button,
            *widget.override_buttons.values(),
            widget.preview_targets_button,
            widget.clear_preview_button,
        ]
        for button in buttons:
            self.assertGreaterEqual(
                button.width(),
                button.sizeHint().width(),
                f"clipped button: {button.text()}",
            )

        widget.close()
        widget.cleanup()

    def test_normal_view_keeps_safety_controls_visible_and_details_collapsed(self):
        input_service = Mock()
        input_service.capability.return_value = InputCapability(
            True,
            "kwin-eis",
            "available",
        )
        widget = CraftingWidget(
            {"app": {"active_game": "poe1"}},
            game_input_service=input_service,
        )
        widget.resize(700, 800)
        widget.show()
        self.app.processEvents()

        for control in (
            widget.action_combo,
            widget.target_spin,
            widget.verify_only,
            widget.unlimited_check,
            widget.max_attempts,
            widget.runtime_summary,
            widget.status_label,
            widget.stop_button,
        ):
            self.assertTrue(control.isVisible(), control.objectName())

        self.assertFalse(widget.calibration_group.isVisible())
        self.assertFalse(widget.advanced_group.isVisible())
        self.assertFalse(widget.log_output.isVisible())
        self.assertIn("Input ready: kwin-eis", widget.runtime_summary.text())
        self.assertIn("Stop Numpad Minus", widget.runtime_summary.text())

        widget._log("Hidden diagnostic remains available")
        self.assertFalse(widget.log_output.isVisible())
        self.assertEqual(
            widget.status_label.text(),
            "Hidden diagnostic remains available",
        )
        self.assertIn(
            "Hidden diagnostic remains available",
            widget.log_output.toPlainText(),
        )

        widget.setup_toggle.setChecked(True)
        widget.advanced_toggle.setChecked(True)
        widget.log_toggle.setChecked(True)
        self.app.processEvents()
        self.assertTrue(widget.calibration_group.isVisible())
        self.assertTrue(widget.advanced_group.isVisible())
        self.assertTrue(widget.log_output.isVisible())

        widget.close()
        widget.cleanup()


class CraftingControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_controller(self):
        fake = FakeInput()
        controller = CraftingController(input_factory=lambda: fake)
        controller.input = fake
        controller.points = {
            "jewellers_orb": ScreenPoint(1, 2),
            "orb_of_fusing": ScreenPoint(3, 4),
            "crafting_item": ScreenPoint(5, 6),
        }
        controller.running = True
        return controller, fake

    def test_verification_only_preflight_never_clicks(self):
        controller, fake = self.make_controller()
        controller.goal = CraftingGoal(CraftingMode.SOCKETS, 6, verify_only=True)
        controller._copy_at = lambda _point, callback: callback(ITEM_4L_6S)
        results = []
        controller.completed.connect(results.append)

        controller._on_currency_copied(JEWELLERS_840, "Jeweller's Orb")

        self.assertTrue(results[0].success)
        self.assertIn("without spending", results[0].reason)
        self.assertFalse(any(call[0] in {"right", "shift-left"} for call in fake.calls))

    def test_copy_waits_until_exact_clipboard_sentinel_is_visible(self):
        controller, fake = self.make_controller()
        point = ScreenPoint(3, 4)
        scheduled = []
        clipboard = QApplication.clipboard()
        clipboard.setText("old clipboard")

        with patch.object(controller, "_is_poe_focused", return_value=True), patch.object(
            controller, "_publish_clipboard_sentinel"
        ), patch.object(
            controller,
            "_schedule",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            controller._copy_at(point, lambda _text: None)
            self.assertNotIn(("copy-at", point), fake.calls)

            clipboard.setText(controller._clipboard_sentinel)
            scheduled.pop(0)()

        self.assertIn(("copy-at", point), fake.calls)

    def test_kde_wayland_publishes_probe_sentinel_through_klipper(self):
        controller, _fake = self.make_controller()
        controller._clipboard_sentinel = "__EXACT_SENTINEL__"
        clipboard = Mock()

        with patch.dict(
            os.environ,
            {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_CURRENT_DESKTOP": "KDE",
            },
            clear=False,
        ), patch(
            "tools.crafting.controller.shutil.which",
            side_effect=lambda name: (
                "/usr/bin/qdbus6" if name == "qdbus6" else None
            ),
        ), patch(
            "tools.crafting.controller.subprocess.run"
        ) as run:
            controller._publish_clipboard_sentinel(clipboard)

        clipboard.setText.assert_not_called()
        self.assertEqual(run.call_args.args[0][-1], "__EXACT_SENTINEL__")

    def test_link_preflight_rejects_item_with_too_few_sockets(self):
        controller, _fake = self.make_controller()
        controller.goal = CraftingGoal(CraftingMode.LINKS, 6)
        results = []
        controller.completed.connect(results.append)
        controller._on_item_preflight("Sockets: R-R-R-R-R")
        self.assertFalse(results[0].success)
        self.assertIn("requires at least 6 sockets", results[0].reason)

    def test_each_counted_attempt_reselects_currency_and_leaves_no_held_state(self):
        controller, fake = self.make_controller()
        controller.goal = CraftingGoal(
            CraftingMode.SOCKETS,
            4,
            max_attempts=3,
        )
        controller.currency_count = 10
        controller.attempts = 0
        scheduled = []

        with patch.object(controller, "_ensure_active", return_value=True), patch.object(
            controller,
            "_schedule",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            controller._apply_once()
            controller._apply_once()

        self.assertEqual(
            fake.calls,
            [
                ("right", controller.points["jewellers_orb"]),
                ("shift-left", controller.points["crafting_item"]),
                ("right", controller.points["jewellers_orb"]),
                ("shift-left", controller.points["crafting_item"]),
            ],
        )
        self.assertEqual(controller.attempts, 2)
        self.assertFalse(controller._currency_selected)

        with patch.object(controller, "_is_poe_focused", return_value=True):
            controller._finish(False, "bounded stop")
        self.assertNotIn(("escape",), fake.calls)

    def test_unchanged_currency_stack_stops_before_another_attempt(self):
        controller, fake = self.make_controller()
        controller.goal = CraftingGoal(
            CraftingMode.SOCKETS,
            4,
            max_attempts=3,
        )
        controller.currency_count = 840
        controller.attempts = 1
        probes = []
        results = []
        controller.completed.connect(results.append)
        controller._copy_at = lambda point, callback: probes.append((point, callback))

        controller._on_item_after_apply("Sockets: B W W")

        self.assertEqual(probes[0][0], controller.points["jewellers_orb"])
        probes[0][1](JEWELLERS_840)
        self.assertFalse(results[0].success)
        self.assertIn("did not decrease", results[0].reason)
        self.assertEqual(fake.calls, [("release",)])

    def test_budget_stop_requires_confirmed_currency_decrement(self):
        controller, fake = self.make_controller()
        controller.goal = CraftingGoal(
            CraftingMode.SOCKETS,
            4,
            max_attempts=3,
        )
        controller.currency_count = 840
        controller.attempts = 3
        probes = []
        results = []
        controller.completed.connect(results.append)
        controller._copy_at = lambda point, callback: probes.append((point, callback))

        controller._on_item_after_apply("Sockets: B W W")
        probes[0][1](JEWELLERS_840.replace("840/20", "837/20"))

        self.assertFalse(results[0].success)
        self.assertIn("3 confirmed application", results[0].reason)
        self.assertEqual(results[0].final_state.socket_count, 3)
        self.assertEqual(fake.calls, [("release",)])

    def test_start_fails_when_exact_game_window_is_not_focused(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        points = derive_currency_points({"x": 0, "y": 0, "width": 800, "height": 800})
        controller = CraftingController(input_factory=FakeInput)
        messages = []
        controller.status_changed.connect(messages.append)
        with patch.object(controller, "_is_poe_focused", return_value=False):
            started = controller.start(CraftingGoal(CraftingMode.SOCKETS, 6), points)
        self.assertFalse(started)
        self.assertIn("not focused", messages[-1])

    def test_delayed_callback_from_stopped_run_cannot_enter_new_run(self):
        controller, _fake = self.make_controller()
        callbacks = []
        fired = []
        with patch.object(QTimer, "singleShot", side_effect=lambda _delay, cb: callbacks.append(cb)):
            controller._schedule(20, lambda: fired.append("stale"))
        controller._finish(False, "stop")
        controller.running = True
        controller._run_generation += 1
        callbacks[0]()
        self.assertEqual(fired, [])

    def test_finish_clears_held_currency_only_while_poe_is_focused(self):
        controller, fake = self.make_controller()
        controller._currency_selected = True
        with patch.object(controller, "_is_poe_focused", return_value=True):
            controller._finish(True, "done")
        self.assertIn(("escape",), fake.calls)

        controller, fake = self.make_controller()
        controller._currency_selected = True
        results = []
        controller.completed.connect(results.append)
        with patch.object(controller, "_is_poe_focused", return_value=False):
            controller._finish(False, "lost focus")
        self.assertNotIn(("escape",), fake.calls)
        self.assertIn("press Escape before clicking", results[0].reason)


if __name__ == "__main__":
    unittest.main()
