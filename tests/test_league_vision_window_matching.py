import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

for module_name in ("mss", "cv2", "pytesseract", "keyboard", "pynput"):
    sys.modules.setdefault(module_name, types.ModuleType(module_name))
pytesseract_stub = sys.modules["pytesseract"]
pytesseract_stub.pytesseract = getattr(pytesseract_stub, "pytesseract", Mock())
pytesseract_stub.Output = getattr(pytesseract_stub, "Output", Mock(DICT="DICT"))
numpy_stub = sys.modules.setdefault("numpy", types.ModuleType("numpy"))
numpy_stub.array = getattr(numpy_stub, "array", lambda value, *_args, **_kwargs: value)


class LeagueVisionWindowMatchingTests(unittest.TestCase):
    def test_windows_process_lookup_uses_pywin32_without_psutil(self):
        import utils.platform_utils as platform_utils

        win32api = types.ModuleType("win32api")
        win32api.OpenProcess = Mock(return_value="handle")
        win32api.CloseHandle = Mock()
        win32con = types.ModuleType("win32con")
        win32con.PROCESS_QUERY_INFORMATION = 1
        win32con.PROCESS_VM_READ = 2
        win32process = types.ModuleType("win32process")
        win32process.GetModuleFileNameEx = Mock(
            return_value=r"C:\\Games\\PathOfExile.exe"
        )

        with patch.dict(
            sys.modules,
            {
                "win32api": win32api,
                "win32con": win32con,
                "win32process": win32process,
            },
        ):
            process_name = platform_utils._windows_process_name(1234)

        self.assertEqual(process_name, r"C:\\Games\\PathOfExile.exe")
        win32api.OpenProcess.assert_called_once_with(3, False, 1234)
        win32api.CloseHandle.assert_called_once_with("handle")


    def test_windows_foreground_identity_includes_exact_title_and_process(self):
        import utils.platform_utils as platform_utils

        fake_win32gui = Mock()
        fake_win32gui.GetForegroundWindow.return_value = 99
        fake_win32gui.GetWindowText.return_value = "Path of Exile 2"
        win32process = types.ModuleType("win32process")
        win32process.GetWindowThreadProcessId = Mock(return_value=(1, 4321))

        with (
            patch.object(platform_utils, "IS_WINDOWS", True),
            patch.object(platform_utils, "HAS_WIN32", True),
            patch.object(platform_utils, "win32gui", fake_win32gui, create=True),
            patch.dict(sys.modules, {"win32process": win32process}),
            patch.object(platform_utils, "_windows_process_name", return_value=r"C:\Games\PathOfExile2.exe"),
        ):
            identity = platform_utils.get_foreground_window_identity()

        self.assertEqual(identity, {"title": "Path of Exile 2", "process_name": r"C:\Games\PathOfExile2.exe", "pid": "4321"})

    def test_linux_xdotool_foreground_identity_includes_title_and_wine_process(self):
        import utils.platform_utils as platform_utils

        def fake_run(command, **_kwargs):
            if command == ["xdotool", "getactivewindow"]:
                return Mock(returncode=0, stdout="101\n")
            if command == ["xdotool", "getwindowname", "101"]:
                return Mock(returncode=0, stdout="Path of Exile\n")
            if command == ["xdotool", "getwindowpid", "101"]:
                return Mock(returncode=0, stdout="2001\n")
            raise AssertionError(f"unexpected command: {command!r}")

        with (
            patch.object(platform_utils, "IS_WINDOWS", False),
            patch.object(platform_utils, "IS_LINUX", True),
            patch.object(platform_utils, "HAS_XLIB", False),
            patch.object(platform_utils.subprocess, "run", side_effect=fake_run),
            patch.object(platform_utils, "_process_name_from_pid", return_value="PathOfExile.exe") as process_from_pid,
        ):
            identity = platform_utils.get_foreground_window_identity()

        self.assertEqual(identity, {"title": "Path of Exile", "process_name": "PathOfExile.exe", "pid": "2001"})
        process_from_pid.assert_called_once_with("2001")

    def test_linux_process_name_prefers_wine_exe_cmdline_over_generic_exe(self):
        import utils.platform_utils as platform_utils

        fake_path = Mock()
        fake_path.return_value.read_bytes.return_value = b"/usr/bin/wine\x00Z:\\Games\\PathOfExile2.exe\x00"

        with (
            patch.object(platform_utils, "IS_LINUX", True),
            patch.object(platform_utils, "Path", fake_path),
            patch.object(platform_utils.subprocess, "run") as run,
        ):
            process_name = platform_utils._process_name_from_pid("2001")

        self.assertEqual(process_name, "PathOfExile2.exe")
        fake_path.return_value.readlink.assert_not_called()
        run.assert_not_called()

    def test_vision_core_requests_exact_active_game_matching(self):
        from tools.league_vision.scanner import POE_GAME_MATCHES, exact_window_title_for_game, is_exact_poe_window_title
        from tools.league_vision.vision_core import VisionCore

        vision = VisionCore(
            exact_window_title_for_game("poe1"),
            exact_title=True,
            process_names=POE_GAME_MATCHES["poe1"]["process_names"],
            title_matcher=lambda title: is_exact_poe_window_title(title, "poe1"),
        )

        with patch("tools.league_vision.vision_core.platform_utils.find_window_rect", return_value={"left": 0, "top": 0, "width": 1, "height": 1}) as finder:
            self.assertIsNotNone(vision.get_window_rect())

        _, kwargs = finder.call_args
        self.assertTrue(kwargs["exact_title"])
        self.assertIn("PathOfExile.exe", kwargs["process_names"])
        self.assertFalse(kwargs["title_matcher"]("Path of Exile 2"))

    def test_linux_xdotool_exact_title_rejects_poe2_for_poe1_substring_search(self):
        import utils.platform_utils as platform_utils

        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[:3] == ["xdotool", "search", "--name"]:
                return Mock(returncode=0, stdout="101\n")
            if command[:2] == ["xdotool", "getwindowname"]:
                return Mock(returncode=0, stdout="Path of Exile 2\n")
            raise AssertionError(f"unexpected command: {command!r}")

        with (
            patch.object(platform_utils, "IS_WINDOWS", False),
            patch.object(platform_utils, "IS_LINUX", True),
            patch.object(platform_utils, "HAS_XLIB", False),
            patch.object(platform_utils.subprocess, "run", side_effect=fake_run),
        ):
            rect = platform_utils.find_window_rect("Path of Exile", exact_title=True)

        self.assertIsNone(rect)
        self.assertIn(["xdotool", "getwindowname", "101"], calls)

    def test_linux_xdotool_filters_process_name_when_available(self):
        import utils.platform_utils as platform_utils

        def fake_run(command, **_kwargs):
            if command[:3] == ["xdotool", "search", "--name"]:
                return Mock(returncode=0, stdout="101\n102\n")
            if command[:2] == ["xdotool", "getwindowname"]:
                return Mock(returncode=0, stdout="Path of Exile\n")
            if command[:2] == ["xdotool", "getwindowpid"]:
                return Mock(returncode=0, stdout=("2001\n" if command[2] == "101" else "2002\n"))
            if command[:2] == ["xdotool", "getwindowgeometry"]:
                self.assertEqual(command[-1], "102")
                return Mock(returncode=0, stdout="X=10\nY=20\nWIDTH=800\nHEIGHT=600\n")
            raise AssertionError(f"unexpected command: {command!r}")

        with (
            patch.object(platform_utils, "IS_WINDOWS", False),
            patch.object(platform_utils, "IS_LINUX", True),
            patch.object(platform_utils, "HAS_XLIB", False),
            patch.object(platform_utils.subprocess, "run", side_effect=fake_run),
            patch.object(
                platform_utils,
                "_process_name_from_pid",
                side_effect=lambda pid: {
                    "2001": "PathOfExile2.exe",
                    "2002": "PathOfExile.exe",
                }.get(str(pid).strip(), ""),
            ),
        ):
            rect = platform_utils.find_window_rect(
                "Path of Exile",
                exact_title=True,
                process_names=("PathOfExile.exe",),
            )

        self.assertEqual(rect, {"left": 10, "top": 20, "width": 800, "height": 600})

    def test_legacy_contains_matching_remains_default(self):
        import utils.platform_utils as platform_utils

        def fake_run(command, **_kwargs):
            if command[:3] == ["xdotool", "search", "--name"]:
                return Mock(returncode=0, stdout="101\n")
            if command[:2] == ["xdotool", "getwindowname"]:
                return Mock(returncode=0, stdout="Path of Exile 2\n")
            if command[:2] == ["xdotool", "getwindowgeometry"]:
                return Mock(returncode=0, stdout="X=1\nY=2\nWIDTH=3\nHEIGHT=4\n")
            raise AssertionError(f"unexpected command: {command!r}")

        with (
            patch.object(platform_utils, "IS_WINDOWS", False),
            patch.object(platform_utils, "IS_LINUX", True),
            patch.object(platform_utils, "HAS_XLIB", False),
            patch.object(platform_utils.subprocess, "run", side_effect=fake_run),
        ):
            rect = platform_utils.find_window_rect("Path of Exile")

        self.assertEqual(rect, {"left": 1, "top": 2, "width": 3, "height": 4})


if __name__ == "__main__":
    unittest.main()
