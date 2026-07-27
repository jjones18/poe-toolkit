"""
Configuration management for POE Toolkit.

Settings are split into two files:
- config.json: Generic/shareable settings (filter presets, keywords, etc.)
- user_config.json: PC-specific settings (credentials, paths, calibration) - gitignored
"""

import copy
import json
import os
import sys


class ConfigManager:
    """Manages application configuration with defaults."""
    
    # Get the project root (parent of src/)
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Base config with shareable defaults (checked into git)
    CONFIG_FILE = os.path.join(_PROJECT_ROOT, "config", "config.json")
    
    # User-specific config (gitignored)
    USER_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "config", "user_config.json")
    
    # Keys that are PC/user-specific and should be saved to user_config.json
    USER_SPECIFIC_KEYS = {
        "app",          # active game selection
        "credentials",  # shared account_name and POESESSID
        "game_settings",# per-game league selections
        "overlay",      # calibration settings are PC-specific
        "window",       # window position is PC-specific
        "calibration",  # All calibration data
    }
    
    # Nested keys within league_vision that are user-specific
    USER_SPECIFIC_LEAGUE_VISION_KEYS = {
        "client_log_path",
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
                "league_options": []
            },
            "poe2": {
                "league": "Standard",
                "league_options": []
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
            "client_log_path": "",
            "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe" if sys.platform == "win32" else "tesseract",
            "ocr_threshold": 70,
            "debug_mode": False,
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
            "cooldown_ms": 5000,
            "auto_resume": False,
            "auto_resume_delay_ms": 60000
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
        """Load config from both base and user config files."""
        config = copy.deepcopy(cls.DEFAULTS)
        
        # Load base config (shareable settings)
        if os.path.exists(cls.CONFIG_FILE):
            try:
                with open(cls.CONFIG_FILE, 'r') as f:
                    base_config = json.load(f)
                    config = cls._deep_merge(config, base_config)
            except (json.JSONDecodeError, OSError):
                pass
        
        # Load user config (PC-specific settings) - overrides base
        if os.path.exists(cls.USER_CONFIG_FILE):
            try:
                with open(cls.USER_CONFIG_FILE, 'r') as f:
                    user_config = json.load(f)
                    config = cls._deep_merge(config, user_config)
            except (json.JSONDecodeError, OSError):
                pass
        
        cls.normalize(config)
        return config

    @classmethod
    def normalize(cls, config: dict) -> dict:
        """Normalize new/legacy config shapes in-place."""
        app_config = config.setdefault("app", {})
        active_game = app_config.get("active_game", "poe1")
        if active_game not in cls.GAME_PROFILES:
            active_game = "poe1"
        app_config["active_game"] = active_game

        credentials = config.setdefault("credentials", {})
        legacy_league = credentials.pop("league", None)
        credentials.setdefault("session_id", "")
        credentials.setdefault("account_name", "")

        game_settings = config.setdefault("game_settings", {})
        for game_id, defaults in cls.DEFAULTS["game_settings"].items():
            game_settings.setdefault(game_id, {})
            game_settings[game_id].setdefault("league", defaults["league"])
            game_settings[game_id].setdefault("league_options", defaults["league_options"])

        # Older builds stored a single league under credentials. Treat that as
        # the PoE1 league so existing users keep their current selection.
        if legacy_league:
            game_settings["poe1"]["league"] = legacy_league

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
    def get_client_log_path(cls, config: dict) -> str:
        return config.get("league_vision", {}).get("client_log_path", "")

    @classmethod
    def set_client_log_path(cls, config: dict, path: str):
        config.setdefault("league_vision", {})["client_log_path"] = path.strip()

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
        """Save config, splitting user-specific settings to user_config.json."""
        os.makedirs(os.path.dirname(cls.CONFIG_FILE), exist_ok=True)
        cls.normalize(config)
        
        # Split config into base and user-specific
        base_config = {}
        user_config = {}
        
        for key, value in config.items():
            if key in cls.USER_SPECIFIC_KEYS:
                # Entirely user-specific section
                user_config[key] = value
            elif key == "league_vision":
                # Split league_vision into user and base parts
                base_lv = {}
                user_lv = {}
                for lv_key, lv_value in value.items():
                    if lv_key in cls.USER_SPECIFIC_LEAGUE_VISION_KEYS:
                        user_lv[lv_key] = lv_value
                    else:
                        base_lv[lv_key] = lv_value
                if base_lv:
                    base_config["league_vision"] = base_lv
                if user_lv:
                    user_config["league_vision"] = user_lv
            else:
                # Generic setting
                base_config[key] = value
        
        # Save base config
        try:
            with open(cls.CONFIG_FILE, 'w') as f:
                json.dump(base_config, f, indent=4)
        except OSError as e:
            print(f"Error saving config: {e}")
        
        # Save user config
        try:
            with open(cls.USER_CONFIG_FILE, 'w') as f:
                json.dump(user_config, f, indent=4)
        except OSError as e:
            print(f"Error saving user config: {e}")

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

