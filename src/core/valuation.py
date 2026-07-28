"""League-aware price fetching, caching, and explicit fetch outcomes."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Mapping

import requests

from utils.app_paths import resolve_runtime_paths
from utils.workers import bounded_http_request


_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: dict[str, threading.RLock] = {}


def _cache_thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _CACHE_LOCKS_GUARD:
        return _CACHE_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _exclusive_cache_write(destination: Path):
    """Serialize cache read/modify/write across threads and processes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock_path = destination.with_name(f"{destination.name}.lock")
    thread_lock = _cache_thread_lock(lock_path)
    with thread_lock:
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class PriceFetchResult:
    """Outcome from loading or refreshing a price snapshot."""

    status: str
    game: str
    league: str
    source: str
    item_count: int
    failed_endpoints: tuple[str, ...] = ()
    from_cache: bool = False
    used_stale_cache: bool = False
    cache_saved: bool = False
    fetched_at: str | None = None
    detail: str = ""

    @property
    def successful(self) -> bool:
        return self.status in {"cache", "success"}


class PriceCache:
    """Store keyed price snapshots in one guarded per-user JSON file."""

    SCHEMA_VERSION = 2

    def __init__(
        self,
        cache_file=None,
        cache_duration_hours=4,
        *,
        game="poe1",
        league="unknown",
        source="poe.ninja",
        endpoint_set="overview-v1",
        now_provider=None,
    ):
        if cache_file is None:
            cache_file = resolve_runtime_paths().prepare_price_cache()
        self.cache_file = str(cache_file)
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.game = str(game)
        self.league = str(league)
        self.source = str(source)
        self.endpoint_set = str(endpoint_set)
        self.now_provider = now_provider or datetime.now
        self.last_error = None

    @property
    def entry_key(self) -> str:
        return json.dumps(
            [
                self.game,
                self.league,
                self.source,
                self.endpoint_set,
                self.SCHEMA_VERSION,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )

    def _read_store(self) -> dict | None:
        path = Path(self.cache_file)
        if not path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "entries": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            self.last_error = f"Price cache read failed: {error}"
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.SCHEMA_VERSION
            or not isinstance(payload.get("entries"), dict)
        ):
            self.last_error = "Price cache schema is unsupported"
            return None
        return payload

    @staticmethod
    def _valid_prices(prices) -> bool:
        return isinstance(prices, dict) and all(
            isinstance(name, str)
            and name
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
            for name, value in prices.items()
        )

    def _validate_entry(self, entry) -> bool:
        if not isinstance(entry, dict):
            return False
        metadata = entry.get("metadata")
        categories = entry.get("categories")
        if not isinstance(metadata, dict) or not isinstance(categories, dict):
            return False
        expected = {
            "game": self.game,
            "league": self.league,
            "source": self.source,
            "endpoint_set": self.endpoint_set,
            "schema_version": self.SCHEMA_VERSION,
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            return False
        if not isinstance(metadata.get("timestamp"), str):
            return False
        if not self._valid_prices(entry.get("prices")):
            return False
        return all(isinstance(key, str) and isinstance(value, str) for key, value in categories.items())

    def load(self, allow_stale=False):
        self.last_error = None
        store = self._read_store()
        if store is None:
            return None
        entry = store["entries"].get(self.entry_key)
        if entry is None:
            return None
        if not self._validate_entry(entry):
            self.last_error = "Price cache entry failed schema validation"
            return None
        try:
            timestamp = datetime.fromisoformat(entry["metadata"]["timestamp"])
        except ValueError as error:
            self.last_error = f"Price cache timestamp is invalid: {error}"
            return None
        stale = self.now_provider() - timestamp > self.cache_duration
        if stale and not allow_stale:
            return None
        loaded = dict(entry)
        loaded["stale"] = stale
        return loaded

    def _atomic_write(self, payload: dict) -> bool:
        destination = Path(self.cache_file)
        temporary = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            temporary = None
            if os.name != "nt":
                directory_fd = os.open(
                    destination.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return True
        except (OSError, TypeError, ValueError) as error:
            self.last_error = f"Price cache write failed: {error}"
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _preserve_legacy_v1(self) -> bool:
        """Preserve a valid unkeyed v1 cache before replacing it."""
        source = Path(self.cache_file)
        if not source.is_file():
            return True
        try:
            legacy_bytes = source.read_bytes()
            payload = json.loads(legacy_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        if not (
            isinstance(payload, dict)
            and "schema_version" not in payload
            and isinstance(payload.get("timestamp"), str)
            and self._valid_prices(payload.get("prices"))
            and isinstance(payload.get("categories", {}), dict)
        ):
            return True

        backup = source.with_name(f"{source.name}.legacy-v1")
        if backup.exists():
            try:
                if backup.read_bytes() == legacy_bytes:
                    return True
            except OSError:
                pass
            suffix = 1
            while backup.exists():
                backup = source.with_name(f"{source.name}.legacy-v1.{suffix}")
                suffix += 1

        temporary = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{backup.name}.",
                suffix=".tmp",
                dir=backup.parent,
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(legacy_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, backup)
            temporary = None
            if os.name != "nt":
                directory_fd = os.open(
                    backup.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return backup.read_bytes() == legacy_bytes
        except OSError as error:
            self.last_error = f"Legacy price cache backup failed: {error}"
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def save(self, prices, categories, *, status="success", failed_endpoints=()):
        self.last_error = None
        if not self._valid_prices(prices) or not isinstance(categories, dict):
            self.last_error = "Price cache data failed schema validation"
            return False
        destination = Path(self.cache_file)
        try:
            with _exclusive_cache_write(destination):
                store = self._read_store()
                if store is None:
                    # A malformed cache must not make in-memory data unusable. It is
                    # regenerated only by a complete successful fetch.
                    if not self._preserve_legacy_v1():
                        return False
                    store = {"schema_version": self.SCHEMA_VERSION, "entries": {}}
                timestamp = self.now_provider().isoformat()
                store["entries"][self.entry_key] = {
                    "metadata": {
                        "schema_version": self.SCHEMA_VERSION,
                        "game": self.game,
                        "league": self.league,
                        "source": self.source,
                        "endpoint_set": self.endpoint_set,
                        "timestamp": timestamp,
                        "status": status,
                        "failed_endpoints": list(failed_endpoints),
                        "item_count": len(prices),
                    },
                    "prices": dict(prices),
                    "categories": dict(categories),
                }
                return self._atomic_write(store)
        except OSError as error:
            self.last_error = f"Price cache lock failed: {error}"
            return False


class NinjaPriceFetcher:
    """Fetch poe.ninja prices with bounded requests and explicit outcomes."""

    BASE_URL = "https://poe.ninja/api/data"
    SOURCE = "poe.ninja"
    ENDPOINT_SET = "overview-v1"
    REQUEST_TIMEOUT = 15

    ENDPOINTS = {
        "Currency": "currencyoverview?type=Currency",
        "Fragment": "currencyoverview?type=Fragment",
        "DivinationCard": "itemoverview?type=DivinationCard",
        "UniqueWeapon": "itemoverview?type=UniqueWeapon",
        "UniqueArmour": "itemoverview?type=UniqueArmour",
        "UniqueAccessory": "itemoverview?type=UniqueAccessory",
        "UniqueFlask": "itemoverview?type=UniqueFlask",
        "UniqueJewel": "itemoverview?type=UniqueJewel",
        "Invitation": "itemoverview?type=Invitation",
    }

    def __init__(
        self,
        league: str,
        cache: PriceCache | None = None,
        *,
        game="poe1",
        session=None,
        endpoints: Mapping[str, str] | None = None,
        rate_limit_seconds=1.0,
    ):
        self.game = game
        self.league = league
        self.endpoints = dict(endpoints or self.ENDPOINTS)
        self.cache = cache or PriceCache(
            game=game,
            league=league,
            source=self.SOURCE,
            endpoint_set=self.ENDPOINT_SET,
        )
        self.prices = {}
        self.categories = {}
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))
        self.last_result = None
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def _request(self, url, context=None):
        if context is not None:
            return bounded_http_request(
                self.session,
                "GET",
                url,
                token=context.token,
                timeout=self.REQUEST_TIMEOUT,
                verify=True,
            )
        return self.session.get(
            url,
            timeout=self.REQUEST_TIMEOUT,
            verify=True,
        )

    def _wait(self, context=None):
        if self.rate_limit_seconds <= 0:
            return
        if context is not None:
            context.sleep(self.rate_limit_seconds)
        else:
            time.sleep(self.rate_limit_seconds)

    def _apply_entry(self, entry):
        self.prices = dict(entry.get("prices", {}))
        self.categories = dict(entry.get("categories", {}))

    def fetch_all_prices(self, force=False, context=None) -> PriceFetchResult:
        if not force:
            cached = self.cache.load()
            if cached is not None:
                self._apply_entry(cached)
                metadata = cached["metadata"]
                self.last_result = PriceFetchResult(
                    status="cache",
                    game=self.game,
                    league=self.league,
                    source=self.SOURCE,
                    item_count=len(self.prices),
                    from_cache=True,
                    fetched_at=metadata.get("timestamp"),
                )
                return self.last_result

        all_prices = {}
        all_categories = {}
        failed = []
        for category, endpoint in self.endpoints.items():
            try:
                if context is not None:
                    context.raise_if_cancelled()
                self._wait(context)
                url = f"{self.BASE_URL}/{endpoint}&league={self.league}"
                response = self._request(url, context)
                response.raise_for_status()
                data = response.json()
                lines = data.get("lines", [])
                if not isinstance(lines, list):
                    raise ValueError("response lines must be a list")
                for line in lines:
                    if not isinstance(line, dict):
                        continue
                    name = line.get("currencyTypeName") or line.get("name")
                    if "chaosEquivalent" in line:
                        price = line.get("chaosEquivalent")
                    else:
                        price = line.get("chaosValue")
                    if (
                        isinstance(name, str)
                        and name
                        and not isinstance(price, bool)
                        and isinstance(price, (int, float))
                        and math.isfinite(price)
                        and price >= 0
                    ):
                        all_prices[name] = float(price)
                        all_categories[name] = category
            except (requests.RequestException, OSError, ValueError, TypeError, json.JSONDecodeError):
                failed.append(category)

        if all_prices and "Chaos Orb" not in all_prices:
            all_prices["Chaos Orb"] = 1.0
            all_categories["Chaos Orb"] = "Currency"

        status = "success" if all_prices and not failed else "partial" if all_prices else "failure"
        cache_saved = False
        used_stale = False
        fetched_at = None

        if status == "success":
            cache_saved = self.cache.save(all_prices, all_categories, status=status)
            self.prices = all_prices
            self.categories = all_categories
            loaded = self.cache.load(allow_stale=True)
            if loaded:
                fetched_at = loaded["metadata"].get("timestamp")
        elif status == "partial":
            self.prices = all_prices
            self.categories = all_categories
        else:
            stale = self.cache.load(allow_stale=True)
            if stale is not None:
                self._apply_entry(stale)
                used_stale = True
                fetched_at = stale["metadata"].get("timestamp")
            else:
                self.prices = {}
                self.categories = {}

        self.last_result = PriceFetchResult(
            status=status,
            game=self.game,
            league=self.league,
            source=self.SOURCE,
            item_count=len(self.prices),
            failed_endpoints=tuple(failed),
            used_stale_cache=used_stale,
            cache_saved=cache_saved,
            fetched_at=fetched_at,
            detail=("Complete refresh" if status == "success" else
                    "Partial refresh; last-known-good cache was not replaced" if status == "partial" else
                    "Refresh failed"),
        )
        return self.last_result

    def get_price(self, item_name: str) -> float | None:
        if not isinstance(item_name, str):
            return None
        value = self.prices.get(item_name)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def close(self):
        if self._owns_session:
            self.session.close()
