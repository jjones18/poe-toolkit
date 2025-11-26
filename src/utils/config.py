"""
Configuration management for POE Toolkit.
"""

import json
import os


class ConfigManager:
    """Manages application configuration with defaults."""
    
    CONFIG_FILE = "config/config.json"

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
            "included_rewards": []
        },
        "league_vision": {
            "client_log_path": "",
            "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe",
            "ocr_threshold": 70,
            "map_device_button": {"x": 0, "y": 0, "w": 0, "h": 0}
        },
        "trade_sniper": {
            "check_interval_ms": 10,
            "cooldown_ms": 5000,
            "auto_resume": False
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
        if not os.path.exists(cls.CONFIG_FILE):
            return cls.DEFAULTS.copy()
        
        try:
            with open(cls.CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                config = cls._deep_merge(cls.DEFAULTS.copy(), user_config)
                return config
        except (json.JSONDecodeError, OSError):
            return cls.DEFAULTS.copy()

    @classmethod
    def save(cls, config: dict):
        os.makedirs(os.path.dirname(cls.CONFIG_FILE), exist_ok=True)
        try:
            with open(cls.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
        except OSError as e:
            print(f"Error saving config: {e}")

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

