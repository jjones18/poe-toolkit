import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtWidgets import QApplication

from tools.trade_sniper.tool import (
    TradeSniperWidget,
    evaluate_devtools_readiness,
    get_trade_profile_dir,
    prepare_trade_profile_dir,
)
from utils.config import ConfigManager, ConfigSaveError

ORIGINAL_CHECK_SETUP = TradeSniperWidget.check_setup


class TradeSniperSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = copy.deepcopy(ConfigManager.DEFAULTS)
        self.config["trade_sniper"].update(
            auto_resume=True,
            auto_resume_delay_ms=75_000,
            cooldown_ms=6_000,
            check_interval_ms=10,
            confirmation_retry_ms=20,
            zone_gate_enabled=True,
        )
        ConfigManager.set_client_log_path(
            self.config,
            "/games/Path of Exile/logs/Client.txt",
            "poe1",
        )
        setup_patch = patch.object(TradeSniperWidget, "check_setup")
        brave_patch = patch.object(TradeSniperWidget, "check_brave_status")
        self.addCleanup(setup_patch.stop)
        self.addCleanup(brave_patch.stop)
        setup_patch.start()
        brave_patch.start()
        self.widget = TradeSniperWidget(self.config)
        self.addCleanup(self.widget.brave_check_timer.stop)
        self.addCleanup(self.widget.close)

    def test_timing_controls_load_saved_values(self):
        self.assertTrue(self.widget.chk_auto_resume.isChecked())
        self.assertEqual(self.widget.auto_resume_delay_spin.value(), 75)
        self.assertEqual(self.widget.cooldown_spin.value(), 6)
        self.assertTrue(self.widget.chk_zone_gate.isChecked())

    def test_fresh_defaults_enable_auto_resume_at_30_seconds(self):
        fresh_config = copy.deepcopy(ConfigManager.DEFAULTS)
        widget = TradeSniperWidget(fresh_config)
        self.addCleanup(widget.brave_check_timer.stop)
        self.addCleanup(widget.close)

        self.assertTrue(widget.chk_auto_resume.isChecked())
        self.assertEqual(widget.auto_resume_delay_spin.value(), 30)
        self.assertTrue(widget.chk_zone_gate.isChecked())

    @patch.object(ConfigManager, "save")
    def test_zone_gate_toggle_persists_locally(self, save):
        self.widget.chk_zone_gate.setChecked(False)

        self.assertFalse(self.config["trade_sniper"]["zone_gate_enabled"])
        save.assert_called_once_with(self.config)

    @patch.object(ConfigManager, "save")
    def test_timing_changes_persist_and_update_running_service(self, save):
        self.widget.is_service_running = True
        self.widget.service.send_input = Mock()

        self.widget.auto_resume_delay_spin.setValue(45)
        self.widget.cooldown_spin.setValue(8)
        self.widget.chk_auto_resume.setChecked(False)

        self.assertFalse(self.config["trade_sniper"]["auto_resume"])
        self.assertEqual(self.config["trade_sniper"]["auto_resume_delay_ms"], 45_000)
        self.assertEqual(self.config["trade_sniper"]["cooldown_ms"], 8_000)
        self.assertEqual(
            self.widget.service.send_input.call_args_list,
            [
                call("__auto_resume_delay__:45\n"),
                call("__cooldown__:8\n"),
                call("__auto_resume__:off\n"),
            ],
        )
        self.assertEqual(save.call_count, 3)

    def test_setting_save_failure_is_visible_in_status_and_log(self):
        with patch.object(
            ConfigManager,
            "save",
            side_effect=ConfigSaveError("simulated disk failure"),
        ):
            saved = self.widget._save_trade_setting("cooldown_ms", 9_000)

        self.assertFalse(saved)
        self.assertIn("config save failed", self.widget.status_label.text().lower())
        self.assertIn("simulated disk failure", self.widget.log_area.toPlainText().lower())

    def test_setting_save_failure_does_not_apply_live_service_update(self):
        self.widget.is_service_running = True
        self.widget.service.send_input = Mock()

        with patch.object(
            ConfigManager,
            "save",
            side_effect=ConfigSaveError("simulated disk failure"),
        ):
            self.widget.cooldown_spin.setValue(9)

        self.widget.service.send_input.assert_not_called()

    def test_start_passes_current_auto_resume_delay(self):
        self.widget.service.start = Mock()
        self.widget.is_service_running = False

        self.widget.on_start_resume_click()

        self.widget.service.start.assert_called_once_with(
            auto_resume=True,
            auto_resume_delay_s=75,
            cooldown_s=6,
            poll_interval_ms=10,
            confirmation_retry_ms=20,
            game_id="poe1",
            zone_gate_enabled=True,
            client_log_path="/games/Path of Exile/logs/Client.txt",
        )

    def test_failed_cleanup_restores_timer_and_keeps_service_connections(self):
        registry = Mock()
        registry.close.return_value = False
        timer = Mock()
        timer.isActive.return_value = True
        self.widget._worker_registry = registry
        self.widget.brave_check_timer = timer
        self.widget.service = Mock()

        cleaned = self.widget.cleanup()

        self.assertFalse(cleaned)
        timer.stop.assert_called_once_with()
        timer.start.assert_called_once_with()
        self.widget.service.status_changed.disconnect.assert_not_called()
        self.widget.service.log_output.disconnect.assert_not_called()

    def test_start_requires_verified_devtools_trade_tab(self):
        self.widget.node_ok = True
        self.widget.deps_ok = True
        self.widget.brave_ready = False
        self.widget.update_start_button_state()
        self.assertFalse(self.widget.start_btn.isEnabled())

        self.widget.brave_ready = True
        self.widget.update_start_button_state()
        self.assertTrue(self.widget.start_btn.isEnabled())

    def test_dependency_check_is_submitted_to_background_worker(self):
        self.widget._start_background_task = Mock(return_value=True)

        ORIGINAL_CHECK_SETUP(self.widget)

        task_name, operation, _callback = self.widget._start_background_task.call_args.args
        self.assertEqual(task_name, "dependency-check")
        self.assertEqual(operation, self.widget.service.check_dependencies)

    def test_install_is_submitted_to_background_worker(self):
        self.widget._start_background_task = Mock(return_value=True)

        self.widget.install_dependencies()

        task_name, operation, _callback = self.widget._start_background_task.call_args.args
        self.assertEqual(task_name, "npm-install")
        self.assertEqual(operation, self.widget.service.install_dependencies)

    def test_stop_is_submitted_to_background_worker(self):
        self.widget._start_background_task = Mock(return_value=True)
        self.widget.service.stop = Mock(return_value=True)
        self.widget.is_service_running = True

        self.widget.stop_service()

        task_name, operation, _callback = self.widget._start_background_task.call_args.args
        self.assertEqual(task_name, "service-stop")
        self.assertEqual(operation, self.widget.service.stop)
        self.widget.service.stop.assert_not_called()

    def test_background_task_uses_shared_registry(self):
        registry = Mock()
        registry.start.return_value = True
        self.widget._worker_registry = registry
        operation = Mock(return_value="done")
        on_result = Mock()

        started = self.widget._start_background_task("dependency-check", operation, on_result)

        self.assertTrue(started)
        registry.start.assert_called_once()
        args = registry.start.call_args.args
        self.assertEqual(args[0], "dependency-check")
        context = Mock()
        self.assertEqual(args[1](context), "done")
        operation.assert_called_once_with(context.token)
        self.assertIs(registry.start.call_args.kwargs["on_result"], on_result)

    def test_cleanup_cancels_and_waits_for_shared_workers(self):
        registry = Mock()
        registry.close.return_value = True
        self.widget._worker_registry = registry

        self.widget.cleanup()

        registry.close.assert_called_once_with(timeout_ms=20_000)


class DevToolsReadinessTests(unittest.TestCase):
    def test_unrelated_listener_metadata_is_not_ready(self):
        ready, status = evaluate_devtools_readiness({}, [], "https://www.pathofexile.com/trade")
        self.assertFalse(ready)
        self.assertIn("not a DevTools", status)

    def test_browser_without_compatible_trade_tab_is_not_ready(self):
        version = {
            "Browser": "Chrome/140",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc",
        }
        targets = [{"type": "page", "url": "https://www.pathofexile.com/trade2/search/Standard"}]

        ready, status = evaluate_devtools_readiness(
            version, targets, "https://www.pathofexile.com/trade"
        )

        self.assertFalse(ready)
        self.assertIn("compatible trade tab", status)

    def test_matching_game_trade_tab_is_ready(self):
        version = {
            "Browser": "Brave/140",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc",
        }
        targets = [{"type": "page", "url": "https://www.pathofexile.com/trade2/search/Standard/abc"}]

        ready, status = evaluate_devtools_readiness(
            version, targets, "https://www.pathofexile.com/trade2"
        )

        self.assertTrue(ready)
        self.assertIn("trade tab ready", status)


class TradeProfilePathTests(unittest.TestCase):
    def test_linux_profile_uses_xdg_user_data_directory(self):
        profile = get_trade_profile_dir(
            platform_name="linux",
            environ={"XDG_DATA_HOME": "/tmp/user-data"},
            home=Path("/home/tester"),
        )

        self.assertEqual(profile, Path("/tmp/user-data/poe-toolkit/brave-profile"))

    def test_legacy_profile_is_moved_once_to_user_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "repo" / "brave-profile"
            target = root / "user-data" / "brave-profile"
            legacy.mkdir(parents=True)
            (legacy / "login-marker").write_text("preserved", encoding="utf-8")

            selected = prepare_trade_profile_dir(target, legacy)

            self.assertEqual(selected, target)
            self.assertEqual((target / "login-marker").read_text(encoding="utf-8"), "preserved")
            self.assertFalse(legacy.exists())

    def test_failed_migration_keeps_using_untouched_legacy_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "repo" / "brave-profile"
            target = root / "user-data" / "brave-profile"
            legacy.mkdir(parents=True)
            marker = legacy / "login-marker"
            marker.write_text("preserved", encoding="utf-8")

            with patch("tools.trade_sniper.tool.shutil.move", side_effect=OSError("busy")):
                selected = prepare_trade_profile_dir(target, legacy)

            self.assertEqual(selected, legacy)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserved")


if __name__ == "__main__":
    unittest.main()
