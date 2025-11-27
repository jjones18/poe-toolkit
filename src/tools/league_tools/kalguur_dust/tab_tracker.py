"""
Tab tracker for Kalguur Dust tool.

Uses OCR to detect which stash tab is currently active in-game,
enabling multi-tab highlighting workflows.
"""

import time
import cv2
import numpy as np
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass
from PyQt6.QtCore import QThread, pyqtSignal, QObject

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    print("Warning: pytesseract not found. Tab tracking disabled.")

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False
    print("Warning: mss not found. Screen capture disabled.")

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


@dataclass
class TabRegionConfig:
    """Configuration for the stash tab header OCR region."""
    # Absolute screen position (from calibration)
    x: int = 0
    y: int = 0
    width: int = 800
    height: int = 35
    
    # OCR settings
    threshold: int = 150    # Binary threshold for OCR preprocessing (used in fallback)
    scale_factor: float = 3.0  # Upscale for better OCR accuracy
    psm: int = 7            # Tesseract Page Segmentation Mode (0 = auto/strategies)
    invert: bool = True     # Invert image (white text on dark bg -> black on white)
    
    @classmethod
    def from_calibration(cls, calibration_data: dict) -> 'TabRegionConfig':
        """Create config from calibration data."""
        if not calibration_data:
            return cls()
        return cls(
            x=calibration_data.get('x', 0),
            y=calibration_data.get('y', 0),
            width=calibration_data.get('width', 800),
            height=calibration_data.get('height', 35),
            threshold=calibration_data.get('threshold', 150),
            scale_factor=calibration_data.get('scale_factor', 3.0),
            psm=calibration_data.get('psm', 0), # Default to 0 (auto/strategies)
            invert=calibration_data.get('invert', True)
        )


class TabTracker(QObject):
    """
    Tracks the currently active stash tab using OCR.
    
    Monitors the stash tab header region and detects tab changes
    by reading the tab names via OCR.
    """
    
    tab_changed = pyqtSignal(str)  # Emits detected tab name
    status_changed = pyqtSignal(str)  # Status updates
    debug_signal = pyqtSignal(str)  # Debug messages
    
    def __init__(self, known_tabs: List[str] = None, 
                 region_config: TabRegionConfig = None,
                 tesseract_path: str = None,
                 debug_mode: bool = False):
        super().__init__()
        
        self.known_tabs = known_tabs or []
        self.region_config = region_config or TabRegionConfig()
        self.current_tab: Optional[str] = None
        self.is_calibrated = False
        self.debug_mode = debug_mode
        
        # Setup tesseract
        if HAS_TESSERACT and tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
    
    def _debug(self, msg: str):
        """Emit debug message if debug mode is enabled."""
        if self.debug_mode:
            self.debug_signal.emit(f"[TabOCR] {msg}")
    
    def set_region_config(self, config: TabRegionConfig):
        """Set the tab bar region configuration."""
        self.region_config = config
        self.is_calibrated = config.width > 0 and config.height > 0
    
    def load_from_calibration(self, calibration_data: dict):
        """Load configuration from calibration data."""
        if calibration_data:
            self.region_config = TabRegionConfig.from_calibration(calibration_data)
            self.is_calibrated = True
        else:
            self.is_calibrated = False
    
    def set_known_tabs(self, tab_names: List[str]):
        """Set the list of known tab names for matching."""
        self.known_tabs = tab_names
    
    def get_capture_region(self) -> dict:
        """Get the screen region to capture for tab OCR."""
        cfg = self.region_config
        
        return {
            'left': max(0, cfg.x),
            'top': max(0, cfg.y),
            'width': cfg.width,
            'height': cfg.height,
        }
    
    def capture_tab_region(self) -> Optional[np.ndarray]:
        """Capture the tab header region of the screen."""
        if not HAS_MSS:
            return None
        
        region = self.get_capture_region()
        
        try:
            with mss.mss() as sct:
                screenshot = sct.grab(region)
            
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return img
        except Exception as e:
            self.status_changed.emit(f"Capture error: {e}")
            return None
    
    def set_ocr_settings(self, threshold: int = None, scale: float = None, psm: int = None, invert: bool = None):
        """Update OCR settings dynamically."""
        if threshold is not None:
            self.region_config.threshold = threshold
        if scale is not None:
            self.region_config.scale_factor = scale
        if psm is not None:
            self.region_config.psm = psm
        if invert is not None:
            self.region_config.invert = invert
        self._debug(f"OCR settings updated: thresh={self.region_config.threshold}, scale={self.region_config.scale_factor}, psm={self.region_config.psm}, invert={self.region_config.invert}")

    def preprocess_image(self, img: np.ndarray) -> np.ndarray:
        """Preprocess image for better OCR accuracy."""
        cfg = self.region_config
        
        # Save debug image if needed
        if self.debug_mode:
            try:
                cv2.imwrite("debug_tab_capture_raw.png", img)
            except: pass
        
        # Upscale for better OCR
        scale = cfg.scale_factor
        h, w = img.shape[:2]
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # If invert is OFF, we assume text is already black on white (unlikely in PoE but good for testing)
        if not cfg.invert:
            # Just threshold
            _, thresh = cv2.threshold(gray, cfg.threshold, 255, cv2.THRESH_BINARY)
        else:
            # Standard PoE: Text is light on dark.
            # Otsu's expects bimodal.
            inverted = cv2.bitwise_not(gray)
            _, thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Check if Otsu failed (garbage result)
            white_pixels = np.sum(thresh == 255)
            total_pixels = thresh.size
            ratio = white_pixels / total_pixels
            
            if ratio < 0.05 or ratio > 0.95:
                # Fallback: Use configured fixed threshold
                _, thresh = cv2.threshold(gray, cfg.threshold, 255, cv2.THRESH_BINARY)
                thresh = cv2.bitwise_not(thresh) # Invert for Tesseract
        
        # Add a black border (value=0) to simulate the "debug box" effect
        final = cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=0)
        
        if self.debug_mode:
            try:
                cv2.imwrite("debug_tab_capture_processed.png", final)
            except: pass
            
        return final
    
    def detect_text_with_strategies(self, processed: np.ndarray) -> str:
        """Try multiple OCR strategies to get text."""
        cfg = self.region_config
        
        # If a specific PSM is forced, use only that
        if cfg.psm > 0:
            try:
                text = pytesseract.image_to_string(processed, config=f'--psm {cfg.psm}').strip()
                return text
            except Exception:
                return ""
                
        # Strategy 1: PSM 6 (Assume a single uniform block of text) - best for multi-line
        try:
            text = pytesseract.image_to_string(processed, config='--psm 6').strip()
            if text:
                return text
        except Exception:
            pass
            
        # Strategy 2: PSM 11 (Sparse text) - good for spread out tabs
        try:
            text = pytesseract.image_to_string(processed, config='--psm 11').strip()
            if text:
                return text
        except Exception:
            pass
            
        # Strategy 3: PSM 7 (Single line) - fallback if calibration is tight
        try:
            text = pytesseract.image_to_string(processed, config='--psm 7').strip()
            if text:
                return text
        except Exception:
            pass
            
        return ""

    def detect_tab_name(self, img: np.ndarray = None) -> Optional[str]:
        """
        Detect the currently active tab name from screen.
        
        Args:
            img: Optional pre-captured image. If None, captures fresh.
        
        Returns:
            Detected tab name or None if detection failed
        """
        if not HAS_TESSERACT:
            self._debug("Tesseract not available")
            return None
        
        if img is None:
            region = self.get_capture_region()
            self._debug(f"Capturing region: ({region['left']}, {region['top']}) {region['width']}x{region['height']}")
            img = self.capture_tab_region()
            if img is None:
                self._debug("Failed to capture screen region")
                return None
        
        # Preprocess
        processed = self.preprocess_image(img)
        
        # OCR
        try:
            text = pytesseract.image_to_string(
                processed,
                config='--psm 7'  # Single line mode
            ).strip()
        except Exception as e:
            self._debug(f"OCR error: {e}")
            self.status_changed.emit(f"OCR error: {e}")
            return None
        
        if not text:
            self._debug("OCR returned empty text")
            return None
        
        self._debug(f"OCR raw text: '{text}'")
        
        # Match against known tabs
        matched = self._match_tab_name(text)
        if matched:
            self._debug(f"Matched to tab: '{matched}'")
        else:
            self._debug(f"No match found for: '{text}' (known tabs: {len(self.known_tabs)})")
        return matched
    
    def _match_tab_name(self, ocr_text: str) -> Optional[str]:
        """
        Match OCR text against known tab names.
        
        Uses fuzzy matching to handle OCR errors.
        Handles PoE trade tabs that include price info (e.g. "~b/o 1 div | TabName").
        """
        ocr_lower = ocr_text.lower().strip()
        
        # Split OCR text by common separators to find potential tab names
        # OCR often sees '|' as 'I' or 'l' or '1' depending on font, but we'll assume user tuned it
        # We also split by '}' or '{' which are common OCR artifacts for tab borders
        separators = ['|', '}', '{', ']']
        candidates = [ocr_lower]
        
        for sep in separators:
            new_candidates = []
            for c in candidates:
                new_candidates.extend(c.split(sep))
            candidates = new_candidates
            
        # Clean up candidates
        candidates = [c.strip() for c in candidates if c.strip()]
        
        # Debug candidates
        # self._debug(f"Matching candidates: {candidates}")
        
        for tab in self.known_tabs:
            tab_lower = tab.lower()
            
            # Determine "clean name" for the known tab (part after last |)
            if '|' in tab_lower:
                tab_clean = tab_lower.split('|')[-1].strip()
            else:
                tab_clean = tab_lower
            
            if not tab_clean:
                continue
                
            for candidate in candidates:
                # 1. Exact match with Clean Name (Allows short names like 'S1', 'M')
                if candidate == tab_clean:
                    self._debug(f"Exact match (Clean): '{tab}' matches candidate '{candidate}'")
                    return tab
                
                # 2. Exact match with Full Name
                if candidate == tab_lower:
                    self._debug(f"Exact match (Full): '{tab}' matches candidate '{candidate}'")
                    return tab
                
                # 3. Substring match (Candidate is inside Tab Name)
                # Only if candidate is long enough to be unique
                if len(candidate) >= 3 and candidate in tab_lower:
                     self._debug(f"Substring match: '{candidate}' in '{tab}'")
                     return tab
                     
                # 4. Tab Clean Name is inside Candidate (e.g. OCR="... S1 ..." matches "S1")
                # Important for when OCR captures multiple tabs
                if len(tab_clean) >= 2 and f" {tab_clean} " in f" {candidate} ":
                    self._debug(f"Token match: '{tab_clean}' found in '{candidate}'")
                    return tab
        
        return None
    
    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio between two strings."""
        if not s1 or not s2:
            return 0.0
        
        # Simple character overlap ratio
        set1 = set(s1)
        set2 = set(s2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def check_tab_change(self) -> Optional[str]:
        """
        Check if tab has changed since last check.
        
        Returns:
            New tab name if changed, None otherwise
        """
        detected = self.detect_tab_name()
        
        if detected and detected != self.current_tab:
            old_tab = self.current_tab
            self.current_tab = detected
            self.tab_changed.emit(detected)
            self.status_changed.emit(f"Tab changed: {old_tab} -> {detected}")
            return detected
        
        return None


class TabTrackerWorker(QThread):
    """
    Background worker that continuously monitors for tab changes.
    """
    
    tab_detected = pyqtSignal(str)  # Emits when a tab is detected
    tab_changed = pyqtSignal(str, str)  # old_tab, new_tab
    status_signal = pyqtSignal(str)
    ocr_debug_signal = pyqtSignal(str, str)  # raw_text, detected_tab (for visual debug)
    
    def __init__(self, tracker: TabTracker, interval_ms: int = 200):
        super().__init__()
        self.tracker = tracker
        self.interval_ms = interval_ms
        self.running = False
        self.waiting_for_tab: Optional[str] = None
        self.ignore_focus_check = False  # If True, runs even if PoE not focused
    
    def set_ignore_focus(self, ignore: bool):
        """Set whether to ignore window focus check (for debugging)."""
        self.ignore_focus_check = ignore
    
    def set_expected_tab(self, tab_name: str):
        """Set the tab we're waiting for the user to click."""
        self.waiting_for_tab = tab_name
    
    def stop(self):
        """Stop the monitoring loop."""
        self.running = False
    
    def run(self):
        """Main monitoring loop."""
        self.running = True
        last_tab = None
        ocr_attempts = 0
        
        # Check if calibrated
        if not self.tracker.is_calibrated:
            self.status_signal.emit("Tab bar not calibrated - using manual mode only. Click 'I'm on the correct tab' to advance.")
        else:
            region = self.tracker.get_capture_region()
            self.status_signal.emit(
                f"Tab OCR started at ({region['left']}, {region['top']}) "
                f"{region['width']}x{region['height']} - monitoring for tab changes..."
            )
        
        while self.running:
            # Skip OCR if not calibrated
            if not self.tracker.is_calibrated:
                time.sleep(0.5)
                continue
            
            # Check if PoE is focused (matches "Path of Exile" or "Path of Exile 2")
            if HAS_WIN32 and not self.ignore_focus_check:
                try:
                    hwnd = win32gui.GetForegroundWindow()
                    title = win32gui.GetWindowText(hwnd)
                    # Check for PoE 1 or PoE 2
                    if "path of exile" not in title.lower():
                        # Log every 5 seconds (25 attempts) to avoid spam
                        if ocr_attempts % 25 == 0:
                            self.status_signal.emit(f"Paused: Focus is on '{title}'")
                        time.sleep(0.5)
                        continue
                except Exception as e:
                    self.status_signal.emit(f"Window check error: {e}")
                    pass
            
            # Detect current tab (raw text is captured internally by tracker but we need to extract it for debug)
            ocr_attempts += 1
            
            # Capture and process manually to get raw text for debug signal
            img = self.tracker.capture_tab_region()
            if img is not None:
                processed = self.tracker.preprocess_image(img)
                try:
                    text = self.tracker.detect_text_with_strategies(processed)
                    matched = self.tracker._match_tab_name(text)
                    
                    # Emit debug signal for overlay - EVERY FRAME
                    self.ocr_debug_signal.emit(text or "<empty>", matched or "")
                    
                    if matched:
                        self.tab_detected.emit(matched)
                        
                        if matched != last_tab:
                            self.tab_changed.emit(last_tab or "", matched)
                            last_tab = matched
                            
                            # Check if this is the tab we're waiting for
                            if self.waiting_for_tab and matched == self.waiting_for_tab:
                                self.status_signal.emit(f"Target tab detected: {matched}")
                    
                    detected = matched
                except Exception as e:
                    self.status_signal.emit(f"OCR error: {e}")
                    self.ocr_debug_signal.emit(f"Error: {e}", "")
                    detected = None
            else:
                self.ocr_debug_signal.emit("<capture failed>", "")
                detected = None
            
            # Periodic status update (every ~10 seconds at 200ms interval)
            if ocr_attempts % 50 == 0:
                if detected:
                    self.status_signal.emit(f"OCR active - detected: '{detected}'")
                else:
                    # Include raw text in failure log to diagnose
                    raw_text = text if 'text' in locals() and text else "<empty>"
                    self.status_signal.emit(f"OCR active - no text detected (attempt {ocr_attempts}) Raw: '{raw_text[:20]}'")
            
            # Sleep for interval
            time.sleep(self.interval_ms / 1000.0)


class MultiTabHighlighter:
    """
    Manages multi-tab highlighting workflow.
    
    Coordinates between:
    - Scan results (items grouped by tab)
    - Tab tracker (detecting current tab)
    - Overlay (showing highlights)
    """
    
    def __init__(self, tab_tracker: TabTracker, 
                 on_highlights_changed: Callable[[List[dict]], None] = None):
        self.tab_tracker = tab_tracker
        self.on_highlights_changed = on_highlights_changed
        
        # Items grouped by tab name
        self.items_by_tab: Dict[str, List[dict]] = {}
        self.tab_order: List[str] = []  # Order to visit tabs
        self.current_tab_index = 0
        
        # Connect tab change signal
        self.tab_tracker.tab_changed.connect(self._on_tab_change)
    
    def set_items(self, items_by_tab: Dict[str, List[dict]]):
        """
        Set the items to highlight, grouped by tab.
        
        Args:
            items_by_tab: Dict mapping tab_name -> list of highlight dicts
        """
        self.items_by_tab = items_by_tab
        self.tab_order = list(items_by_tab.keys())
        self.current_tab_index = 0
        
        # Update known tabs for tracker
        self.tab_tracker.set_known_tabs(self.tab_order)
    
    def get_current_target_tab(self) -> Optional[str]:
        """Get the tab the user should click next."""
        if 0 <= self.current_tab_index < len(self.tab_order):
            return self.tab_order[self.current_tab_index]
        return None
    
    def get_items_remaining(self) -> int:
        """Get total items remaining across all tabs."""
        total = 0
        for i in range(self.current_tab_index, len(self.tab_order)):
            tab = self.tab_order[i]
            total += len(self.items_by_tab.get(tab, []))
        return total
    
    def advance_to_next_tab(self):
        """Move to the next tab in the sequence."""
        self.current_tab_index += 1
        if self.current_tab_index < len(self.tab_order):
            return self.tab_order[self.current_tab_index]
        return None
    
    def _on_tab_change(self, new_tab: str):
        """Handle tab change detected by tracker."""
        if new_tab in self.items_by_tab:
            # Show highlights for this tab
            highlights = self.items_by_tab[new_tab]
            if self.on_highlights_changed:
                self.on_highlights_changed(highlights)
            
            # Update current index if this tab is in our sequence
            if new_tab in self.tab_order:
                self.current_tab_index = self.tab_order.index(new_tab)
    
    def get_highlights_for_tab(self, tab_name: str) -> List[dict]:
        """Get highlight data for a specific tab."""
        return self.items_by_tab.get(tab_name, [])

