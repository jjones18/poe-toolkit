"""Deterministic source and frozen-package smoke test."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils import APP_VERSION
from utils.config import ConfigManager
from utils.app_paths import resolve_immutable_resource
from utils.optional_features import feature_status


def run_package_smoke() -> dict[str, object]:
    """Construct, show, and cleanly close the real application offscreen."""
    app = QApplication.instance() or QApplication([])
    original_paths = (
        ConfigManager.USER_CONFIG_FILE,
        ConfigManager.USER_CONFIG_BACKUP_FILE,
        ConfigManager.LEGACY_USER_CONFIG_FILE,
    )

    window = None
    assets = {
        "dust_data": resolve_immutable_resource("data/poedust_cache.json"),
        "trade_monitor": resolve_immutable_resource("trade_service/trade_monitor.js"),
        "trade_lock": resolve_immutable_resource("trade_service/package-lock.json"),
    }
    missing_assets = [name for name, path in assets.items() if not path.is_file()]
    if missing_assets:
        raise RuntimeError(f"Missing immutable package assets: {', '.join(missing_assets)}")

    with tempfile.TemporaryDirectory(prefix="poe-toolkit-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        environment_overrides = {
            "APPDATA": str(temp_root / "appdata"),
            "LOCALAPPDATA": str(temp_root / "localappdata"),
            "XDG_CONFIG_HOME": str(temp_root / "xdg" / "config"),
            "XDG_CACHE_HOME": str(temp_root / "xdg" / "cache"),
            "XDG_DATA_HOME": str(temp_root / "xdg" / "data"),
            "XDG_STATE_HOME": str(temp_root / "xdg" / "state"),
        }
        original_environment = {
            name: os.environ.get(name) for name in environment_overrides
        }
        os.environ.update(environment_overrides)
        user_config = temp_root / "config" / "user_config.json"
        ConfigManager.USER_CONFIG_FILE = str(user_config)
        ConfigManager.USER_CONFIG_BACKUP_FILE = str(user_config) + ".bak"
        ConfigManager.LEGACY_USER_CONFIG_FILE = str(Path(temp_dir) / "legacy-user-config.json")
        try:
            window = MainWindow()
            window.show()
            app.processEvents()
            tool_names = [tool.name for tool in window.tools]
            aligned = (
                len(window.tools)
                == len(window.sidebar_buttons)
                == window.content_stack.count()
            )
            if not aligned:
                raise RuntimeError("Tool/sidebar/content navigation entries are misaligned")
            if not window.close():
                raise RuntimeError("MainWindow rejected package-smoke cleanup")
            app.processEvents()
        finally:
            (
                ConfigManager.USER_CONFIG_FILE,
                ConfigManager.USER_CONFIG_BACKUP_FILE,
                ConfigManager.LEGACY_USER_CONFIG_FILE,
            ) = original_paths
            for name, original_value in original_environment.items():
                if original_value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = original_value

    return {
        "version": APP_VERSION,
        "tool_names": tool_names,
        "sidebar_items": len(tool_names),
        "navigation_aligned": aligned,
        "closed": bool(window is not None and not window.isVisible()),
        "immutable_assets": sorted(assets),
        "features": feature_status(),
    }


def main() -> int:
    result = run_package_smoke()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["closed"] and result["navigation_aligned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
