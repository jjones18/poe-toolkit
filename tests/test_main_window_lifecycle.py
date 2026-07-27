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

from PyQt6.QtWidgets import QApplication

from services.trade_service import TradeService
from tools.trade_sniper import TradeSniperTool
from ui.main_window import MainWindow
from utils.config import ConfigManager


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


if __name__ == "__main__":
    unittest.main()
