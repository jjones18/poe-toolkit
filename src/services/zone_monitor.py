"""
Zone monitoring service - watches Client.txt for zone changes.
"""

import os
import threading
import time
from PyQt6.QtCore import QObject, pyqtSignal


class ZoneMonitor(QObject):
    """
    Monitors the POE Client.txt log file to detect zone changes.
    Emits signals when the player enters a new zone.
    """
    
    zone_changed = pyqtSignal(str)  # Emits zone name
    
    def __init__(self, log_path: str = None):
        super().__init__()
        self.log_path = log_path
        self.current_zone = "Unknown"
        self.running = False
        self._thread = None
    
    def set_log_path(self, path: str):
        """Set the path to Client.txt."""
        self.log_path = path
    
    def start(self):
        """Start monitoring the log file."""
        if not self.log_path or not os.path.exists(self.log_path):
            print(f"ZoneMonitor: Log path not found: {self.log_path}")
            return False
        
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print(f"ZoneMonitor: Monitoring {self.log_path}")
        return True
    
    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
    
    def _monitor_loop(self):
        """Background thread that tails the log file."""
        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to end of file
                f.seek(0, 2)
                
                while self.running:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    
                    # Check for zone entry
                    if ": You have entered" in line:
                        try:
                            parts = line.split(": You have entered ")
                            if len(parts) > 1:
                                zone = parts[1].strip().rstrip('.')
                                if zone != self.current_zone:
                                    self.current_zone = zone
                                    self.zone_changed.emit(zone)
                        except Exception:
                            pass
        except Exception as e:
            print(f"ZoneMonitor Error: {e}")
    
    def get_current_zone(self) -> str:
        """Get the current zone name."""
        return self.current_zone
    
    def is_in_hideout(self) -> bool:
        """Check if currently in a hideout."""
        return "Hideout" in self.current_zone
    
    def is_in_map(self) -> bool:
        """Check if currently in a map (not hideout, not town)."""
        towns = ["Lioneye's Watch", "The Forest Encampment", "The Sarn Encampment",
                 "Highgate", "Overseer's Tower", "The Bridge Encampment", 
                 "Oriath", "Karui Shores"]
        
        if self.is_in_hideout():
            return False
        
        for town in towns:
            if town in self.current_zone:
                return False
        
        return self.current_zone != "Unknown"

