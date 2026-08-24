"""Shared, fail-closed game input for exact PoE windows.

Linux Wayland uses KWin's compositor-native EIS/libei interface. XTest/pynput
and ydotool are deliberately not used there because their coordinate/event
spaces can diverge from XWayland game hit-testing on mixed monitor layouts.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
import sys
import time
from typing import Any, Callable

from utils import platform_utils


class GameInputUnavailable(RuntimeError):
    """Raised before unsafe or unverifiable input can be injected."""


@dataclass(frozen=True)
class DesktopPoint:
    x: int
    y: int


@dataclass(frozen=True)
class WindowSnapshot:
    game_id: str
    title: str
    process_name: str
    pid: str
    left: int
    top: int
    width: int
    height: int

    def contains(self, point: DesktopPoint) -> bool:
        return (
            self.left <= point.x < self.left + self.width
            and self.top <= point.y < self.top + self.height
        )


@dataclass(frozen=True)
class WindowRelativePoint:
    """A target tied to the exact game-window size used during calibration."""

    x: int
    y: int
    reference_width: int
    reference_height: int

    def to_desktop(self, window: WindowSnapshot) -> DesktopPoint:
        if (window.width, window.height) != (
            self.reference_width,
            self.reference_height,
        ):
            raise GameInputUnavailable(
                "Game window size changed since calibration: "
                f"expected {self.reference_width}x{self.reference_height}, "
                f"found {window.width}x{window.height}. Recalibrate before input."
            )
        if not (0 <= self.x < window.width and 0 <= self.y < window.height):
            raise GameInputUnavailable(
                f"Target ({self.x}, {self.y}) is outside the calibrated game window"
            )
        return DesktopPoint(window.left + self.x, window.top + self.y)


@dataclass(frozen=True)
class InputCapability:
    available: bool
    backend: str
    detail: str = ""


def preferred_backend_name(platform_name: str | None = None, session_type: str | None = None) -> str:
    platform_name = platform_name if platform_name is not None else sys.platform
    session_type = (
        session_type
        if session_type is not None
        else os.environ.get("XDG_SESSION_TYPE", "")
    )
    if str(platform_name).startswith("linux") and str(session_type).lower() == "wayland":
        return "kwin-eis"
    return "pynput"


def focused_game_window_snapshot(game_id: str) -> WindowSnapshot | None:
    """Return the exact focused game and geometry, otherwise None."""
    identity = platform_utils.get_foreground_window_identity()
    if not platform_utils.is_exact_poe_window_title(identity.get("title", ""), game_id):
        return None
    if not platform_utils.is_exact_poe_process_name(identity.get("process_name", ""), game_id):
        return None
    match = platform_utils.POE_GAME_MATCHES[platform_utils.normalize_game_id(game_id)]
    rect = platform_utils.find_window_rect(
        platform_utils.exact_window_title_for_game(game_id),
        exact_title=True,
        process_names=match["process_names"],
    )
    if not rect or int(rect.get("width", 0)) <= 0 or int(rect.get("height", 0)) <= 0:
        return None
    return WindowSnapshot(
        game_id=platform_utils.normalize_game_id(game_id),
        title=str(identity.get("title", "")),
        process_name=str(identity.get("process_name", "")),
        pid=str(identity.get("pid", "")),
        left=int(rect["left"]),
        top=int(rect["top"]),
        width=int(rect["width"]),
        height=int(rect["height"]),
    )


class KWinEisBackend:
    """Compositor-native KDE Wayland input through KWin EIS/libei."""

    name = "kwin-eis"
    _KEY_CODES = {
        "ctrl": 29,
        "shift": 42,
        "c": 46,
        "escape": 1,
    }
    _BUTTON_CODES = {"left": 0x110, "right": 0x111}

    def __init__(
        self,
        *,
        client_factory: Callable | None = None,
        cursor_reader: Callable[[], tuple[int, int]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        tolerance_px: int = 2,
        verification_attempts: int = 3,
        key_step_delay: float = 0.005,
    ):
        self.client_factory = client_factory or self._default_client_factory
        self.cursor_reader = cursor_reader
        self.sleep = sleep
        self.tolerance_px = max(0, int(tolerance_px))
        self.verification_attempts = max(1, int(verification_attempts))
        self.key_step_delay = max(0.0, float(key_step_delay))
        self.client: Any = None
        self.prepared = False

    @staticmethod
    def _default_client_factory():
        from .kwin_eis import KWinEisClient

        return KWinEisClient()

    def capability(self) -> InputCapability:
        import ctypes.util
        import importlib.util

        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return InputCapability(False, self.name, "DBUS session address is unavailable")
        if ctypes.util.find_library("ei") is None:
            return InputCapability(False, self.name, "libei.so is unavailable")
        if importlib.util.find_spec("dbus") is None:
            return InputCapability(
                False,
                self.name,
                "dbus-python is unavailable; install the full input extra",
            )
        return InputCapability(
            True,
            self.name,
            "KWin compositor-native input available; targets validated against EIS regions and compositor cursor feedback",
        )

    def prepare(self):
        capability = self.capability()
        if not capability.available:
            raise GameInputUnavailable(capability.detail)
        if self.prepared:
            return
        try:
            self.client = self.client_factory()
        except Exception as error:
            self.client = None
            raise GameInputUnavailable(f"Could not connect to KWin EIS: {error}") from error
        self.prepared = True

    def _require_prepared(self):
        if not self.prepared or self.client is None:
            raise GameInputUnavailable("KWin EIS input is not connected")

    def move_to(self, point: DesktopPoint):
        self._require_prepared()
        target = DesktopPoint(int(point.x), int(point.y))
        if self.cursor_reader is None:
            try:
                self.client.pointer_move_absolute(float(target.x), float(target.y))
            except Exception as error:
                raise GameInputUnavailable(f"KWin EIS pointer movement failed: {error}") from error
            self.sleep(0.05)
            return
        for _attempt in range(self.verification_attempts):
            try:
                self.client.pointer_move_absolute(float(target.x), float(target.y))
            except Exception as error:
                raise GameInputUnavailable(f"KWin EIS pointer movement failed: {error}") from error
            self.sleep(0.05)
            current = self.cursor_reader()
            if (
                abs(int(current[0]) - target.x) <= self.tolerance_px
                and abs(int(current[1]) - target.y) <= self.tolerance_px
            ):
                return
        final = self.cursor_reader()
        raise GameInputUnavailable(
            f"Native cursor did not reach ({target.x}, {target.y}); "
            f"ended at ({int(final[0])}, {int(final[1])})"
        )

    def click(self, button: str):
        self._require_prepared()
        try:
            code = self._BUTTON_CODES[button]
        except KeyError as error:
            raise ValueError(f"Unsupported mouse button: {button}") from error
        try:
            self.client.pointer_button(code, 1)
            self.sleep(0.01)
            self.client.pointer_button(code, 0)
        except Exception as error:
            with contextlib.suppress(Exception):
                self.client.pointer_button(code, 0)
            raise GameInputUnavailable(f"KWin EIS click failed: {error}") from error

    def key_down(self, key: str):
        self._key_event(key, True)

    def key_up(self, key: str):
        self._key_event(key, False)

    def _key_event(self, key: str, pressed: bool):
        self._require_prepared()
        try:
            code = self._KEY_CODES[key]
        except KeyError as error:
            raise ValueError(f"Unsupported key: {key}") from error
        try:
            self.client.keyboard_key(code, 1 if pressed else 0)
        except Exception as error:
            raise GameInputUnavailable(f"KWin EIS key event failed: {error}") from error

    def key_chord(self, *keys: str):
        self._require_prepared()
        pressed: list[str] = []
        try:
            for key in keys:
                self.key_down(key)
                pressed.append(key)
                self.sleep(self.key_step_delay)
        finally:
            for index, key in enumerate(reversed(pressed)):
                with contextlib.suppress(Exception):
                    self.key_up(key)
                if index < len(pressed) - 1:
                    self.sleep(self.key_step_delay)

    def release_all(self):
        if not self.prepared or self.client is None:
            return
        for button in self._BUTTON_CODES.values():
            with contextlib.suppress(Exception):
                self.client.pointer_button(button, 0)
        for key in ("ctrl", "shift"):
            with contextlib.suppress(Exception):
                self.client.keyboard_key(self._KEY_CODES[key], 0)

    def close(self):
        client = self.client
        try:
            self.release_all()
        finally:
            self.client = None
            self.prepared = False
            if client is not None:
                with contextlib.suppress(Exception):
                    client.close()


class PynputBackend:
    """Non-Wayland fallback for Windows and X11."""

    name = "pynput"

    def __init__(self):
        self.keyboard = None
        self.mouse = None
        self.keyboard_module = None
        self.mouse_module = None

    def capability(self) -> InputCapability:
        try:
            from pynput import keyboard, mouse  # noqa: F401
        except (ImportError, OSError) as error:
            return InputCapability(False, self.name, str(error))
        return InputCapability(True, self.name, "pynput input available")

    def prepare(self):
        capability = self.capability()
        if not capability.available:
            raise GameInputUnavailable(capability.detail)
        from pynput import keyboard, mouse

        self.keyboard_module = keyboard
        self.mouse_module = mouse
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()

    def _require_prepared(self):
        if self.keyboard is None or self.mouse is None:
            raise GameInputUnavailable("pynput backend is not prepared")

    def move_to(self, point: DesktopPoint):
        self._require_prepared()
        self.mouse.position = (point.x, point.y)

    def click(self, button: str):
        self._require_prepared()
        button_value = getattr(self.mouse_module.Button, button)
        self.mouse.click(button_value, 1)

    def _key_value(self, key: str):
        if key == "ctrl":
            return self.keyboard_module.Key.ctrl
        if key == "shift":
            return self.keyboard_module.Key.shift
        if key == "escape":
            return self.keyboard_module.Key.esc
        return key

    def key_down(self, key: str):
        self._require_prepared()
        self.keyboard.press(self._key_value(key))

    def key_up(self, key: str):
        self._require_prepared()
        self.keyboard.release(self._key_value(key))

    def key_chord(self, *keys: str):
        self._require_prepared()
        values = [self._key_value(key) for key in keys]
        for value in values:
            self.keyboard.press(value)
        for value in reversed(values):
            self.keyboard.release(value)

    def release_all(self):
        if self.keyboard is None:
            return
        for key in ("ctrl", "shift"):
            try:
                self.key_up(key)
            except Exception:
                pass

    def close(self):
        self.release_all()
        self.keyboard = None
        self.mouse = None


class GuardedGameInput:
    """Per-game session that revalidates exact focus before every event."""

    def __init__(self, game_id: str, backend, *, snapshot_provider=focused_game_window_snapshot):
        self.game_id = platform_utils.normalize_game_id(game_id)
        self.backend = backend
        self.snapshot_provider = snapshot_provider

    def _focused(self) -> WindowSnapshot:
        snapshot = self.snapshot_provider(self.game_id)
        if snapshot is None:
            raise GameInputUnavailable(
                f"Exact {platform_utils.exact_window_title_for_game(self.game_id)} window is not focused"
            )
        return snapshot

    @staticmethod
    def _same_window(first: WindowSnapshot, second: WindowSnapshot) -> bool:
        return (
            first.game_id == second.game_id
            and first.pid == second.pid
            and first.title == second.title
            and first.process_name == second.process_name
            and (first.left, first.top, first.width, first.height)
            == (second.left, second.top, second.width, second.height)
        )

    def _move_and_revalidate(self, target: WindowRelativePoint) -> tuple[WindowSnapshot, DesktopPoint]:
        before = self._focused()
        desktop = target.to_desktop(before)
        if not before.contains(desktop):
            raise GameInputUnavailable("Resolved target is outside the exact game window")
        self.backend.move_to(desktop)
        after = self._focused()
        if not self._same_window(before, after):
            raise GameInputUnavailable("Exact game window lost focus or changed after cursor movement")
        target.to_desktop(after)
        return after, desktop

    def move_to(self, target: WindowRelativePoint):
        self._move_and_revalidate(target)

    def _require_same_focused_window(self, expected: WindowSnapshot, action: str):
        current = self._focused()
        if not self._same_window(expected, current):
            raise GameInputUnavailable(f"Exact game window changed before {action}")

    def right_click(self, target: WindowRelativePoint):
        expected, _desktop = self._move_and_revalidate(target)
        self._require_same_focused_window(expected, "click")
        self.backend.click("right")

    def left_click(self, target: WindowRelativePoint):
        expected, _desktop = self._move_and_revalidate(target)
        self._require_same_focused_window(expected, "click")
        self.backend.click("left")

    def shift_left_click(self, target: WindowRelativePoint):
        expected, _desktop = self._move_and_revalidate(target)
        self._require_same_focused_window(expected, "modifier press")
        self.backend.key_down("shift")
        try:
            self._require_same_focused_window(expected, "click")
            self.backend.click("left")
        finally:
            self.backend.key_up("shift")

    def copy_at(self, target: WindowRelativePoint):
        expected, _desktop = self._move_and_revalidate(target)
        self._require_same_focused_window(expected, "copy")
        self.backend.key_chord("ctrl", "c")

    def copy(self):
        self._focused()
        self.backend.key_chord("ctrl", "c")

    def cancel_selection(self):
        self._focused()
        self.backend.key_chord("escape")

    def release_all(self):
        self.backend.release_all()


class GameInputService:
    """Application-owned backend shared by every module that injects game input."""

    def __init__(self, *, backend=None, snapshot_provider=focused_game_window_snapshot):
        self.snapshot_provider = snapshot_provider
        self.backend = backend or self._create_preferred_backend()
        self.prepared = False

    @staticmethod
    def _create_preferred_backend():
        if preferred_backend_name() == "kwin-eis":
            from services.kwin_cursor import read_kwin_cursor_position

            return KWinEisBackend(cursor_reader=read_kwin_cursor_position)
        return PynputBackend()

    def capability(self) -> InputCapability:
        return self.backend.capability()

    def prepare(self):
        if not self.prepared:
            self.backend.prepare()
            self.prepared = True
        return self.capability()

    def session(self, game_id: str) -> GuardedGameInput:
        self.prepare()
        return GuardedGameInput(
            game_id,
            self.backend,
            snapshot_provider=self.snapshot_provider,
        )

    def close(self):
        try:
            self.backend.close()
        finally:
            self.prepared = False
        return True
