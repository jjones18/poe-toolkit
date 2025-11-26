"""
Stash tab selection widget.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QScrollArea, QFrame, QGridLayout, QLabel, QLineEdit)
from PyQt6.QtCore import Qt


class StashTabButton(QPushButton):
    """Button representing a single stash tab."""
    
    def __init__(self, tab_data):
        super().__init__()
        self.tab_data = tab_data
        self.index = tab_data.get('i')
        self.label = tab_data.get('n', f"Tab {self.index}")
        self.color_data = tab_data.get('colour', {'r': 100, 'g': 100, 'b': 100})
        
        self.setText(self.label)
        self.setCheckable(True)
        self.setFixedHeight(30)
        
        r = self.color_data.get('r', 100)
        g = self.color_data.get('g', 100)
        b = self.color_data.get('b', 100)
        
        lum = (0.299 * r + 0.587 * g + 0.114 * b)
        text_color = "black" if lum > 128 else "white"
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r}, {g}, {b});
                color: {text_color};
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }}
            QPushButton:checked {{
                border: 2px solid #FFF;
                font-weight: bold;
            }}
        """)


class StashTabSelector(QWidget):
    """Widget for selecting stash tabs with filtering."""
    
    def __init__(self):
        super().__init__()
        self.selected_indices = set()
        self.buttons = {}
        self.tabs_list = []
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Filter Controls
        filter_layout = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter tabs (e.g. 'Ult')...")
        self.filter_input.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_input)
        
        self.sel_all_btn = QPushButton("All")
        self.sel_all_btn.setFixedWidth(40)
        self.sel_all_btn.setToolTip("Select all visible tabs")
        self.sel_all_btn.clicked.connect(lambda: self.bulk_select(True))
        filter_layout.addWidget(self.sel_all_btn)
        
        self.sel_none_btn = QPushButton("None")
        self.sel_none_btn.setFixedWidth(40)
        self.sel_none_btn.setToolTip("Deselect all visible tabs")
        self.sel_none_btn.clicked.connect(lambda: self.bulk_select(False))
        filter_layout.addWidget(self.sel_none_btn)
        
        self.layout.addLayout(filter_layout)
        
        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid = QGridLayout(self.scroll_content)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        
        self.layout.addWidget(self.scroll)
        
        # Status Label
        self.status_label = QLabel("No tabs loaded.")
        self.layout.addWidget(self.status_label)

    def load_tabs(self, tabs_list, preselected_indices=None):
        """Populates the grid with tab buttons."""
        self.tabs_list = tabs_list
        
        self.clear_grid()
        self.buttons.clear()
        self.selected_indices.clear()
        
        if not tabs_list:
            self.status_label.setText("No tabs found.")
            return

        if preselected_indices:
            preselected_indices = set(int(x) for x in preselected_indices)

        for tab in tabs_list:
            btn = StashTabButton(tab)
            btn.clicked.connect(lambda checked, idx=tab['i']: self.toggle_tab(idx))
            
            if preselected_indices and tab['i'] in preselected_indices:
                btn.setChecked(True)
                self.selected_indices.add(tab['i'])
                
            self.buttons[tab['i']] = btn

        self.apply_filter()
        self.update_status()

    def clear_grid(self):
        for i in reversed(range(self.grid.count())): 
            item = self.grid.itemAt(i)
            if item.widget():
                item.widget().setParent(None)

    def apply_filter(self):
        text = self.filter_input.text().lower()
        self.clear_grid()
        
        visible_buttons = []
        for tab in self.tabs_list:
            if text in tab.get('n', '').lower():
                if tab['i'] in self.buttons:
                    visible_buttons.append(self.buttons[tab['i']])
        
        cols = 4
        for i, btn in enumerate(visible_buttons):
            row = i // cols
            col = i % cols
            self.grid.addWidget(btn, row, col)
            btn.setVisible(True)

    def bulk_select(self, select: bool):
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), StashTabButton):
                widget = item.widget()
                if select:
                    if not widget.isChecked():
                        widget.setChecked(True)
                        self.selected_indices.add(widget.index)
                else:
                    if widget.isChecked():
                        widget.setChecked(False)
                        self.selected_indices.discard(widget.index)
        self.update_status()

    def toggle_tab(self, index):
        if index in self.selected_indices:
            self.selected_indices.discard(index)
        else:
            self.selected_indices.add(index)
        self.update_status()

    def update_status(self):
        count = len(self.selected_indices)
        self.status_label.setText(f"{count} tabs selected.")

    def get_selected_indices(self):
        return list(self.selected_indices)

