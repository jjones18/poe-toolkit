import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.valuation import PriceCache
from utils.app_paths import (
    migrate_legacy_json_cache,
    resolve_immutable_resource,
    resolve_runtime_paths,
)
from utils.logger import DebugLogger

DUST_MODULE_PATH = SRC_DIR / "tools" / "league_tools" / "kalguur_dust" / "dust_data.py"
DUST_SPEC = importlib.util.spec_from_file_location("mutable_data_dust_data", DUST_MODULE_PATH)
assert DUST_SPEC is not None and DUST_SPEC.loader is not None
dust_data_module = importlib.util.module_from_spec(DUST_SPEC)
DUST_SPEC.loader.exec_module(dust_data_module)
DustDataCache = dust_data_module.DustDataCache


class RuntimePathTests(unittest.TestCase):
    def test_linux_runtime_files_follow_xdg_directories(self):
        paths = resolve_runtime_paths(
            platform_name="linux",
            environ={
                "XDG_CONFIG_HOME": "/cfg",
                "XDG_CACHE_HOME": "/cache",
                "XDG_DATA_HOME": "/data",
                "XDG_STATE_HOME": "/state",
            },
            home=Path("/home/tester"),
            project_root=Path("/checkout"),
        )

        self.assertEqual(paths.price_cache_file, Path("/cache/poe-toolkit/price_cache.json"))
        self.assertEqual(paths.dust_cache_file, Path("/cache/poe-toolkit/dust_cache.json"))
        self.assertEqual(paths.debug_log_file, Path("/state/poe-toolkit/logs/debug.log"))
        self.assertEqual(paths.debug_capture_dir, Path("/cache/poe-toolkit/debug-captures"))
        self.assertEqual(
            paths.legacy_price_cache_files,
            (Path("/checkout/price_cache.json"), Path("/checkout/src/price_cache.json")),
        )
        self.assertEqual(paths.legacy_dust_cache_files, (Path("/checkout/dust_cache.json"),))

    def test_migration_chooses_newest_valid_cache_and_removes_verified_legacy_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "older.json"
            newer = root / "newer.json"
            target = root / "user-cache" / "cache.json"
            older.write_text(json.dumps({"timestamp": "2026-01-01T00:00:00", "value": "old"}))
            newer.write_text(json.dumps({"timestamp": "2026-02-01T00:00:00", "value": "new"}))

            with patch("utils.app_paths._fsync_directory", return_value=True) as fsync_directory:
                migrated = migrate_legacy_json_cache(target, (older, newer))

            self.assertEqual(migrated, newer)
            fsync_directory.assert_called_once_with(target.parent)
            self.assertEqual(json.loads(target.read_text())["value"], "new")
            self.assertFalse(older.exists())
            self.assertFalse(newer.exists())

    def test_valid_destination_wins_and_legacy_duplicates_are_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "cache.json"
            legacy = root / "legacy.json"
            target.write_text(json.dumps({"timestamp": "2026-03-01T00:00:00", "value": "destination"}))
            legacy.write_text(json.dumps({"timestamp": "2026-04-01T00:00:00", "value": "legacy"}))

            migrated = migrate_legacy_json_cache(target, (legacy,))

            self.assertIsNone(migrated)
            self.assertEqual(json.loads(target.read_text())["value"], "destination")
            self.assertFalse(legacy.exists())

    def test_invalid_legacy_cache_is_preserved_when_no_verified_destination_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "cache.json"
            legacy = root / "legacy.json"
            legacy.write_text("not json")

            migrated = migrate_legacy_json_cache(target, (legacy,))

            self.assertIsNone(migrated)
            self.assertFalse(target.exists())
            self.assertTrue(legacy.exists())

    def test_invalid_destination_is_backed_up_before_valid_legacy_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "user-cache" / "cache.json"
            target.parent.mkdir(parents=True)
            invalid_bytes = b"{ broken destination"
            target.write_bytes(invalid_bytes)
            legacy = root / "legacy.json"
            legacy.write_text(
                json.dumps({"timestamp": "2026-07-27T12:00:00", "value": "legacy-valid"})
            )

            migrated = migrate_legacy_json_cache(target, (legacy,))

            self.assertEqual(migrated, legacy)
            self.assertEqual(json.loads(target.read_text())["value"], "legacy-valid")
            self.assertEqual(target.with_suffix(".json.invalid").read_bytes(), invalid_bytes)
            self.assertFalse(legacy.exists())


class ImmutableResourceTests(unittest.TestCase):
    def test_frozen_bundle_root_is_preferred(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset = Path(temp_dir) / "trade_service" / "trade_monitor.js"
            asset.parent.mkdir()
            asset.write_text("bundle", encoding="utf-8")
            with patch.object(sys, "_MEIPASS", temp_dir, create=True):
                resolved = resolve_immutable_resource("trade_service/trade_monitor.js")
        self.assertEqual(resolved, asset)

    def test_installed_share_fallback_is_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset = Path(temp_dir) / "share" / "poe-toolkit" / "wheel-only.txt"
            asset.parent.mkdir(parents=True)
            asset.write_text("wheel", encoding="utf-8")
            with patch("utils.app_paths.sysconfig.get_path", return_value=temp_dir):
                resolved = resolve_immutable_resource("wheel-only.txt")
        self.assertEqual(resolved, asset)

    def test_resource_path_cannot_escape_bundle(self):
        with self.assertRaises(ValueError):
            resolve_immutable_resource("../secret")


class CacheDefaultPathTests(unittest.TestCase):
    def test_price_cache_uses_prepared_per_user_path_by_default(self):
        runtime = Mock()
        runtime.prepare_price_cache.return_value = Path("/user/cache/price_cache.json")
        with patch("core.valuation.resolve_runtime_paths", return_value=runtime):
            cache = PriceCache()

        self.assertEqual(cache.cache_file, "/user/cache/price_cache.json")
        runtime.prepare_price_cache.assert_called_once_with()

    def test_explicit_price_cache_path_is_not_migrated(self):
        with patch("core.valuation.resolve_runtime_paths") as resolver:
            cache = PriceCache("/custom/cache.json")

        self.assertEqual(cache.cache_file, "/custom/cache.json")
        resolver.assert_not_called()

    def test_dust_cache_uses_prepared_per_user_path_by_default(self):
        runtime = Mock()
        runtime.prepare_dust_cache.return_value = Path("/user/cache/dust_cache.json")
        with patch.object(dust_data_module, "resolve_runtime_paths", return_value=runtime):
            cache = DustDataCache()

        self.assertEqual(cache.cache_file, "/user/cache/dust_cache.json")
        runtime.prepare_dust_cache.assert_called_once_with()


class DebugArtifactTests(unittest.TestCase):
    def setUp(self):
        self.original_log_file = DebugLogger.LOG_FILE
        self.original_capture_dir = DebugLogger.CAPTURE_DIR
        self.original_enabled = DebugLogger._enabled

    def tearDown(self):
        DebugLogger.LOG_FILE = self.original_log_file
        DebugLogger.CAPTURE_DIR = self.original_capture_dir
        DebugLogger._enabled = self.original_enabled

    def test_debug_log_and_capture_paths_are_per_user_and_capture_names_are_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = Mock(
                debug_log_file=root / "logs" / "debug.log",
                debug_capture_dir=root / "captures",
            )
            DebugLogger.configure(runtime)
            DebugLogger.set_enabled(True)
            DebugLogger.log("hello", "Test")
            capture = DebugLogger.capture_path("../../debug_tab_capture_raw.png")

            self.assertTrue(Path(DebugLogger.LOG_FILE).is_file())
            self.assertIn("hello", Path(DebugLogger.LOG_FILE).read_text())
            self.assertEqual(capture, root / "captures" / "debug_tab_capture_raw.png")

    def test_debug_capture_retention_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = Mock(
                debug_log_file=root / "logs" / "debug.log",
                debug_capture_dir=root / "captures",
            )
            DebugLogger.configure(runtime)
            DebugLogger.CAPTURE_DIR.mkdir(parents=True)
            for index in range(8):
                path = DebugLogger.CAPTURE_DIR / f"old-{index}.png"
                path.write_bytes(b"png")
                os.utime(path, (index + 1, index + 1))

            next_capture = DebugLogger.capture_path("next.png", max_files=5)
            next_capture.write_bytes(b"png")

            self.assertLessEqual(len(list(DebugLogger.CAPTURE_DIR.glob("*.png"))), 5)
            self.assertTrue(next_capture.exists())

    def test_debug_capture_retention_ignores_files_that_disappear_during_stat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = Mock(
                debug_log_file=root / "logs" / "debug.log",
                debug_capture_dir=root / "captures",
            )
            DebugLogger.configure(runtime)
            DebugLogger.CAPTURE_DIR.mkdir(parents=True)
            disappearing = DebugLogger.CAPTURE_DIR / "disappearing.png"
            disappearing.write_bytes(b"png")
            original_stat = Path.stat

            def flaky_stat(path, *args, **kwargs):
                if path == disappearing:
                    raise FileNotFoundError(path)
                return original_stat(path, *args, **kwargs)

            with patch.object(Path, "stat", flaky_stat):
                capture = DebugLogger.capture_path("next.png", max_files=5)

            self.assertEqual(capture, DebugLogger.CAPTURE_DIR / "next.png")


if __name__ == "__main__":
    unittest.main()
