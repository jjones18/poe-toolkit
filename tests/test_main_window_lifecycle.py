import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication

from services.trade_service import TradeService
from tools.trade_sniper import TradeSniperTool
from ui.main_window import MainWindow
from utils import config as config_module

ConfigManager = config_module.ConfigManager


class RunningProcess:
    pid = 424242
    stdin = None
    stdout = None

    @staticmethod
    def poll():
        return None

    @staticmethod
    def kill():
        return None


class MainWindowTradeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.save_patcher = patch.object(ConfigManager, "save", return_value=True)
        self.save_patcher.start()
        self.addCleanup(self.save_patcher.stop)

    def test_mode_reload_reuses_application_trade_service_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TradeService(owner_file=os.path.join(temp_dir, "trade.lock"))
            service.process = RunningProcess()
            service._running = True
            service.stop = Mock()
            config = copy.deepcopy(ConfigManager.DEFAULTS)
            ConfigManager.set_active_game(config, "poe2")

            with (
                patch.object(ConfigManager, "load", return_value=config),
                patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
                patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
            ):
                window = MainWindow(trade_service=service)
                first_tool = next(tool for tool in window.tools if isinstance(tool, TradeSniperTool))
                self.assertIs(first_tool.widget.service, service)

                window.reload_tools()

                second_tool = next(tool for tool in window.tools if isinstance(tool, TradeSniperTool))
                self.assertIs(second_tool.widget.service, service)
                service.stop.assert_not_called()

                window.close()
                service.stop.assert_called_once_with()
                service.process = None
                service._running = False

    def test_load_error_is_visible_after_window_construction(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        ConfigManager.last_error = "User configuration could not be loaded"
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        self.addCleanup(window.close)
        self.addCleanup(setattr, ConfigManager, "last_error", "")
        self.assertIn("config error", window.status_label.text().lower())
        self.assertIn("could not be loaded", window.status_label.text().lower())

    def test_save_failure_is_visible_and_returns_false(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        with patch.object(
            ConfigManager,
            "save",
            side_effect=config_module.ConfigSaveError("simulated disk failure"),
        ):
            saved = window.save_config()

        self.assertFalse(saved)
        self.assertIn("config save failed", window.status_label.text().lower())
        window.close()

    def test_game_combo_rolls_back_when_pre_switch_save_fails(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        self.addCleanup(window.close)
        with patch.object(window, "save_config", return_value=False):
            window.game_combo.setCurrentIndex(window.game_combo.findData("poe1"))

        self.assertEqual(window.game_combo.currentData(), "poe2")
        self.assertEqual(ConfigManager.get_active_game(window.config), "poe2")

    def test_game_combo_rolls_back_when_mode_persist_fails(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        self.addCleanup(window.close)
        with (
            patch.object(window, "save_config", return_value=True),
            patch.object(window, "_persist_config", return_value=False),
        ):
            window.game_combo.setCurrentIndex(window.game_combo.findData("poe1"))

        self.assertEqual(window.game_combo.currentData(), "poe2")
        self.assertEqual(ConfigManager.get_active_game(window.config), "poe2")
    def test_clear_tools_preserves_widgets_when_worker_shutdown_is_unverified(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        self.addCleanup(window.close)
        blocking_tool = Mock()
        blocking_tool.cleanup.return_value = False
        window.tools = [blocking_tool]
        content_count = window.content_stack.count()

        self.assertFalse(window.clear_tools())

        self.assertEqual(window.tools, [blocking_tool])
        self.assertEqual(window.content_stack.count(), content_count)
        self.assertIn("cleanup", window.status_label.text().lower())

    def test_reload_aborts_when_existing_tools_do_not_shut_down(self):
        window = Mock()
        window.clear_tools.return_value = False
        window.sidebar_buttons = []

        reloaded = MainWindow.reload_tools(window)

        self.assertFalse(reloaded)
        window.load_tools.assert_not_called()

    def test_close_is_rejected_when_worker_shutdown_is_unverified(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        service = Mock()
        service.is_running = False

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_setup"),
            patch("tools.trade_sniper.tool.TradeSniperWidget.check_brave_status"),
        ):
            window = MainWindow(trade_service=service)

        blocking_tool = Mock()
        blocking_tool.cleanup.return_value = False
        window.tools = [blocking_tool]
        event = QCloseEvent()

        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertIn("cleanup", window.status_label.text().lower())
        window.tools = []
        window.close()

    def test_sidebar_mode_change_rolls_back_when_worker_cleanup_blocks_reload(self):
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
            blocking_tool = Mock()
            blocking_tool.cleanup.return_value = False
            window.tools = [blocking_tool]

            window.game_combo.setCurrentIndex(window.game_combo.findData("poe1"))

        self.assertEqual(ConfigManager.get_active_game(window.config), "poe2")
        self.assertEqual(window.game_combo.currentData(), "poe2")
        self.assertGreaterEqual(save.call_count, 3)
        self.assertIn("cleanup", window.status_label.text().lower())
        window.tools = []
        window.close()

    def test_settings_mode_change_rolls_back_when_worker_cleanup_blocks_reload(self):
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
            blocking_tool = Mock()
            blocking_tool.cleanup.return_value = False
            window.tools = [blocking_tool]
            ConfigManager.set_active_game(window.config, "poe1")

            changed = window.on_settings_game_changed("poe1")

        self.assertFalse(changed)
        self.assertEqual(ConfigManager.get_active_game(window.config), "poe2")
        self.assertEqual(window.game_combo.currentData(), "poe2")
        save.assert_called()
        self.assertIn("cleanup", window.status_label.text().lower())
        window.tools = []
        window.close()


if __name__ == "__main__":
    unittest.main()
