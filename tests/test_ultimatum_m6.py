import copy
import os
import sys
import time
import types
import importlib.machinery
import unittest
from unittest.mock import Mock, call, patch

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
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel

from core.filters import FilteringRuleEngine, RewardRule, RewardIncludeOverride, ValueRule
from core.valuation import PriceFetchResult
from services.price_service import PriceService
from ui.components.filter_dialog import FilterConfigDialog
from tools.league_tools.ultimatum.tool import (
    UltimatumTool,
    UltimatumWidget,
    build_ultimatum_filter_engine,
    scan_ultimatum_operation,
)
from utils.config import ConfigManager
from utils.workers import CancelledError


class _FastPrice:
    league = "Settlers"
    prices = {"Chaos Orb": 1.0, "Divine Orb": 200.0, "Vaal Orb": 2.0}
    def get_price(self, name):
        return self.prices.get(name)


def _ultimatum_item(reward="Divine Orbs", sacrifice="Chaos Orbs", encounter="Defeat Waves", x=1, y=2):
    return {
        "typeLine": "Inscribed Ultimatum",
        "x": x,
        "y": y,
        "properties": [
            {"name": "Challenge", "values": [[encounter, 0]]},
            {"name": "Requires Sacrifice", "values": [[sacrifice, 0], ["x10", 0]]},
            {"name": "Reward", "values": [[reward, 0], ["x1", 0]]},
        ],
        "explicitMods": ["100% increased Monster Life"],
    }


class UltimatumM6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _config(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_account_credentials(config, "sid", "acct")
        ConfigManager.set_game_league(config, "poe1", "Settlers")
        config.setdefault("ultimatum", {})["min_profit"] = 20
        return config

    def _drain_until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        QCoreApplication.processEvents()
        return predicate()

    def test_include_override_wins_over_exclude_and_unknown_price(self):
        config = {
            "min_profit": 9999,
            "excluded_rewards": ["Mystery Box"],
            "included_rewards": ["Mystery Box"],
        }
        engine = build_ultimatum_filter_engine(config)
        price = Mock()
        price.get_price.return_value = None
        self.assertTrue(engine.evaluate({"reward": "Mystery Box", "sacrifice": "Chaos Orb"}, price))

        no_override = FilteringRuleEngine()
        no_override.add_rule(ValueRule(min_profit=1))
        no_override.add_rule(RewardRule(excluded_rewards=["Mystery Box"]))
        no_override.add_override(RewardIncludeOverride(included_rewards=["Other"]))
        self.assertFalse(no_override.evaluate({"reward": "Mystery Box", "sacrifice": "Chaos Orb"}, price))

    def test_scan_operation_uses_cancellable_context_rate_limit_progress_and_errors(self):
        class Client:
            def __init__(self, *args, **kwargs):
                self.closed = False
            def get_stash_items(self, tab_idx, **kwargs):
                self.kwargs = kwargs
                kwargs["rate_limit_callback"]({"phase": "rate_limit", "retry_after": 1})
                return {"quadLayout": False, "items": [_ultimatum_item()]}
            def close(self):
                self.closed = True
        progress = []
        context = Mock()
        context.report_progress.side_effect = progress.append
        context.sleep.side_effect = CancelledError("cancelled")
        with patch("tools.league_tools.ultimatum.tool.PoEClient", Client):
            highlights, stats, items, fetcher = scan_ultimatum_operation(
                "sid", "acct", "Settlers", {"min_profit": 20}, [0], _FastPrice(), context=context
            )
        self.assertEqual(len(highlights), 1)
        self.assertEqual(items[0]["parsed"]["reward"], "Divine Orb")
        self.assertTrue(any(p.get("phase") == "rate_limit" for p in progress))

        class FailingClient(Client):
            def get_stash_items(self, tab_idx, **kwargs):
                raise RuntimeError("offline")
        with patch("tools.league_tools.ultimatum.tool.PoEClient", FailingClient):
            with self.assertRaisesRegex(RuntimeError, "Every selected stash tab fetch failed"):
                scan_ultimatum_operation("sid", "acct", "Settlers", {}, [0, 1], _FastPrice(), context=Mock(report_progress=lambda p: None))

        class CancelledClient(Client):
            def get_stash_items(self, tab_idx, **kwargs):
                raise CancelledError("cancelled")
        with patch("tools.league_tools.ultimatum.tool.PoEClient", CancelledClient):
            with self.assertRaises(CancelledError):
                scan_ultimatum_operation(
                    "sid", "acct", "Settlers", {}, [0], _FastPrice(),
                    context=Mock(report_progress=lambda p: None),
                )

    def test_filter_dialog_explains_include_override_precedence(self):
        dialog = FilterConfigDialog(
            found_data={"types": {"Defeat Waves"}, "rewards": set(), "tiers": set()},
            current_config={},
        )
        try:
            semantics = dialog.findChild(QLabel, "filter_semantics_label")
            self.assertIsNotNone(semantics)
            self.assertIn("wins over Exclude", semantics.text())
            self.assertIn("unknown prices", semantics.text())
            checkbox_texts = [checkbox.text() for checkbox in dialog.findChildren(QCheckBox)]
            self.assertIn("Include override", checkbox_texts)
        finally:
            dialog.close()

    def test_sync_config_captures_current_profit_slider_for_persistence(self):
        config = self._config()
        widget = UltimatumWidget(config, price_service=Mock(spec=PriceService))
        try:
            widget.profit_slider.blockSignals(True)
            widget.profit_slider.setValue(73)
            widget.profit_slider.blockSignals(False)

            widget.sync_config()

            self.assertEqual(config["ultimatum"]["min_profit"], 73)
        finally:
            widget.cleanup()

    def test_tab_and_scan_use_worker_registry_and_gui_thread_does_not_block_on_prices(self):
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = None
        price_service.refresh_prices.return_value = True
        price_service.runtime_state.return_value = {
            "game": "poe1",
            "league": "Settlers",
            "last_error": None,
        }
        widget = UltimatumWidget(self._config(), price_service=price_service)
        try:
            with patch.object(widget.worker_registry, "start", return_value=True) as start_worker, patch(
                "tools.league_tools.ultimatum.tool.fetch_ultimatum_tab_list_operation",
                return_value=[{"i": 0, "n": "Ultimatums"}],
            ) as fetch_tabs:
                self.assertTrue(widget.fetch_tab_list())
                fetch_tabs.assert_not_called()
                self.assertTrue(widget.cancel_tabs_btn.isEnabled())

                tab_start = start_worker.call_args
                self.assertEqual(tab_start.args[0], "ultimatum-tab-fetch")
                tab_context = Mock()
                self.assertEqual(
                    tab_start.args[1](tab_context),
                    [{"i": 0, "n": "Ultimatums"}],
                )
                fetch_tabs.assert_called_once_with(
                    "sid", "acct", "Settlers", context=tab_context
                )

            widget.tab_selector.load_tabs([{"i": 0, "n": "Ultimatums"}], preselected_indices=[0])
            with patch.object(widget.worker_registry, "start", return_value=True) as start_worker, patch(
                "tools.league_tools.ultimatum.tool.scan_ultimatum_operation",
                return_value=([], {}, [], Mock()),
            ) as scan_operation:
                self.assertTrue(widget.start_scan())
                price_service.refresh_prices.assert_called_once_with(force=False)
                scan_operation.assert_not_called()
                start_worker.assert_not_called()
                self.assertTrue(widget.cancel_scan_btn.isEnabled())

                price_fetcher = Mock()
                price_service.current_fetcher.return_value = price_fetcher
                widget._on_price_refresh_completed(
                    PriceFetchResult(
                        status="success",
                        game="poe1",
                        league="Settlers",
                        source="poe.ninja",
                        item_count=2,
                    )
                )
                scan_operation.assert_not_called()
                scan_start = start_worker.call_args
                self.assertEqual(scan_start.args[0], "ultimatum-scan")

                scan_context = Mock()
                scan_start.args[1](scan_context)
                scan_operation.assert_called_once()
                self.assertIs(scan_operation.call_args.args[5], price_fetcher)
                self.assertIs(scan_operation.call_args.kwargs["context"], scan_context)
        finally:
            widget.cleanup()

    def test_cancel_retry_failure_and_stale_price_callbacks(self):
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = None
        price_service.refresh_prices.return_value = True
        price_service.active_refresh_context.return_value = ("poe1", "Settlers")
        price_service.runtime_state.return_value = {"game": "poe1", "league": "Settlers", "last_error": None}
        widget = UltimatumWidget(self._config(), price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Ultimatums"}], preselected_indices=[0])
            self.assertTrue(widget.start_scan())
            widget.cancel_operation("scan")
            self.assertIsNone(widget._pending_scan_args)
            self.assertTrue(widget.retry_scan_btn.isEnabled())
            with patch.object(widget, "_dispatch_scan_with_prices") as dispatch:
                widget._on_price_refresh_completed(PriceFetchResult(status="success", game="poe1", league="Other", source="poe.ninja", item_count=1))
                dispatch.assert_not_called()
            self.assertTrue(widget.start_scan())
            widget._on_price_refresh_failed("offline")
            self.assertTrue(widget.retry_scan_btn.isEnabled())
            self.assertIn("Retry", widget.phase_status.text())
        finally:
            widget.cleanup()

    def test_settings_context_change_cancels_stale_preparation_and_active_work(self):
        config = self._config()
        price_service = Mock(spec=PriceService)
        price_service.set_context.return_value = False
        price_service.current_fetcher.return_value = None
        price_service.refresh_prices.return_value = True
        price_service.active_refresh_context.return_value = ("poe1", "Settlers")
        widget = UltimatumWidget(config, price_service=price_service)
        try:
            widget.tab_selector.load_tabs([{"i": 0, "n": "Ultimatums"}], preselected_indices=[0])
            widget._tab_list_context = ("Account", "Settlers")
            self.assertTrue(widget.start_scan())
            self.assertIsNotNone(widget._pending_scan_args)

            ConfigManager.set_game_league(config, "poe1", "Hardcore")
            widget.refresh_shared_settings()
            self.assertIsNone(widget._pending_scan_args)
            self.assertFalse(widget.scan_btn.isEnabled())
            self.assertFalse(widget.cancel_scan_btn.isEnabled())
            self.assertTrue(widget.retry_scan_btn.isEnabled())
            self.assertTrue(widget.retry_tabs_btn.isEnabled())
            self.assertEqual(widget.tab_selector.get_selected_indices(), [])
            self.assertEqual(widget.tab_selector.tabs_list, [])
            self.assertIn("stale tabs/work cleared", widget.phase_status.text())

            with patch.object(widget, "on_tabs_fetched") as apply_tabs:
                widget._on_tabs_fetched_for_context(("Account", "Settlers"), [{"i": 0, "n": "Old"}])
                apply_tabs.assert_not_called()
            with patch.object(widget, "on_scan_result") as apply_scan:
                widget._on_scan_result_for_context(("Account", "Settlers"), ([], {}, [], Mock()))
                apply_scan.assert_not_called()
            self.assertIn("Discarded stale scan results", widget.phase_status.text())

            widget._active_scan_context = ("Account", "Settlers")
            widget._active_tab_fetch_context = ("Account", "Settlers")
            with patch.object(widget.worker_registry, "cancel", return_value=True) as cancel:
                widget.refresh_shared_settings()
            self.assertEqual(
                cancel.call_args_list,
                [call("ultimatum-scan"), call("ultimatum-tab-fetch")],
            )
        finally:
            widget._active_scan_context = None
            widget._active_tab_fetch_context = None
            widget.cleanup()

    def test_cleanup_fails_closed_preserves_registry_and_unowned_price_service(self):
        service = Mock(spec=PriceService)
        widget = UltimatumWidget(self._config(), price_service=service)
        try:
            with patch.object(widget.worker_registry, "close", return_value=False):
                self.assertFalse(widget.cleanup())
            service.close.assert_not_called()
        finally:
            widget.worker_registry.close(timeout_ms=1000)

    def test_settings_are_sole_owner_of_league_and_sync_reads_active_settings(self):
        config = self._config()
        widget = UltimatumWidget(config, price_service=Mock(spec=PriceService))
        try:
            self.assertFalse(widget.league_input.isEnabled())
            ConfigManager.set_game_league(config, "poe1", "Hardcore")
            tool = UltimatumTool(config, price_service=widget.price_service)
            tool.widget = widget
            tool.on_activated()
            self.assertEqual(widget.league_input.currentText(), "Hardcore")
            before = copy.deepcopy(config.get("games"))
            widget.sync_config()
            self.assertEqual(config.get("games"), before)
            self.assertNotIn("league", config.get("ultimatum", {}))
        finally:
            widget.cleanup()


if __name__ == "__main__":
    unittest.main()
