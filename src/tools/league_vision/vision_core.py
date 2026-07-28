"""
Vision core for screen capture and window detection.
"""

import mss
import numpy as np
import cv2

from utils import platform_utils


class VisionCore:
    """Core vision functionality for screen capture."""

    def __init__(self, window_title="Path of Exile", resolution_config=None, *, exact_title=False, process_names=None, title_matcher=None):
        self.window_title = window_title
        self.resolution_config = resolution_config
        self.exact_title = exact_title
        self.process_names = tuple(process_names or ())
        self.title_matcher = title_matcher

    def find_window(self):
        """Finds the PoE window."""
        return self.get_window_rect() is not None

    def get_window_rect(self):
        """Returns the window rectangle as {"left", "top", "width", "height"}, or None."""
        if self.resolution_config and self.resolution_config.get("enabled"):
            return {
                "top": 0,
                "left": 0,
                "width": self.resolution_config["width"],
                "height": self.resolution_config["height"]
            }
        return platform_utils.find_window_rect(
            self.window_title,
            exact_title=self.exact_title,
            process_names=self.process_names,
            title_matcher=self.title_matcher,
        )

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
        mx, my = platform_utils.get_cursor_pos()

        region = {
            "top": max(0, my - 50),
            "left": max(0, mx + 20),
            "width": width,
            "height": height
        }

        return region

