import os
import sys
import unittest
from unittest.mock import Mock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from services.game_input_service import (
    DesktopPoint,
    GameInputService,
    GameInputUnavailable,
    GuardedGameInput,
    KWinEisBackend,
    WindowRelativePoint,
    WindowSnapshot,
    preferred_backend_name,
)
from services.kwin_cursor import read_kwin_cursor_position
from services.kwin_eis import KWinEisClient


class FakeEisClient:
    def __init__(self, cursor, *, apply_motion=True):
        self.cursor = cursor
        self.apply_motion = apply_motion
        self.calls = []
        self.closed = False

    def pointer_move_absolute(self, x, y):
        self.calls.append(("move_absolute", x, y))
        if self.apply_motion:
            self.cursor[:] = [int(x), int(y)]

    def pointer_button(self, button, state):
        self.calls.append(("button", button, state))

    def keyboard_key(self, keycode, state):
        self.calls.append(("key", keycode, state))

    def close(self):
        self.closed = True
        self.calls.append(("close",))


class FakeLowLevelBackend:
    def __init__(self):
        self.calls = []

    def move_to(self, point):
        self.calls.append(("move", point))

    def click(self, button):
        self.calls.append(("click", button))

    def key_chord(self, *keys):
        self.calls.append(("keys", keys))

    def release_all(self):
        self.calls.append(("release",))


class GameInputCoordinateTests(unittest.TestCase):
    def test_window_relative_point_resolves_only_for_matching_window_size(self):
        window = WindowSnapshot(
            game_id="poe1",
            title="Path of Exile",
            process_name="PathOfExileSteam.exe",
            pid="123",
            left=1440,
            top=1595,
            width=3440,
            height=1440,
        )
        target = WindowRelativePoint(100, 200, reference_width=3440, reference_height=1440)
        self.assertEqual(target.to_desktop(window), DesktopPoint(1540, 1795))

        resized = WindowSnapshot(**{**window.__dict__, "width": 1440, "height": 1080})
        with self.assertRaisesRegex(GameInputUnavailable, "window size changed"):
            target.to_desktop(resized)

    def test_window_relative_point_rejects_coordinates_outside_window(self):
        window = WindowSnapshot("poe1", "Path of Exile", "PathOfExileSteam.exe", "123", 10, 20, 800, 600)
        target = WindowRelativePoint(900, 20, reference_width=800, reference_height=600)
        with self.assertRaisesRegex(GameInputUnavailable, "outside"):
            target.to_desktop(window)


class WaylandBackendTests(unittest.TestCase):
    def test_wayland_prefers_kwin_eis_and_other_platforms_keep_pynput(self):
        self.assertEqual(preferred_backend_name("linux", "wayland"), "kwin-eis")
        self.assertEqual(preferred_backend_name("linux", "x11"), "pynput")
        self.assertEqual(preferred_backend_name("win32", ""), "pynput")

    def test_default_wayland_service_requires_compositor_cursor_feedback(self):
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}):
            service = GameInputService()

        self.assertIsInstance(service.backend, KWinEisBackend)
        self.assertIs(service.backend.cursor_reader, read_kwin_cursor_position)

    def make_backend(self, cursor, client):
        return KWinEisBackend(
            client_factory=lambda: client,
            cursor_reader=lambda: tuple(cursor),
            sleep=lambda _seconds: None,
        )

    def test_prepare_connects_without_starting_a_uinput_service_and_close_disconnects(self):
        cursor = [100, 100]
        client = FakeEisClient(cursor)
        backend = self.make_backend(cursor, client)

        backend.prepare()
        self.assertTrue(backend.prepared)
        backend.close()

        self.assertEqual(
            client.calls,
            [
                ("button", 0x110, 0),
                ("button", 0x111, 0),
                ("key", 29, 0),
                ("key", 42, 0),
                ("close",),
            ],
        )
        self.assertTrue(client.closed)
        self.assertFalse(backend.prepared)

    def test_move_uses_absolute_compositor_coordinates_and_verifies_feedback(self):
        cursor = [100, 100]
        client = FakeEisClient(cursor)
        backend = self.make_backend(cursor, client)
        backend.prepare()

        backend.move_to(DesktopPoint(340, 260))

        self.assertEqual(client.calls[0], ("move_absolute", 340.0, 260.0))
        self.assertEqual(cursor, [340, 260])

    def test_key_chord_uses_wine_safe_press_hold_release_timing(self):
        cursor = [100, 100]
        client = FakeEisClient(cursor)
        delays = []
        backend = KWinEisBackend(
            client_factory=lambda: client,
            cursor_reader=lambda: tuple(cursor),
            sleep=delays.append,
            key_step_delay=0.1,
        )
        backend.prepare()
        client.calls.clear()

        backend.key_chord("ctrl", "c")

        self.assertEqual(
            client.calls,
            [
                ("key", 29, 1),
                ("key", 46, 1),
                ("key", 46, 0),
                ("key", 29, 0),
            ],
        )
        self.assertEqual(delays, [0.1, 0.1, 0.1])

    def test_default_key_step_delay_uses_measured_fast_value(self):
        cursor = [100, 100]
        client = FakeEisClient(cursor)
        backend = KWinEisBackend(
            client_factory=lambda: client,
            cursor_reader=lambda: tuple(cursor),
            sleep=lambda _seconds: None,
        )

        self.assertEqual(backend.key_step_delay, 0.005)

    def test_move_fails_closed_when_compositor_cursor_does_not_reach_target(self):
        cursor = [100, 100]
        client = FakeEisClient(cursor, apply_motion=False)
        backend = self.make_backend(cursor, client)
        backend.prepare()

        with self.assertRaisesRegex(GameInputUnavailable, "did not reach"):
            backend.move_to(DesktopPoint(400, 400))


class KWinEisRegionTests(unittest.TestCase):
    class FakeLibEi:
        def __init__(self, accepted):
            self.accepted = accepted

        def ei_device_get_region_at(self, pointer, x, y):
            return int((pointer, int(x), int(y)) in self.accepted)

    def client(self, accepted):
        client = object.__new__(KWinEisClient)
        client._pointer_devices = [11, 22]
        client.__dict__["_libei"] = self.FakeLibEi(accepted)
        return client

    def test_selects_pointer_device_whose_compositor_region_contains_target(self):
        client = self.client({(22, 3160, 2315)})

        self.assertEqual(client._pointer_for_point(3160, 2315), 22)

    def test_rejects_target_outside_every_compositor_region(self):
        client = self.client(set())

        with self.assertRaisesRegex(RuntimeError, "no absolute-pointer region"):
            client._pointer_for_point(9000, 9000)


class GuardedInputTests(unittest.TestCase):
    def snapshot(self, *, pid="123", width=3440, height=1440):
        return WindowSnapshot(
            "poe1", "Path of Exile", "PathOfExileSteam.exe", pid,
            1440, 1595, width, height,
        )

    def test_click_revalidates_exact_window_after_move_before_button_event(self):
        backend = FakeLowLevelBackend()
        snapshots = [self.snapshot(), None]
        session = GuardedGameInput("poe1", backend, snapshot_provider=lambda _game: snapshots.pop(0))
        target = WindowRelativePoint(100, 200, 3440, 1440)

        with self.assertRaisesRegex(GameInputUnavailable, "focused"):
            session.right_click(target)

        self.assertEqual(backend.calls, [("move", DesktopPoint(1540, 1795))])

    def test_guarded_left_click_moves_then_revalidates_before_one_click(self):
        backend = FakeLowLevelBackend()
        snapshot = self.snapshot()
        session = GuardedGameInput(
            "poe1",
            backend,
            snapshot_provider=lambda _game: snapshot,
        )
        target = WindowRelativePoint(100, 200, 3440, 1440)

        session.left_click(target)

        self.assertEqual(
            backend.calls,
            [
                ("move", DesktopPoint(1540, 1795)),
                ("click", "left"),
            ],
        )

    def test_click_rejects_window_size_change_before_any_input(self):
        backend = FakeLowLevelBackend()
        session = GuardedGameInput(
            "poe1",
            backend,
            snapshot_provider=lambda _game: self.snapshot(width=1440, height=1080),
        )
        target = WindowRelativePoint(100, 200, 3440, 1440)

        with self.assertRaisesRegex(GameInputUnavailable, "window size changed"):
            session.right_click(target)
        self.assertEqual(backend.calls, [])


if __name__ == "__main__":
    unittest.main()
