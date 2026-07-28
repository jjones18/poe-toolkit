"""
Trade automation service wrapper.
Manages the Node.js trade sniper as a subprocess.
"""

import atexit
import hashlib
import os
import platform
import signal
import subprocess
import tempfile
import threading
from PyQt6.QtCore import QObject, pyqtSignal

from utils.workers import CancelledError, CancellationToken, run_cancellable_process


class TradeService(QObject):
    """
    Manages the Node.js trade automation service.
    Provides start/stop control and status monitoring.
    """
    
    status_changed = pyqtSignal(str)  # running, stopped, error
    log_output = pyqtSignal(str)
    
    def __init__(self, service_dir: str = None, owner_file: str = None):
        super().__init__()
        if service_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.service_dir = os.path.join(project_root, "trade_service")
        else:
            self.service_dir = os.path.abspath(service_dir)

        if owner_file is None:
            install_id = hashlib.sha256(self.service_dir.encode("utf-8")).hexdigest()[:16]
            owner_file = os.path.join(
                tempfile.gettempdir(), f"poe-toolkit-trade-{install_id}.lock"
            )
        self.owner_file = os.path.abspath(owner_file)
        
        self.process = None
        self.output_thread = None
        self._running = False
        self._stopping = False
        
        atexit.register(self._force_cleanup)
        if platform.system() != 'Windows':
            for sig in (signal.SIGTERM, signal.SIGHUP):
                try:
                    signal.signal(sig, self._signal_handler)
                except (OSError, ValueError):
                    pass
    
    def _signal_handler(self, signum, frame):
        """Best-effort cleanup on unexpected termination signals."""
        self._force_cleanup()

    @staticmethod
    def _taskkill_tree(process, *, force: bool, wait_timeout: float) -> None:
        """Run bounded Windows process-tree termination without a shell."""
        command = ["taskkill"]
        if force:
            command.append("/F")
        command.extend(["/T", "/PID", str(process.pid)])
        try:
            subprocess.run(
                command,
                shell=False,
                capture_output=True,
                timeout=3,
                check=False,
            )
            process.wait(timeout=wait_timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _force_cleanup(self):
        """Best-effort graceful cleanup for atexit and termination signals."""
        process = self.process
        if process is None:
            return

        self._stopping = True

        try:
            if process.poll() is None and process.stdin:
                try:
                    process.stdin.write("__shutdown__\n")
                    process.stdin.flush()
                    process.wait(timeout=7)
                except (subprocess.TimeoutExpired, BrokenPipeError, OSError):
                    pass

            if process.poll() is None:
                if platform.system() == 'Windows':
                    self._taskkill_tree(process, force=False, wait_timeout=3)
                    if process.poll() is None:
                        self._taskkill_tree(process, force=True, wait_timeout=2)
                else:
                    pgid = None
                    try:
                        pgid = os.getpgid(process.pid)
                        os.killpg(pgid, signal.SIGTERM)
                        process.wait(timeout=7)
                    except subprocess.TimeoutExpired:
                        if pgid is not None:
                            os.killpg(pgid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait(timeout=2)
                    except (OSError, ProcessLookupError):
                        process.kill()
                        process.wait(timeout=2)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
        finally:
            if process.poll() is not None:
                self.process = None
                self._running = False
                self._release_ownership()
            self._stopping = False
    
    @property
    def is_running(self) -> bool:
        return self._running and self.process is not None and self.process.poll() is None
    
    def get_script_path(self) -> str:
        """Get the path to the trade monitor script."""
        return os.path.join(self.service_dir, "trade_monitor.js")
    
    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        """Return whether a local process ID is still alive."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _read_owner_pid(self):
        try:
            with open(self.owner_file, "r", encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (OSError, TypeError, ValueError):
            return None

    def _claim_ownership(self):
        """Atomically claim this installation without inspecting other Node processes."""
        owner_pid = self._read_owner_pid()
        if owner_pid and self._pid_is_alive(owner_pid):
            return False, owner_pid

        if owner_pid is not None or os.path.exists(self.owner_file):
            try:
                os.remove(self.owner_file)
            except FileNotFoundError:
                pass
            except OSError:
                return False, owner_pid

        os.makedirs(os.path.dirname(self.owner_file), exist_ok=True)
        try:
            descriptor = os.open(
                self.owner_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            return True, os.getpid()
        except FileExistsError:
            return False, self._read_owner_pid()
        except OSError:
            return False, None

    def _release_ownership(self):
        """Release this controller's installation-scoped ownership file."""
        if self._read_owner_pid() != os.getpid():
            return
        try:
            os.remove(self.owner_file)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _close_process_resources(self, process):
        """Close controller pipes and join its output reader after process exit."""
        for stream_name in ("stdin", "stdout"):
            stream = getattr(process, stream_name, None)
            if stream is not None and hasattr(stream, "close"):
                try:
                    stream.close()
                except OSError:
                    pass

        output_thread = self.output_thread
        if output_thread is not None and output_thread is not threading.current_thread():
            output_thread.join(timeout=2)
        self.output_thread = None
    
    def check_dependencies(self, token: CancellationToken | None = None) -> tuple:
        """Check if Node.js and npm are available."""
        token = token or CancellationToken()
        try:
            result = run_cancellable_process(
                ["node", "--version"],
                token=token,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            node_version = result.stdout.strip() if result.returncode == 0 else None
        except CancelledError:
            raise
        except Exception:
            node_version = None

        try:
            npm_command = "npm.cmd" if platform.system() == "Windows" else "npm"
            result = run_cancellable_process(
                [npm_command, "--version"],
                token=token,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            npm_version = result.stdout.strip() if result.returncode == 0 else None
        except CancelledError:
            raise
        except Exception:
            npm_version = None

        return (node_version, npm_version)

    def install_dependencies(self, token: CancellationToken | None = None):
        """Install npm dependencies."""
        token = token or CancellationToken()
        if not os.path.exists(os.path.join(self.service_dir, "package.json")):
            self.log_output.emit("Error: package.json not found in trade_service/")
            return False

        self.log_output.emit("Installing npm dependencies...")

        try:
            npm_command = "npm.cmd" if platform.system() == "Windows" else "npm"
            result = run_cancellable_process(
                [npm_command, "install"],
                token=token,
                cwd=self.service_dir,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )

            if result.returncode == 0:
                self.log_output.emit("Dependencies installed successfully.")
                return True
            self.log_output.emit(f"npm install failed: {result.stderr}")
            return False
        except CancelledError:
            raise
        except Exception as error:
            self.log_output.emit(f"Error installing dependencies: {error}")
            return False

    def start(
        self,
        auto_resume: bool = False,
        auto_resume_delay_s: int = 60,
        cooldown_s: int = 5,
        game_id: str = "poe1",
    ):
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
        
        claimed, owner_pid = self._claim_ownership()
        if not claimed:
            owner_text = f" (PID {owner_pid})" if owner_pid else ""
            self.log_output.emit(
                "Another controller already owns this Trade Sniper installation"
                f"{owner_text}. Stop it before starting another controller."
            )
            self.status_changed.emit("error")
            return
        
        try:
            safe_game_id = "poe2" if game_id == "poe2" else "poe1"
            cmd = [
                "node",
                "trade_monitor.js",
                f"--cooldown={cooldown_s}",
                f"--auto-resume-delay={auto_resume_delay_s}",
                f"--game={safe_game_id}",
            ]
            if auto_resume:
                cmd.append("--auto-resume")
            
            popen_kwargs = dict(
                cwd=self.service_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                shell=False,
                encoding='utf-8',
                errors='replace',
            )
            if platform.system() != 'Windows':
                popen_kwargs['start_new_session'] = True
            
            self.process = subprocess.Popen(cmd, **popen_kwargs)
            
            self._stopping = False
            self._running = True
            self.status_changed.emit("running")
            self.log_output.emit("Trade service started.")
            
            # Start output reader thread
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            
        except Exception as e:
            self._release_ownership()
            self.log_output.emit(f"Error starting service: {e}")
            self.status_changed.emit("error")
    
    def stop(self, token: CancellationToken | None = None):
        """Disarm browser workers, accelerating escalation when cancellation is requested."""
        token = token or CancellationToken()
        if not self.is_running:
            self.log_output.emit("Service is not running.")
            return False

        process = self.process
        if process is None:
            self._running = False
            self.status_changed.emit("stopped")
            return True

        self._stopping = True

        try:
            # Always ask Node to disarm browser workers. Cancellation skips only
            # the grace wait; it never abandons process shutdown half-complete.
            if process.stdin:
                try:
                    process.stdin.write("__shutdown__\n")
                    process.stdin.flush()
                    if not token.is_cancelled:
                        process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    pass
                except (BrokenPipeError, OSError):
                    pass

            # Escalate only if the graceful protocol did not stop the process.
            if process.poll() is None:
                if platform.system() == 'Windows':
                    if not token.is_cancelled:
                        self._taskkill_tree(process, force=False, wait_timeout=3)
                    if process.poll() is None:
                        self._taskkill_tree(process, force=True, wait_timeout=2)
                else:
                    pgid = None
                    try:
                        pgid = os.getpgid(process.pid)
                        if token.is_cancelled:
                            os.killpg(pgid, signal.SIGKILL)
                            process.wait(timeout=2)
                        else:
                            os.killpg(pgid, signal.SIGTERM)
                            process.wait(timeout=7)
                    except subprocess.TimeoutExpired:
                        if pgid is not None:
                            os.killpg(pgid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait(timeout=2)
                    except (OSError, ProcessLookupError):
                        process.kill()
        except Exception as e:
            self.log_output.emit(f"Error stopping service: {e}")

        if process.poll() is None:
            self._stopping = False
            self._running = True
            self.process = process
            self.status_changed.emit("error")
            self.log_output.emit("Trade service could not be stopped; browser automation may still be active.")
            return False

        self._running = False
        self.process = None
        self._stopping = False
        self._close_process_resources(process)
        self._release_ownership()
        self.status_changed.emit("stopped")
        self.log_output.emit("Trade service stopped.")
        return True

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
        process = self.process
        if process is None or process.stdout is None:
            return
        stdout = process.stdout

        try:
            while self._running and self.process is process:
                try:
                    line = stdout.readline()
                    if line:
                        self.log_output.emit(line.rstrip())
                    elif process.poll() is not None:
                        break
                except UnicodeDecodeError as e:
                    # Skip lines that can't be decoded
                    self.log_output.emit(f"[decode error: {e}]")
                    continue
        except Exception as e:
            self.log_output.emit(f"Output reader error: {e}")
        
        # Unexpected process exits update status. Intentional Stop owns its status.
        if self._running and not self._stopping and self.process is process:
            self._running = False
            self.process = None
            self._release_ownership()
            self.status_changed.emit("stopped")
            self.log_output.emit("Trade service ended.")

