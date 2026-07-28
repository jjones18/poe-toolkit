import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

for optional_module in ("cv2", "mss", "pytesseract"):
    if importlib.util.find_spec(optional_module) is None:
        sys.modules[optional_module] = Mock()

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from tools.league_tools.kalguur_dust.tool import KalguurDustTool, KalguurDustWidget
from tools.league_tools.tool import LeagueToolsWidget
from tools.league_tools.ultimatum.tool import UltimatumWidget


class QueuedResultWorker(QThread):
    result_signal = pyqtSignal(list, dict, list, object)

    def run(self):
        self.result_signal.emit([], {}, [{"late": True}], None)


class ResultReceiver(QObject):
    def __init__(self):
        super().__init__()
        self.results = []
        self.worker: QThread | None = None
        self.tab_worker: QThread | None = None
        self.clear_overlay = Mock()

    @pyqtSlot(list, dict, list, object)
    def receive(self, _highlights, _stats, items, _fetcher):
        self.results.append(items)


class LeagueToolCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_container_propagates_child_cleanup_failure(self):
        successful = Mock()
        successful.cleanup.return_value = True
        blocked = Mock()
        blocked.cleanup.return_value = False
        container = SimpleNamespace(league_widgets=[successful, blocked])

        result = LeagueToolsWidget.cleanup(container)

        self.assertIs(result, False)
        successful.cleanup.assert_called_once_with()
        blocked.cleanup.assert_called_once_with()

    def test_ultimatum_cleanup_retains_worker_when_shutdown_is_unverified(self):
        scan_worker = Mock()
        tab_worker = Mock()
        widget = SimpleNamespace(
            worker=scan_worker,
            tab_worker=tab_worker,
            clear_overlay=Mock(),
        )

        with patch(
            "tools.league_tools.ultimatum.tool.stop_legacy_qthread",
            side_effect=[False, True],
        ):
            result = UltimatumWidget.cleanup(widget)

        self.assertIs(result, False)
        self.assertIs(widget.worker, scan_worker)
        self.assertIsNone(widget.tab_worker)
        widget.clear_overlay.assert_called_once_with()

    def test_verified_cleanup_disconnects_already_queued_worker_results(self):
        worker = QueuedResultWorker()
        receiver = ResultReceiver()
        worker.result_signal.connect(receiver.receive)
        worker.start()
        self.assertTrue(worker.wait(1000))
        receiver.worker = worker

        self.assertIs(UltimatumWidget.cleanup(receiver), True)
        self.app.processEvents()

        self.assertEqual(receiver.results, [])

    def test_failed_cleanup_keeps_worker_connections_for_preserved_widget(self):
        worker = QueuedResultWorker()
        receiver = ResultReceiver()
        receiver.worker = worker
        worker.result_signal.connect(receiver.receive)

        with patch(
            "tools.league_tools.ultimatum.tool.stop_legacy_qthread",
            side_effect=[False, True],
        ):
            self.assertIs(UltimatumWidget.cleanup(receiver), False)

        worker.result_signal.emit([], {}, [{"preserved": True}], None)
        self.assertEqual(receiver.results, [[{"preserved": True}]])

    def test_owned_price_service_closes_only_after_workers_stop(self):
        service = Mock()
        service.close.return_value = True
        widget = SimpleNamespace(
            worker=None,
            tab_worker=None,
            clear_overlay=Mock(),
            _owns_price_service=True,
            price_service=service,
        )

        self.assertIs(UltimatumWidget.cleanup(widget), True)
        service.close.assert_called_once_with()

        blocked_service = Mock()
        blocked = SimpleNamespace(
            worker=Mock(),
            tab_worker=None,
            clear_overlay=Mock(),
            _owns_price_service=True,
            price_service=blocked_service,
        )
        with patch(
            "tools.league_tools.ultimatum.tool.stop_legacy_qthread",
            side_effect=[False, True],
        ):
            self.assertIs(UltimatumWidget.cleanup(blocked), False)
        blocked_service.close.assert_not_called()

    def test_dust_cleanup_propagates_failed_worker_shutdown(self):
        widget = SimpleNamespace(
            stop_highlighting=Mock(return_value=False),
            _stop_worker=Mock(side_effect=[True, False]),
            tab_worker=Mock(),
            scan_worker=Mock(),
            clear_overlay=Mock(),
        )

        result = KalguurDustWidget.cleanup(widget)

        self.assertIs(result, False)
        widget.clear_overlay.assert_called_once_with()

    def test_standalone_dust_tool_injects_service_and_parent_by_keyword(self):
        config = {"game": "poe1"}
        service = Mock()
        parent = Mock()
        widget = Mock()
        tool = KalguurDustTool(config, price_service=service)

        with patch(
            "tools.league_tools.kalguur_dust.tool.KalguurDustWidget",
            return_value=widget,
        ) as widget_class:
            result = tool.create_widget(parent)

        self.assertIs(result, widget)
        widget_class.assert_called_once_with(
            config,
            price_service=service,
            parent=parent,
        )


if __name__ == "__main__":
    unittest.main()
