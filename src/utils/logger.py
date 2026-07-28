"""Debug logging and bounded debug-artifact storage."""

import datetime
from pathlib import Path

from utils.app_paths import resolve_runtime_paths


_DEFAULT_RUNTIME_PATHS = resolve_runtime_paths()


class DebugLogger:
    """Simple opt-in file logger with per-user debug capture storage."""

    LOG_FILE = _DEFAULT_RUNTIME_PATHS.debug_log_file
    CAPTURE_DIR = _DEFAULT_RUNTIME_PATHS.debug_capture_dir
    DEFAULT_CAPTURE_LIMIT = 20
    _enabled = False

    @classmethod
    def configure(cls, runtime_paths=None):
        """Configure paths explicitly for tests or embedding."""
        runtime_paths = runtime_paths or resolve_runtime_paths()
        cls.LOG_FILE = Path(runtime_paths.debug_log_file)
        cls.CAPTURE_DIR = Path(runtime_paths.debug_capture_dir)

    @classmethod
    def set_enabled(cls, enabled: bool):
        cls._enabled = enabled
        if enabled:
            cls.log("--- Debug Session Started ---")

    @classmethod
    def reset(cls, header: str = "--- Debug Session Started ---"):
        """Replace the current debug log after ensuring its parent exists."""
        if not cls._enabled:
            return
        try:
            log_file = Path(cls.LOG_FILE)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(f"{header}\n", encoding="utf-8")
        except OSError as error:
            print(f"Failed to reset debug log: {error}")

    @classmethod
    def log(cls, message: str, component: str = "System"):
        if not cls._enabled:
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{component}] {message}\n"

        try:
            log_file = Path(cls.LOG_FILE)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(entry)
        except OSError as error:
            print(f"Failed to write to log: {error}")

    @classmethod
    def capture_path(cls, filename: str, max_files: int | None = None) -> Path:
        """Return a sanitized per-user capture path and prune oldest PNGs."""
        limit = cls.DEFAULT_CAPTURE_LIMIT if max_files is None else max(1, max_files)
        directory = Path(cls.CAPTURE_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".png"):
            safe_name += ".png"
        destination = directory / safe_name

        capture_metadata = []
        for path in directory.glob("*.png"):
            if path == destination:
                continue
            try:
                capture_metadata.append((path.stat().st_mtime, path))
            except OSError:
                continue
        captures = [
            path
            for _modified, path in sorted(
                capture_metadata,
                key=lambda item: item[0],
                reverse=True,
            )
        ]
        for stale in captures[max(0, limit - 1):]:
            try:
                stale.unlink()
            except OSError:
                continue
        return destination
