"""Minimal KWin EIS sender used for compositor-native input.

This module is adapted from kwin-mcp's ``kwin_mcp/input.py`` by
Byeonghoon Yoo (https://github.com/isac322/kwin-mcp), used under the MIT
License.  The adaptation intentionally keeps only the absolute-pointer,
button, and keyboard pieces needed by POE Toolkit.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import select
import time
from typing import Any

# Linux evdev codes used by the high-level backend.
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

PRESSED = 1
RELEASED = 0

EI_CAP_POINTER = 1 << 0
EI_CAP_POINTER_ABSOLUTE = 1 << 1
EI_CAP_KEYBOARD = 1 << 2
EI_CAP_TOUCH = 1 << 3
EI_CAP_SCROLL = 1 << 4
EI_CAP_BUTTON = 1 << 5

EI_EVENT_DISCONNECT = 2
EI_EVENT_SEAT_ADDED = 3
EI_EVENT_DEVICE_ADDED = 5


def _load_libei() -> ctypes.CDLL:
    """Load libei and declare the subset of its C API that we use."""
    lib = ctypes.CDLL("libei.so.1")

    lib.ei_new_sender.restype = ctypes.c_void_p
    lib.ei_new_sender.argtypes = [ctypes.c_void_p]
    lib.ei_configure_name.restype = None
    lib.ei_configure_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.ei_setup_backend_fd.restype = ctypes.c_int
    lib.ei_setup_backend_fd.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ei_dispatch.restype = ctypes.c_int
    lib.ei_dispatch.argtypes = [ctypes.c_void_p]
    lib.ei_get_event.restype = ctypes.c_void_p
    lib.ei_get_event.argtypes = [ctypes.c_void_p]
    lib.ei_event_get_type.restype = ctypes.c_int
    lib.ei_event_get_type.argtypes = [ctypes.c_void_p]
    lib.ei_event_unref.restype = ctypes.c_void_p
    lib.ei_event_unref.argtypes = [ctypes.c_void_p]
    lib.ei_unref.restype = ctypes.c_void_p
    lib.ei_unref.argtypes = [ctypes.c_void_p]
    lib.ei_get_fd.restype = ctypes.c_int
    lib.ei_get_fd.argtypes = [ctypes.c_void_p]

    lib.ei_event_get_seat.restype = ctypes.c_void_p
    lib.ei_event_get_seat.argtypes = [ctypes.c_void_p]
    lib.ei_seat_has_capability.restype = ctypes.c_int
    lib.ei_seat_has_capability.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    lib.ei_seat_bind_capabilities.restype = None
    lib.ei_seat_bind_capabilities.argtypes = [ctypes.c_void_p]

    lib.ei_event_get_device.restype = ctypes.c_void_p
    lib.ei_event_get_device.argtypes = [ctypes.c_void_p]
    lib.ei_device_has_capability.restype = ctypes.c_int
    lib.ei_device_has_capability.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    lib.ei_device_ref.restype = ctypes.c_void_p
    lib.ei_device_ref.argtypes = [ctypes.c_void_p]
    lib.ei_device_unref.restype = ctypes.c_void_p
    lib.ei_device_unref.argtypes = [ctypes.c_void_p]
    lib.ei_device_get_region_at.restype = ctypes.c_void_p
    lib.ei_device_get_region_at.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
    ]

    lib.ei_device_pointer_motion_absolute.restype = None
    lib.ei_device_pointer_motion_absolute.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
    ]
    lib.ei_device_button_button.restype = None
    lib.ei_device_button_button.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
    lib.ei_device_keyboard_key.restype = None
    lib.ei_device_keyboard_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
    lib.ei_device_frame.restype = None
    lib.ei_device_frame.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.ei_device_start_emulating.restype = None
    lib.ei_device_start_emulating.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.ei_device_stop_emulating.restype = None
    lib.ei_device_stop_emulating.argtypes = [ctypes.c_void_p]

    return lib


class KWinEisClient:
    """Direct KWin RemoteDesktop EIS connection using libei sender mode."""

    def __init__(self, dbus_address: str | None = None, timeout: float = 5.0):
        try:
            import dbus
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "dbus-python is required for KDE Wayland input; install the full input extra"
            ) from exc

        self._dbus = dbus
        address = dbus_address or os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not address:
            raise RuntimeError("DBUS_SESSION_BUS_ADDRESS is unavailable")

        self._libei = _load_libei()
        self._bus: Any = dbus.bus.BusConnection(address)
        self._ei = 0
        self._cookie = 0
        self._pointer_devices: list[int] = []
        self._active_pointer = 0
        self._keyboard = 0
        self._eis_iface: Any = None
        self._setup(timeout)

    def _setup(self, timeout: float):
        obj = self._bus.get_object(
            "org.kde.KWin",
            "/org/kde/KWin/EIS/RemoteDesktop",
        )
        self._eis_iface = self._dbus.Interface(
            obj,
            "org.kde.KWin.EIS.RemoteDesktop",
        )
        # KWin currently advertises its keyboard device only when the client
        # requests/binds the complete desktop-input capability set. Toolkit
        # still registers and exposes only absolute pointer/button + keyboard.
        caps = (
            EI_CAP_POINTER
            | EI_CAP_POINTER_ABSOLUTE
            | EI_CAP_KEYBOARD
            | EI_CAP_TOUCH
            | EI_CAP_SCROLL
            | EI_CAP_BUTTON
        )
        result = self._eis_iface.connectToEIS(self._dbus.Int32(caps))
        fd = result[0].take()
        self._cookie = int(result[1])

        self._ei = self._libei.ei_new_sender(None)
        if not self._ei:
            raise RuntimeError("Failed to create libei sender context")
        self._libei.ei_configure_name(self._ei, b"poe-toolkit")
        ret = self._libei.ei_setup_backend_fd(self._ei, fd)
        if ret != 0:
            self._libei.ei_unref(self._ei)
            self._ei = 0
            raise RuntimeError(f"ei_setup_backend_fd failed: {ret}")

        self._negotiate_devices(timeout)

    def _negotiate_devices(self, timeout: float):
        fd = self._libei.ei_get_fd(self._ei)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            readable, _, _ = select.select([fd], [], [], 0.3)
            if readable and self._libei.ei_dispatch(self._ei) < 0:
                break

            while True:
                event = self._libei.ei_get_event(self._ei)
                if not event:
                    break
                try:
                    event_type = self._libei.ei_event_get_type(event)
                    if event_type == EI_EVENT_DISCONNECT:
                        raise RuntimeError("KWin EIS disconnected during handshake")
                    if event_type == EI_EVENT_SEAT_ADDED:
                        self._bind_capabilities(event)
                    elif event_type == EI_EVENT_DEVICE_ADDED:
                        self._register_device(event)
                finally:
                    self._libei.ei_event_unref(event)

            if self._pointer_devices and self._keyboard:
                for pointer in self._pointer_devices:
                    self._libei.ei_device_start_emulating(pointer, 0)
                if self._keyboard not in self._pointer_devices:
                    self._libei.ei_device_start_emulating(self._keyboard, 0)
                return

        missing = []
        if not self._pointer_devices:
            missing.append("absolute pointer")
        if not self._keyboard:
            missing.append("keyboard")
        raise RuntimeError(f"KWin EIS did not provide: {', '.join(missing)}")

    def _bind_capabilities(self, event: int):
        seat = self._libei.ei_event_get_seat(event)
        caps = [
            cap
            for cap in (
                EI_CAP_POINTER,
                EI_CAP_POINTER_ABSOLUTE,
                EI_CAP_KEYBOARD,
                EI_CAP_TOUCH,
                EI_CAP_SCROLL,
                EI_CAP_BUTTON,
            )
            if self._libei.ei_seat_has_capability(seat, cap)
        ]
        args: list[Any] = [ctypes.c_uint(cap) for cap in caps]
        args.append(ctypes.c_void_p(None))
        self._libei.ei_seat_bind_capabilities(seat, *args)

    def _register_device(self, event: int):
        device = self._libei.ei_event_get_device(event)
        if (
            self._libei.ei_device_has_capability(device, EI_CAP_POINTER_ABSOLUTE)
            and self._libei.ei_device_has_capability(device, EI_CAP_BUTTON)
        ):
            pointer = self._libei.ei_device_ref(device)
            if pointer not in self._pointer_devices:
                self._pointer_devices.append(pointer)
        if not self._keyboard and self._libei.ei_device_has_capability(device, EI_CAP_KEYBOARD):
            self._keyboard = self._libei.ei_device_ref(device)

    @staticmethod
    def _now_us() -> int:
        return int(time.monotonic() * 1_000_000)

    def _frame(self, device: int):
        self._libei.ei_device_frame(device, self._now_us())
        if self._libei.ei_dispatch(self._ei) < 0:
            raise RuntimeError("KWin EIS dispatch failed")

    def _pointer_for_point(self, x: float, y: float) -> int:
        for pointer in self._pointer_devices:
            if self._libei.ei_device_get_region_at(pointer, x, y):
                return pointer
        raise RuntimeError(
            f"KWin EIS has no absolute-pointer region containing ({x:g}, {y:g})"
        )

    def pointer_move_absolute(self, x: float, y: float):
        pointer = self._pointer_for_point(x, y)
        self._libei.ei_device_pointer_motion_absolute(pointer, x, y)
        self._frame(pointer)
        self._active_pointer = pointer

    def pointer_button(self, button: int, state: int):
        if not self._active_pointer:
            raise RuntimeError("Move the KWin EIS pointer before sending a button event")
        self._libei.ei_device_button_button(self._active_pointer, button, state)
        self._frame(self._active_pointer)

    def keyboard_key(self, keycode: int, state: int):
        self._libei.ei_device_keyboard_key(self._keyboard, keycode, state)
        self._frame(self._keyboard)

    def close(self):
        pointers = self._pointer_devices
        keyboard = self._keyboard
        self._pointer_devices = []
        self._active_pointer = 0
        self._keyboard = 0

        if keyboard:
            with contextlib.suppress(Exception):
                self._libei.ei_device_stop_emulating(keyboard)
            if keyboard not in pointers:
                self._libei.ei_device_unref(keyboard)
        for pointer in pointers:
            with contextlib.suppress(Exception):
                self._libei.ei_device_stop_emulating(pointer)
            self._libei.ei_device_unref(pointer)

        if self._ei:
            self._libei.ei_unref(self._ei)
            self._ei = 0

        if self._eis_iface and self._cookie:
            with contextlib.suppress(Exception):
                self._eis_iface.disconnect(self._dbus.Int32(self._cookie))
        self._cookie = 0
