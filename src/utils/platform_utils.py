"""
Cross-platform window and input utilities for POE Toolkit.

Provides a unified interface for window detection and cursor position,
abstracting over win32gui (Windows), python-xlib (Linux), and pynput.
"""

import sys
import subprocess
from pathlib import Path


IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# --- Windows: win32gui ---
if IS_WINDOWS:
    try:
        import win32gui
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
else:
    HAS_WIN32 = False

# --- Linux: python-xlib ---
HAS_XLIB = False
if IS_LINUX:
    try:
        from Xlib import display as _xlib_display, X as _X
        _display = _xlib_display.Display()
        _NET_ACTIVE_WINDOW = _display.intern_atom('_NET_ACTIVE_WINDOW')
        _NET_WM_NAME = _display.intern_atom('_NET_WM_NAME')
        _NET_WM_PID = _display.intern_atom('_NET_WM_PID')
        _NET_CLIENT_LIST = _display.intern_atom('_NET_CLIENT_LIST')
        HAS_XLIB = True
    except Exception:
        pass

# --- pynput for cursor position (cross-platform, already a dependency) ---
HAS_PYNPUT = False
try:
    from pynput.mouse import Controller as _MouseController
    _mouse_controller = _MouseController()
    HAS_PYNPUT = True
except ImportError:
    pass


def get_cursor_pos() -> tuple:
    """Returns (x, y) cursor position as integers."""
    if IS_WINDOWS and HAS_WIN32:
        return win32gui.GetCursorPos()
    if HAS_PYNPUT:
        pos = _mouse_controller.position
        return (int(pos[0]), int(pos[1]))
    return (0, 0)


def _window_name_from_xlib_window(win) -> str:
    name_prop = win.get_full_property(_NET_WM_NAME, 0)
    if name_prop and name_prop.value:
        val = name_prop.value
        return val.decode('utf-8', errors='ignore') if isinstance(val, bytes) else str(val)
    return win.get_wm_name() or ""


def get_foreground_window_identity() -> dict:
    """Return {title, process_name, pid} for the active window, or empty values on failure."""
    if IS_WINDOWS and HAS_WIN32:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return {"title": "", "process_name": "", "pid": ""}
            title = win32gui.GetWindowText(hwnd) or ""
            pid = ""
            process_name = ""
            try:
                import win32process
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = _windows_process_name(pid)
            except Exception:
                process_name = ""
            return {"title": title, "process_name": process_name, "pid": str(pid or "")}
        except Exception:
            return {"title": "", "process_name": "", "pid": ""}

    if IS_LINUX:
        if HAS_XLIB:
            try:
                _display.sync()
                root = _display.screen().root
                active_prop = root.get_full_property(_NET_ACTIVE_WINDOW, _X.AnyPropertyType)
                if active_prop and active_prop.value:
                    win_id = active_prop.value[0]
                    win = _display.create_resource_object('window', win_id)
                    title = _window_name_from_xlib_window(win)
                    pid = ""
                    process_name = ""
                    pid_prop = win.get_full_property(_NET_WM_PID, _X.AnyPropertyType)
                    if pid_prop and getattr(pid_prop, 'value', None):
                        pid = str(pid_prop.value[0])
                        process_name = _process_name_from_pid(pid)
                    return {"title": title, "process_name": process_name, "pid": pid}
            except Exception:
                pass

        # Fallback: xdotool, split into bounded calls so PID failures can fail closed.
        try:
            active = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True, text=True, timeout=1
            )
            if active.returncode == 0 and active.stdout.strip():
                wid = active.stdout.strip().splitlines()[0]
                title = ""
                pid = ""
                name = subprocess.run(
                    ["xdotool", "getwindowname", wid],
                    capture_output=True, text=True, timeout=1
                )
                if name.returncode == 0:
                    title = name.stdout.strip()
                pid_result = subprocess.run(
                    ["xdotool", "getwindowpid", wid],
                    capture_output=True, text=True, timeout=1
                )
                if pid_result.returncode == 0:
                    pid = pid_result.stdout.strip()
                return {"title": title, "process_name": _process_name_from_pid(pid), "pid": str(pid or "").strip()}
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return {"title": "", "process_name": "", "pid": ""}


def get_foreground_window_title() -> str:
    """Returns the title of the currently focused window, or '' on failure."""
    return get_foreground_window_identity().get("title", "")


def _window_title_matches(name: str, title: str, *, exact_title: bool = False, title_matcher=None) -> bool:
    if title_matcher is not None:
        return bool(title_matcher(name))
    if exact_title:
        return str(name or "").strip() == str(title or "").strip()
    return str(title or "").lower() in str(name or "").lower()


def _process_name_matches(process_name: str, process_names) -> bool:
    if not process_names:
        return True
    expected = {str(name).lower() for name in process_names}
    candidate = str(process_name or "").strip()
    if not candidate:
        return False
    base = candidate.replace('\\', '/').rsplit('/', 1)[-1]
    return candidate.lower() in expected or base.lower() in expected


def _exe_token_from_cmdline(pid: str) -> str:
    """Return a .exe token from /proc cmdline for Wine/Proton processes, if present."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    for token in raw.replace(b'\x00', b' ').split():
        text = token.decode('utf-8', errors='ignore').strip().strip('"')
        base = text.replace('\\', '/').rsplit('/', 1)[-1]
        if base.lower().endswith('.exe'):
            return base
    return ""


def _process_name_from_pid(pid: str) -> str:
    pid = str(pid or "").strip()
    if not pid:
        return ""
    if IS_LINUX:
        exe_token = _exe_token_from_cmdline(pid)
        if exe_token:
            return exe_token
        try:
            exe = Path(f"/proc/{pid}/exe").readlink()
            if exe:
                return str(exe).rsplit('/', 1)[-1]
        except OSError:
            pass
    try:
        ps = subprocess.run(
            ["ps", "-p", pid, "-o", "comm="],
            capture_output=True, text=True, timeout=1
        )
        if ps.returncode == 0:
            return ps.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _linux_window_process_name(wid: str) -> str:
    try:
        pid = subprocess.run(
            ["xdotool", "getwindowpid", str(wid)],
            capture_output=True, text=True, timeout=1
        )
        if pid.returncode == 0:
            return _process_name_from_pid(pid.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _windows_process_name(pid: int) -> str:
    """Return a Windows executable path/name using the existing pywin32 dependency."""
    try:
        import win32api
        import win32con
        import win32process

        access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
        handle = win32api.OpenProcess(access, False, int(pid))
        try:
            return win32process.GetModuleFileNameEx(handle, 0) or ""
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def find_window_rect(title: str, *, exact_title: bool = False, process_names=None, title_matcher=None):
    """
    Find a window by title and return its screen rect as
    {"left": x, "top": y, "width": w, "height": h}, or None if not found.

    By default, preserves legacy contains matching. Callers that know the exact
    game/window identity can request exact title and/or process-name filtering.
    """
    if IS_WINDOWS and HAS_WIN32:
        try:
            hwnd = win32gui.FindWindow(None, title)
            if not hwnd:
                return None
            if process_names:
                try:
                    import win32process
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    process_name = _windows_process_name(pid)
                    if not _process_name_matches(process_name, process_names):
                        return None
                except Exception:
                    return None
            rect = win32gui.GetWindowRect(hwnd)
            x, y, x2, y2 = rect
            return {"left": x, "top": y, "width": x2 - x, "height": y2 - y}
        except Exception:
            return None

    if IS_LINUX:
        if HAS_XLIB:
            try:
                _display.sync()
                root = _display.screen().root
                client_list_prop = root.get_full_property(_NET_CLIENT_LIST, _X.AnyPropertyType)
                if client_list_prop and client_list_prop.value:
                    for win_id in client_list_prop.value:
                        win = _display.create_resource_object('window', win_id)
                        try:
                            name = _window_name_from_xlib_window(win)
                            if _window_title_matches(name, title, exact_title=exact_title, title_matcher=title_matcher):
                                if process_names:
                                    pid_prop = win.get_full_property(_NET_WM_PID, _X.AnyPropertyType)
                                    if not pid_prop or not getattr(pid_prop, 'value', None):
                                        continue
                                    if not _process_name_matches(_process_name_from_pid(pid_prop.value[0]), process_names):
                                        continue
                                geom = win.get_geometry()
                                translated = root.translate_coords(win, 0, 0)
                                return {
                                    "left": translated.x,
                                    "top": translated.y,
                                    "width": geom.width,
                                    "height": geom.height,
                                }
                        except Exception:
                            continue
            except Exception:
                pass

        # Fallback: xdotool
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0 and result.stdout.strip():
                matching_wid = None
                for wid in result.stdout.strip().split('\n'):
                    name = subprocess.run(
                        ["xdotool", "getwindowname", wid],
                        capture_output=True, text=True, timeout=1
                    )
                    if name.returncode != 0 or not _window_title_matches(name.stdout.strip(), title, exact_title=exact_title, title_matcher=title_matcher):
                        continue
                    if process_names and not _process_name_matches(_linux_window_process_name(wid), process_names):
                        continue
                    matching_wid = wid
                    break
                if matching_wid is None:
                    return None
                geo = subprocess.run(
                    ["xdotool", "getwindowgeometry", "--shell", matching_wid],
                    capture_output=True, text=True, timeout=1
                )
                if geo.returncode == 0:
                    vals = {}
                    for line in geo.stdout.strip().split('\n'):
                        if '=' in line:
                            k, v = line.split('=', 1)
                            vals[k.strip()] = v.strip()
                    return {
                        "left": int(vals.get("X", 0)),
                        "top": int(vals.get("Y", 0)),
                        "width": int(vals.get("WIDTH", 0)),
                        "height": int(vals.get("HEIGHT", 0)),
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
            pass

    return None
