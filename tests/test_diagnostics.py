import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtWidgets import QApplication

from services.diagnostics_service import CacheTarget, DiagnosticsService
from tools.diagnostics_tool import DiagnosticsWidget
from utils.app_paths import resolve_app_directories
from utils.config import ConfigManager
from utils.workers import CancellationToken, WorkerContext


class AppDirectoryTests(unittest.TestCase):
    def test_linux_directories_follow_xdg_locations(self):
        paths = resolve_app_directories(
            platform_name="linux",
            environ={
                "XDG_CONFIG_HOME": "/cfg",
                "XDG_CACHE_HOME": "/cache",
                "XDG_DATA_HOME": "/data",
                "XDG_STATE_HOME": "/state",
            },
            home=Path("/home/tester"),
        )

        self.assertEqual(paths.config_dir, Path("/cfg/poe-toolkit"))
        self.assertEqual(paths.cache_dir, Path("/cache/poe-toolkit"))
        self.assertEqual(paths.data_dir, Path("/data/poe-toolkit"))
        self.assertEqual(paths.log_dir, Path("/state/poe-toolkit/logs"))
        self.assertEqual(paths.profile_dir, Path("/data/poe-toolkit/brave-profile"))

    def test_windows_directories_use_roaming_config_and_local_runtime_data(self):
        paths = resolve_app_directories(
            platform_name="win32",
            environ={"APPDATA": "C:/Roaming", "LOCALAPPDATA": "C:/Local"},
            home=Path("C:/Users/tester"),
        )

        self.assertEqual(paths.config_dir, Path("C:/Roaming/poe-toolkit"))
        self.assertEqual(paths.cache_dir, Path("C:/Local/poe-toolkit/cache"))
        self.assertEqual(paths.log_dir, Path("C:/Local/poe-toolkit/logs"))
        self.assertEqual(paths.profile_dir, Path("C:/Local/poe-toolkit/brave-profile"))


class DiagnosticsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.now = datetime(2026, 7, 27, 22, 0, 0)
        self.config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(self.config, "poe2")
        ConfigManager.set_game_league(self.config, "poe2", "Rise of the Abyssal")
        ConfigManager.set_account_credentials(
            self.config,
            "never-export-this-session-token",
            "NeverExportThisAccount",
        )
        ConfigManager.set_client_log_path(self.config, str(self.root / "Client.txt"))
        (self.root / "Client.txt").write_text("", encoding="utf-8")

        self.price_path = self.root / "price_cache.json"
        self.dust_path = self.root / "dust_cache.json"
        self.targets = [
            CacheTarget(
                key="price-root",
                label="Price cache",
                path=self.price_path,
                kind="price",
                source="poe.ninja legacy cache",
                stale_after=timedelta(hours=4),
                clearable=True,
            ),
            CacheTarget(
                key="dust-root",
                label="Dust cache",
                path=self.dust_path,
                kind="dust",
                source="PoEDB legacy cache",
                stale_after=timedelta(hours=24),
            ),
        ]

    def make_service(self, **kwargs):
        return DiagnosticsService(
            self.config,
            project_root=self.root,
            cache_targets=self.targets,
            now=lambda: self.now,
            **kwargs,
        )

    def test_snapshot_is_redacted_and_reports_shared_runtime_state(self):
        self.price_path.write_text(json.dumps({
            "timestamp": self.now.isoformat(),
            "source": "mirror never-export-this-session-token",
            "prices": {},
        }), encoding="utf-8")
        trade_service = Mock()
        trade_service.is_running = True
        trade_service.process.pid = 1234
        runtime_provider = Mock(return_value={
            "workers": ["Trade: dependency-check"],
            "zone_monitor": {"state": "running", "zone": "Hideout"},
            "last_error": "worker retry required for NeverExportThisAccount",
        })
        service = self.make_service(
            trade_service=trade_service,
            runtime_provider=runtime_provider,
        )

        snapshot = service.collect_snapshot()
        serialized = json.dumps(snapshot)

        self.assertEqual(snapshot["application"]["active_game"], "poe2")
        self.assertEqual(snapshot["application"]["active_league"], "Rise of the Abyssal")
        self.assertEqual(snapshot["credentials"]["account"], "configured")
        self.assertEqual(snapshot["credentials"]["session"], "configured")
        self.assertEqual(snapshot["credentials"]["validation"], "not tested")
        self.assertEqual(snapshot["runtime"]["trade_service"], "running")
        self.assertEqual(snapshot["runtime"]["workers"], ["Trade: dependency-check"])
        self.assertEqual(snapshot["runtime"]["zone_monitor"]["zone"], "Hideout")
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("never-export-this-session-token", serialized)
        self.assertNotIn("NeverExportThisAccount", serialized)

    def test_cache_metadata_reports_age_schema_source_league_and_item_count(self):
        self.price_path.write_text(json.dumps({
            "timestamp": (self.now - timedelta(hours=2)).isoformat(),
            "schema_version": 3,
            "league": "Rise of the Abyssal",
            "source": "poe.ninja",
            "prices": {"Divine Orb": 180, "Chaos Orb": 1},
        }), encoding="utf-8")
        self.dust_path.write_text(json.dumps({
            "timestamp": (self.now - timedelta(hours=30)).isoformat(),
            "dust_values": {"A": {}, "B": {}, "C": {}},
        }), encoding="utf-8")

        caches = {item["key"]: item for item in self.make_service().collect_snapshot()["caches"]}

        self.assertEqual(caches["price-root"]["item_count"], 2)
        self.assertEqual(caches["price-root"]["schema"], 3)
        self.assertEqual(caches["price-root"]["league"], "Rise of the Abyssal")
        self.assertEqual(caches["price-root"]["source"], "poe.ninja")
        self.assertEqual(caches["price-root"]["age_seconds"], 7200)
        self.assertFalse(caches["price-root"]["stale"])
        self.assertEqual(caches["dust-root"]["item_count"], 3)
        self.assertEqual(caches["dust-root"]["schema"], "legacy/unversioned")
        self.assertEqual(caches["dust-root"]["league"], "unknown")
        self.assertTrue(caches["dust-root"]["stale"])

    def test_cache_metadata_reads_active_entry_from_schema_v2_stores(self):
        timestamp = (self.now - timedelta(hours=1)).isoformat()
        entry_key = json.dumps(
            ["poe2", "Rise of the Abyssal", "poe.ninja", "overview-v1", 2],
            separators=(",", ":"),
        )
        self.price_path.write_text(json.dumps({
            "schema_version": 2,
            "entries": {
                "malformed-same-context-entry": {
                    "metadata": {
                        "schema_version": 99,
                        "game": "poe2",
                        "league": "Rise of the Abyssal",
                        "source": "untrusted-source",
                        "endpoint_set": "wrong-set",
                        "timestamp": timestamp,
                        "item_count": 1,
                    },
                    "prices": {"Wrong Item": 999},
                    "categories": {},
                },
                entry_key: {
                    "metadata": {
                        "schema_version": 2,
                        "game": "poe2",
                        "league": "Rise of the Abyssal",
                        "source": "poe.ninja",
                        "endpoint_set": "overview-v1",
                        "timestamp": timestamp,
                        "item_count": 2,
                    },
                    "prices": {"Divine Orb": 180, "Chaos Orb": 1},
                    "categories": {},
                }
            },
        }), encoding="utf-8")
        self.dust_path.write_text(json.dumps({
            "schema_version": 2,
            "metadata": {
                "schema_version": 2,
                "game": "poe2",
                "league": "Rise of the Abyssal",
                "source": "bundled-poedust",
                "timestamp": timestamp,
                "estimated": True,
                "item_count": 1,
            },
            "dust_values": {"A": {"base_dust": 10}},
        }), encoding="utf-8")

        caches = {item["key"]: item for item in self.make_service().collect_snapshot()["caches"]}

        self.assertEqual(caches["price-root"]["game"], "poe2")
        self.assertEqual(caches["price-root"]["league"], "Rise of the Abyssal")
        self.assertEqual(caches["price-root"]["item_count"], 2)
        self.assertEqual(caches["price-root"]["schema"], 2)
        self.assertEqual(caches["dust-root"]["source"], "bundled-poedust")
        self.assertTrue(caches["dust-root"]["estimated"])

    def test_invalid_cache_is_visible_without_exposing_file_contents(self):
        self.price_path.write_text("{ definitely not json secret-value", encoding="utf-8")

        cache = self.make_service().collect_snapshot()["caches"][0]

        self.assertTrue(cache["exists"])
        self.assertIn("invalid JSON", cache["error"])
        self.assertNotIn("secret-value", json.dumps(cache))

    def test_cache_metadata_rejects_nested_or_oversized_display_values(self):
        self.price_path.write_text(json.dumps({
            "timestamp": self.now.isoformat(),
            "schema_version": {"cached_secret": "must-not-render"},
            "source": "x" * 500,
            "league": ["must-not-render"],
            "prices": {},
        }), encoding="utf-8")

        cache = self.make_service().collect_snapshot()["caches"][0]
        serialized = json.dumps(cache)

        self.assertEqual(cache["schema"], "invalid")
        self.assertEqual(cache["league"], "unknown")
        self.assertLessEqual(len(cache["source"]), 200)
        self.assertNotIn("must-not-render", serialized)

    def test_clear_cache_only_accepts_declared_targets(self):
        self.price_path.write_text("{}", encoding="utf-8")
        service = self.make_service()

        self.assertTrue(service.clear_cache("price-root"))
        self.assertFalse(self.price_path.exists())
        with self.assertRaises(KeyError):
            service.clear_cache("../../not-a-cache")

    def test_clear_cache_refuses_display_only_legacy_target(self):
        self.dust_path.write_text("{}", encoding="utf-8")
        service = self.make_service()

        with self.assertRaises(PermissionError):
            service.clear_cache("dust-root")
        self.assertTrue(self.dust_path.exists())

    def test_export_writes_only_redacted_snapshot(self):
        export_path = self.root / "diagnostics.json"
        service = self.make_service()
        snapshot = {
            "message": "never-export-this-session-token / NeverExportThisAccount",
            "home_path": str(Path.home() / ".config" / "poe-toolkit"),
        }
        service.export_redacted(export_path, snapshot)
        exported = export_path.read_text(encoding="utf-8")

        self.assertNotIn("never-export-this-session-token", exported)
        self.assertNotIn("NeverExportThisAccount", exported)
        self.assertNotIn(str(Path.home()), exported)
        self.assertIn("~/.config/poe-toolkit", exported)
        self.assertIn("[REDACTED]", exported)

    @patch("services.diagnostics_service.shutil.which")
    def test_dependency_check_is_bounded_and_uses_shared_cancellation(self, which):
        which.return_value = "/usr/bin/tesseract"
        trade_service = Mock()
        trade_service.check_dependencies.return_value = ("v24.0.0", "11.0.0")
        trade_service.service_dir = str(self.root / "trade_service")
        Path(trade_service.service_dir, "node_modules").mkdir(parents=True)
        devtools_probe = Mock(return_value=(True, "Chromium: compatible trade tab ready"))
        token = CancellationToken()
        context = WorkerContext(token=token, progress_callback=lambda _value: None)
        service = self.make_service(
            trade_service=trade_service,
            devtools_probe=devtools_probe,
        )

        result = service.collect_dependencies(context)

        trade_service.check_dependencies.assert_called_once_with(token)
        devtools_probe.assert_called_once_with(context)
        self.assertTrue(result["node"]["ready"])
        self.assertTrue(result["npm"]["ready"])
        self.assertTrue(result["npm_dependencies"]["ready"])
        self.assertTrue(result["tesseract"]["ready"])
        self.assertTrue(result["devtools"]["ready"])

    @patch("services.diagnostics_service.requests.Session")
    def test_devtools_probe_ignores_proxies_and_requires_configured_trade_host(self, session_type):
        session = session_type.return_value
        version_response = Mock()
        version_response.json.return_value = {
            "Browser": "Brave/1.0",
            "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/id",
        }
        targets_response = Mock()
        targets_response.json.return_value = [
            {"type": "page", "url": "https://example.invalid/trade2/search/abc"},
        ]
        session.request.side_effect = [version_response, targets_response]
        context = WorkerContext(
            token=CancellationToken(),
            progress_callback=lambda _value: None,
        )
        service = self.make_service()

        ready, _detail = service._probe_devtools(context)

        self.assertFalse(ready)
        self.assertFalse(session.trust_env)
        session.close.assert_called_once_with()


class DiagnosticsWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_construction_reads_local_snapshot_without_testing_dependencies(self):
        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_account_credentials(config, "secret-session", "secret-account")
        diagnostics = Mock()
        diagnostics.collect_snapshot.return_value = {
            "generated_at": "2026-07-27T22:00:00",
            "application": {"active_game": "poe1", "active_league": "Standard"},
            "credentials": {"account": "configured", "session": "configured", "validation": "not tested"},
            "dependencies": {},
            "runtime": {"trade_service": "stopped", "workers": [], "zone_monitor": {"state": "not running", "zone": "Unknown"}, "last_error": ""},
            "paths": {},
            "caches": [],
        }
        diagnostics.collect_dependencies = Mock()

        widget = DiagnosticsWidget(config, diagnostics=diagnostics)
        self.addCleanup(widget.close)

        diagnostics.collect_snapshot.assert_called_once_with()
        diagnostics.collect_dependencies.assert_not_called()
        rendered = widget.summary_text.toPlainText()
        self.assertIn("values redacted", rendered)
        self.assertIn("PoE 1", rendered)
        self.assertIn("Standard", rendered)
        self.assertNotIn("secret-session", rendered)
        self.assertNotIn("secret-account", rendered)
        self.assertTrue(widget.cleanup())

    def test_explicit_refresh_is_submitted_to_shared_worker_registry(self):
        diagnostics = Mock()
        diagnostics.collect_snapshot.return_value = {
            "application": {"active_game": "poe2"},
            "credentials": {},
            "dependencies": {"items": {}},
            "runtime": {},
            "paths": {},
            "caches": [],
        }
        widget = DiagnosticsWidget(
            config=ConfigManager.DEFAULTS,
            trade_service=Mock(),
            diagnostics=diagnostics,
        )
        self.addCleanup(widget.close)
        diagnostics.collect_snapshot.reset_mock()

        with patch.object(widget._worker_registry, "start", return_value=True) as start:
            self.assertTrue(widget.request_refresh())

        name, operation = start.call_args.args[:2]
        self.assertEqual(name, "local-refresh")
        diagnostics.collect_snapshot.assert_not_called()
        context = WorkerContext(
            token=CancellationToken(),
            progress_callback=lambda _value: None,
        )
        operation(context)
        diagnostics.collect_snapshot.assert_called_once_with()
        self.assertTrue(widget.cleanup())


if __name__ == "__main__":
    unittest.main()
