"""
Application themes.
"""

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


def apply_dark_theme(app):
    """Apply dark theme to the application."""
    palette = QPalette()
    
    dark_color = QColor(45, 45, 45)
    base_color = QColor(30, 30, 30)
    text_color = QColor(240, 240, 240)
    disabled_text = QColor(127, 127, 127)
    accent_color = QColor(42, 130, 218)
    
    palette.setColor(QPalette.ColorRole.Window, dark_color)
    palette.setColor(QPalette.ColorRole.WindowText, text_color)
    palette.setColor(QPalette.ColorRole.Base, base_color)
    palette.setColor(QPalette.ColorRole.AlternateBase, dark_color)
    palette.setColor(QPalette.ColorRole.ToolTipBase, text_color)
    palette.setColor(QPalette.ColorRole.ToolTipText, text_color)
    palette.setColor(QPalette.ColorRole.Text, text_color)
    palette.setColor(QPalette.ColorRole.Button, dark_color)
    palette.setColor(QPalette.ColorRole.ButtonText, text_color)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, accent_color)
    palette.setColor(QPalette.ColorRole.Highlight, accent_color)
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(80, 80, 80))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled_text)

    app.setPalette(palette)
    
    app.setStyleSheet("""
        QToolTip { 
            color: #ffffff; 
            background-color: #2a82da; 
            border: 1px solid white; 
        }
        QLineEdit, QTextEdit, QListWidget, QAbstractItemView {
            background-color: #1e1e1e;
            color: #f0f0f0;
            border: 1px solid #555;
            border-radius: 2px;
        }
        QLineEdit:focus {
            border: 1px solid #2a82da;
        }
        QPushButton {
            background-color: #3a3a3a;
            color: #ffffff;
            border: 1px solid #555;
            padding: 5px 10px;
            border-radius: 3px;
        }
        QPushButton:hover {
            background-color: #484848;
            border: 1px solid #666;
        }
        QPushButton:pressed {
            background-color: #252525;
            border: 1px solid #2a82da;
        }
        QPushButton:disabled {
            background-color: #2d2d2d;
            color: #707070;
            border: 1px solid #444;
        }
        QMessageBox {
            background-color: #2d2d2d;
        }
        QMessageBox QLabel {
            color: #f0f0f0;
            font-size: 12px;
        }
        QMessageBox QPushButton {
            min-width: 80px;
            min-height: 24px;
        }
        QDialog {
            background-color: #2d2d2d;
        }
        QDialog QLabel {
            color: #f0f0f0;
        }
        QMenuBar {
            background-color: #2d2d2d;
            color: #f0f0f0;
        }
        QMenuBar::item {
            background-color: transparent;
            padding: 4px 10px;
        }
        QMenuBar::item:selected {
            background-color: #3a3a3a;
        }
        QMenu {
            background-color: #2d2d2d;
            border: 1px solid #555;
        }
        QMenu::item {
            padding: 4px 20px;
        }
        QMenu::item:selected {
            background-color: #2a82da;
            color: white;
        }
        QTabWidget::pane {
            border: 1px solid #444;
        }
        QTabBar::tab {
            background: #3a3a3a;
            border: 1px solid #444;
            padding: 5px 10px;
            color: #ccc;
        }
        QTabBar::tab:selected {
            background: #2d2d2d;
            color: white;
            border-bottom: 1px solid #2d2d2d;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 5px;
            color: #f0f0f0;
        }
        QCheckBox {
            spacing: 5px;
            color: #f0f0f0;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            background-color: #1e1e1e;
            border: 1px solid #555;
            border-radius: 3px;
        }
        QCheckBox::indicator:hover {
            border: 1px solid #2a82da;
        }
        QCheckBox::indicator:checked {
            background-color: #2a82da;
            border: 1px solid #2a82da;
            image: none;
        }
        QCheckBox::indicator:checked:hover {
            background-color: #3a92ea;
            border: 1px solid #3a92ea;
        }
        QSlider::groove:horizontal {
            border: 1px solid #555;
            height: 8px;
            background: #1e1e1e;
            margin: 2px 0;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #2a82da;
            border: 1px solid #2a82da;
            width: 18px;
            height: 18px;
            margin: -7px 0;
            border-radius: 9px;
        }
        QScrollBar:vertical {
            border: none;
            background: #2d2d2d;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #555;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
    """)


def apply_light_theme(app):
    """Apply light theme (system default)."""
    app.setPalette(QApplication.style().standardPalette())
    app.setStyleSheet("")

