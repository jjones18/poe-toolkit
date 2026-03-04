"""
Cross-platform window and input utilities for POE Toolkit.

Provides a unified interface for window detection and cursor position,
abstracting over win32gui (Windows), python-xlib (Linux), and pynput.
"""

import sys
import subprocess

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


def get_foreground_window_title() -> str:
    """Returns the title of the currently focused window, or '' on failure."""
    if IS_WINDOWS and HAS_WIN32:
        try:
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    if IS_LINUX:
        if HAS_XLIB:
            try:
                _display.sync()
                root = _display.screen().root
                active_prop = root.get_full_property(_NET_ACTIVE_WINDOW, _X.AnyPropertyType)
                if active_prop and active_prop.value:
                    win_id = active_prop.value[0]
                    win = _display.create_resource_object('window', win_id)
                    name_prop = win.get_full_property(_NET_WM_NAME, 0)
                    if name_prop and name_prop.value:
                        val = name_prop.value
                        return val.decode('utf-8', errors='ignore') if isinstance(val, bytes) else str(val)
                    wm_name = win.get_wm_name()
                    return wm_name or ""
            except Exception:
                pass

        # Fallback: xdotool
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return ""


def find_window_rect(title: str):
    """
    Find a window by title and return its screen rect as
    {"left": x, "top": y, "width": w, "height": h}, or None if not found.
    On Linux, matches windows whose title contains `title` (case-insensitive).
    """
    if IS_WINDOWS and HAS_WIN32:
        try:
            hwnd = win32gui.FindWindow(None, title)
            if not hwnd:
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
                            name_prop = win.get_full_property(_NET_WM_NAME, 0)
                            if name_prop and name_prop.value:
                                val = name_prop.value
                                name = val.decode('utf-8', errors='ignore') if isinstance(val, bytes) else str(val)
                                if title.lower() in name.lower():
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
                wid = result.stdout.strip().split('\n')[0]
                geo = subprocess.run(
                    ["xdotool", "getwindowgeometry", "--shell", wid],
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
