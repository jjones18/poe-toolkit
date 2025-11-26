"""
POE Toolkit - Unified Path of Exile Helper
Main entry point
"""

import sys
import os

# Ensure src is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.theme import apply_dark_theme


def main():
    print("Starting POE Toolkit...")
    
    # Set high DPI scaling for Qt
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    app.setApplicationName("POE Toolkit")
    app.setOrganizationName("POE Toolkit")
    
    # Apply dark theme
    apply_dark_theme(app)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
