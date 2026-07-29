import copy
from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = import_module("tomli")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PyQt6.QtWidgets import QApplication

from utils.config import ConfigManager


class Milestone8PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pyproject_uses_single_version_source_and_bounded_extras(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("version", data["project"]["dynamic"])
        self.assertEqual(
            data["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "utils.APP_VERSION",
        )
        extras = data["project"]["optional-dependencies"]
        for name in ("capture", "overlay-input", "platform", "dev", "test", "packaging", "full"):
            self.assertIn(name, extras)
        self.assertNotIn("trade", extras)
        all_requirements = "\n".join(
            data["project"]["dependencies"]
            + [item for group in extras.values() for item in group]
        )
        self.assertNotIn("keyboard", all_requirements)
        self.assertIn("numpy>=2,<2.3", all_requirements)

    def test_release_guard_scripts_pass(self):
        for script, expected in (
            ("scripts/check_version_consistency.py", "version consistency ok"),
            ("scripts/check_packaging_assets.py", "packaging assets ok"),
            ("scripts/check_no_mutable_checkout_data.py", "mutable runtime/secret check ok"),
        ):
            result = subprocess.run(
                [sys.executable, script],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(expected, result.stdout)

    def test_packaging_uses_immutable_defaults_and_excludes_runtime_state(self):
        from scripts.check_packaging_assets import EXPECTED_ASSETS, bundled_sources

        spec = (ROOT / "packaging" / "poe_toolkit.spec").read_text(encoding="utf-8")
        self.assertEqual(bundled_sources(spec), EXPECTED_ASSETS)
        self.assertIn("src/utils/default_config.json", EXPECTED_ASSETS)
        self.assertNotIn("config/config.json", EXPECTED_ASSETS)
        self.assertTrue((ROOT / "src" / "utils" / "default_config.json").is_file())
        self.assertTrue(ConfigManager.CONFIG_FILE.endswith("src/utils/default_config.json"))
        self.assertNotIn("unittest", (ROOT / "src" / "package_smoke.py").read_text(encoding="utf-8"))

    def test_optional_feature_error_is_actionable(self):
        from utils.optional_features import OptionalFeatureUnavailable, import_optional

        with patch("utils.optional_features.import_module", side_effect=ImportError("missing")):
            with self.assertRaises(OptionalFeatureUnavailable) as context:
                import_optional("ocr_capture", "cv2")
        self.assertIn("pip install .[capture]", str(context.exception))
        self.assertIn("Tesseract OCR", str(context.exception))

    def test_package_smoke_constructs_aligned_main_window(self):
        from package_smoke import run_package_smoke
        from utils import APP_VERSION

        with patch.dict(os.environ, {"XDG_CACHE_HOME": "/sentinel-cache"}):
            payload = run_package_smoke()
            self.assertEqual(os.environ["XDG_CACHE_HOME"], "/sentinel-cache")
        self.assertEqual(payload["version"], APP_VERSION)
        for tool in ("Settings", "Trade", "Diagnostics"):
            self.assertIn(tool, payload["tool_names"])
        self.assertEqual(payload["sidebar_items"], len(payload["tool_names"]))
        self.assertEqual(
            payload["immutable_assets"],
            ["dust_data", "trade_lock", "trade_monitor"],
        )
        self.assertTrue(payload["navigation_aligned"])
        self.assertTrue(payload["closed"])

    def test_failed_tool_creation_keeps_navigation_indices_aligned(self):
        from ui.main_window import MainWindow, _UnavailableTool

        config = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.set_active_game(config, "poe2")
        trade_service = Mock(is_running=False)
        trade_service.stop.return_value = True
        trade_service.close.return_value = True
        price_service = Mock()
        price_service.set_context.return_value = True
        price_service.close.return_value = True
        price_service.runtime_state.return_value = {}

        with (
            patch.object(ConfigManager, "load", return_value=config),
            patch.object(ConfigManager, "save", return_value=True),
            patch("tools.trade_sniper.TradeSniperTool.create_widget", side_effect=RuntimeError("optional dependency missing")),
        ):
            window = MainWindow(trade_service=trade_service, price_service=price_service)
            try:
                self.assertEqual(len(window.tools), len(window.sidebar_buttons))
                self.assertEqual(len(window.tools), window.content_stack.count())
                self.assertEqual(window.game_combo.accessibleName(), "Active toolkit mode")
                self.assertEqual(window.sidebar_buttons[0].shortcut().toString(), "Alt+1")
                self.assertIn("QPushButton:focus", window.sidebar_buttons[0].styleSheet())
                unavailable = next(index for index, tool in enumerate(window.tools) if isinstance(tool, _UnavailableTool))
                window.on_tool_selected(unavailable)
                self.assertEqual(window.content_stack.currentIndex(), unavailable)
                self.assertIn("unavailable", window.sidebar_buttons[unavailable].accessibleName().lower())
            finally:
                window.close()

    def test_setup_paths_use_virtual_environments_and_no_direct_executable_download(self):
        powershell = (ROOT / "setup.ps1").read_text(encoding="utf-8")
        linux = (ROOT / "setup.sh").read_text(encoding="utf-8")
        self.assertIn("-m venv", powershell)
        self.assertIn("npm ci", powershell)
        self.assertNotIn("Invoke-WebRequest", powershell)
        self.assertIn("-m venv", linux)
        self.assertIn("npm ci", linux)

    def test_distribution_ci_smokes_wheel_on_linux_and_windows(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        distribution = workflow.split("  distribution:\n", 1)[1].split("\n  package:\n", 1)[0]
        self.assertIn("ubuntu-latest", distribution)
        self.assertIn("windows-latest", distribution)
        self.assertIn(".wheel-smoke/bin/poe-toolkit", distribution)
        self.assertIn(".wheel-smoke/Scripts/poe-toolkit.exe", distribution)

    def test_linux_ci_jobs_install_qt_runtime_libraries(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertEqual(
            workflow.count("name: Install Linux Qt runtime libraries"),
            4,
        )
        for package in (
            "libdbus-1-3",
            "libegl1",
            "libfontconfig1",
            "libgl1",
            "libglib2.0-0t64",
            "libxkbcommon0",
        ):
            self.assertGreaterEqual(workflow.count(package), 4, package)

    def test_mutable_runtime_paths_absent_from_clean_checkout(self):
        for rel in (
            "config/user_config.json",
            "src/config/user_config.json",
            "trade_service/brave-profile",
            "trade_service/node_modules",
            "price_cache.json",
            "dust_cache.json",
        ):
            self.assertFalse((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
