"""
Configuration management for POE Toolkit.

Settings are split into two files:
- config.json: Generic/shareable settings (filter presets, keywords, etc.)
- user_config.json: PC-specific settings (credentials, paths, calibration) - gitignored
"""

import json
import os


class ConfigManager:
    """Manages application configuration with defaults."""
    
    # Base config with shareable defaults (checked into git)
    CONFIG_FILE = "config/config.json"
    
    # User-specific config (gitignored)
    USER_CONFIG_FILE = "config/user_config.json"
    
    # Keys that are PC/user-specific and should be saved to user_config.json
    USER_SPECIFIC_KEYS = {
        "credentials",  # session_id, account_name, league
        "overlay",      # calibration settings are PC-specific
        "window",       # window position is PC-specific
    }
    
    # Nested keys within league_vision that are user-specific
    USER_SPECIFIC_LEAGUE_VISION_KEYS = {
        "client_log_path",
        "tesseract_path", 
        "map_device_button",
        "resolution_override",
        "scan_region_hover",
    }

    DEFAULTS = {
        "version": "1.0.0",
        "theme": "dark",
        "credentials": {
            "session_id": "",
            "account_name": "",
            "league": "Settlers"
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
            "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe",
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
        config = cls.DEFAULTS.copy()
        
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
        
        return config

    @classmethod
    def save(cls, config: dict):
        """Save config, splitting user-specific settings to user_config.json."""
        os.makedirs(os.path.dirname(cls.CONFIG_FILE), exist_ok=True)
        
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

