"""Application-owned centralized price service."""

from threading import Lock, RLock

from PyQt6.QtCore import QObject, pyqtSignal

from core.valuation import NinjaPriceFetcher, PriceFetchResult
from utils.workers import WorkerRegistry


class PriceService(QObject):
    """Own one active game/league price snapshot and its refresh worker."""

    prices_updated = pyqtSignal()
    refresh_completed = pyqtSignal(object)
    refresh_failed = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(
        self,
        game: str = "poe1",
        league: str = "Standard",
        *,
        fetcher_factory=None,
        worker_registry=None,
    ):
        super().__init__()
        self.game = game
        self.league = league
        self.fetcher_factory = fetcher_factory or NinjaPriceFetcher
        self._worker_registry = worker_registry or WorkerRegistry(max_threads=1)
        self._fetcher = None
        self._lock = RLock()
        self._load_lock = Lock()
        self.last_result: PriceFetchResult | None = None
        self.last_error = None

    def set_context(self, game: str, league: str) -> bool:
        """Switch active context and invalidate any incompatible in-memory data."""
        with self._lock:
            changed = (self.game, self.league) != (game, league)
            if changed:
                old_fetcher = self._fetcher
                self.game = game
                self.league = league
                self._fetcher = None
                self.last_result = None
                self.last_error = None
                if old_fetcher is not None and hasattr(old_fetcher, "close"):
                    old_fetcher.close()
        if changed:
            self._worker_registry.cancel("price-refresh")
        return changed

    def set_league(self, league: str):
        """Compatibility wrapper for PoE 1 callers."""
        return self.set_context(self.game, league)

    def _new_fetcher(self, game=None, league=None):
        return self.fetcher_factory(
            league if league is not None else self.league,
            game=game if game is not None else self.game,
        )

    @staticmethod
    def _can_replace_active(fetcher, result) -> bool:
        if result.status == "failure":
            return False
        return fetcher is None or result.status in {"cache", "success"}

    def get_fetcher(self, *, force=False, context=None) -> NinjaPriceFetcher:
        """Return the active snapshot, loading it once for this context."""
        with self._load_lock:
            for _attempt in range(3):
                with self._lock:
                    if self._fetcher is not None and not force:
                        return self._fetcher
                    game, league = self.game, self.league

                fetcher = self._new_fetcher(game, league)
                try:
                    result = fetcher.fetch_all_prices(force=force, context=context)
                except BaseException:
                    if hasattr(fetcher, "close"):
                        fetcher.close()
                    raise

                with self._lock:
                    if (game, league) != (self.game, self.league):
                        if hasattr(fetcher, "close"):
                            fetcher.close()
                        force = False
                        continue

                    old_fetcher = self._fetcher
                    self.last_result = result
                    self.last_error = (
                        result.detail if result.status == "failure" else None
                    )
                    if not self._can_replace_active(old_fetcher, result):
                        if hasattr(fetcher, "close"):
                            fetcher.close()
                        return old_fetcher if old_fetcher is not None else fetcher

                    self._fetcher = fetcher
                    if (
                        old_fetcher is not None
                        and old_fetcher is not fetcher
                        and hasattr(old_fetcher, "close")
                    ):
                        old_fetcher.close()
                    return fetcher
            raise RuntimeError("Price context changed repeatedly while loading")

    def get_price(self, item_name: str) -> float | None:
        return self.get_fetcher().get_price(item_name)

    def refresh_prices(self, force: bool = True) -> bool:
        """Refresh in the shared cancellable worker registry."""
        game = self.game
        league = self.league

        def operation(context):
            self.log.emit(f"Refreshing {game}/{league} prices from poe.ninja...")
            fetcher = self.fetcher_factory(league, game=game)
            try:
                result = fetcher.fetch_all_prices(force=force, context=context)
                return game, league, fetcher, result
            except BaseException:
                if hasattr(fetcher, "close"):
                    fetcher.close()
                raise

        return self._worker_registry.start(
            "price-refresh",
            operation,
            on_result=self._on_refresh_result,
            on_error=self._on_refresh_error,
        )

    def _on_refresh_result(self, payload):
        game, league, fetcher, result = payload
        with self._lock:
            if (game, league) != (self.game, self.league):
                if hasattr(fetcher, "close"):
                    fetcher.close()
                return
            old_fetcher = self._fetcher
            self.last_result = result
            self.last_error = None if result.status != "failure" else result.detail
            if not self._can_replace_active(old_fetcher, result):
                if hasattr(fetcher, "close"):
                    fetcher.close()
                fetcher = old_fetcher
            else:
                self._fetcher = fetcher
            if old_fetcher is not None and old_fetcher is not fetcher and hasattr(old_fetcher, "close"):
                old_fetcher.close()
        self.prices_updated.emit()
        self.refresh_completed.emit(result)
        self.log.emit(
            f"Price refresh {result.status}: {result.item_count} items"
        )

    def _on_refresh_error(self, error):
        self.last_error = getattr(error, "message", str(error))
        self.refresh_failed.emit(self.last_error)
        self.log.emit(f"Price refresh failed: {self.last_error}")

    def runtime_state(self) -> dict:
        result = self.last_result
        return {
            "game": self.game,
            "league": self.league,
            "status": result.status if result else "not loaded",
            "item_count": result.item_count if result else 0,
            "source": result.source if result else "poe.ninja",
            "fetched_at": result.fetched_at if result else None,
            "last_error": self.last_error,
        }

    def close(self, timeout_ms=5000) -> bool:
        closed = self._worker_registry.close(timeout_ms=timeout_ms)
        if not closed:
            return False
        with self._lock:
            if self._fetcher is not None and hasattr(self._fetcher, "close"):
                self._fetcher.close()
            self._fetcher = None
        return True
