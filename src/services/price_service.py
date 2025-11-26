"""
Centralized price fetching service.
"""

import os
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from core.valuation import NinjaPriceFetcher, PriceCache


class PriceRefreshWorker(QThread):
    """Background worker for refreshing prices."""
    
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(object)  # Emits the price fetcher
    
    def __init__(self, league: str, cache_path: str = 'price_cache.json'):
        super().__init__()
        self.league = league
        self.cache_path = cache_path
        
    def run(self):
        self.log_signal.emit("Fetching fresh prices from poe.ninja...")
        
        # Force cache invalidation
        if os.path.exists(self.cache_path):
            try:
                os.remove(self.cache_path)
                self.log_signal.emit("Cache cleared.")
            except Exception as e:
                self.log_signal.emit(f"Error clearing cache: {e}")
        
        fetcher = NinjaPriceFetcher(self.league, PriceCache(self.cache_path))
        fetcher.fetch_all_prices()
        self.log_signal.emit(f"Prices updated: {len(fetcher.prices)} items.")
        self.finished_signal.emit(fetcher)


class PriceService(QObject):
    """
    Centralized service for fetching and caching prices.
    Can be shared across multiple tools.
    """
    
    prices_updated = pyqtSignal()
    log = pyqtSignal(str)
    
    def __init__(self, league: str = "Settlers"):
        super().__init__()
        self.league = league
        self._fetcher = None
        self._worker = None
    
    def set_league(self, league: str):
        """Set the league for price fetching."""
        self.league = league
    
    def get_fetcher(self) -> NinjaPriceFetcher:
        """Get the current price fetcher, creating one if needed."""
        if not self._fetcher:
            self._fetcher = NinjaPriceFetcher(self.league)
            self._fetcher.fetch_all_prices()
        return self._fetcher
    
    def get_price(self, item_name: str) -> float:
        """Get the price of an item."""
        fetcher = self.get_fetcher()
        return fetcher.get_price(item_name)
    
    def refresh_prices(self, force: bool = False):
        """Refresh prices in background."""
        if self._worker and self._worker.isRunning():
            return
        
        self._worker = PriceRefreshWorker(self.league)
        self._worker.log_signal.connect(lambda msg: self.log.emit(msg))
        self._worker.finished_signal.connect(self._on_refresh_complete)
        self._worker.start()
    
    def _on_refresh_complete(self, fetcher):
        self._fetcher = fetcher
        self.prices_updated.emit()

