"""Cross-platform per-user directories and mutable runtime-file migration."""

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


@dataclass(frozen=True)
class AppDirectories:
    config_dir: Path
    cache_dir: Path
    data_dir: Path
    log_dir: Path
    profile_dir: Path


@dataclass(frozen=True)
class RuntimePaths:
    """Canonical mutable files plus checkout-local migration sources."""

    directories: AppDirectories
    project_root: Path

    @property
    def price_cache_file(self) -> Path:
        return self.directories.cache_dir / "price_cache.json"

    @property
    def dust_cache_file(self) -> Path:
        return self.directories.cache_dir / "dust_cache.json"

    @property
    def debug_log_file(self) -> Path:
        return self.directories.log_dir / "debug.log"

    @property
    def debug_capture_dir(self) -> Path:
        return self.directories.cache_dir / "debug-captures"

    @property
    def legacy_price_cache_files(self) -> tuple[Path, ...]:
        return (
            self.project_root / "price_cache.json",
            self.project_root / "src" / "price_cache.json",
        )

    @property
    def legacy_dust_cache_files(self) -> tuple[Path, ...]:
        return (self.project_root / "dust_cache.json",)

    def prepare_price_cache(self) -> Path:
        migrate_legacy_json_cache(
            self.price_cache_file,
            self.legacy_price_cache_files,
        )
        return self.price_cache_file

    def prepare_dust_cache(self) -> Path:
        migrate_legacy_json_cache(
            self.dust_cache_file,
            self.legacy_dust_cache_files,
        )
        return self.dust_cache_file


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


def resolve_runtime_paths(
    platform_name=None,
    environ=None,
    home=None,
    project_root=None,
) -> RuntimePaths:
    """Resolve canonical runtime files without performing migration."""
    root = (
        Path(__file__).resolve().parents[2]
        if project_root is None
        else Path(project_root)
    )
    return RuntimePaths(
        directories=resolve_app_directories(platform_name, environ, home),
        project_root=root,
    )


def _read_json_object(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cache_rank(path: Path, payload: dict) -> float:
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp).timestamp()
        except ValueError:
            pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _remove_legacy_files(paths, target: Path):
    target_resolved = target.resolve(strict=False)
    for path in paths:
        candidate = Path(path)
        if candidate.resolve(strict=False) == target_resolved:
            continue
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # A verified per-user destination already exists. A locked legacy
            # duplicate is harmless and can be retried on the next launch.
            continue


def _fsync_directory(directory: Path) -> bool:
    """Durably record a same-directory replacement where the OS supports it."""
    if os.name == "nt":
        return True
    descriptor = None
    try:
        descriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        os.fsync(descriptor)
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_verified_copy(source: Path, destination: Path) -> bool:
    """Copy a file with fsync/atomic replacement and verify exact bytes."""
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if temporary.read_bytes() != source.read_bytes():
            return False
        os.replace(temporary, destination)
        temporary = None
        if not _fsync_directory(destination.parent):
            return False
        return destination.read_bytes() == source.read_bytes()
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def migrate_legacy_json_cache(target, legacy_paths) -> Path | None:
    """Atomically migrate the newest valid JSON cache and remove duplicates.

    A valid destination wins. An invalid destination is preserved as ``.invalid``
    before a valid legacy cache replaces it. No legacy source is removed until
    the installed destination has been byte-verified and parsed successfully.
    """
    target = Path(target)
    legacy_paths = tuple(Path(path) for path in legacy_paths)

    if target.exists() and _read_json_object(target) is not None:
        _remove_legacy_files(legacy_paths, target)
        return None

    candidates = []
    for path in legacy_paths:
        payload = _read_json_object(path)
        if payload is not None:
            candidates.append((path, payload))
    if not candidates:
        return None

    source, _payload = max(
        candidates,
        key=lambda candidate: _cache_rank(candidate[0], candidate[1]),
    )

    if target.exists():
        invalid_backup = target.with_suffix(target.suffix + ".invalid")
        if not _atomic_verified_copy(target, invalid_backup):
            return None

    if not _atomic_verified_copy(source, target):
        return None
    if _read_json_object(target) is None:
        return None

    _remove_legacy_files(legacy_paths, target)
    return source
