import copy
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import types
import importlib.machinery

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Keep optional OCR/capture dependencies optional in offscreen tests.
if "cv2" not in sys.modules:
    cv2 = types.ModuleType("cv2")
    cv2.__spec__ = importlib.machinery.ModuleSpec("cv2", loader=None)
    cv2.COLOR_BGRA2BGR = 1; cv2.COLOR_BGR2GRAY = 2; cv2.THRESH_BINARY = 1; cv2.THRESH_OTSU = 2; cv2.BORDER_CONSTANT = 0; cv2.INTER_CUBIC = 0
    cv2.cvtColor = lambda img, code: img
    cv2.resize = lambda img, shape, interpolation=None: img
    cv2.threshold = lambda img, thresh, maxval, typ: (0, img)
    cv2.bitwise_not = lambda img: img
    cv2.copyMakeBorder = lambda img, *a, **kw: img
    cv2.imwrite = lambda *a, **kw: True
    sys.modules["cv2"] = cv2
if "numpy" not in sys.modules:
    np = types.ModuleType("numpy")
    np.__spec__ = importlib.machinery.ModuleSpec("numpy", loader=None)
    np.ndarray = object
    np.array = lambda x: x
    np.sum = lambda x: 0
    sys.modules["numpy"] = np
if "pytesseract" not in sys.modules:
    pt = types.ModuleType("pytesseract")
    pt.__spec__ = importlib.machinery.ModuleSpec("pytesseract", loader=None)
    pt.image_to_string = lambda image, timeout=None, **kw: ""
    pt.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract")
    sys.modules["pytesseract"] = pt

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication

from api.client import PoEClient, PoEClientError
from api.auth import SessionAuthProvider
from core.valuation import PriceFetchResult
from services.price_service import PriceService
from tools.league_tools.kalguur_dust.dust_data import DustDataFetcher
from tools.league_tools.kalguur_dust.scanner import fetch_tab_list_operation, scan_stash_operation
from tools.league_tools.kalguur_dust.tab_tracker import TabTracker, TabRegionConfig, TabTrackerWorker
from tools.league_tools.kalguur_dust.tool import KalguurDustWidget
from utils.config import ConfigManager
from utils.workers import CancellationToken, WorkerContext, CancelledError


class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.closed = False
        self.calls = []
    def get(self, *a, **kw):
        self.calls.append((a, kw))
        return self.responses.pop(0)
    def request(self, method, url, **kw):
        self.calls.append(((method, url), kw))
        return self.responses.pop(0)
    def close(self):
        self.closed = True


class KalguurPoEClientTests(unittest.TestCase):
    def test_timeout_rate_limit_callback_and_session_ownership_for_sync_callers(self):
        session = _Session([
            _Response(429, headers={"Retry-After": "0"}),
            _Response(200, {"items": [], "tabs": []}),
        ])
        events = []
        client = PoEClient(SessionAuthProvider("sid"), "acct", "Settlers", session=session, timeout=(1, 2))
        self.assertEqual(client.get_stash_items(0, rate_limit_callback=events.append), {"items": [], "tabs": []})
        self.assertEqual(events[0]["phase"], "rate_limit")
        self.assertEqual(session.calls[0][1]["timeout"], (1, 2))
        client.close()
        self.assertFalse(session.closed)

    def test_429_retry_sleep_is_cancellable(self):
        session = _Session([_Response(429, headers={"Retry-After": "2"})])
        token = CancellationToken()
        context = WorkerContext(token, lambda p: None)
        client = PoEClient(SessionAuthProvider("sid"), "acct", "Settlers", session=session, timeout=(1, 2))
        timer = threading.Timer(0.02, token.cancel)
        timer.start()
        try:
            with self.assertRaises(CancelledError):
                client.get_stash_items(0, context=context)
        finally:
            timer.cancel()

    def test_network_auth_failure_raises_actionable_structured_error(self):
        session = _Session([_Response(403, {"error": "forbidden"})])
        client = PoEClient(SessionAuthProvider("bad"), "acct", "Settlers", session=session, timeout=(1, 2))
        with self.assertRaises(PoEClientError) as raised:
            client.get_stash_tab_list()
        self.assertEqual(raised.exception.operation, "stash tab fetch")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("Retry", str(raised.exception))


class KalguurPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _config(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_account_credentials(config, "sid", "acct")
        ConfigManager.set_game_league(config, "poe1", "Settlers")
        return config

    def _drain_until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        QCoreApplication.processEvents()
        return predicate()

    def test_prepare_runs_in_worker_registry_and_gui_thread_not_blocked(self):
        class SlowDust:
            league = "Settlers"
            provenance = {"source": "built-in estimates", "estimated": True, "status": "last-resort fallback"}
            dust_values = {"Goldrim": {"base_dust": 5, "dust_ilvl84": 5, "dust_ilvl84_q20": 5}}
            def __init__(self, league): self.league = league
            def fetch_dust_data(self, context=None):
                context.sleep(0.1)
                return True
        class FastPrice:
            prices = {"Goldrim": 1.0}
            league = "Settlers"
            def get_price(self, name): return self.prices.get(name)
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = FastPrice()
        price_service.runtime_state.return_value = {"game": "poe1", "league": "Settlers", "source": "poe.ninja", "status": "cache", "fetched_at": "now"}
        widget = KalguurDustWidget(self._config(), price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            with patch("tools.league_tools.kalguur_dust.tool.DustDataFetcher", SlowDust), \
                 patch("tools.league_tools.kalguur_dust.tool.scan_stash_operation", return_value=([], {"tabs_with_items": []})):
                started = time.monotonic()
                widget.start_scan()
                QCoreApplication.processEvents()
                self.assertLess(time.monotonic() - started, 0.05)
                self.assertFalse(widget.scan_btn.isEnabled())
                self.assertFalse(widget.start_scan())
                self.assertTrue(widget.worker_registry.close(timeout_ms=2000))
                price_service.set_context.assert_called_with("poe1", "Settlers")
                price_service.current_fetcher.assert_called_once_with()
                price_service.refresh_prices.assert_not_called()
        finally:
            widget.cleanup()

    def test_scan_worker_uses_progress_not_gui_log_callbacks(self):
        class FastDust:
            league = "Settlers"
            provenance = {"source": "bundled-poedust", "estimated": True, "status": "stale fallback"}
            dust_values = {}
            def __init__(self, league): self.league = league
            def fetch_dust_data(self, context=None): return True
        class FastPrice:
            league = "Settlers"
            def get_price(self, name): return None

        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = FastPrice()
        price_service.runtime_state.return_value = {"game": "poe1", "league": "Settlers", "source": "poe.ninja", "status": "cache", "fetched_at": "now"}
        widget = KalguurDustWidget(self._config(), price_service=price_service)
        seen = {}
        def fake_scan(*args, **kwargs):
            seen.update(kwargs)
            kwargs["context"].report_progress({"phase": "scan_log", "message": "worker log"})
            return [], {"tabs_with_items": [], "failed_tabs": []}
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            with patch("tools.league_tools.kalguur_dust.tool.DustDataFetcher", FastDust), \
                 patch("tools.league_tools.kalguur_dust.tool.scan_stash_operation", side_effect=fake_scan):
                widget.start_scan()
                deadline = time.monotonic() + 2.0
                while widget.worker_registry.active_names and time.monotonic() < deadline:
                    QCoreApplication.processEvents()
                    time.sleep(0.01)
                QCoreApplication.processEvents()
                self.assertFalse(widget.worker_registry.active_names)
        finally:
            widget.cleanup()
        self.assertIsNone(seen.get("log_callback"))
        self.assertIsNone(seen.get("debug_callback"))
        self.assertIn("worker log", widget.log_area.toPlainText())

    def test_slow_price_refresh_does_not_block_and_scan_waits_for_completion(self):
        class SlowPrice:
            def __init__(self, league, game):
                self.league = league
                self.game = game
                self.prices = {"Goldrim": 1.0}
            def fetch_all_prices(self, force=False, context=None):
                context.sleep(0.12)
                return PriceFetchResult(status="success", game=self.game, league=self.league, source="poe.ninja", item_count=1)
            def get_price(self, name): return self.prices.get(name)
            def close(self): pass
        class FastDust:
            provenance = {"source": "test"}
            dust_values = {}
            def __init__(self, league): self.league = league
            def fetch_dust_data(self, context=None): return True

        service = PriceService("poe1", "Settlers", fetcher_factory=SlowPrice)
        widget = KalguurDustWidget(self._config(), price_service=service)
        calls = []
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            with patch("tools.league_tools.kalguur_dust.tool.DustDataFetcher", FastDust), \
                 patch("tools.league_tools.kalguur_dust.tool.scan_stash_operation", side_effect=lambda *a, **kw: calls.append(a) or ([], {"tabs_with_items": []})):
                started = time.monotonic()
                self.assertTrue(widget.start_scan())
                QCoreApplication.processEvents()
                self.assertLess(time.monotonic() - started, 0.05)
                self.assertEqual(calls, [])
                self.assertTrue(widget.cancel_scan_btn.isEnabled())
                self.assertTrue(self._drain_until(lambda: len(calls) == 1 and not widget.worker_registry.active_names, timeout=3.0))
        finally:
            widget.cleanup()
            service.close()

    def test_cancel_pending_price_refresh_suppresses_scan_dispatch(self):
        class SlowPrice:
            def __init__(self, league, game): self.league = league; self.game = game
            def fetch_all_prices(self, force=False, context=None):
                context.sleep(0.08)
                return PriceFetchResult(status="success", game=self.game, league=self.league, source="poe.ninja", item_count=1)
            def close(self): pass
        service = PriceService("poe1", "Settlers", fetcher_factory=SlowPrice)
        widget = KalguurDustWidget(self._config(), price_service=service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            with patch("tools.league_tools.kalguur_dust.tool.scan_stash_operation") as scan:
                self.assertTrue(widget.start_scan())
                widget.cancel_operation("scan")
                self.assertIsNone(widget._pending_scan_args)
                self.assertTrue(self._drain_until(lambda: not service._worker_registry.active_names, timeout=3.0))
                scan.assert_not_called()
                self.assertTrue(widget.retry_scan_btn.isEnabled())
        finally:
            widget.cleanup()
            service.close()

    def test_price_refresh_failure_enables_retry_without_dispatch(self):
        class FailingPrice:
            def __init__(self, league, game): self.league = league; self.game = game
            def fetch_all_prices(self, force=False, context=None): raise RuntimeError("offline")
            def close(self): pass
        service = PriceService("poe1", "Settlers", fetcher_factory=FailingPrice)
        widget = KalguurDustWidget(self._config(), price_service=service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            with patch("tools.league_tools.kalguur_dust.tool.scan_stash_operation") as scan:
                self.assertTrue(widget.start_scan())
                self.assertTrue(self._drain_until(lambda: widget.retry_scan_btn.isEnabled(), timeout=3.0))
                scan.assert_not_called()
                self.assertIn("Retry", widget.phase_status.text())
        finally:
            widget.cleanup()
            service.close()

    def test_stale_price_refresh_callback_is_ignored(self):
        class FastPrice:
            league = "Other"
            def get_price(self, name): return 1.0
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = None
        price_service.refresh_prices.return_value = True
        price_service.runtime_state.return_value = {"game": "poe1", "league": "Other", "source": "poe.ninja", "status": "success", "fetched_at": "now"}
        widget = KalguurDustWidget(self._config(), price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])
            self.assertTrue(widget.start_scan())
            with patch.object(widget, "_dispatch_scan_with_prices") as dispatch:
                widget._on_price_refresh_completed(PriceFetchResult(status="success", game="poe1", league="Other", source="poe.ninja", item_count=1))
                dispatch.assert_not_called()
            self.assertIsNotNone(widget._pending_scan_args)
        finally:
            widget.cleanup()

    def test_stale_active_price_refresh_context_fails_closed_without_pending_scan(self):
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = True
        price_service.current_fetcher.return_value = None
        price_service.refresh_prices.return_value = False
        price_service.active_refresh_context.return_value = ("poe1", "Other")
        widget = KalguurDustWidget(self._config(), price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])

            self.assertFalse(widget.start_scan())

            self.assertIsNone(widget._pending_scan_args)
            self.assertTrue(widget.scan_btn.isEnabled())
            self.assertFalse(widget.cancel_scan_btn.isEnabled())
            self.assertTrue(widget.retry_scan_btn.isEnabled())
            self.assertIn("still stopping", widget.phase_status.text())
            self.assertIn("Retry", widget.phase_status.text())
        finally:
            widget.cleanup()

    def test_same_context_active_price_refresh_still_waits_and_dispatches(self):
        class FastPrice:
            league = "Settlers"
            def get_price(self, name): return 1.0

        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.side_effect = [None, FastPrice()]
        price_service.refresh_prices.return_value = False
        price_service.active_refresh_context.return_value = ("poe1", "Settlers")
        price_service.runtime_state.return_value = {"game": "poe1", "league": "Settlers", "source": "poe.ninja", "status": "success", "fetched_at": "now"}
        widget = KalguurDustWidget(self._config(), price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Uniques"}], preselected_indices=[0])

            self.assertTrue(widget.start_scan())
            self.assertIsNotNone(widget._pending_scan_args)
            self.assertIn("already in progress", widget.phase_status.text())
            with patch.object(widget, "_dispatch_scan_with_prices", return_value=True) as dispatch:
                widget._on_price_refresh_completed(PriceFetchResult(status="success", game="poe1", league="Settlers", source="poe.ninja", item_count=1))
                dispatch.assert_called_once()
            self.assertIsNone(widget._pending_scan_args)
        finally:
            widget.cleanup()

    def test_empty_tab_fetch_result_fails_closed_and_keeps_scan_disabled(self):
        widget = KalguurDustWidget(self._config(), price_service=Mock(spec=PriceService))
        try:
            widget.on_tabs_fetched([])
            self.assertFalse(widget.scan_btn.isEnabled())
            self.assertTrue(widget.retry_tabs_btn.isEnabled())
            self.assertIn("No stash tabs", widget.phase_status.text())
        finally:
            widget.cleanup()

    def test_settings_and_presets_round_trip_and_restore_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user_config.json")
            with patch.object(ConfigManager, "USER_CONFIG_FILE", user), \
                 patch.object(ConfigManager, "USER_CONFIG_BACKUP_FILE", user + ".bak"), \
                 patch.object(ConfigManager, "CONFIG_FILE", os.path.join(tmp, "missing.json")), \
                 patch.object(ConfigManager, "LEGACY_USER_CONFIG_FILE", os.path.join(tmp, "legacy.json")):
                config = self._config()
                config["kalguur_dust"]["min_efficiency"] = 42
                config["kalguur_dust"]["include_unknown_prices"] = True
                config["kalguur_dust"]["selected_tabs"] = [{"id": "1", "index": 1, "name": "Dust"}]
                config["kalguur_dust"]["tab_presets"] = {"farm": [{"id": "1", "index": 1, "name": "Dust"}]}
                ConfigManager.save(config)
                loaded = ConfigManager.load()
                self.assertEqual(loaded["kalguur_dust"]["min_efficiency"], 42)
                widget = KalguurDustWidget(loaded, price_service=Mock(spec=PriceService))
                try:
                    widget.on_tabs_fetched([{"i": 1, "n": "Dust"}, {"i": 2, "n": "Other"}])
                    self.assertEqual(widget.tab_selector.get_selected_indices(), [1])
                    widget.apply_tab_preset()
                    self.assertEqual(widget.tab_selector.get_selected_indices(), [1])
                finally:
                    widget.cleanup()

    def test_provenance_labels_bundled_fallback_and_partial_price_preserved(self):
        widget = KalguurDustWidget(self._config(), price_service=Mock(spec=PriceService))
        try:
            widget.dust_fetcher = Mock()
            widget.dust_fetcher.provenance = {"source": "built-in estimates", "estimated": True, "status": "last-resort fallback"}
            widget.price_service.runtime_state.return_value = {"source": "poe.ninja", "status": "partial", "fetched_at": None}
            widget._update_provenance()
            text = widget.provenance_label.text()
            self.assertIn("bundled fallback estimate", text)
            self.assertIn("last-known-good preserved", text)
        finally:
            widget.cleanup()

    def test_cleanup_fails_closed_when_registry_will_not_stop(self):
        widget = KalguurDustWidget(self._config(), price_service=Mock(spec=PriceService))
        try:
            with patch.object(widget.worker_registry, "close", return_value=False):
                self.assertFalse(widget.cleanup())
        finally:
            widget.worker_registry.close(timeout_ms=1000)


class KalguurOCRTests(unittest.TestCase):
    def test_ocr_uses_bounded_call_timeout_argument(self):
        tracker = TabTracker(["Dust"], TabRegionConfig(psm=7), debug_mode=False)
        calls = []
        with patch("tools.league_tools.kalguur_dust.tab_tracker.pytesseract.image_to_string", side_effect=lambda image, timeout=None, **kw: calls.append(timeout) or "Dust"):
            self.assertEqual(tracker.detect_text_with_strategies(object()), "Dust")
        self.assertEqual(calls[0], 15.0)

    def test_tab_tracker_worker_stop_interrupts_sleep(self):
        tracker = Mock()
        tracker.is_calibrated = False
        worker = TabTrackerWorker(tracker, interval_ms=500)
        worker.start()
        time.sleep(0.03)
        started = time.monotonic()
        worker.stop()
        self.assertTrue(worker.wait(1000))
        self.assertLess(time.monotonic() - started, 0.5)

    def test_invalid_tesseract_path_warns_before_highlighting_start(self):
        app = QApplication.instance() or QApplication([])
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        config["league_vision"]["tesseract_path"] = os.path.join(tempfile.gettempdir(), "missing-tesseract-for-test")
        widget = KalguurDustWidget(config, price_service=Mock(spec=PriceService))
        widget.scan_results = [Mock(tab_name="Dust")]
        widget.items_by_tab = {"Dust": []}
        try:
            with patch("PyQt6.QtWidgets.QMessageBox.warning") as warning:
                widget.start_highlighting()
            warning.assert_called_once()
            self.assertIsNone(widget.tab_tracker_worker)
            self.assertIn("Tesseract path is invalid", widget.phase_status.text())
        finally:
            widget.cleanup()


class KalguurScanFailureTests(unittest.TestCase):
    def test_every_selected_tab_fetch_failure_errors_instead_of_empty_success(self):
        class FailingClient:
            def get_stash_items(self, tab_idx, **kwargs):
                raise RuntimeError(f"boom {tab_idx}")
            def close(self):
                pass
        with patch("tools.league_tools.kalguur_dust.scanner._make_client", return_value=FailingClient()):
            with self.assertRaisesRegex(RuntimeError, "Every selected stash tab fetch failed"):
                scan_stash_operation("sid", "acct", "Settlers", [1, 2], Mock(), context=None)

    def test_tab_list_operation_empty_tabs_is_actionable_failure(self):
        class EmptyClient:
            def get_stash_tab_list(self, **kwargs):
                return []
            def close(self):
                pass
        with patch("tools.league_tools.kalguur_dust.scanner._make_client", return_value=EmptyClient()):
            with self.assertRaisesRegex(RuntimeError, "No stash tabs were returned"):
                fetch_tab_list_operation("sid", "acct", "Settlers")


if __name__ == "__main__":
    unittest.main()
