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
from .dust_data import DustDataFetcher, DustEfficiencyAnalyzer


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
    chaos_price: float = 0.0
    efficiency: float = 0.0


# Tab types that are not supported by the PoE stash API
# See docs/API_LIMITATIONS.md for details
UNSUPPORTED_TAB_TYPES = {'UniqueStash'}


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
        self.log_signal.emit("Initializing API client...")
        
        auth = SessionAuthProvider(self.session_id)
        client = PoEClient(auth, self.account, self.league)
        
        all_items: List[UniqueItemInfo] = []
        stats = {
            'total_uniques': 0,
            'valuable_uniques': 0,
            'total_dust': 0,
            'tabs_with_items': set(),
        }
        
        total_tabs = len(self.tab_indices)
        self.log_signal.emit(f"Scanning {total_tabs} tabs for unique items...")
        
        for i, tab_idx in enumerate(self.tab_indices):
            self.log_signal.emit(f"Scanning tab {tab_idx} ({i+1}/{total_tabs})...")
            self.progress_signal.emit(i + 1, total_tabs)
            
            # Rate limiting
            if i > 0:
                time.sleep(1.5)
            
            # Fetch tab data
            data = client.get_stash_items(tab_idx)
            if not data or 'items' not in data:
                self.log_signal.emit(f"Failed to fetch tab {tab_idx} - no items key")
                continue
            
            # Get tab metadata
            is_quad = data.get('quadLayout', False)
            tab_name = self._get_tab_name(data, tab_idx)
            self.tab_names[tab_idx] = tab_name
            
            items = data.get('items', [])
            
            # Get tab type from tab metadata
            tab_type = 'unknown'
            for tab_meta in data.get('tabs', []):
                if tab_meta.get('i') == tab_idx:
                    tab_type = tab_meta.get('type', 'unknown')
                    break
            
            # Skip unsupported tab types (see docs/API_LIMITATIONS.md)
            if tab_type in UNSUPPORTED_TAB_TYPES:
                self.log_signal.emit(f"  Skipping {tab_type} tab '{tab_name}' - not supported by PoE API")
                continue
            
            # Process items
            items_in_tab = 0
            items_with_dust = 0
            items_no_dust = []
            
            for item in items:
                unique_info = self._process_item(item, tab_idx, tab_name, is_quad)
                if unique_info:
                    stats['total_uniques'] += 1
                    items_in_tab += 1
                    
                    # Debug: Track items without dust data
                    if unique_info.dust == 0:
                        items_no_dust.append(unique_info.name)
                    else:
                        items_with_dust += 1
                    
                    # Check if meets efficiency threshold (must have dust data and valid efficiency)
                    if unique_info.dust > 0 and unique_info.efficiency >= self.min_efficiency:
                        all_items.append(unique_info)
                        stats['valuable_uniques'] += 1
                        stats['total_dust'] += unique_info.dust
                        stats['tabs_with_items'].add(tab_idx)
            
            # Debug logging for this tab
            if self.debug_mode:
                self.debug_signal.emit(f"  Tab {tab_idx}: {items_in_tab} uniques, {items_with_dust} with dust data")
                if items_no_dust and len(items_no_dust) <= 10:
                    self.debug_signal.emit(f"    No dust data: {', '.join(items_no_dust)}")
                elif items_no_dust:
                    self.debug_signal.emit(f"    No dust data: {len(items_no_dust)} items (first 5: {', '.join(items_no_dust[:5])}...)")
        
        # Convert sets to lists for JSON serialization
        stats['tabs_with_items'] = list(stats['tabs_with_items'])
        
        self.log_signal.emit(
            f"Scan complete. Found {stats['valuable_uniques']} valuable uniques "
            f"out of {stats['total_uniques']} total."
        )
        
        # Sort by efficiency (best first)
        all_items.sort(key=lambda x: x.efficiency, reverse=True)
        
        self.result_signal.emit(all_items, stats)
    
    def _get_tab_name(self, data: dict, tab_idx: int) -> str:
        """Extract tab name from API response."""
        tabs = data.get('tabs', [])
        for tab in tabs:
            if tab.get('i') == tab_idx:
                return tab.get('n', f'Tab {tab_idx}')
        return f'Tab {tab_idx}'
    
    def _process_item(self, item: dict, tab_idx: int, tab_name: str, 
                      is_quad: bool) -> Optional[UniqueItemInfo]:
        """
        Process a single item from stash API.
        
        Returns UniqueItemInfo if item is a unique, None otherwise.
        """
        # Check if unique (frameType 3 = unique)
        frame_type = item.get('frameType', 0)
        if frame_type != 3:
            return None
        
        # Extract item info
        name = item.get('name', '')
        # Remove prefix for uniques (e.g., "<<set:MS>><<set:M>><<set:S>>Goldrim")
        if '>>' in name:
            name = name.split('>>')[-1]
        
        # Some uniques don't have a name field, use typeLine
        if not name:
            name = item.get('typeLine', 'Unknown')
        
        base_type = item.get('typeLine', '')
        ilvl = item.get('ilvl', 1)
        
        # Get quality from properties
        quality = 0
        properties = item.get('properties', [])
        for prop in properties:
            if prop.get('name') == 'Quality':
                values = prop.get('values', [[]])
                if values and values[0]:
                    qual_str = values[0][0]
                    # Parse "+20%" format
                    qual_str = qual_str.replace('+', '').replace('%', '')
                    try:
                        quality = int(qual_str)
                    except ValueError:
                        quality = 0
                break
        
        corrupted = item.get('corrupted', False)
        
        # Position in stash
        x = item.get('x', 0)
        y = item.get('y', 0)
        w = item.get('w', 1)
        h = item.get('h', 1)
        
        # Calculate dust efficiency
        if self.dust_analyzer:
            eff_data = self.dust_analyzer.get_efficiency(
                name, ilvl, quality, corrupted
            )
            dust = eff_data['dust']
            chaos_price = eff_data['chaos_price']
            efficiency = eff_data['efficiency']
        else:
            dust = 0
            chaos_price = 0
            efficiency = 0
        
        return UniqueItemInfo(
            name=name,
            base_type=base_type,
            ilvl=ilvl,
            quality=quality,
            corrupted=corrupted,
            tab_index=tab_idx,
            tab_name=tab_name,
            x=x,
            y=y,
            w=w,
            h=h,
            is_quad=is_quad,
            dust=dust,
            chaos_price=chaos_price,
            efficiency=efficiency,
        )


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
            auth = SessionAuthProvider(self.session_id)
            client = PoEClient(auth, self.account, self.league)
            tabs = client.get_stash_tab_list()
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

