"""
OCR Scanner for League Vision tool.
"""

import re
import time
import cv2
import pytesseract
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from .vision_core import VisionCore

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class ScanResult:
    """Represents a scan result with message and display info."""
    
    def __init__(self, message: str, color: str = "green", is_blocking: bool = False, blocker_rect: dict = None):
        self.message = message
        self.color = color
        self.is_blocking = is_blocking
        self.blocker_rect = blocker_rect


class ScannerWorker(QThread):
    """Background worker that continuously scans the screen."""
    
    result_signal = pyqtSignal(object)  # Emits ScanResult
    status_signal = pyqtSignal(str)  # Status updates
    
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.running = False
        self.paused = False
        self.current_zone = "Unknown"
        self.tooltip_side_mode = 0
        
        # Initialize vision
        resolution_config = config.get("resolution_override")
        self.vision = VisionCore(resolution_config=resolution_config)
        
        # Setup Tesseract
        tesseract_path = config.get("tesseract_path", "C:/Program Files/Tesseract-OCR/tesseract.exe")
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    
    def set_zone(self, zone: str):
        """Update the current zone."""
        self.current_zone = zone
    
    def stop(self):
        """Stop the scanner."""
        self.running = False
    
    def pause(self):
        """Pause scanning."""
        self.paused = True
    
    def resume(self):
        """Resume scanning."""
        self.paused = False
    
    def is_poe_focused(self):
        """Check if PoE window is focused."""
        if not HAS_WIN32:
            return True
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return "Path of Exile" in title
        except:
            return False
    
    def get_active_strategy(self):
        """Determine scan strategy based on zone."""
        if "Hideout" in self.current_zone or self.current_zone == "Unknown":
            return "mouse"
        return "center"
    
    def run(self):
        """Main scan loop."""
        self.running = True
        
        while self.running:
            if self.paused or not self.is_poe_focused():
                time.sleep(0.5)
                continue
            
            strategy = self.get_active_strategy()
            
            if strategy == "mouse":
                interval_ms = self.config.get("scan_interval_mouse", 100)
            else:
                interval_ms = self.config.get("scan_interval_center", 500)
            
            start_time = time.time()
            
            # Get scan region
            rect = self.vision.get_window_rect()
            region = None
            
            if rect:
                if strategy == "mouse" and HAS_WIN32:
                    mx, my = win32gui.GetCursorPos()
                    h_cfg = self.config.get("scan_region_hover", {
                        "width": 600, "height": 800, 
                        "x_offset": 50, "y_offset": -100
                    })
                    
                    w = h_cfg.get("width", 600)
                    h = h_cfg.get("height", 800)
                    
                    if self.tooltip_side_mode == 0:
                        x = mx + h_cfg.get("x_offset", 50)
                    else:
                        x = mx + h_cfg.get("x_offset_right", -100)
                    
                    y = my + h_cfg.get("y_offset", -100)
                    
                    # Clamp to screen
                    screen_w = 1920
                    screen_h = 1080
                    x = max(0, min(x, screen_w - w))
                    y = max(0, min(y, screen_h - h))
                    
                    region = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
                else:
                    r_config = self.config.get("scan_region", {
                        "x_offset": 0.2, "y_offset": 0.1,
                        "width_pct": 0.6, "height_pct": 0.8
                    })
                    region = {
                        "top": int(rect["top"] + (rect["height"] * r_config.get("y_offset", 0.1))),
                        "left": int(rect["left"] + (rect["width"] * r_config.get("x_offset", 0.2))),
                        "width": int(rect["width"] * r_config.get("width_pct", 0.6)),
                        "height": int(rect["height"] * r_config.get("height_pct", 0.8))
                    }
            
            if region:
                img = self.vision.capture_region(region)
                if img is not None:
                    found = self.process_image(img)
                    
                    if strategy == "mouse" and not found:
                        self.tooltip_side_mode = 1 - self.tooltip_side_mode
            
            # Timing
            elapsed = time.time() - start_time
            sleep_time = max(0, (interval_ms / 1000.0) - elapsed)
            time.sleep(sleep_time)
    
    def process_image(self, img) -> bool:
        """Process captured image through OCR and check modules."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh_val = self.config.get("ocr_threshold", 70)
        _, thresh = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        
        try:
            data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        except Exception as e:
            return False
        
        full_text = " ".join(data['text'])
        in_hideout = "Hideout" in self.current_zone
        
        # Check modules
        results = []
        
        # Essence/Ritual keywords
        if not in_hideout:
            active_keywords = []
            
            ess_cfg = self.config.get("essence", {})
            if ess_cfg.get("enabled", False):
                active_keywords.extend(ess_cfg.get("keywords", []))
            
            rit_cfg = self.config.get("ritual", {})
            if rit_cfg.get("enabled", False):
                active_keywords.extend(rit_cfg.get("keywords", []))
            
            for keyword in active_keywords:
                if keyword.lower() in full_text.lower():
                    results.append(ScanResult(f"FOUND: {keyword}", "green"))
        
        # Map Safety Check
        map_result = self.check_map_safety(full_text)
        if map_result:
            results.append(map_result)
        
        # Eldritch Altars
        if not in_hideout:
            altar_result = self.check_eldritch(full_text)
            if altar_result:
                results.append(altar_result)
        
        # Expedition
        if not in_hideout:
            exp_result = self.check_expedition(full_text)
            if exp_result:
                results.append(exp_result)
        
        # Emit first result
        if results:
            self.result_signal.emit(results[0])
            return True
        
        return False
    
    def check_map_safety(self, text: str):
        """Check for dangerous map mods."""
        cfg = self.config.get("map_check", {})
        if not cfg.get("enabled"):
            return None
        
        # Check context
        context_found = False
        for ctx in cfg.get("required_context", []):
            if ctx.lower() in text.lower():
                context_found = True
                break
        
        if not context_found:
            return None
        
        # Check bad mods
        for mod in cfg.get("bad_mods", []):
            if mod.lower() in text.lower():
                btn_rect = self.config.get("map_device_button", {})
                return ScanResult(
                    f"UNSAFE MAP: {mod.upper()}", 
                    "red", 
                    is_blocking=True,
                    blocker_rect=btn_rect
                )
        
        return ScanResult("MAP SAFE", "green")
    
    def check_eldritch(self, text: str):
        """Check for valuable eldritch altar rewards."""
        cfg = self.config.get("eldritch_altars", {})
        if not cfg.get("enabled"):
            return None
        
        # Check bad mods first
        for mod in cfg.get("bad_mods", []):
            if mod.lower() in text.lower():
                return ScanResult(f"DANGER: {mod.upper()}", "red")
        
        # Check tiers
        min_tier = cfg.get("min_tier_to_highlight", 1)
        tiers = cfg.get("tiers", {})
        
        found_tier = 99
        found_reward = None
        
        for tier_str, rewards in tiers.items():
            tier = int(tier_str)
            if tier > min_tier:
                continue
            
            for reward in rewards:
                if reward.lower() in text.lower():
                    if tier < found_tier:
                        found_tier = tier
                        found_reward = reward
        
        if found_reward:
            return ScanResult(f"ALTAR T{found_tier}: {found_reward}", "green")
        
        return None
    
    def check_expedition(self, text: str):
        """Check for dangerous expedition mods."""
        cfg = self.config.get("expedition", {})
        if not cfg.get("enabled"):
            return None
        
        if "remnant" not in text.lower():
            return None
        
        for dtype in cfg.get("immune_warning", []):
            if f"immune to {dtype}".lower() in text.lower():
                return ScanResult(f"IMMUNE TO {dtype.upper()}", "red")
        
        return None

