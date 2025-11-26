"""
Debug logging utility.
"""

import os
import datetime


class DebugLogger:
    """Simple file-based debug logger."""
    
    LOG_FILE = "debug.log"
    _enabled = False

    @classmethod
    def set_enabled(cls, enabled: bool):
        cls._enabled = enabled
        if enabled:
            cls.log("--- Debug Session Started ---")

    @classmethod
    def log(cls, message: str, component: str = "System"):
        if not cls._enabled:
            return
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{component}] {message}\n"
        
        try:
            with open(cls.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"Failed to write to log: {e}")

