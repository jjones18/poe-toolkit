"""Cross-platform per-user directories used by diagnostics and runtime data."""

from dataclasses import dataclass
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class AppDirectories:
    config_dir: Path
    cache_dir: Path
    data_dir: Path
    log_dir: Path
    profile_dir: Path


def resolve_app_directories(platform_name=None, environ=None, home=None) -> AppDirectories:
    """Resolve per-user directories without creating or mutating them."""
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)

    if platform_name == "win32":
        roaming = Path(
            environ.get("APPDATA")
            or environ.get("LOCALAPPDATA")
            or home / "AppData" / "Roaming"
        )
        local = Path(
            environ.get("LOCALAPPDATA")
            or environ.get("APPDATA")
            or home / "AppData" / "Local"
        )
        config_dir = roaming / "poe-toolkit"
        data_dir = local / "poe-toolkit"
        cache_dir = data_dir / "cache"
        log_dir = data_dir / "logs"
    elif platform_name == "darwin":
        config_dir = home / "Library" / "Application Support" / "poe-toolkit"
        data_dir = config_dir
        cache_dir = home / "Library" / "Caches" / "poe-toolkit"
        log_dir = home / "Library" / "Logs" / "poe-toolkit"
    else:
        config_root = Path(environ.get("XDG_CONFIG_HOME") or home / ".config")
        cache_root = Path(environ.get("XDG_CACHE_HOME") or home / ".cache")
        data_root = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        state_root = Path(environ.get("XDG_STATE_HOME") or home / ".local" / "state")
        config_dir = config_root / "poe-toolkit"
        cache_dir = cache_root / "poe-toolkit"
        data_dir = data_root / "poe-toolkit"
        log_dir = state_root / "poe-toolkit" / "logs"

    return AppDirectories(
        config_dir=config_dir,
        cache_dir=cache_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        profile_dir=data_dir / "brave-profile",
    )
