"""
Stash scanner for Kalguur Dust tool.

Scans stash tabs via PoE API to find unique items and calculate their dust efficiency.
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from PyQt6.QtCore import QThread, pyqtSignal

from api.auth import SessionAuthProvider
from api.client import PoEClient
from .dust_data import DustEfficiencyAnalyzer
from utils.workers import CancellationToken, CancelledError


@dataclass
class UniqueItemInfo:
    """Information about a unique item found in stash."""
    name: str
    base_type: str
    ilvl: int
    quality: int
    corrupted: bool
    tab_index: int
    tab_name: str
    x: int
    y: int
    w: int
    h: int
    is_quad: bool
    # Calculated values
    dust: int = 0
    chaos_price: Optional[float] = None
    efficiency: Optional[float] = None


# Tab types that are not supported by the PoE stash API
# See docs/API_LIMITATIONS.md for details
UNSUPPORTED_TAB_TYPES = {'UniqueStash'}


def _ctx_progress(context, value):
    if context is not None:
        context.report_progress(value)

def _ctx_sleep(context, seconds: float):
    if context is not None:
        context.sleep(seconds)
    else:
        time.sleep(seconds)

def _make_client(session_id: str, account: str, league: str) -> PoEClient:
    return PoEClient(SessionAuthProvider(session_id), account, league)

def fetch_tab_list_operation(session_id: str, account: str, league: str, context=None) -> list:
    client = _make_client(session_id, account, league)
    try:
        _ctx_progress(context, {"phase": "tab_fetch", "message": "Fetching stash tab list", "current": 0, "total": 1})
        tabs = client.get_stash_tab_list(context=context, rate_limit_callback=lambda p: _ctx_progress(context, {**p, "phase": "rate_limit", "operation": "tab_fetch"}))
        if not tabs:
            raise RuntimeError("No stash tabs were returned. Verify account name, POESESSID, and league, then Retry.")
        _ctx_progress(context, {"phase": "tab_fetch", "message": f"Fetched {len(tabs)} tabs", "current": 1, "total": 1})
        return tabs
    finally:
        client.close()

class StashItemProcessor:
    def __init__(self, dust_analyzer):
        self.dust_analyzer = dust_analyzer
    def get_tab_name(self, data: dict, tab_idx: int) -> str:
        for tab in data.get('tabs', []):
            if tab.get('i') == tab_idx:
                return tab.get('n', f'Tab {tab_idx}')
        return f'Tab {tab_idx}'
    def process_item(self, item: dict, tab_idx: int, tab_name: str, is_quad: bool) -> Optional[UniqueItemInfo]:
        if item.get('frameType', 0) != 3:
            return None
        name = item.get('name', '')
        if '>>' in name:
            name = name.split('>>')[-1]
        if not name:
            name = item.get('typeLine', 'Unknown')
        base_type = item.get('typeLine', '')
        ilvl = item.get('ilvl', 1)
        quality = 0
        for prop in item.get('properties', []):
            if prop.get('name') == 'Quality':
                values = prop.get('values', [[]])
                if values and values[0]:
                    try:
                        quality = int(values[0][0].replace('+','').replace('%',''))
                    except ValueError:
                        quality = 0
                break
        x = item.get('x', 0); y = item.get('y', 0); w = item.get('w', 1); h = item.get('h', 1)
        if self.dust_analyzer:
            eff_data = self.dust_analyzer.get_efficiency(name, ilvl, quality, item.get('corrupted', False))
            dust = eff_data['dust']; chaos_price = eff_data['chaos_price']; efficiency = eff_data['efficiency']
        else:
            dust = 0; chaos_price = None; efficiency = None
        return UniqueItemInfo(name, base_type, ilvl, quality, item.get('corrupted', False), tab_idx, tab_name, x, y, w, h, is_quad, dust, chaos_price, efficiency)

def scan_stash_operation(session_id: str, account: str, league: str, tab_indices: List[int], dust_analyzer: DustEfficiencyAnalyzer, min_efficiency: float = 1.0, debug_mode: bool = False, context=None, log_callback=None, debug_callback=None):
    def log(message):
        _ctx_progress(context, {"phase": "scan_log", "message": message})
        if log_callback:
            log_callback(message)
    def debug(message):
        if debug_mode:
            _ctx_progress(context, {"phase": "scan_debug", "message": message})
        if debug_mode and debug_callback:
            debug_callback(message)
    client = _make_client(session_id, account, league)
    processor = StashItemProcessor(dust_analyzer)
    all_items: List[UniqueItemInfo] = []
    stats = {'total_uniques': 0, 'valuable_uniques': 0, 'total_dust': 0, 'tabs_with_items': set()}
    total_tabs = len(tab_indices)
    failed_tabs: list[str] = []
    fetched_tabs = 0
    try:
        log(f"Scanning {total_tabs} tabs for unique items...")
        for i, tab_idx in enumerate(tab_indices):
            if context is not None:
                context.raise_if_cancelled()
            log(f"Scanning tab {tab_idx} ({i+1}/{total_tabs})...")
            _ctx_progress(context, {"phase": "scan", "current": i + 1, "total": total_tabs, "tab_index": tab_idx, "message": f"Scanning tab {tab_idx}"})
            if i > 0:
                _ctx_progress(context, {"phase": "scan_wait", "current": i, "total": total_tabs, "seconds": 1.5, "message": "Respecting stash API rate limit"})
                _ctx_sleep(context, 1.5)
            try:
                data = client.get_stash_items(tab_idx, context=context, rate_limit_callback=lambda p: _ctx_progress(context, {**p, "phase": "rate_limit", "operation": "scan"}))
            except Exception as error:
                message = f"tab {tab_idx}: {error}"
                failed_tabs.append(message)
                log(f"Failed to fetch {message}")
                continue
            if 'items' not in data:
                message = f"tab {tab_idx}: API response did not include items"
                failed_tabs.append(message)
                log(f"Failed to fetch {message}")
                continue
            fetched_tabs += 1
            is_quad = data.get('quadLayout', False)
            tab_name = processor.get_tab_name(data, tab_idx)
            tab_type = 'unknown'
            for tab_meta in data.get('tabs', []):
                if tab_meta.get('i') == tab_idx:
                    tab_type = tab_meta.get('type', 'unknown')
                    break
            if tab_type in UNSUPPORTED_TAB_TYPES:
                log(f"  Skipping {tab_type} tab '{tab_name}' - not supported by PoE API")
                continue
            items_in_tab = 0; items_with_dust = 0; items_no_dust = []
            for item in data.get('items', []):
                if context is not None:
                    context.raise_if_cancelled()
                unique_info = processor.process_item(item, tab_idx, tab_name, is_quad)
                if unique_info:
                    stats['total_uniques'] += 1; items_in_tab += 1
                    if unique_info.dust == 0:
                        items_no_dust.append(unique_info.name)
                    else:
                        items_with_dust += 1
                    if unique_info.dust > 0 and (min_efficiency <= 0 or (unique_info.efficiency is not None and unique_info.efficiency >= min_efficiency)):
                        all_items.append(unique_info); stats['valuable_uniques'] += 1; stats['total_dust'] += unique_info.dust; stats['tabs_with_items'].add(tab_idx)
            debug(f"  Tab {tab_idx}: {items_in_tab} uniques, {items_with_dust} with dust data")
            if items_no_dust and len(items_no_dust) <= 10:
                debug(f"    No dust data: {', '.join(items_no_dust)}")
        if total_tabs and fetched_tabs == 0:
            detail = "; ".join(failed_tabs[:3]) or "all selected tabs returned invalid responses"
            raise RuntimeError(f"Every selected stash tab fetch failed ({total_tabs}/{total_tabs}). {detail}. Check credentials/league/network and Retry.")
        stats['failed_tabs'] = failed_tabs
        # C4: make rate-limit losses obvious so a rescan is clearly needed
        # instead of tabs disappearing as individual log lines.
        rate_limited = [m for m in failed_tabs if "429" in m or "rate limit" in m.lower()]
        stats['rate_limited_tabs'] = len(rate_limited)
        if rate_limited:
            log(
                f"WARNING: {len(rate_limited)}/{total_tabs} tab(s) were skipped due to PoE API "
                f"rate limiting. Wait a minute and rescan those tabs."
            )
        stats['tabs_with_items'] = list(stats['tabs_with_items'])
        all_items.sort(key=lambda item: item.efficiency if item.efficiency is not None else -1, reverse=True)
        log(f"Scan complete. Found {stats['valuable_uniques']} valuable uniques out of {stats['total_uniques']} total.")
        return all_items, stats
    finally:
        client.close()


class StashScanWorker(QThread):
    """Background worker for scanning stash tabs for unique items."""
    
    log_signal = pyqtSignal(str)
    debug_signal = pyqtSignal(str)  # Debug-only messages
    progress_signal = pyqtSignal(int, int)  # current, total
    result_signal = pyqtSignal(list, dict)  # items, stats
    
    def __init__(self, session_id: str, account: str, league: str,
                 tab_indices: List[int], dust_analyzer: DustEfficiencyAnalyzer,
                 min_efficiency: float = 1.0, debug_mode: bool = False):
        super().__init__()
        self.session_id = session_id
        self.account = account
        self.league = league
        self.tab_indices = tab_indices
        self.dust_analyzer = dust_analyzer
        self.min_efficiency = min_efficiency
        self.debug_mode = debug_mode
        self.tab_names: Dict[int, str] = {}  # index -> name mapping
    
    def run(self):
        """Main scan loop."""
        token = CancellationToken()
        class _Context:
            def __init__(self, outer):
                self.outer = outer; self.token = token
            def raise_if_cancelled(self):
                if self.outer.isInterruptionRequested():
                    raise CancelledError("Operation cancelled")
            def sleep(self, seconds):
                deadline = time.monotonic() + max(0.0, seconds)
                while time.monotonic() < deadline:
                    self.raise_if_cancelled()
                    time.sleep(min(0.05, deadline - time.monotonic()))
            def report_progress(self, value):
                if isinstance(value, dict) and value.get("phase") == "scan":
                    self.outer.progress_signal.emit(value.get("current", 0), value.get("total", 0))
        try:
            items, stats = scan_stash_operation(self.session_id, self.account, self.league, self.tab_indices, self.dust_analyzer, self.min_efficiency, self.debug_mode, context=_Context(self), log_callback=self.log_signal.emit, debug_callback=self.debug_signal.emit)
        except CancelledError:
            return
        self.result_signal.emit(items, stats)

    def _get_tab_name(self, data: dict, tab_idx: int) -> str:
        """Extract tab name from API response."""
        return StashItemProcessor(self.dust_analyzer).get_tab_name(data, tab_idx)
    
    def _process_item(self, item: dict, tab_idx: int, tab_name: str, 
                      is_quad: bool) -> Optional[UniqueItemInfo]:
        return StashItemProcessor(self.dust_analyzer).process_item(item, tab_idx, tab_name, is_quad)



class TabListWorker(QThread):
    """Fetches list of stash tabs."""
    
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)
    
    def __init__(self, session_id: str, account: str, league: str):
        super().__init__()
        self.session_id = session_id
        self.account = account
        self.league = league
    
    def run(self):
        try:
            tabs = fetch_tab_list_operation(self.session_id, self.account, self.league)
            self.finished_signal.emit(tabs)
        except Exception as e:
            self.error_signal.emit(str(e))


def group_items_by_tab(items: List[UniqueItemInfo]) -> Dict[str, List[UniqueItemInfo]]:
    """
    Group items by their tab name for multi-tab highlighting.
    
    Returns:
        Dict mapping tab_name -> list of items in that tab
    """
    grouped: Dict[str, List[UniqueItemInfo]] = {}
    
    for item in items:
        if item.tab_name not in grouped:
            grouped[item.tab_name] = []
        grouped[item.tab_name].append(item)
    
    return grouped


def items_to_highlights(items: List[UniqueItemInfo]) -> List[dict]:
    """
    Convert UniqueItemInfo list to highlight format for overlay.
    
    Returns:
        List of highlight dicts with position and metadata
    """
    highlights = []
    
    for item in items:
        highlights.append({
            'tab_index': item.tab_index,
            'tab_name': item.tab_name,
            'x': item.x,
            'y': item.y,
            'w': item.w,
            'h': item.h,
            'name': item.name,
            'is_quad': item.is_quad,
            'dust': item.dust,
            'efficiency': item.efficiency,
        })
    
    return highlights

