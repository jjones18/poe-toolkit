"""
Trade automation service wrapper.
Manages the Node.js trade sniper as a subprocess.
"""

import os
import subprocess
import threading
import time
from PyQt6.QtCore import QObject, pyqtSignal


class TradeService(QObject):
    """
    Manages the Node.js trade automation service.
    Provides start/stop control and status monitoring.
    """
    
    status_changed = pyqtSignal(str)  # running, stopped, error
    log_output = pyqtSignal(str)
    
    def __init__(self, service_dir: str = "trade_service"):
        super().__init__()
        self.service_dir = service_dir
        self.process = None
        self.output_thread = None
        self._running = False
    
    @property
    def is_running(self) -> bool:
        return self._running and self.process is not None and self.process.poll() is None
    
    def get_script_path(self) -> str:
        """Get the path to the trade monitor script."""
        return os.path.join(self.service_dir, "trade_monitor.js")
    
    def check_dependencies(self) -> tuple:
        """Check if Node.js and npm are available."""
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True)
            node_version = result.stdout.strip() if result.returncode == 0 else None
        except FileNotFoundError:
            node_version = None
        
        try:
            result = subprocess.run(["npm", "--version"], capture_output=True, text=True)
            npm_version = result.stdout.strip() if result.returncode == 0 else None
        except FileNotFoundError:
            npm_version = None
        
        return (node_version, npm_version)
    
    def install_dependencies(self):
        """Install npm dependencies."""
        if not os.path.exists(os.path.join(self.service_dir, "package.json")):
            self.log_output.emit("Error: package.json not found in trade_service/")
            return False
        
        self.log_output.emit("Installing npm dependencies...")
        
        try:
            result = subprocess.run(
                ["npm", "install"],
                cwd=self.service_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.log_output.emit("Dependencies installed successfully.")
                return True
            else:
                self.log_output.emit(f"npm install failed: {result.stderr}")
                return False
        except Exception as e:
            self.log_output.emit(f"Error installing dependencies: {e}")
            return False
    
    def start(self, auto_resume: bool = False):
        """Start the trade monitoring service."""
        if self.is_running:
            self.log_output.emit("Service is already running.")
            return
        
        script_path = self.get_script_path()
        if not os.path.exists(script_path):
            self.log_output.emit(f"Error: Script not found at {script_path}")
            self.status_changed.emit("error")
            return
        
        node_ver, _ = self.check_dependencies()
        if not node_ver:
            self.log_output.emit("Error: Node.js not found. Please install Node.js.")
            self.status_changed.emit("error")
            return
        
        try:
            # Start the Node.js process
            self.process = subprocess.Popen(
                ["node", script_path],
                cwd=self.service_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            self._running = True
            self.status_changed.emit("running")
            self.log_output.emit("Trade service started.")
            
            # Start output reader thread
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            
            # Send auto-resume choice if applicable
            if auto_resume:
                time.sleep(0.5)
                self.send_input("2\n")
            else:
                time.sleep(0.5)
                self.send_input("1\n")
            
        except Exception as e:
            self.log_output.emit(f"Error starting service: {e}")
            self.status_changed.emit("error")
    
    def stop(self):
        """Stop the trade monitoring service."""
        if not self.is_running:
            self.log_output.emit("Service is not running.")
            return
        
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        except Exception as e:
            self.log_output.emit(f"Error stopping service: {e}")
        
        self._running = False
        self.process = None
        self.status_changed.emit("stopped")
        self.log_output.emit("Trade service stopped.")
    
    def send_input(self, text: str):
        """Send input to the running process (e.g., Enter to resume)."""
        if self.is_running and self.process.stdin:
            try:
                self.process.stdin.write(text)
                self.process.stdin.flush()
            except Exception as e:
                self.log_output.emit(f"Error sending input: {e}")
    
    def resume(self):
        """Resume the paused service (send Enter key)."""
        self.send_input("\n")
        self.log_output.emit("Sent resume signal.")
    
    def _read_output(self):
        """Background thread to read process output."""
        try:
            while self._running and self.process:
                line = self.process.stdout.readline()
                if line:
                    self.log_output.emit(line.rstrip())
                elif self.process.poll() is not None:
                    break
        except Exception as e:
            self.log_output.emit(f"Output reader error: {e}")
        
        # Process ended
        if self._running:
            self._running = False
            self.status_changed.emit("stopped")
            self.log_output.emit("Trade service ended.")

