"""Redacted application diagnostics and mutable-data freshness inspection."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
from typing import Callable, Optional, cast
from urllib.parse import urlparse

import requests

from utils.app_paths import resolve_app_directories
from utils.config import ConfigManager
from utils.workers import WorkerContext, bounded_http_request


MAX_CACHE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class CacheTarget:
    key: str
    label: str
    path: Path
    kind: str
    source: str
    stale_after: timedelta
    clearable: bool = False


class DiagnosticsService:
    """Collect diagnostics without returning account names, tokens, or cache data."""

    def __init__(
        self,
        config: dict,
        *,
        trade_service=None,
        runtime_provider: Optional[Callable[[], dict]] = None,
        project_root=None,
        cache_targets: Optional[list[CacheTarget]] = None,
        now: Optional[Callable[[], datetime]] = None,
        devtools_probe: Optional[Callable[[WorkerContext], tuple[bool, str]]] = None,
    ):
        self.config = config
        self.trade_service = trade_service
        self.runtime_provider = runtime_provider or (lambda: {})
        self.project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.now = now or datetime.now
        self.app_directories = resolve_app_directories()
        self.cache_targets = cache_targets or self._default_cache_targets()
        self._target_by_key = {target.key: target for target in self.cache_targets}
        self._dependency_results = self._unknown_dependencies()
        self._dependency_tested_at = None
        self.devtools_probe = devtools_probe or self._probe_devtools

    def _default_cache_targets(self) -> list[CacheTarget]:
        return [
            CacheTarget(
                key="price-user",
                label="Price cache (per-user)",
                path=self.app_directories.cache_dir / "price_cache.json",
                kind="price",
                source="poe.ninja runtime cache",
                stale_after=timedelta(hours=4),
                clearable=True,
            ),
            CacheTarget(
                key="dust-user",
                label="Dust cache (per-user)",
                path=self.app_directories.cache_dir / "dust_cache.json",
                kind="dust",
                source="dust runtime cache",
                stale_after=timedelta(hours=24),
                clearable=True,
            ),
            CacheTarget(
                key="price-root",
                label="Price cache (project root)",
                path=self.project_root / "price_cache.json",
                kind="price",
                source="poe.ninja legacy cache",
                stale_after=timedelta(hours=4),
            ),
            CacheTarget(
                key="price-src",
                label="Price cache (src legacy)",
                path=self.project_root / "src" / "price_cache.json",
                kind="price",
                source="poe.ninja legacy cache",
                stale_after=timedelta(hours=4),
            ),
            CacheTarget(
                key="dust-root",
                label="Dust cache (project root)",
                path=self.project_root / "dust_cache.json",
                kind="dust",
                source="PoEDB legacy cache",
                stale_after=timedelta(hours=24),
            ),
        ]

    @staticmethod
    def _unknown_dependencies() -> dict:
        return {
            key: {"ready": None, "detail": "not tested"}
            for key in ("node", "npm", "npm_dependencies", "tesseract", "devtools")
        }

    def _runtime_state(self) -> dict:
        try:
            state = self.runtime_provider() or {}
        except Exception as error:
            state = {"last_error": f"Runtime diagnostics failed: {error}"}
        workers = [str(name) for name in state.get("workers", [])]
        zone = state.get("zone_monitor")
        if not isinstance(zone, dict):
            zone = {
                "state": "not running",
                "zone": "Unknown",
            }
        return {
            "trade_service": (
                "running"
                if self.trade_service is not None and self.trade_service.is_running
                else "stopped"
            ),
            "workers": workers,
            "zone_monitor": {
                "state": str(zone.get("state", "not running")),
                "zone": str(zone.get("zone", "Unknown")),
            },
            "last_error": str(
                state.get("last_error")
                or ConfigManager.last_error
                or ""
            ),
        }

    def _redact(self, value):
        """Recursively remove configured credential values from diagnostics."""
        sensitive_values = tuple(
            secret
            for secret in (
                ConfigManager.get_session_id(self.config).strip(),
                ConfigManager.get_account_name(self.config).strip(),
            )
            if secret
        )
        if isinstance(value, str):
            for secret in sensitive_values:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        return value

    def _redact_home_path(self, value):
        """Contract the local home path in exported diagnostics only."""
        home = str(Path.home())
        if isinstance(value, str):
            return value.replace(home, "~") if home else value
        if isinstance(value, dict):
            return {key: self._redact_home_path(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_home_path(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_home_path(item) for item in value)
        return value

    def _inspect_cache(self, target: CacheTarget) -> dict:
        result = {
            "key": target.key,
            "label": target.label,
            "kind": target.kind,
            "path": str(target.path),
            "exists": target.path.is_file(),
            "source": target.source,
            "timestamp": None,
            "age_seconds": None,
            "stale": None,
            "schema": "unknown",
            "league": "unknown",
            "item_count": 0,
            "error": "",
            "clearable": target.clearable,
        }
        if not result["exists"]:
            return result

        try:
            if target.path.stat().st_size > MAX_CACHE_BYTES:
                raise ValueError("cache exceeds the 2 MiB diagnostics limit")
            with target.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("cache root must be a JSON object")
        except json.JSONDecodeError:
            result["error"] = "invalid JSON"
            return result
        except (OSError, ValueError) as error:
            result["error"] = str(error)
            return result

        source = payload.get("source") or target.source
        result["source"] = (
            str(source)[:200]
            if isinstance(source, (str, int, float))
            else target.source
        )
        schema = payload.get(
            "schema_version",
            payload.get("config_schema_version", "legacy/unversioned"),
        )
        result["schema"] = (
            schema if isinstance(schema, (int, float)) else str(schema)[:200]
        ) if isinstance(schema, (str, int, float)) else "invalid"
        league = payload.get("league") or "unknown"
        result["league"] = (
            str(league)[:200]
            if isinstance(league, (str, int, float))
            else "unknown"
        )

        collection_key = "prices" if target.kind == "price" else "dust_values"
        collection = payload.get(collection_key, {})
        if isinstance(collection, dict):
            result["item_count"] = len(collection)

        timestamp_text = payload.get("timestamp")
        if timestamp_text:
            try:
                timestamp = datetime.fromisoformat(str(timestamp_text))
                current = self.now()
                if timestamp.tzinfo is not None and current.tzinfo is None:
                    current = current.astimezone(timestamp.tzinfo)
                elif timestamp.tzinfo is None and current.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=current.tzinfo)
                age = max(0, int((current - timestamp).total_seconds()))
                result["timestamp"] = timestamp.isoformat()
                result["age_seconds"] = age
                result["stale"] = age > int(target.stale_after.total_seconds())
            except (TypeError, ValueError):
                result["error"] = "invalid cache timestamp"
        else:
            result["error"] = "cache timestamp missing"
        return result

    def collect_snapshot(self) -> dict:
        game_id = ConfigManager.get_active_game(self.config)
        client_log = Path(ConfigManager.get_client_log_path(self.config)).expanduser()
        runtime = self._runtime_state()
        snapshot = {
            "generated_at": self.now().isoformat(),
            "application": {
                "active_game": game_id,
                "active_league": ConfigManager.get_game_league(self.config, game_id),
            },
            "credentials": {
                "account": (
                    "configured"
                    if ConfigManager.get_account_name(self.config).strip()
                    else "not configured"
                ),
                "session": (
                    "configured"
                    if ConfigManager.get_session_id(self.config).strip()
                    else "not configured"
                ),
                "validation": "not tested",
            },
            "dependencies": {
                "tested_at": self._dependency_tested_at,
                "items": self._dependency_results,
            },
            "runtime": runtime,
            "paths": {
                "project": str(self.project_root),
                "config_file": str(ConfigManager.USER_CONFIG_FILE),
                "config_dir": str(self.app_directories.config_dir),
                "cache_dir": str(self.app_directories.cache_dir),
                "data_dir": str(self.app_directories.data_dir),
                "log_dir": str(self.app_directories.log_dir),
                "profile_dir": str(self.app_directories.profile_dir),
                "client_log": str(client_log) if str(client_log) != "." else "",
                "client_log_exists": client_log.is_file() if str(client_log) != "." else False,
            },
            "caches": [self._inspect_cache(target) for target in self.cache_targets],
        }
        return cast(dict, self._redact(snapshot))

    def _probe_devtools(self, context: WorkerContext) -> tuple[bool, str]:
        game_id = ConfigManager.get_active_game(self.config)
        expected_url = urlparse(ConfigManager.get_trade_url(self.config, game_id))
        expected_host = (expected_url.hostname or "").lower()
        expected_path = expected_url.path.rstrip("/")
        session = requests.Session()
        session.trust_env = False
        try:
            version_response = bounded_http_request(
                session,
                "GET",
                "http://127.0.0.1:9222/json/version",
                token=context.token,
                timeout=(0.5, 1.5),
            )
            version_response.raise_for_status()
            version = version_response.json()
            targets_response = bounded_http_request(
                session,
                "GET",
                "http://127.0.0.1:9222/json",
                token=context.token,
                timeout=(0.5, 1.5),
            )
            targets_response.raise_for_status()
            targets = targets_response.json()
        except (requests.RequestException, ValueError, TypeError):
            return False, "DevTools unavailable on 127.0.0.1:9222"
        finally:
            session.close()

        if not isinstance(version, dict) or not version.get("webSocketDebuggerUrl"):
            return False, "port 9222 is not a DevTools browser endpoint"
        for target in targets if isinstance(targets, list) else []:
            if target.get("type") != "page":
                continue
            target_url = urlparse(str(target.get("url", "")))
            path = target_url.path.rstrip("/")
            host_matches = (target_url.hostname or "").lower() == expected_host
            if host_matches and (
                path == expected_path or path.startswith(f"{expected_path}/")
            ):
                browser = version.get("Browser", "Chromium")
                return True, f"{browser}: compatible trade tab ready"
        return False, "DevTools connected; compatible trade tab not found"

    def collect_dependencies(self, context: WorkerContext) -> dict:
        context.report_progress("Checking Node.js and npm")
        if self.trade_service is not None:
            node_version, npm_version = self.trade_service.check_dependencies(context.token)
            service_dir = Path(self.trade_service.service_dir)
        else:
            node_version, npm_version = None, None
            service_dir = self.project_root / "trade_service"
        context.token.raise_if_cancelled()

        configured_tesseract = str(
            self.config.get("league_vision", {}).get("tesseract_path", "tesseract")
        ).strip() or "tesseract"
        tesseract_path = Path(configured_tesseract).expanduser()
        if tesseract_path.is_absolute() or tesseract_path.parent != Path("."):
            resolved_tesseract = str(tesseract_path) if tesseract_path.is_file() else None
        else:
            resolved_tesseract = shutil.which(configured_tesseract)

        context.report_progress("Checking local DevTools endpoint")
        devtools_ready, devtools_detail = self.devtools_probe(context)
        context.token.raise_if_cancelled()

        results = {
            "node": {
                "ready": bool(node_version),
                "detail": node_version or "not found",
            },
            "npm": {
                "ready": bool(npm_version),
                "detail": npm_version or "not found",
            },
            "npm_dependencies": {
                "ready": (service_dir / "node_modules").is_dir(),
                "detail": str(service_dir / "node_modules"),
            },
            "tesseract": {
                "ready": bool(resolved_tesseract),
                "detail": resolved_tesseract or "not found",
            },
            "devtools": {
                "ready": bool(devtools_ready),
                "detail": str(devtools_detail),
            },
        }
        self._dependency_results = results
        self._dependency_tested_at = self.now().isoformat()
        return results

    def clear_cache(self, key: str) -> bool:
        target = self._target_by_key.get(key)
        if target is None:
            raise KeyError(f"Unknown cache target: {key}")
        if not target.clearable:
            raise PermissionError(f"Cache target is display-only: {key}")
        if not target.path.exists():
            return False
        target.path.unlink()
        return True

    def clear_existing_caches(self) -> list[str]:
        removed = []
        for target in self.cache_targets:
            if target.clearable and self.clear_cache(target.key):
                removed.append(target.key)
        return removed

    def export_redacted(self, path, snapshot: Optional[dict] = None) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self._redact(snapshot or self.collect_snapshot())
        payload = self._redact_home_path(payload)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination
