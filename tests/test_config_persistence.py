import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from utils import config as config_module

ConfigManager = config_module.ConfigManager


class ConfigPathTests(unittest.TestCase):
    def test_linux_path_uses_xdg_config_home(self):
        path = ConfigManager.resolve_user_config_file(
            platform_name="linux",
            environ={"XDG_CONFIG_HOME": "/tmp/xdg-config"},
            home=Path("/home/tester"),
        )

        self.assertEqual(path, "/tmp/xdg-config/poe-toolkit/user_config.json")

    def test_windows_path_uses_roaming_app_data(self):
        path = ConfigManager.resolve_user_config_file(
            platform_name="win32",
            environ={"APPDATA": r"C:\Users\tester\AppData\Roaming"},
            home=Path("C:/Users/tester"),
        )

        self.assertEqual(
            PureWindowsPath(path),
            PureWindowsPath(r"C:\Users\tester\AppData\Roaming") / "poe-toolkit" / "user_config.json",
        )

    def test_macos_path_uses_application_support(self):
        path = ConfigManager.resolve_user_config_file(
            platform_name="darwin",
            environ={},
            home=Path("/Users/tester"),
        )

        self.assertEqual(
            path,
            "/Users/tester/Library/Application Support/poe-toolkit/user_config.json",
        )


class ConfigMigrationTests(unittest.TestCase):
    def setUp(self):
        ConfigManager.last_warning = ""
        ConfigManager.last_error = ""
        ConfigManager.save_blocked = False
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.base_file = self.root / "checkout" / "config" / "config.json"
        self.legacy_file = self.root / "checkout" / "config" / "user_config.json"
        self.user_file = self.root / "user-config" / "poe-toolkit" / "user_config.json"
        self.backup_file = Path(str(self.user_file) + ".bak")
        self.base_file.parent.mkdir(parents=True)

        self.patchers = [
            patch.object(ConfigManager, "CONFIG_FILE", str(self.base_file)),
            patch.object(ConfigManager, "LEGACY_USER_CONFIG_FILE", str(self.legacy_file), create=True),
            patch.object(ConfigManager, "USER_CONFIG_FILE", str(self.user_file)),
            patch.object(ConfigManager, "USER_CONFIG_BACKUP_FILE", str(self.backup_file), create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    @staticmethod
    def _write_json(path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_legacy_user_config_is_migrated_without_losing_credentials(self):
        self._write_json(
            self.legacy_file,
            {
                "credentials": {
                    "session_id": "TEST_SESSION_PLACEHOLDER",
                    "account_name": "LegacyAccount",
                }
            },
        )

        loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["session_id"], "TEST_SESSION_PLACEHOLDER")
        self.assertEqual(loaded["credentials"]["account_name"], "LegacyAccount")
        self.assertTrue(self.user_file.exists())
        self.assertFalse(self.legacy_file.exists())
        self.assertEqual(
            json.loads(self.user_file.read_text(encoding="utf-8"))["credentials"]["session_id"],
            "TEST_SESSION_PLACEHOLDER",
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.user_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.user_file.parent.stat().st_mode), 0o700)

    def test_existing_new_user_config_wins_without_deleting_legacy_copy(self):
        self._write_json(
            self.legacy_file,
            {"credentials": {"account_name": "LegacyAccount"}},
        )
        self._write_json(
            self.user_file,
            {"credentials": {"account_name": "CurrentAccount"}},
        )

        loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["account_name"], "CurrentAccount")
        self.assertTrue(self.legacy_file.exists())

    def test_failed_migration_keeps_loading_untouched_legacy_config(self):
        self._write_json(
            self.legacy_file,
            {"credentials": {"account_name": "LegacyAccount"}},
        )

        with patch.object(
            ConfigManager,
            "_atomic_write_json",
            side_effect=OSError("simulated migration failure"),
            create=True,
        ):
            loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["account_name"], "LegacyAccount")
        self.assertTrue(self.legacy_file.exists())
        self.assertFalse(self.user_file.exists())
        self.assertIn("migration", ConfigManager.last_warning.lower())

    def test_migration_verifies_destination_before_removing_legacy_file(self):
        legacy_payload = {"credentials": {"account_name": "LegacyAccount"}}
        self._write_json(self.legacy_file, legacy_payload)

        def write_wrong_payload(path, _payload, mode=0o600):
            self._write_json(Path(path), {"credentials": {"account_name": "WrongAccount"}})

        with patch.object(ConfigManager, "_atomic_write_json", side_effect=write_wrong_payload):
            loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["account_name"], "LegacyAccount")
        self.assertTrue(self.legacy_file.exists())
        self.assertFalse(self.user_file.exists())
        self.assertIn("verification", ConfigManager.last_warning.lower())


class ConfigPersistenceTests(unittest.TestCase):
    def setUp(self):
        ConfigManager.last_warning = ""
        ConfigManager.last_error = ""
        ConfigManager.save_blocked = False
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.base_file = self.root / "checkout" / "config" / "config.json"
        self.legacy_file = self.root / "checkout" / "config" / "user_config.json"
        self.user_file = self.root / "private" / "poe-toolkit" / "user_config.json"
        self.backup_file = Path(str(self.user_file) + ".bak")
        self.base_file.parent.mkdir(parents=True)

        self.patchers = [
            patch.object(ConfigManager, "CONFIG_FILE", str(self.base_file)),
            patch.object(ConfigManager, "LEGACY_USER_CONFIG_FILE", str(self.legacy_file), create=True),
            patch.object(ConfigManager, "USER_CONFIG_FILE", str(self.user_file)),
            patch.object(ConfigManager, "USER_CONFIG_BACKUP_FILE", str(self.backup_file), create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    @staticmethod
    def _write_json(path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_save_writes_full_private_override_without_modifying_checked_in_base(self):
        original_base = '{"theme": "base-theme"}\n'
        self.base_file.write_text(original_base, encoding="utf-8")
        config = copy_config = json.loads(json.dumps(ConfigManager.DEFAULTS))
        copy_config["theme"] = "user-theme"
        copy_config["credentials"]["account_name"] = "PrivateAccount"

        ConfigManager.save(config)

        self.assertEqual(self.base_file.read_text(encoding="utf-8"), original_base)
        saved = json.loads(self.user_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "user-theme")
        self.assertEqual(saved["credentials"]["account_name"], "PrivateAccount")
        self.assertEqual(saved["config_schema_version"], ConfigManager.CURRENT_SCHEMA_VERSION)

    def test_save_preserves_previous_valid_config_as_last_known_good_backup(self):
        previous = {
            "config_schema_version": 2,
            "credentials": {"account_name": "PreviousAccount"},
        }
        self._write_json(self.user_file, previous)
        config = json.loads(json.dumps(ConfigManager.DEFAULTS))
        config["credentials"]["account_name"] = "NewAccount"

        ConfigManager.save(config)

        self.assertEqual(json.loads(self.backup_file.read_text(encoding="utf-8")), previous)
        self.assertEqual(
            json.loads(self.user_file.read_text(encoding="utf-8"))["credentials"]["account_name"],
            "NewAccount",
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.backup_file.stat().st_mode), 0o600)

    def test_malformed_primary_recovers_from_valid_backup_and_reports_warning(self):
        self.user_file.parent.mkdir(parents=True)
        self.user_file.write_text('{"credentials": ', encoding="utf-8")
        self._write_json(
            self.backup_file,
            {
                "config_schema_version": ConfigManager.CURRENT_SCHEMA_VERSION,
                "credentials": {"account_name": "BackupAccount"},
            },
        )
        if os.name != "nt":
            os.chmod(self.backup_file, 0o644)

        loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["account_name"], "BackupAccount")
        self.assertIn("recovered", ConfigManager.last_warning.lower())
        self.assertFalse(ConfigManager.save_blocked)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.backup_file.stat().st_mode), 0o600)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), '{"credentials": ')

    def test_malformed_primary_without_valid_backup_blocks_save_and_preserves_file(self):
        self.user_file.parent.mkdir(parents=True)
        malformed = '{"credentials": '
        self.user_file.write_text(malformed, encoding="utf-8")

        loaded = ConfigManager.load()

        self.assertEqual(loaded["credentials"]["account_name"], "")
        self.assertTrue(ConfigManager.save_blocked)
        self.assertIn("could not be loaded", ConfigManager.last_error.lower())
        with self.assertRaises(config_module.ConfigSaveError):
            ConfigManager.save(loaded)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), malformed)

    def test_invalid_utf8_primary_is_treated_as_malformed_and_blocks_save(self):
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_bytes(b"\xff\xfe\x00")

        loaded = ConfigManager.load()

        self.assertTrue(ConfigManager.save_blocked)
        self.assertIn("could not be loaded", ConfigManager.last_error.lower())
        with self.assertRaises(config_module.ConfigSaveError):
            ConfigManager.save(loaded)
        self.assertEqual(self.user_file.read_bytes(), b"\xff\xfe\x00")

    @unittest.skipIf(os.name == "nt", "POSIX permission behavior")
    def test_permission_hardening_failure_blocks_load_without_crashing(self):
        self._write_json(
            self.user_file,
            {
                "config_schema_version": ConfigManager.CURRENT_SCHEMA_VERSION,
                "credentials": {"account_name": "PrivateAccount"},
            },
        )

        with patch("utils.config.os.chmod", side_effect=PermissionError("denied")):
            loaded = ConfigManager.load()

        self.assertTrue(ConfigManager.save_blocked)
        self.assertIn("permission", ConfigManager.last_error.lower())
        self.assertEqual(loaded["credentials"]["account_name"], "")
        self.assertTrue(self.user_file.exists())

    def test_atomic_serialization_failure_leaves_existing_config_untouched(self):
        previous = {
            "config_schema_version": 2,
            "credentials": {"account_name": "PreviousAccount"},
        }
        self._write_json(self.user_file, previous)
        config = json.loads(json.dumps(ConfigManager.DEFAULTS))

        with patch("utils.config.json.dump", side_effect=TypeError("not serializable")):
            with self.assertRaises(config_module.ConfigSaveError):
                ConfigManager.save(config)

        self.assertEqual(json.loads(self.user_file.read_text(encoding="utf-8")), previous)
        self.assertEqual(list(self.user_file.parent.glob(".user-config-*")), [])

    def test_unversioned_legacy_shape_is_migrated_to_current_schema(self):
        self._write_json(
            self.user_file,
            {
                "credentials": {
                    "account_name": "LegacyAccount",
                    "league": "Legacy League",
                }
            },
        )

        loaded = ConfigManager.load()

        self.assertEqual(loaded["config_schema_version"], ConfigManager.CURRENT_SCHEMA_VERSION)
        self.assertEqual(loaded["game_settings"]["poe1"]["league"], "Legacy League")
        self.assertNotIn("league", loaded["credentials"])

    def test_schema_v2_single_client_log_path_migrates_to_poe1(self):
        legacy_path = "/games/Path of Exile/logs/Client.txt"
        self._write_json(
            self.user_file,
            {
                "config_schema_version": 2,
                "league_vision": {"client_log_path": legacy_path},
            },
        )

        loaded = ConfigManager.load()

        self.assertEqual(
            ConfigManager.get_client_log_path(loaded, "poe1"),
            legacy_path,
        )
        self.assertEqual(ConfigManager.get_client_log_path(loaded, "poe2"), "")
        self.assertNotIn("client_log_path", loaded["league_vision"])

    def test_future_schema_is_not_silently_loaded_or_overwritten(self):
        self._write_json(
            self.user_file,
            {
                "config_schema_version": 999,
                "credentials": {"account_name": "FutureAccount"},
            },
        )

        loaded = ConfigManager.load()

        self.assertNotEqual(loaded["credentials"]["account_name"], "FutureAccount")
        self.assertTrue(ConfigManager.save_blocked)
        self.assertIn("newer schema", ConfigManager.last_error.lower())
        with self.assertRaises(config_module.ConfigSaveError):
            ConfigManager.save(loaded)


class InstallerConfigPathTests(unittest.TestCase):
    def test_linux_setup_targets_private_xdg_config_directory(self):
        setup = (Path(PROJECT_ROOT) / "setup.sh").read_text(encoding="utf-8")

        self.assertIn("XDG_CONFIG_HOME", setup)
        self.assertIn("poe-toolkit", setup)
        self.assertNotIn("cp config/user_config.template.json config/user_config.json", setup)

    def test_windows_setup_targets_appdata_and_hardens_acl(self):
        setup = (Path(PROJECT_ROOT) / "setup.ps1").read_text(encoding="utf-8")

        self.assertIn("$env:APPDATA", setup)
        self.assertIn("$env:LOCALAPPDATA", setup)
        self.assertIn(
            '$configBase = if ($env:APPDATA) { $env:APPDATA } elseif ($env:LOCALAPPDATA)',
            setup,
        )
        self.assertIn('Join-Path $HOME "AppData\\Roaming"', setup)
        self.assertIn("poe-toolkit", setup)
        self.assertIn("icacls", setup.lower())
        self.assertNotIn('$userConfigPath = Join-Path $scriptDir', setup)


if __name__ == "__main__":
    unittest.main()
