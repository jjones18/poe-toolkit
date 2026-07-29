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

from PyQt6.QtWidgets import QApplication

from tools.settings_tool import SettingsWidget, fetch_league_options
from ui.main_window import MainWindow
from utils import config as config_module
from utils.workers import CancellationToken

ConfigManager = config_module.ConfigManager


class SettingsOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_config(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_account_credentials(config, "saved-session", "SavedAccount")
        ConfigManager.set_game_league_options(config, "poe1", ["Standard", "Current One"])
        ConfigManager.set_game_league_options(config, "poe2", ["Standard", "Current Two"])
        ConfigManager.set_game_league(config, "poe1", "Current One")
        ConfigManager.set_game_league(config, "poe2", "Current Two")
        ConfigManager.set_client_log_path(config, "/games/poe1/logs/Client.txt", "poe1")
        ConfigManager.set_client_log_path(config, "/games/poe2/logs/Client.txt", "poe2")
        return config

    def test_default_client_log_accessor_follows_active_game(self):
        config = self.make_config()

        ConfigManager.set_active_game(config, "poe2")

        self.assertEqual(
            ConfigManager.get_client_log_path(config),
            "/games/poe2/logs/Client.txt",
        )


    def test_settings_construction_uses_cached_leagues_without_network_refresh(self):
        config = self.make_config()
        with patch.object(SettingsWidget, "fetch_leagues") as fetch:
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)

        fetch.assert_not_called()
        self.assertEqual(widget.league_combo.currentText(), "Current One")
        self.assertEqual(widget.client_log_input.text(), "/games/poe1/logs/Client.txt")

    def test_league_refresh_error_preserves_last_known_selections(self):
        config = self.make_config()
        with patch.object(SettingsWidget, "fetch_leagues"):
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)

        widget.on_league_fetch_error("temporary failure")

        self.assertEqual(widget.league_combo.currentText(), "Current One")
        self.assertIn("temporary failure", widget.status_label.text())

    def test_active_game_switch_swaps_league_and_client_log_without_losing_edits(self):
        widget = SettingsWidget(self.make_config())
        self.addCleanup(widget.close)

        widget.client_log_input.setText("/edited/poe1/Client.txt")
        widget.active_game_combo.setCurrentIndex(
            widget.active_game_combo.findData("poe2")
        )

        self.assertEqual(widget.league_combo.currentText(), "Current Two")
        self.assertEqual(widget.client_log_input.text(), "/games/poe2/logs/Client.txt")
        widget.client_log_input.setText("/edited/poe2/Client.txt")

        widget.active_game_combo.setCurrentIndex(
            widget.active_game_combo.findData("poe1")
        )

        self.assertEqual(widget.league_combo.currentText(), "Current One")
        self.assertEqual(widget.client_log_input.text(), "/edited/poe1/Client.txt")

    def test_reset_to_defaults_is_unsaved_and_preserves_credentials(self):
        config = self.make_config()
        ConfigManager.set_active_game(config, "poe2")
        widget = SettingsWidget(config)
        self.addCleanup(widget.close)
        widget.session_input.setText("edited-session")
        widget.account_input.setText("EditedAccount")
        widget.client_log_input.setText("/edited/poe2/Client.txt")

        self.assertTrue(widget.reset_to_defaults())

        defaults = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.normalize(defaults)
        default_game = ConfigManager.get_active_game(defaults)
        self.assertEqual(widget.active_game_combo.currentData(), default_game)
        self.assertEqual(
            widget.client_log_input.text(),
            ConfigManager.get_client_log_path(defaults, default_game),
        )
        self.assertEqual(widget.session_input.text(), "edited-session")
        self.assertEqual(widget.account_input.text(), "EditedAccount")
        self.assertEqual(ConfigManager.get_active_game(config), "poe2")
        self.assertEqual(
            ConfigManager.get_client_log_path(config, "poe2"),
            "/games/poe2/logs/Client.txt",
        )
        self.assertIn("Save Settings", widget.status_label.text())

    def test_save_persists_independent_client_logs_for_both_games(self):
        config = self.make_config()
        widget = SettingsWidget(config)
        self.addCleanup(widget.close)
        widget.client_log_input.setText("/edited/poe1/Client.txt")
        widget.active_game_combo.setCurrentIndex(
            widget.active_game_combo.findData("poe2")
        )
        widget.client_log_input.setText("/edited/poe2/Client.txt")

        with patch.object(ConfigManager, "save", return_value=True):
            self.assertTrue(widget.save_settings())

        self.assertEqual(
            ConfigManager.get_client_log_path(config, "poe1"),
            "/edited/poe1/Client.txt",
        )
        self.assertEqual(
            ConfigManager.get_client_log_path(config, "poe2"),
            "/edited/poe2/Client.txt",
        )

    def test_league_refresh_uses_bounded_shared_worker(self):
        config = self.make_config()
        widget = SettingsWidget(config)
        registry = Mock()
        registry.start.return_value = True
        widget._worker_registry = registry
        self.addCleanup(widget.close)

        widget.fetch_leagues()

        self.assertFalse(widget.refresh_leagues_btn.isEnabled())
        registry.start.assert_called_once()
        self.assertEqual(registry.start.call_args.args[0], "league-refresh")
        self.assertEqual(
            registry.start.call_args.kwargs["on_result"],
            widget.on_leagues_fetched,
        )

    def test_settings_cleanup_cancels_and_waits_for_refresh(self):
        widget = SettingsWidget(self.make_config())
        registry = Mock()
        registry.close.return_value = True
        widget._worker_registry = registry

        widget.cleanup()

        registry.close.assert_called_once_with(timeout_ms=20_000)

    def test_league_fetch_operation_uses_request_timeout_and_progress(self):
        responses = []
        for league in ("League One", "League Two"):
            response = Mock()
            response.json.return_value = {"result": [{"id": league}]}
            response.raise_for_status = Mock()
            responses.append(response)
        session = Mock()
        session.request.side_effect = responses
        context = Mock()
        context.token = CancellationToken()

        result = fetch_league_options(context, session=session)

        self.assertEqual(result, {"poe1": ["League One"], "poe2": ["League Two"]})
        self.assertEqual(session.request.call_count, 2)
        for invocation in session.request.call_args_list:
            self.assertEqual(invocation.kwargs["timeout"], (5.0, 10.0))
        self.assertEqual(context.report_progress.call_count, 2)
        session.close.assert_not_called()

    def test_league_fetch_closes_internally_owned_session_on_failure(self):
        context = Mock()
        context.token = CancellationToken()
        owned_session = Mock()
        owned_session.request.side_effect = RuntimeError("temporary failure")

        with patch("tools.settings_tool.requests.Session", return_value=owned_session):
            with self.assertRaisesRegex(RuntimeError, "temporary failure"):
                fetch_league_options(context)

        owned_session.close.assert_called_once_with()

    def test_shared_settings_owner_is_synchronized_after_dependent_widgets(self):
        calls = []
        dependent = Mock()
        dependent.owns_shared_settings = False
        dependent.sync_config.side_effect = lambda: calls.append("dependent")
        owner = Mock()
        owner.owns_shared_settings = True
        owner.sync_config.side_effect = lambda: calls.append("owner")

        ordered = MainWindow._ordered_config_widgets([owner, dependent])
        for widget in ordered:
            widget.sync_config()

        self.assertEqual(calls, ["dependent", "owner"])

    def test_settings_save_refreshes_dependent_shared_setting_views(self):
        settings_owner = Mock()
        dependent = Mock()

        MainWindow._refresh_shared_settings_views([settings_owner, dependent])

        settings_owner.refresh_shared_settings.assert_called_once_with()
        dependent.refresh_shared_settings.assert_called_once_with()

    def test_settings_save_failure_is_visible_and_does_not_emit_success(self):
        config = self.make_config()
        original = copy.deepcopy(config)
        with patch.object(SettingsWidget, "fetch_leagues"):
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)
        saved = Mock()
        widget.settings_saved.connect(saved)
        widget.account_input.setText("UnsavedAccount")
        widget.active_game_combo.setCurrentIndex(
            widget.active_game_combo.findData("poe2")
        )
        widget.client_log_input.setText("/unsaved/poe2/Client.txt")

        with patch.object(
            ConfigManager,
            "save",
            side_effect=config_module.ConfigSaveError("simulated disk failure"),
        ):
            widget.save_settings()

        self.assertIn("save failed", widget.status_label.text().lower())
        self.assertIn("simulated disk failure", widget.status_label.text().lower())
        self.assertEqual(config, original)
        saved.assert_not_called()


if __name__ == "__main__":
    unittest.main()
