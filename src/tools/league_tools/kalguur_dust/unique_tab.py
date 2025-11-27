"""
Unique Tab workflow handler for Kalguur Dust tool.

Provides a clipboard-based workflow for collecting items from Unique Stash Tabs,
since standard grid highlighting doesn't work with the scrollable unique tab layout.
"""

import time
from enum import Enum, auto
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal, QThread

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False
    print("Warning: pyperclip not found. Clipboard integration disabled.")
    print("Install with: pip install pyperclip")

try:
    from pynput import mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


class WorkflowState(Enum):
    """States for the unique tab collection workflow."""
    IDLE = auto()
    WAITING_FOR_TAB = auto()      # Waiting for user to navigate to correct tab
    ITEM_COPIED = auto()          # Item name copied, waiting for user to paste/search
    WAITING_FOR_CLICK = auto()    # Waiting for user to click the result slot
    COMPLETE = auto()             # All items collected


@dataclass
class UniqueTabItem:
    """Item to collect from unique tab."""
    name: str
    category: str
    dust: int
    efficiency: float
    tab_name: str


@dataclass  
class CategoryPosition:
    """Position of a category icon in the unique tab grid."""
    row: int
    col: int
    x: int
    y: int
    width: int
    height: int


class ClipboardManager:
    """Manages clipboard operations for unique tab workflow."""
    
    @staticmethod
    def copy_item_name(name: str, with_quotes: bool = True) -> bool:
        """
        Copy item name to clipboard.
        
        Args:
            name: Item name to copy
            with_quotes: Whether to wrap in quotes for exact match
        
        Returns:
            True if successful, False otherwise
        """
        if not HAS_PYPERCLIP:
            return False
        
        try:
            text = f'"{name}"' if with_quotes else name
            pyperclip.copy(text)
            return True
        except Exception as e:
            print(f"Clipboard error: {e}")
            return False
    
    @staticmethod
    def get_clipboard() -> str:
        """Get current clipboard contents."""
        if not HAS_PYPERCLIP:
            return ""
        try:
            return pyperclip.paste()
        except:
            return ""


class ResultSlotMonitor(QThread):
    """
    Monitors for clicks in the result slot area of unique tabs.
    
    When user searches for an item, it appears in the top-left slot.
    This monitors for clicks in that area to detect item pickup.
    """
    
    click_detected = pyqtSignal()  # Emitted when click in result slot
    
    def __init__(self, result_slot: dict):
        """
        Args:
            result_slot: Dict with x, y, w, h defining the result slot area
        """
        super().__init__()
        self.result_slot = result_slot
        self.running = False
        self.listener = None
    
    def _is_in_result_slot(self, x: int, y: int) -> bool:
        """Check if coordinates are within the result slot."""
        rs = self.result_slot
        return (rs['x'] <= x <= rs['x'] + rs['w'] and
                rs['y'] <= y <= rs['y'] + rs['h'])
    
    def _on_click(self, x: int, y: int, button, pressed):
        """Handle mouse click events."""
        if pressed and button == mouse.Button.left:
            if self._is_in_result_slot(x, y):
                self.click_detected.emit()
    
    def run(self):
        """Main monitoring loop."""
        if not HAS_PYNPUT:
            return
        
        self.running = True
        self.listener = mouse.Listener(on_click=self._on_click)
        self.listener.start()
        
        while self.running:
            time.sleep(0.1)
        
        if self.listener:
            self.listener.stop()
    
    def stop(self):
        """Stop monitoring."""
        self.running = False


class UniqueTabWorkflow(QObject):
    """
    Manages the workflow for collecting items from unique stash tabs.
    
    Workflow:
    1. Copy item name to clipboard (with quotes for exact match)
    2. Highlight category icon if calibrated
    3. Wait for user to paste into search and click item
    4. Detect click, advance to next item
    5. Repeat until all items collected
    """
    
    # Signals
    state_changed = pyqtSignal(str)  # WorkflowState name
    item_changed = pyqtSignal(int, int, str)  # current_index, total, item_name
    category_highlight = pyqtSignal(str, dict)  # category_name, position_dict
    status_message = pyqtSignal(str)
    workflow_complete = pyqtSignal()
    
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        
        self.state = WorkflowState.IDLE
        self.items: List[UniqueTabItem] = []
        self.current_index = 0
        
        # Category positions from calibration
        self.category_positions: Dict[str, CategoryPosition] = {}
        
        # Result slot position from calibration
        self.result_slot = self.config.get('result_slot', {
            'x': 0, 'y': 0, 'w': 200, 'h': 200
        })
        
        # Click monitor
        self.click_monitor: Optional[ResultSlotMonitor] = None
        
        # Load category positions from config
        self._load_category_positions()
    
    def _load_category_positions(self):
        """Load category positions from config."""
        cat_config = self.config.get('category_positions', {})
        
        for category, pos in cat_config.items():
            self.category_positions[category] = CategoryPosition(
                row=pos.get('row', 0),
                col=pos.get('col', 0),
                x=pos.get('x', 0),
                y=pos.get('y', 0),
                width=pos.get('width', 50),
                height=pos.get('height', 50),
            )
    
    def set_items(self, items: List[UniqueTabItem]):
        """Set the items to collect."""
        self.items = items
        self.current_index = 0
        self._set_state(WorkflowState.IDLE)
    
    def _set_state(self, state: WorkflowState):
        """Update workflow state and emit signal."""
        self.state = state
        self.state_changed.emit(state.name)
    
    def start(self):
        """Start the collection workflow."""
        if not self.items:
            self.status_message.emit("No items to collect")
            return
        
        self.current_index = 0
        self._set_state(WorkflowState.ITEM_COPIED)
        
        # Start click monitor
        if HAS_PYNPUT:
            self.click_monitor = ResultSlotMonitor(self.result_slot)
            self.click_monitor.click_detected.connect(self._on_result_click)
            self.click_monitor.start()
        
        # Process first item
        self._process_current_item()
    
    def stop(self):
        """Stop the workflow."""
        if self.click_monitor:
            self.click_monitor.stop()
            self.click_monitor.wait()
            self.click_monitor = None
        
        self._set_state(WorkflowState.IDLE)
        self.status_message.emit("Workflow stopped")
    
    def _process_current_item(self):
        """Process the current item - copy to clipboard and highlight category."""
        if self.current_index >= len(self.items):
            self._complete()
            return
        
        item = self.items[self.current_index]
        
        # Copy item name to clipboard
        success = ClipboardManager.copy_item_name(item.name)
        
        if success:
            self.status_message.emit(
                f'Copied "{item.name}" to clipboard - paste into search bar'
            )
        else:
            self.status_message.emit(
                f'Item {self.current_index + 1}/{len(self.items)}: {item.name}'
            )
        
        # Emit item changed signal
        self.item_changed.emit(
            self.current_index + 1, 
            len(self.items), 
            item.name
        )
        
        # Highlight category if position is known
        if item.category in self.category_positions:
            pos = self.category_positions[item.category]
            self.category_highlight.emit(item.category, {
                'x': pos.x, 'y': pos.y, 
                'w': pos.width, 'h': pos.height
            })
        
        self._set_state(WorkflowState.WAITING_FOR_CLICK)
    
    def _on_result_click(self):
        """Handle click detected in result slot."""
        if self.state != WorkflowState.WAITING_FOR_CLICK:
            return
        
        # Advance to next item
        self.current_index += 1
        
        if self.current_index >= len(self.items):
            self._complete()
        else:
            self._set_state(WorkflowState.ITEM_COPIED)
            self._process_current_item()
    
    def manual_advance(self):
        """Manually advance to next item (for when click detection fails)."""
        self._on_result_click()
    
    def skip_item(self):
        """Skip the current item."""
        self.current_index += 1
        if self.current_index >= len(self.items):
            self._complete()
        else:
            self._process_current_item()
    
    def _complete(self):
        """Mark workflow as complete."""
        if self.click_monitor:
            self.click_monitor.stop()
            self.click_monitor.wait()
            self.click_monitor = None
        
        self._set_state(WorkflowState.COMPLETE)
        self.status_message.emit(f"Complete! Collected {len(self.items)} items")
        self.workflow_complete.emit()
    
    def get_current_item(self) -> Optional[UniqueTabItem]:
        """Get the current item being collected."""
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None
    
    def get_progress(self) -> tuple:
        """Get current progress as (current, total)."""
        return (self.current_index, len(self.items))


def create_unique_tab_items(items_from_scanner: list) -> List[UniqueTabItem]:
    """
    Convert scanner UniqueItemInfo items to UniqueTabItem for workflow.
    
    Args:
        items_from_scanner: List of UniqueItemInfo from scanner
    
    Returns:
        List of UniqueTabItem for the workflow
    """
    result = []
    
    for item in items_from_scanner:
        if item.is_unique_tab:
            result.append(UniqueTabItem(
                name=item.name,
                category=item.item_category,
                dust=item.dust,
                efficiency=item.efficiency,
                tab_name=item.tab_name,
            ))
    
    return result

