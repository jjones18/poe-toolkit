"""Configurable global start/stop hotkeys for the active Crafting page."""

from __future__ import annotations

import os
import select
import threading

from PyQt6.QtCore import QObject, pyqtSignal


SUPPORTED_HOTKEYS = (
    "Numpad Plus",
    "Numpad Minus",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
)

_NUMPAD_VKS = {
    "Numpad Plus": {107, 65451},
    "Numpad Minus": {109, 65453},
}

_EVDEV_KEYS = {
    "Numpad Plus": "KEY_KPPLUS",
    "Numpad Minus": "KEY_KPMINUS",
    "F6": "KEY_F6",
    "F7": "KEY_F7",
    "F8": "KEY_F8",
    "F9": "KEY_F9",
    "F10": "KEY_F10",
    "F11": "KEY_F11",
    "F12": "KEY_F12",
}


class EvdevKeyboardListener:
    """Read exact physical key codes without conflating keypad and main keys."""

    def __init__(self, on_press):
        self.on_press = on_press
        self._devices = []
        self._stop_event = threading.Event()
        self._thread = None
        self._evdev = None

    def start(self):
        import evdev

        tracked_codes = {
            getattr(evdev.ecodes, name) for name in _EVDEV_KEYS.values()
        }
        devices = []
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
                key_codes = set(
                    device.capabilities().get(evdev.ecodes.EV_KEY, ())
                )
                if key_codes & tracked_codes:
                    devices.append(device)
                else:
                    device.close()
            except (OSError, PermissionError):
                continue
        if not devices:
            raise RuntimeError(
                "no readable keyboard device exposes the configured hotkeys"
            )

        self._evdev = evdev
        self._devices = devices
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="crafting-evdev-hotkeys",
            daemon=True,
        )
        self._thread.start()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                ready, _, _ = select.select(self._devices, [], [], 0.2)
            except (OSError, ValueError):
                if not self._stop_event.is_set():
                    continue
                break
            for device in ready:
                try:
                    events = device.read()
                except (BlockingIOError, OSError):
                    continue
                for event in events:
                    if (
                        event.type != self._evdev.ecodes.EV_KEY
                        or event.value != 1
                    ):
                        continue
                    key_name = self._evdev.ecodes.KEY.get(event.code)
                    if isinstance(key_name, list):
                        key_name = key_name[0]
                    self.on_press(str(key_name))

    def stop(self):
        self._stop_event.set()

    def join(self, timeout=1.0):
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        for device in self._devices:
            try:
                device.close()
            except OSError:
                pass
        self._devices = []
        self._thread = None


class CraftingHotkeys(QObject):
    triggered = pyqtSignal(str)
    availability_changed = pyqtSignal(bool, str)

    def __init__(self, start_key="Numpad Plus", stop_key="Numpad Minus", parent=None):
        super().__init__(parent)
        self.start_key = start_key
        self.stop_key = stop_key
        self.listener = None

    def configure(self, start_key: str, stop_key: str):
        self.start_key = start_key if start_key in SUPPORTED_HOTKEYS else "Numpad Plus"
        self.stop_key = stop_key if stop_key in SUPPORTED_HOTKEYS else "Numpad Minus"

    @staticmethod
    def _matches(key, configured: str) -> bool:
        vk = getattr(key, "vk", None)
        if configured in _NUMPAD_VKS:
            return vk in _NUMPAD_VKS[configured]
        name = str(getattr(key, "name", "") or "").upper()
        return name == configured.upper()

    @staticmethod
    def _matches_evdev(key_name: str, configured: str) -> bool:
        return key_name == _EVDEV_KEYS.get(configured)

    @staticmethod
    def _use_evdev() -> bool:
        return (
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )

    def start(self) -> bool:
        if self.listener is not None:
            return True
        try:
            if self._use_evdev():
                self.listener = EvdevKeyboardListener(self._on_evdev_press)
                detail = "evdev exact physical keycodes"
            else:
                from pynput import keyboard

                self.listener = keyboard.Listener(on_press=self._on_press)
                detail = "pynput global listener"
            self.listener.start()
        except (ImportError, OSError, PermissionError, RuntimeError) as error:
            self.listener = None
            self.availability_changed.emit(False, str(error))
            return False
        self.availability_changed.emit(True, detail)
        return True

    def _on_press(self, key):
        if self._matches(key, self.stop_key):
            self.triggered.emit("stop")
        elif self._matches(key, self.start_key):
            self.triggered.emit("start")

    def _on_evdev_press(self, key_name: str):
        if self._matches_evdev(key_name, self.stop_key):
            self.triggered.emit("stop")
        elif self._matches_evdev(key_name, self.start_key):
            self.triggered.emit("start")

    def stop(self):
        listener, self.listener = self.listener, None
        if listener is not None:
            try:
                listener.stop()
                listener.join(timeout=1.0)
            except Exception:
                return False
        return True
