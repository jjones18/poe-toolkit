"""
Calibration system for POE Toolkit.

Supports calibrating multiple screen regions:
- Stash grid (for item highlighting)
- Tab bar (for OCR tab detection)
- Unique tab category grid (for unique stash tab workflow)
- Unique tab result slot (for click detection)
"""

from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any
from enum import Enum, auto


class CalibrationType(Enum):
    """Types of calibration supported."""
    STASH_GRID = auto()           # 2 points: top-left, bottom-right
    TAB_BAR = auto()              # 2 points: region to OCR for tab names
    UNIQUE_CATEGORY_GRID = auto() # 2 points: category icons at top of unique tab
    UNIQUE_RESULT_SLOT = auto()   # 2 points: where searched items appear


@dataclass
class CalibrationConfig:
    """Configuration for a calibration type."""
    name: str
    description: str
    step1_msg: str
    step2_msg: str
    config_key: str  # Key in user_config to save to
    
    
CALIBRATION_CONFIGS = {
    CalibrationType.STASH_GRID: CalibrationConfig(
        name="Stash Grid",
        description="Calibrate the stash inventory grid position for item highlighting",
        step1_msg="Click TOP-LEFT corner of stash grid",
        step2_msg="Click BOTTOM-RIGHT corner of stash grid\n(Use a QUAD tab if calibrating quad size)",
        config_key="overlay",
    ),
    CalibrationType.TAB_BAR: CalibrationConfig(
        name="Tab Bar Region",
        description="Calibrate where stash tab names appear for OCR detection",
        step1_msg="Click TOP-LEFT of the tab bar\n(where tab names like 'Currency', 'Maps' appear)",
        step2_msg="Click BOTTOM-RIGHT of the tab bar region",
        config_key="tab_bar",
    ),
    CalibrationType.UNIQUE_CATEGORY_GRID: CalibrationConfig(
        name="Unique Tab Categories",
        description="Calibrate the category icon grid at the top of unique stash tabs",
        step1_msg="Open a UNIQUE stash tab, then\nclick TOP-LEFT of the first category icon",
        step2_msg="Click BOTTOM-RIGHT of the last category icon\n(the grid of small icons at the top)",
        config_key="unique_category_grid",
    ),
    CalibrationType.UNIQUE_RESULT_SLOT: CalibrationConfig(
        name="Unique Tab Result Slot",
        description="Calibrate where items appear after searching in unique tabs",
        step1_msg="In a UNIQUE tab, search for any item, then\nclick TOP-LEFT of the result slot",
        step2_msg="Click BOTTOM-RIGHT of the result slot\n(the large item display area)",
        config_key="unique_result_slot",
    ),
}


class CalibrationManager:
    """
    Manages calibration workflows for different screen regions.
    """
    
    def __init__(self, config: dict, save_callback: Callable[[], None] = None):
        """
        Args:
            config: Reference to the user config dict
            save_callback: Function to call to persist config changes
        """
        self.config = config
        self.save_callback = save_callback
        
        # Current calibration state
        self.active_type: Optional[CalibrationType] = None
        self.step: int = 0
        self.point1: Optional[tuple] = None
        
        # Callbacks
        self.on_complete: Optional[Callable[[CalibrationType, dict], None]] = None
        self.on_message: Optional[Callable[[str], None]] = None
    
    def start_calibration(self, cal_type: CalibrationType) -> str:
        """
        Start a calibration workflow.
        
        Args:
            cal_type: Type of calibration to perform
            
        Returns:
            Initial instruction message
        """
        self.active_type = cal_type
        self.step = 1
        self.point1 = None
        
        config = CALIBRATION_CONFIGS[cal_type]
        return config.step1_msg
    
    def handle_click(self, x: int, y: int) -> Optional[str]:
        """
        Handle a calibration click.
        
        Args:
            x, y: Click coordinates
            
        Returns:
            Next instruction message, or None if calibration complete
        """
        if self.active_type is None:
            return None
        
        config = CALIBRATION_CONFIGS[self.active_type]
        
        if self.step == 1:
            self.point1 = (x, y)
            self.step = 2
            return config.step2_msg
        
        elif self.step == 2:
            point2 = (x, y)
            
            # Calculate and save calibration
            result = self._calculate_calibration(self.point1, point2)
            
            # Don't save immediately - wait for user confirmation
            # Notify completion but keep state active for confirmation
            if self.on_complete:
                self.on_complete(self.active_type, result)
            
            # We DO NOT reset state here anymore
            # The UI dialog (CalibrationDialog) should call finish_calibration()
            # which calls manager.confirm_calibration()
            
            return None
        
        return None
    
    def confirm_calibration(self, result: dict):
        """
        Confirm and save the pending calibration.
        Called by UI after showing preview.
        """
        self._save_calibration(result)
        
        # Reset state
        self.active_type = None
        self.step = 0
        self.point1 = None

    def cancel(self):
        """Cancel the current calibration."""
        self.active_type = None
        self.step = 0
        self.point1 = None
    
    def is_active(self) -> bool:
        """Check if a calibration is in progress."""
        return self.active_type is not None
    
    def _calculate_calibration(self, p1: tuple, p2: tuple) -> dict:
        """Calculate calibration values from two points."""
        x1, y1 = p1
        x2, y2 = p2
        
        # Ensure p1 is top-left and p2 is bottom-right
        left = min(x1, x2)
        top = min(y1, y2)
        right = max(x1, x2)
        bottom = max(y1, y2)
        
        width = right - left
        height = bottom - top
        
        result = {
            'x': left,
            'y': top,
            'width': width,
            'height': height,
            'x2': right,
            'y2': bottom,
        }
        
        # Special handling for stash grid - calculate cell size
        if self.active_type == CalibrationType.STASH_GRID:
            # Standard stash is 12x12, quad is 24x24
            # Detect based on aspect ratio and size
            cell_size_12 = width / 12
            cell_size_24 = width / 24
            
            # If cell size for 12x12 is reasonable (40-80 pixels), use standard
            # Otherwise assume quad
            is_quad = cell_size_12 > 80 or cell_size_12 < 30
            
            if is_quad:
                cell_size = cell_size_24
            else:
                cell_size = cell_size_12
            
            result['cell_size'] = int(cell_size)
            result['is_quad_calibrated'] = is_quad
            result['x_offset'] = left
            result['y_offset'] = top
        
        # Special handling for unique category grid
        elif self.active_type == CalibrationType.UNIQUE_CATEGORY_GRID:
            # Unique tab has 2 rows of ~12 category icons
            cols = 12
            rows = 2
            result['cell_width'] = width // cols
            result['cell_height'] = height // rows
            result['cols'] = cols
            result['rows'] = rows
        
        return result
    
    def _save_calibration(self, result: dict):
        """Save calibration to config."""
        if self.active_type is None:
            return
        
        config_info = CALIBRATION_CONFIGS[self.active_type]
        key = config_info.config_key
        
        # Special handling for stash grid (legacy format)
        if self.active_type == CalibrationType.STASH_GRID:
            if 'overlay' not in self.config:
                self.config['overlay'] = {}
            self.config['overlay']['x_offset'] = result['x_offset']
            self.config['overlay']['y_offset'] = result['y_offset']
            self.config['overlay']['cell_size'] = result['cell_size']
            self.config['overlay']['is_quad_calibrated'] = result['is_quad_calibrated']
        else:
            # Standard format for other calibrations
            if 'calibration' not in self.config:
                self.config['calibration'] = {}
            self.config['calibration'][key] = result
        
        # Persist changes
        if self.save_callback:
            self.save_callback()
    
    def get_calibration(self, cal_type: CalibrationType) -> Optional[dict]:
        """Get saved calibration for a type."""
        config_info = CALIBRATION_CONFIGS[cal_type]
        key = config_info.config_key
        
        if cal_type == CalibrationType.STASH_GRID:
            overlay = self.config.get('overlay', {})
            if 'x_offset' in overlay:
                return {
                    'x': overlay['x_offset'],
                    'y': overlay['y_offset'],
                    'cell_size': overlay.get('cell_size', 52),
                    'is_quad_calibrated': overlay.get('is_quad_calibrated', False),
                }
            return None
        else:
            return self.config.get('calibration', {}).get(key)
    
    def is_calibrated(self, cal_type: CalibrationType) -> bool:
        """Check if a calibration type has been completed."""
        return self.get_calibration(cal_type) is not None


def get_calibration_status_text(manager: CalibrationManager) -> str:
    """Generate a status string showing calibration state."""
    lines = []
    for cal_type in CalibrationType:
        config = CALIBRATION_CONFIGS[cal_type]
        status = "Done" if manager.is_calibrated(cal_type) else "Not set"
        lines.append(f"  {config.name}: {status}")
    return "\n".join(lines)

