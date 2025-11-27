"""
OCR Scanner for League Vision tool.
"""

import re
import time
import cv2
import numpy as np
import pytesseract
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import QApplication

from .vision_core import VisionCore
from utils.logger import DebugLogger

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


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
    mode_signal = pyqtSignal(str)  # Emits current scan mode (mouse/center)
    debug_rect_signal = pyqtSignal(int, int, int, int, str)  # x, y, w, h, color
    debug_box_signal = pyqtSignal(int, int, int, int, str)  # For keyword highlight boxes
    clear_debug_signal = pyqtSignal()  # Clear all debug boxes
    stop_requested_signal = pyqtSignal()  # Emitted when hotkey pressed
    
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.running = False
        self.paused = False
        self.current_zone = "Unknown"
        self.tooltip_side_mode = 0
        self.manual_override = None  # For manual mode toggle
        
        # Debug mode
        self.debug_mode = config.get("debug_mode", False)
        DebugLogger.set_enabled(self.debug_mode)
        
        # Syndicate Memory: { "MemberName": (time_of_last_good_scan, result) }
        self.syndicate_memory = {}
        
        # Track if we're in syndicate board mode (for expanded scan region)
        self.in_syndicate_board = False
        self.syndicate_board_last_seen = 0
        
        # Initialize vision
        resolution_config = config.get("resolution_override")
        self.vision = VisionCore(resolution_config=resolution_config)
        
        # Setup Tesseract - check if it exists
        tesseract_path = config.get("tesseract_path", "C:/Program Files/Tesseract-OCR/tesseract.exe")
        import os
        if not os.path.exists(tesseract_path):
            self.status_signal.emit(f"WARNING: Tesseract not found at {tesseract_path}")
            DebugLogger.log(f"Tesseract not found at {tesseract_path}", "Vision")
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        
        # Clear debug log on start
        if self.debug_mode:
            try:
                with open("debug.log", "w", encoding="utf-8") as f:
                    f.write("--- Scanner Debug Log Started ---\n")
            except:
                pass
            DebugLogger.log(f"Scanner initialized. Tesseract: {tesseract_path}", "Vision")
        
        # Setup hotkey (Shift+Esc to stop)
        self.hotkey_id = None
        if HAS_KEYBOARD:
            try:
                self.hotkey_id = keyboard.add_hotkey("shift+esc", self._on_stop_hotkey)
                DebugLogger.log("Hotkey registered: Shift+Esc to stop scanner", "Vision")
            except Exception as e:
                DebugLogger.log(f"Failed to register hotkey: {e}", "Vision")
    
    def _on_stop_hotkey(self):
        """Called when stop hotkey is pressed."""
        self.status_signal.emit("Shift+Esc pressed - stopping scanner...")
        self.stop_requested_signal.emit()
        self.stop()
    
    def set_zone(self, zone: str):
        """Update the current zone."""
        self.current_zone = zone
    
    def stop(self):
        """Stop the scanner."""
        self.running = False
        
        # Remove hotkey
        if HAS_KEYBOARD and self.hotkey_id is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_id)
                self.hotkey_id = None
            except:
                pass
    
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
        """Determine scan strategy based on zone or manual override."""
        if self.manual_override:
            return self.manual_override
        
        # Auto logic based on zone
        # Mouse mode: Hideout (for map tooltip reading)
        # Center mode: Maps, acts, and other zones (for in-game mechanics)
        # Unknown defaults to center since most gameplay happens in maps
        if "Hideout" in self.current_zone:
            return "mouse"
        return "center"
    
    def set_manual_override(self, mode: str = None):
        """Set manual override for scan strategy. None = auto."""
        self.manual_override = mode
    
    def toggle_mode(self):
        """Toggle between mouse and center mode."""
        current = self.get_active_strategy()
        new_mode = "center" if current == "mouse" else "mouse"
        self.manual_override = new_mode
        self.mode_signal.emit(new_mode.upper())
        return new_mode
    
    def run(self):
        """Main scan loop."""
        self.running = True
        last_strategy = None
        
        # Emit initial mode based on current zone
        initial_strategy = self.get_active_strategy()
        self.mode_signal.emit(initial_strategy.upper())
        last_strategy = initial_strategy
        
        if self.debug_mode:
            DebugLogger.log(f"Scanner started in {initial_strategy.upper()} mode (Zone: {self.current_zone})", "Vision")
        
        while self.running:
            if self.paused or not self.is_poe_focused():
                time.sleep(0.5)
                continue
            
            strategy = self.get_active_strategy()
            
            if strategy != last_strategy:
                self.mode_signal.emit(strategy.upper())
                last_strategy = strategy
            
            if strategy == "mouse":
                interval_ms = self.config.get("scan_interval_mouse", 100)
            else:
                interval_ms = self.config.get("scan_interval_center", 500)
            
            start_time = time.time()
            
            # Get scan region
            rect = self.vision.get_window_rect()
            region = None
            
            if rect:
                # Check if we should use expanded syndicate board region
                # Stay in syndicate mode for 3 seconds after last detection
                use_syndicate_region = (
                    self.in_syndicate_board and 
                    (time.time() - self.syndicate_board_last_seen) < 3.0
                )
                
                if use_syndicate_region:
                    # Expanded region for syndicate board - cover almost full screen
                    # Leave small margins for UI elements
                    region = {
                        "top": int(rect["top"] + (rect["height"] * 0.05)),
                        "left": int(rect["left"] + (rect["width"] * 0.05)),
                        "width": int(rect["width"] * 0.90),
                        "height": int(rect["height"] * 0.85)
                    }
                elif strategy == "mouse" and HAS_WIN32:
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
                    
                    # Clamp to screen - get actual screen size dynamically
                    screen = QApplication.primaryScreen()
                    if screen:
                        screen_w = screen.size().width()
                        screen_h = screen.size().height()
                    else:
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
                # Clear previous debug boxes
                if self.debug_mode:
                    self.clear_debug_signal.emit()
                    
                    # Yellow for center mode, cyan for mouse/hideout mode
                    debug_color = "cyan" if (strategy == "mouse" or "Hideout" in self.current_zone) else "yellow"
                    self.debug_rect_signal.emit(
                        region["left"], region["top"], 
                        region["width"], region["height"],
                        debug_color
                    )
                
                img = self.vision.capture_region(region)
                if img is not None:
                    # Pass region_offset for debug box positioning
                    region_offset = (region["left"], region["top"])
                    found = self.process_image(img, region_offset=region_offset)
                    
                    if strategy == "mouse" and not found:
                        self.tooltip_side_mode = 1 - self.tooltip_side_mode
            
            # Timing
            elapsed = time.time() - start_time
            sleep_time = max(0, (interval_ms / 1000.0) - elapsed)
            time.sleep(sleep_time)
    
    def process_image(self, img, region_offset=None) -> bool:
        """Process captured image through OCR and check modules."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh_val = self.config.get("ocr_threshold", 70)
        _, thresh = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        
        try:
            data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        except Exception as e:
            if self.debug_mode:
                DebugLogger.log(f"OCR Error: {e}", "Vision")
            return False
        
        # Filter out empty strings and low-confidence results
        full_text = " ".join([t for t in data['text'] if t.strip()])
        full_text_lower = full_text.lower()
        in_hideout = "Hideout" in self.current_zone
        n_boxes = len(data['text'])
        
        # Calculate offset for debug boxes
        scan_offset_x = region_offset[0] if region_offset else 0
        scan_offset_y = region_offset[1] if region_offset else 0
        
        # Check for Syndicate Board/Card context - use enhanced OCR if detected
        syndicate_keywords = ["transportation", "fortification", "research", "intervention", 
                             "execute", "interrogate", "imprisoned", "intelligence"]
        is_syndicate_context = any(kw in full_text_lower for kw in syndicate_keywords)
        
        if is_syndicate_context:
            # Mark that we're in syndicate board mode - this will expand the scan region
            self.in_syndicate_board = True
            self.syndicate_board_last_seen = time.time()
            
            # Re-process with enhanced filtering for syndicate board
            # The syndicate board has specific colors we can target
            data, full_text, n_boxes = self.process_syndicate_ocr(img, gray)
            full_text_lower = full_text.lower()
            
            if self.debug_mode:
                DebugLogger.log("Syndicate board detected - using expanded scan region", "Vision")
        
        # Debug: Log OCR output
        if self.debug_mode and full_text.strip():
            DebugLogger.log(f"OCR Text: {full_text[:500]}", "Vision")
            self.status_signal.emit(f"[DEBUG OCR] {full_text[:200]}...")
        
        # Check modules
        results = []
        
        # Essence/Ritual keywords - with debug boxes
        if not in_hideout:
            active_keywords = []
            
            ess_cfg = self.config.get("essence", {})
            if ess_cfg.get("enabled", False):
                active_keywords.extend(ess_cfg.get("keywords", []))
            
            rit_cfg = self.config.get("ritual", {})
            if rit_cfg.get("enabled", False):
                active_keywords.extend(rit_cfg.get("keywords", []))
            
            if active_keywords:
                for i in range(n_boxes):
                    word = data['text'][i].strip()
                    if len(word) < 3:
                        continue
                    word_lower = word.lower()
                    for keyword in active_keywords:
                        if keyword.lower() in word_lower:
                            results.append(ScanResult(f"FOUND: {keyword}", "green"))
                            # Draw RED debug box around found keyword
                            if self.debug_mode:
                                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                                self.debug_box_signal.emit(
                                    scan_offset_x + x, scan_offset_y + y, w, h, "red"
                                )
        
        # Syndicate Check (uses re-processed data if syndicate card detected)
        if not in_hideout:
            syndicate_result = self.check_syndicate(data, full_text, scan_offset_x, scan_offset_y)
            if syndicate_result:
                results.append(syndicate_result)
        
        # Map Safety Check - only in hideout (reading map tooltips before activating)
        if in_hideout:
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
        
        # Check if we found map context even without alerts (still counts as "found something")
        if "map tier" in full_text.lower() or "item class: maps" in full_text.lower():
            return True
        
        return False
    
    def process_syndicate_ocr(self, img, gray):
        """
        Enhanced OCR processing specifically for the syndicate board.
        Uses multiple color filters and thresholds to better detect text.
        """
        all_texts = []
        best_data = None
        best_text = ""
        best_count = 0
        
        # Convert to HSV for color filtering
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Method 1: Standard grayscale with lower threshold (for white/light text)
        _, thresh1 = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
        
        # Method 2: Higher threshold for darker backgrounds
        _, thresh2 = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        
        # Method 3: Adaptive threshold (good for varying lighting)
        thresh3 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                        cv2.THRESH_BINARY, 11, 2)
        
        # Method 4: Filter for golden/yellow text (member names on cards)
        # Yellow/gold hue range: roughly 15-35
        lower_gold = np.array([15, 80, 80])
        upper_gold = np.array([35, 255, 255])
        gold_mask = cv2.inRange(hsv, lower_gold, upper_gold)
        
        # Method 5: Filter for white/cream text (card text)
        lower_white = np.array([0, 0, 180])
        upper_white = np.array([180, 50, 255])
        white_mask = cv2.inRange(hsv, lower_white, upper_white)
        
        # Method 6: Filter for red text (house names like "Transportation")
        lower_red1 = np.array([0, 100, 100])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([160, 100, 100])
        upper_red2 = np.array([180, 255, 255])
        red_mask = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)
        
        # Combine color masks
        combined_color = cv2.bitwise_or(gold_mask, white_mask)
        combined_color = cv2.bitwise_or(combined_color, red_mask)
        
        # Process each threshold method
        thresh_methods = [
            ("low_thresh", thresh1),
            ("high_thresh", thresh2),
            ("adaptive", thresh3),
            ("color_filter", combined_color),
        ]
        
        for method_name, thresh_img in thresh_methods:
            try:
                data = pytesseract.image_to_data(thresh_img, output_type=pytesseract.Output.DICT)
                text = " ".join([t for t in data['text'] if t.strip()])
                all_texts.append(text)
                
                # Count meaningful words (length > 2)
                word_count = len([t for t in data['text'] if len(t.strip()) > 2])
                
                if word_count > best_count:
                    best_count = word_count
                    best_data = data
                    best_text = text
                    
                if self.debug_mode:
                    DebugLogger.log(f"Syndicate OCR [{method_name}]: {text[:200]}", "Vision")
            except Exception as e:
                if self.debug_mode:
                    DebugLogger.log(f"Syndicate OCR [{method_name}] error: {e}", "Vision")
        
        # Combine all detected texts for comprehensive matching
        combined_text = " ".join(all_texts)
        
        # Use the best data structure but with combined text for matching
        if best_data is None:
            # Fallback to simple threshold
            _, thresh_fallback = cv2.threshold(gray, 70, 255, cv2.THRESH_BINARY)
            best_data = pytesseract.image_to_data(thresh_fallback, output_type=pytesseract.Output.DICT)
            combined_text = " ".join([t for t in best_data['text'] if t.strip()])
        
        n_boxes = len(best_data['text'])
        
        if self.debug_mode:
            DebugLogger.log(f"Syndicate OCR COMBINED: {combined_text[:500]}", "Vision")
        
        return best_data, combined_text, n_boxes
    
    def check_map_safety(self, text: str):
        """Check for dangerous map mods."""
        cfg = self.config.get("map_check", {})
        if not cfg.get("enabled"):
            if self.debug_mode:
                DebugLogger.log("Map check disabled", "MapSafety")
            return None
        
        # Check context - must see one of these keywords to know we're looking at a map
        context_found = False
        required_contexts = cfg.get("required_context", [])
        
        for ctx in required_contexts:
            if ctx.lower() in text.lower():
                context_found = True
                if self.debug_mode:
                    DebugLogger.log(f"Context found: '{ctx}'", "MapSafety")
                break
        
        if not context_found:
            if self.debug_mode and text.strip():
                DebugLogger.log(f"No map context found. Looking for: {required_contexts}", "MapSafety")
            return None
        
        # Check bad mods
        bad_mods = cfg.get("bad_mods", [])
        for mod in bad_mods:
            if mod.lower() in text.lower():
                if self.debug_mode:
                    DebugLogger.log(f"DANGEROUS MOD FOUND: {mod}", "MapSafety")
                btn_rect = self.config.get("map_device_button", {})
                return ScanResult(
                    f"UNSAFE MAP: {mod.upper()}", 
                    "red", 
                    is_blocking=True,
                    blocker_rect=btn_rect
                )
        
        if self.debug_mode:
            DebugLogger.log("Map is safe", "MapSafety")
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
        
        # Check immune warnings
        for dtype in cfg.get("immune_warning", []):
            if f"immune to {dtype}".lower() in text.lower():
                return ScanResult(f"IMMUNE TO {dtype.upper()}", "red")
        
        # Check bad mods
        for mod in cfg.get("bad_mods", []):
            if mod.lower() in text.lower():
                return ScanResult(f"EXPEDITION DANGER: {mod.upper()}", "red")
        
        return None
    
    def check_syndicate(self, data: dict, full_text: str, off_x: int = 0, off_y: int = 0):
        """Check for syndicate member interactions and provide guidance."""
        goals = self.config.get("syndicate_goals", {})
        if not goals:
            return None
        
        full_text_lower = full_text.lower()
        
        # Check if we're in a syndicate interaction context
        # Can be: execute/interrogate buttons, OR syndicate-specific keywords
        has_buttons = "execute" in full_text_lower or "interrogate" in full_text_lower or "release" in full_text_lower
        has_syndicate_context = (
            "intelligence" in full_text_lower or 
            "imprisoned" in full_text_lower or
            "rank" in full_text_lower or
            "transportation" in full_text_lower or
            "fortification" in full_text_lower or
            "research" in full_text_lower or
            "intervention" in full_text_lower
        )
        
        is_syndicate_card = has_buttons or has_syndicate_context
        if not is_syndicate_card:
            return None
        
        n_boxes = len(data['text'])
        current_time = time.time()
        
        # --- Text-Based Rank Detection ---
        detected_rank = 0
        
        # Debug: Draw PURPLE boxes around Rank/House keywords
        if self.debug_mode:
            for i in range(n_boxes):
                w_text = data['text'][i].lower().strip()
                if w_text in ["sergeant", "lieutenant", "captain", "leader", "member", 
                              "transportation", "fortification", "research", "intervention"]:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    self.debug_box_signal.emit(off_x + x, off_y + y, w, h, "purple")
        
        if "captain" in full_text.lower() or "leader" in full_text.lower():
            detected_rank = 3
        elif "lieutenant" in full_text.lower():
            detected_rank = 2
        elif "sergeant" in full_text.lower():
            detected_rank = 1
        
        best_result = None
        best_priority = 0
        current_member_name = None
        candidates_log = []
        
        for i in range(n_boxes):
            word = data['text'][i].strip()
            if not word:
                continue
            word_lower = word.lower()
            
            for member, goal in goals.items():
                if member.lower() == word_lower:
                    current_member_name = member
                    found_member = f"{member} -> {goal.upper()}"
                    
                    # Draw BLUE debug box around member name
                    if self.debug_mode:
                        x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                        self.debug_box_signal.emit(off_x + x, off_y + y, w, h, "blue")
                    
                    # Get available actions
                    actions = []
                    if "execute" in full_text.lower(): actions.append("EXECUTE")
                    if "interrogate" in full_text.lower(): actions.append("INTERROGATE")
                    if "bargain" in full_text.lower(): actions.append("BARGAIN")
                    if "betray" in full_text.lower(): actions.append("BETRAY")
                    if "release" in full_text.lower(): actions.append("RELEASE")
                    
                    result_msg = f"{found_member} | {', '.join(actions)}"
                    result_color = "cyan"
                    priority = 1  # Default priority
                    
                    # Special handling for "Remove" goal
                    if goal.lower() == "remove":
                        result_msg = f"{member}: REMOVE (Do not Rank Up)"
                        result_color = "orange"
                        priority = 2
                    
                    # Determine current house from text
                    current_house = None
                    intel_match_str = "None"
                    
                    # Method 1: Look for "+X [House] Intelligence"
                    intel_match = re.search(r"\+\d+\s+(Transportation|Fortification|Research|Intervention)\s+Intelligence", full_text, re.IGNORECASE)
                    if intel_match:
                        current_house = intel_match.group(1).title()
                        intel_match_str = current_house
                    
                    # Method 2: Try "Rank House" pattern
                    if not current_house:
                        rank_house_match = re.search(r"(Member|Leader|Captain|Sergeant|Lieutenant).{0,10}(Transportation|Fortification|Research|Intervention)", full_text, re.IGNORECASE)
                        if rank_house_match:
                            current_house = rank_house_match.group(2).title()
                        else:
                            house_rank_match = re.search(r"(Transportation|Fortification|Research|Intervention).{0,10}(Member|Leader|Captain|Sergeant|Lieutenant)", full_text, re.IGNORECASE)
                            if house_rank_match:
                                current_house = house_rank_match.group(1).title()
                    
                    # Check for "moves to" pattern (Rank 0 / unassigned members)
                    move_match = re.search(r"moves to.{0,10}(Transportation|Fortification|Research|Intervention)", full_text, re.IGNORECASE)
                    
                    if move_match:
                        target_house = move_match.group(1).title()
                        if target_house.lower() != goal.lower():
                            if "release" in full_text.lower():
                                result_msg = f"{found_member} | RELEASE (Keep Free)"
                                result_color = "green"
                            else:
                                result_msg = f"{found_member} | AVOID {target_house.upper()}"
                                result_color = "orange"
                        else:
                            result_msg = f"{found_member} | EXECUTE (Join {goal})"
                            result_color = "green"
                        priority = 3
                    
                    elif current_house:
                        if current_house.lower() != goal.lower():
                            if "interrogate" in full_text.lower():
                                result_msg = f"{found_member} | INTERROGATE (Remove from {current_house})"
                                result_color = "green"
                            else:
                                result_msg = f"{found_member} | REMOVE FROM {current_house.upper()}"
                                result_color = "orange"
                        else:
                            # Correct house
                            if "execute" in full_text.lower():
                                result_msg = f"{found_member} | EXECUTE (Rank Up in {current_house})"
                                result_color = "green"
                            elif "release" in full_text.lower():
                                result_msg = f"{found_member} | RELEASE (Stay in {current_house})"
                                result_color = "green"
                            else:
                                result_msg = f"{found_member} | STAY IN {current_house.upper()}"
                                result_color = "green"
                        priority = 3
                    
                    candidates_log.append(f"Mem:{member} House:{current_house}(Intel:{intel_match_str}) Rank:{detected_rank} -> P{priority}")
                    
                    # Update best result if this candidate is better
                    if priority > best_priority:
                        best_priority = priority
                        best_result = ScanResult(result_msg, result_color)
        
        # Memory Persistence Logic (3 second cache for flicker resistance)
        if current_member_name:
            if best_result and best_priority == 3:
                # High confidence scan! Save it.
                self.syndicate_memory[current_member_name] = (current_time, best_result)
                # Also save to a general "last good result" for fallback
                self.syndicate_memory["_last_good"] = (current_time, best_result, current_member_name)
                if self.debug_mode:
                    DebugLogger.log(f"Memorized P3 for {current_member_name}", "Syndicate")
            elif best_result and best_priority < 3:
                # Low confidence scan. Do we have a recent memory for this member?
                mem = self.syndicate_memory.get(current_member_name)
                if mem:
                    last_time, cached_result = mem
                    if current_time - last_time < 3.0:  # 3 Seconds persistence
                        # Use cached high-confidence result
                        best_result = cached_result
                        if self.debug_mode:
                            DebugLogger.log(f"Using Cached P3 for {current_member_name} (Age: {current_time - last_time:.1f}s)", "Syndicate")
        
        # Fallback: If we have syndicate context but no specific member match, check last good result
        if not best_result and has_syndicate_context:
            last_good = self.syndicate_memory.get("_last_good")
            if last_good:
                last_time, cached_result, cached_member = last_good
                if current_time - last_time < 2.0:  # 2 second window for general fallback
                    best_result = cached_result
                    if self.debug_mode:
                        DebugLogger.log(f"Using fallback cache for {cached_member} (Age: {current_time - last_time:.1f}s)", "Syndicate")
        
        if self.debug_mode and candidates_log:
            DebugLogger.log(f"Candidates: {candidates_log}", "Syndicate")
            if best_result:
                DebugLogger.log(f"Selected: {best_result.message} (P{best_priority})", "Syndicate")
        
        return best_result

