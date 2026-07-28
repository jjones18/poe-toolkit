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

from tools.settings_tool import SettingsWidget
from ui.main_window import MainWindow
from utils import config as config_module

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
        return config

    def test_settings_construction_uses_cached_leagues_without_network_refresh(self):
        config = self.make_config()
        with patch.object(SettingsWidget, "fetch_leagues") as fetch:
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)

        fetch.assert_not_called()
        self.assertEqual(widget.poe1_league_combo.currentText(), "Current One")
        self.assertEqual(widget.poe2_league_combo.currentText(), "Current Two")

    def test_league_refresh_error_preserves_last_known_selections(self):
        config = self.make_config()
        with patch.object(SettingsWidget, "fetch_leagues"):
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)

        widget.on_league_fetch_error("temporary failure")

        self.assertEqual(widget.poe1_league_combo.currentText(), "Current One")
        self.assertEqual(widget.poe2_league_combo.currentText(), "Current Two")
        self.assertIn("temporary failure", widget.status_label.text())

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
        with patch.object(SettingsWidget, "fetch_leagues"):
            widget = SettingsWidget(config)
            self.addCleanup(widget.close)
        saved = Mock()
        widget.settings_saved.connect(saved)

        with patch.object(
            ConfigManager,
            "save",
            side_effect=config_module.ConfigSaveError("simulated disk failure"),
        ):
            widget.save_settings()

        self.assertIn("save failed", widget.status_label.text().lower())
        self.assertIn("simulated disk failure", widget.status_label.text().lower())
        saved.assert_not_called()


if __name__ == "__main__":
    unittest.main()
