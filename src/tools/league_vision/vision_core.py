"""
Vision core for screen capture and window detection.
"""

import mss
import numpy as np
import cv2

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("Warning: win32gui not found. Window detection may not work.")


class VisionCore:
    """Core vision functionality for screen capture."""
    
    def __init__(self, window_title="Path of Exile", resolution_config=None):
        self.window_title = window_title
        self.hwnd = None
        self.resolution_config = resolution_config
        
    def find_window(self):
        """Finds the PoE window and stores its handle."""
        if not HAS_WIN32:
            return False
        self.hwnd = win32gui.FindWindow(None, self.window_title)
        return self.hwnd is not None and self.hwnd != 0

    def get_window_rect(self):
        """Returns the window rectangle."""
        if self.resolution_config and self.resolution_config.get("enabled"):
            return {
                "top": 0, 
                "left": 0, 
                "width": self.resolution_config["width"], 
                "height": self.resolution_config["height"]
            }

        if not self.find_window():
            return None

        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            x, y, w, h = rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
            return {"top": y, "left": x, "width": w, "height": h}
        except Exception as e:
            print(f"Error getting window rect: {e}")
            return None

    def capture_region(self, region=None):
        """Captures a region of the screen."""
        if region is None:
            region = self.get_window_rect()
            if region is None:
                return None
        
        with mss.mss() as sct:
            screenshot = sct.grab(region)
        
        img = np.array(screenshot)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    def get_mouse_tooltip_region(self, width=400, height=200):
        """Calculates a region around the mouse cursor."""
        if not HAS_WIN32:
            return None
            
        point = win32gui.GetCursorPos()
        mx, my = point
        
        region = {
            "top": max(0, my - 50),
            "left": max(0, mx + 20),
            "width": width,
            "height": height
        }
        
        return region

