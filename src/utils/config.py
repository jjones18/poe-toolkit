"""
Configuration management for POE Toolkit.

Settings are split into two files:
- default_config.json: Generic/shareable defaults bundled read-only with the app
- user_config.json: PC-specific settings and persisted overrides in the OS user directory
"""

import copy
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath


def _resolve_user_config_file(platform_name=None, environ=None, home=None):
    """Resolve the per-user config file without depending on the checkout."""
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    home_text = str(Path.home() if home is None else home)

    if platform_name == "win32":
        path_type = PureWindowsPath
        home_path = path_type(home_text)
        base_dir = (
            environ.get("APPDATA")
            or environ.get("LOCALAPPDATA")
            or str(home_path / "AppData" / "Roaming")
        )
    elif platform_name == "darwin":
        path_type = PurePosixPath
        home_path = path_type(home_text.replace("\\", "/"))
        base_dir = str(home_path / "Library" / "Application Support")
    else:
        path_type = PurePosixPath
        home_path = path_type(home_text.replace("\\", "/"))
        base_dir = environ.get("XDG_CONFIG_HOME") or str(home_path / ".config")

    if path_type is PurePosixPath:
        base_dir = str(base_dir).replace("\\", "/")
    return str(path_type(base_dir) / "poe-toolkit" / "user_config.json")


class ConfigError(Exception):
    """Base error for configuration persistence failures."""


class ConfigLoadError(ConfigError):
    """Raised when configuration cannot be safely interpreted."""


class ConfigSaveError(ConfigError):
    """Raised when configuration cannot be safely persisted."""


class ConfigManager:
    """Manages application configuration with defaults."""
    
    # Get the project root (parent of src/)
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Immutable package data shared by source, wheel, and frozen builds.
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), "default_config.json")
    
    # Legacy checkout-local user config (gitignored) and its new per-user home.
    LEGACY_USER_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "config", "user_config.json")
    USER_CONFIG_FILE = _resolve_user_config_file()
    USER_CONFIG_BACKUP_FILE = USER_CONFIG_FILE + ".bak"
    CURRENT_SCHEMA_VERSION = 3
    last_warning = ""
    last_error = ""
    save_blocked = False
    _recovered_from_backup = False

    @staticmethod
    def resolve_user_config_file(platform_name=None, environ=None, home=None):
        return _resolve_user_config_file(platform_name, environ, home)

    @classmethod
    def _ensure_private_directory(cls, path):
        directory = os.path.dirname(path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.name != "nt":
            os.chmod(directory, 0o700)

    @classmethod
    def _secure_existing_file(cls, path, secure_parent=True):
        """Apply private modes or convert permission failures into load errors."""
        try:
            if secure_parent:
                cls._ensure_private_directory(path)
            if os.name != "nt" and os.path.exists(path):
                os.chmod(path, 0o600)
        except OSError as error:
            raise ConfigLoadError(
                "Configuration permission hardening failed; refusing to load it"
            ) from error

    @classmethod
    def _atomic_write_json(cls, path, payload, mode=0o600):
        """Write JSON through a same-directory temporary file and atomic replace."""
        cls._ensure_private_directory(path)
        directory = os.path.dirname(path)
        descriptor, temp_path = tempfile.mkstemp(prefix=".user-config-", dir=directory)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=4)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            if os.name != "nt":
                os.chmod(path, mode)
                directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _read_json(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, UnicodeError, OSError) as error:
            raise ConfigLoadError(f"{path} could not be loaded: {error}") from error
        if not isinstance(payload, dict):
            raise ConfigLoadError(f"{path} must contain a JSON object")
        return payload

    @classmethod
    def _migrate_payload(cls, payload):
        """Return a copy upgraded to the current explicit config schema."""
        migrated = copy.deepcopy(payload)
        raw_version = migrated.get("config_schema_version", 1)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise ConfigLoadError("Configuration schema version must be an integer")
        if raw_version > cls.CURRENT_SCHEMA_VERSION:
            raise ConfigLoadError(
                f"Configuration uses newer schema {raw_version}; "
                f"this build supports {cls.CURRENT_SCHEMA_VERSION}"
            )
        if raw_version < 1:
            raise ConfigLoadError(f"Unsupported configuration schema {raw_version}")

        if raw_version == 1:
            credentials = migrated.setdefault("credentials", {})
            legacy_league = credentials.pop("league", None)
            if legacy_league:
                migrated.setdefault("game_settings", {}).setdefault("poe1", {})[
                    "league"
                ] = legacy_league

        if raw_version <= 2:
            vision = migrated.get("league_vision", {})
            legacy_client_log = (
                vision.pop("client_log_path", None)
                if isinstance(vision, dict)
                else None
            )
            if legacy_client_log:
                migrated.setdefault("game_settings", {}).setdefault("poe1", {}).setdefault(
                    "client_log_path", legacy_client_log
                )

        migrated["config_schema_version"] = cls.CURRENT_SCHEMA_VERSION
        return migrated
    
    # Keys that are PC/user-specific and should be saved to user_config.json
    USER_SPECIFIC_KEYS = {
        "app",          # active game selection
        "credentials",  # shared account_name and POESESSID
        "game_settings",# per-game league and Client.txt selections
        "overlay",      # calibration settings are PC-specific
        "window",       # window position is PC-specific
        "calibration",  # All calibration data
        "crafting",     # Per-user hotkeys, timing, and attempt preferences
    }
    
    # Nested keys within league_vision that are user-specific
    USER_SPECIFIC_LEAGUE_VISION_KEYS = {
        "tesseract_path",
        "map_device_button",
        "resolution_override",
        "scan_region_hover",
    }

    GAME_PROFILES = {
        "poe1": {
            "label": "PoE 1",
            "full_name": "Path of Exile 1",
            "trade_url": "https://www.pathofexile.com/trade",
            "trade_path": "/trade",
        },
        "poe2": {
            "label": "PoE 2",
            "full_name": "Path of Exile 2",
            "trade_url": "https://www.pathofexile.com/trade2",
            "trade_path": "/trade2",
        },
    }

    DEFAULTS = {
        "config_schema_version": CURRENT_SCHEMA_VERSION,
        "version": "1.0.0",
        "theme": "dark",
        "app": {
            "active_game": "poe1"
        },
        "credentials": {
            "session_id": "",
            "account_name": ""
        },
        "game_settings": {
            "poe1": {
                "league": "Settlers",
                "league_options": [],
                "client_log_path": ""
            },
            "poe2": {
                "league": "Standard",
                "league_options": [],
                "client_log_path": ""
            }
        },
        "overlay": {
            "x_offset": 18,
            "y_offset": 160,
            "cell_size": 53,
            "is_quad_calibrated": False
        },
        "ultimatum": {
            "min_profit": 20,
            "excluded_types": [],
            "included_types": [],
            "excluded_rewards": [],
            "included_rewards": [],
            "excluded_tiers": [],
            "included_tiers": []
        },
        "league_vision": {
            "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe" if sys.platform == "win32" else "tesseract",
            "ocr_threshold": 70,
            "scan_mode": "auto",
            "scan_interval_mouse": 100,
            "scan_interval_center": 500,
            "scan_strategy": "center",
            "map_device_button": {"x": 0, "y": 0, "w": 0, "h": 0},
            "resolution_override": {
                "enabled": False,
                "width": 1920,
                "height": 1080
            },
            "scan_region_hover": {
                "width": 700,
                "height": 800,
                "x_offset": -600,
                "x_offset_right": -100,
                "y_offset": -800
            },
            "scan_region": {
                "x_offset": 0.2,
                "y_offset": 0.1,
                "width_pct": 0.6,
                "height_pct": 0.8
            }
        },
        "trade_sniper": {
            "check_interval_ms": 10,
            "confirmation_retry_ms": 20,
            "cooldown_ms": 5000,
            "auto_resume": True,
            "auto_resume_delay_ms": 30000,
            "custom_allowed_zones": {
                "poe1": [],
                "poe2": []
            }
        },
        "crafting": {
            "poe1": {
                "mode": "links",
                "target": 5,
                "unlimited": True,
                "max_attempts": 1500,
                "apply_delay_ms": 80,
                "start_hotkey": "Numpad Plus",
                "stop_hotkey": "Numpad Minus"
            }
        },
        "kalguur_dust": {
            "min_efficiency": 10,
            "include_unknown_prices": False,
            "selected_tabs": [],
            "tab_presets": {}
        },
        "window": {
            "x": 100,
            "y": 100,
            "width": 1100,
            "height": 800
        }
    }

    @classmethod
    def load(cls) -> dict:
        """Load checked-in defaults plus a recoverable private override."""
        cls.last_warning = ""
        cls.last_error = ""
        cls.save_blocked = False
        cls._recovered_from_backup = False
        config = copy.deepcopy(cls.DEFAULTS)

        # The checked-in base remains read-only at runtime.
        if os.path.exists(cls.CONFIG_FILE):
            try:
                base_config = cls._migrate_payload(cls._read_json(cls.CONFIG_FILE))
                config = cls._deep_merge(config, base_config)
            except ConfigLoadError as error:
                cls.last_warning = f"Checked-in base configuration was ignored: {error}"

        user_config = None
        if os.path.exists(cls.USER_CONFIG_FILE):
            try:
                cls._secure_existing_file(cls.USER_CONFIG_FILE)
                user_config = cls._migrate_payload(cls._read_json(cls.USER_CONFIG_FILE))
            except ConfigLoadError as primary_error:
                try:
                    cls._secure_existing_file(cls.USER_CONFIG_BACKUP_FILE)
                    user_config = cls._migrate_payload(
                        cls._read_json(cls.USER_CONFIG_BACKUP_FILE)
                    )
                    cls._recovered_from_backup = True
                    cls.last_warning = (
                        "User configuration was recovered from the last-known-good "
                        f"backup because the primary could not be loaded: {primary_error}"
                    )
                except ConfigLoadError as backup_error:
                    cls.save_blocked = True
                    cls.last_error = (
                        f"User configuration could not be loaded: {primary_error}. "
                        f"No valid backup is available: {backup_error}"
                    )
        elif os.path.exists(cls.LEGACY_USER_CONFIG_FILE):
            try:
                cls._secure_existing_file(
                    cls.LEGACY_USER_CONFIG_FILE,
                    secure_parent=False,
                )
                user_config = cls._migrate_payload(
                    cls._read_json(cls.LEGACY_USER_CONFIG_FILE)
                )
            except ConfigLoadError as error:
                cls.save_blocked = True
                cls.last_error = f"Legacy user configuration could not be loaded: {error}"

            if user_config is not None:
                try:
                    cls._atomic_write_json(cls.USER_CONFIG_FILE, user_config)
                    verified_config = cls._migrate_payload(
                        cls._read_json(cls.USER_CONFIG_FILE)
                    )
                    if verified_config != user_config:
                        raise ConfigSaveError(
                            "migration verification failed: destination content differs"
                        )
                    os.remove(cls.LEGACY_USER_CONFIG_FILE)
                except Exception as error:
                    cleanup_error = None
                    if os.path.exists(cls.USER_CONFIG_FILE):
                        try:
                            os.remove(cls.USER_CONFIG_FILE)
                        except OSError as removal_error:
                            cleanup_error = removal_error
                    if cleanup_error is not None:
                        cls.save_blocked = True
                        cls.last_error = (
                            "User configuration migration failed and its incomplete "
                            f"destination could not be removed: {cleanup_error}"
                        )
                    else:
                        cls.last_warning = (
                            "User configuration migration could not be completed; "
                            f"the untouched legacy file is still in use: {error}"
                        )

        if isinstance(user_config, dict):
            config = cls._deep_merge(config, user_config)

        cls.normalize(config)
        return config

    @classmethod
    def normalize(cls, config: dict) -> dict:
        """Normalize new/legacy config shapes in-place."""
        config["config_schema_version"] = cls.CURRENT_SCHEMA_VERSION
        app_config = config.setdefault("app", {})
        active_game = app_config.get("active_game", "poe1")
        if active_game not in cls.GAME_PROFILES:
            active_game = "poe1"
        app_config["active_game"] = active_game

        credentials = config.setdefault("credentials", {})
        legacy_league = credentials.pop("league", None)
        credentials.setdefault("session_id", "")
        credentials.setdefault("account_name", "")

        vision_config = config.setdefault("league_vision", {})
        legacy_client_log = vision_config.pop("client_log_path", None)

        kalguur = config.setdefault("kalguur_dust", {})
        defaults = cls.DEFAULTS.get("kalguur_dust", {})
        kalguur.setdefault("min_efficiency", defaults.get("min_efficiency", 10))
        kalguur.setdefault("include_unknown_prices", defaults.get("include_unknown_prices", False))
        if not isinstance(kalguur.get("selected_tabs"), list):
            kalguur["selected_tabs"] = []
        if not isinstance(kalguur.get("tab_presets"), dict):
            kalguur["tab_presets"] = {}

        game_settings = config.setdefault("game_settings", {})
        for game_id, defaults in cls.DEFAULTS["game_settings"].items():
            game_settings.setdefault(game_id, {})
            game_settings[game_id].setdefault("league", defaults["league"])
            game_settings[game_id].setdefault("league_options", defaults["league_options"])
            game_settings[game_id].setdefault(
                "client_log_path", defaults["client_log_path"]
            )

        # Older builds stored a single league under credentials. Treat that as
        # the PoE1 league so existing users keep their current selection.
        if legacy_league:
            game_settings["poe1"]["league"] = legacy_league
        if legacy_client_log and not game_settings["poe1"]["client_log_path"]:
            game_settings["poe1"]["client_log_path"] = legacy_client_log

        return config

    @classmethod
    def get_game_profile(cls, game_id: str) -> dict:
        return cls.GAME_PROFILES.get(game_id, cls.GAME_PROFILES["poe1"])

    @classmethod
    def get_active_game(cls, config: dict) -> str:
        game_id = config.get("app", {}).get("active_game", "poe1")
        return game_id if game_id in cls.GAME_PROFILES else "poe1"

    @classmethod
    def set_active_game(cls, config: dict, game_id: str):
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        config.setdefault("app", {})["active_game"] = game_id

    @classmethod
    def get_account_name(cls, config: dict) -> str:
        return config.get("credentials", {}).get("account_name", "")

    @classmethod
    def get_session_id(cls, config: dict) -> str:
        return config.get("credentials", {}).get("session_id", "")

    @classmethod
    def set_account_credentials(cls, config: dict, session_id: str, account_name: str):
        credentials = config.setdefault("credentials", {})
        credentials["session_id"] = session_id
        credentials["account_name"] = account_name

    @classmethod
    def get_game_league(cls, config: dict, game_id: str | None = None) -> str:
        game_id = game_id or cls.get_active_game(config)
        game_defaults = cls.DEFAULTS["game_settings"].get(game_id, {"league": "Standard"})
        return config.get("game_settings", {}).get(game_id, {}).get("league", game_defaults["league"])

    @classmethod
    def set_game_league(cls, config: dict, game_id: str, league: str):
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        config.setdefault("game_settings", {}).setdefault(game_id, {})["league"] = league

    @classmethod
    def get_game_league_options(cls, config: dict, game_id: str) -> list[str]:
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        options = config.get("game_settings", {}).get(game_id, {}).get("league_options", [])
        return [str(option) for option in options if str(option).strip()]

    @classmethod
    def set_game_league_options(cls, config: dict, game_id: str, leagues: list[str]):
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        cleaned = []
        seen = set()
        for league in leagues:
            league = str(league).strip()
            if league and league not in seen:
                cleaned.append(league)
                seen.add(league)
        config.setdefault("game_settings", {}).setdefault(game_id, {})["league_options"] = cleaned

    @classmethod
    def get_client_log_path(cls, config: dict, game_id: str | None = None) -> str:
        game_id = game_id or cls.get_active_game(config)
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        return str(
            config.get("game_settings", {})
            .get(game_id, {})
            .get("client_log_path", "")
        )

    @classmethod
    def set_client_log_path(
        cls,
        config: dict,
        path: str,
        game_id: str | None = None,
    ):
        game_id = game_id or cls.get_active_game(config)
        if game_id not in cls.GAME_PROFILES:
            game_id = "poe1"
        config.setdefault("game_settings", {}).setdefault(game_id, {})[
            "client_log_path"
        ] = path.strip()

    @classmethod
    def get_trade_url(cls, config: dict, game_id: str | None = None) -> str:
        game_id = game_id or cls.get_active_game(config)
        return cls.get_game_profile(game_id)["trade_url"]

    @classmethod
    def get_trade_path(cls, config: dict, game_id: str | None = None) -> str:
        game_id = game_id or cls.get_active_game(config)
        return cls.get_game_profile(game_id)["trade_path"]

    @classmethod
    def save(cls, config: dict):
        """Atomically save the complete private override; never rewrite the checkout."""
        if cls.save_blocked:
            message = cls.last_error or (
                "Saving is blocked because the existing user configuration could not "
                "be loaded safely"
            )
            raise ConfigSaveError(message)

        payload = copy.deepcopy(config)
        cls.normalize(payload)

        try:
            if os.path.exists(cls.USER_CONFIG_FILE):
                try:
                    previous = cls._read_json(cls.USER_CONFIG_FILE)
                    cls._migrate_payload(previous)  # Validate before making it a backup.
                except ConfigLoadError as error:
                    if not cls._recovered_from_backup:
                        cls.save_blocked = True
                        cls.last_error = str(error)
                        raise ConfigSaveError(
                            "Refusing to overwrite an unreadable user configuration: "
                            f"{error}"
                        ) from error
                else:
                    cls._atomic_write_json(cls.USER_CONFIG_BACKUP_FILE, previous)

            cls._atomic_write_json(cls.USER_CONFIG_FILE, payload)
        except ConfigSaveError:
            raise
        except Exception as error:
            cls.last_error = f"User configuration could not be saved: {error}"
            raise ConfigSaveError(cls.last_error) from error

        cls.last_error = ""
        cls.save_blocked = False
        cls._recovered_from_backup = False
        return True

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """Deep merge override into base."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

