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

from utils.config import ConfigManager


class LeagueVisionSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_active_games_client_log_path_drives_label_and_monitor(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_client_log_path(
            config, "/games/poe1/logs/Client.txt", "poe1"
        )
        ConfigManager.set_client_log_path(
            config, "/games/poe2/logs/Client.txt", "poe2"
        )
        ConfigManager.set_active_game(config, "poe2")
        monitor = Mock()
        monitor.start.return_value = True

        with patch.dict(sys.modules, {
            "cv2": Mock(),
            "pytesseract": Mock(),
            "mss": Mock(),
        }):
            from tools.league_vision.tool import LeagueVisionWidget

            with (
                patch("tools.league_vision.tool.os.path.exists", return_value=True),
                patch(
                    "tools.league_vision.tool.ZoneMonitor",
                    return_value=monitor,
                ) as monitor_type,
            ):
                widget = LeagueVisionWidget(config)

        self.addCleanup(widget.cleanup)
        expected = "/games/poe2/logs/Client.txt"
        self.assertEqual(widget.log_path_label.text(), expected)
        monitor_type.assert_called_once_with(expected)


if __name__ == "__main__":
    unittest.main()
