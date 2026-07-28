import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QComboBox

from ui.theme import apply_dark_theme


class DarkThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_combo_popup_selected_text_remains_light_and_readable(self):
        apply_dark_theme(self.app)
        combo = QComboBox()
        combo.addItems(["Allflame", "Hardcore Allflame"])

        selected_text = combo.view().palette().color(
            QPalette.ColorRole.HighlightedText
        )

        self.assertEqual(selected_text.name(), "#f0f0f0")
        self.assertIn(
            "QAbstractItemView::item:selected",
            self.app.styleSheet(),
        )


if __name__ == "__main__":
    unittest.main()
