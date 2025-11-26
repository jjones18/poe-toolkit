"""
Filter configuration dialog for Ultimatum tool.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QListWidget, QListWidgetItem, QPushButton, QTabWidget, QWidget,
                             QCheckBox, QAbstractItemView)
from PyQt6.QtCore import Qt


class FilterConfigDialog(QDialog):
    """Dialog for configuring item filters."""
    
    def __init__(self, parent=None, found_data=None, current_config=None, price_fetcher=None):
        super().__init__(parent)
        self.setWindowTitle("Filter Configuration")
        self.resize(600, 500)
        
        self.found_data = found_data or {}
        self.config = current_config or {}
        self.price_fetcher = price_fetcher
        
        self.excluded_types = set(self.config.get("excluded_types", []))
        self.included_types = set(self.config.get("included_types", []))
        
        self.excluded_rewards = set(self.config.get("excluded_rewards", []))
        self.included_rewards = set(self.config.get("included_rewards", []))
        
        self.excluded_tiers = set(str(x) for x in self.config.get("excluded_tiers", []))
        self.included_tiers = set(str(x) for x in self.config.get("included_tiers", []))

        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        
        categories = {}
        if price_fetcher:
            categories = price_fetcher.categories
        
        # Encounter Types
        self.type_tab = self.create_list_tab(
            "Encounter Types", 
            sorted(list(self.found_data.get('types', []))),
            self.excluded_types,
            self.included_types
        )
        self.tabs.addTab(self.type_tab, "Encounter Types")
        
        # Categorize Rewards
        currency_list = []
        div_list = []
        unique_list = []
        
        all_rewards = sorted(list(self.found_data.get('rewards', [])))
        
        for r in all_rewards:
            cat = categories.get(r, '')
            if cat in ['Currency', 'Fragment', 'Invitation']:
                currency_list.append(r)
            elif cat == 'DivinationCard':
                div_list.append(r)
            else:
                unique_list.append(r)

        # Currency Tab
        self.curr_tab = self.create_list_tab(
            "Currency", 
            currency_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher
        )
        self.tabs.addTab(self.curr_tab, "Currency")

        # Div Cards Tab
        self.div_tab = self.create_list_tab(
            "Div Cards", 
            div_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher
        )
        self.tabs.addTab(self.div_tab, "Div Cards")

        # Uniques Tab
        self.unique_tab = self.create_list_tab(
            "Uniques", 
            unique_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher
        )
        self.tabs.addTab(self.unique_tab, "Uniques")
        
        # Monster Life
        tiers = sorted(list(self.found_data.get('tiers', [])), 
                      key=lambda x: int(x) if isinstance(x, int) else 0)
        tier_strs = [str(t) for t in tiers]
        
        self.life_tab = self.create_list_tab(
            "Monster Life %",
            tier_strs,
            self.excluded_tiers,
            self.included_tiers
        )
        self.tabs.addTab(self.life_tab, "Monster Life")
        
        layout.addWidget(self.tabs)
        
        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)

    def create_list_tab(self, label, items, excluded_set, included_set, price_source=None):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        layout.addWidget(QLabel(f"Available {label}:"))
        
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        
        for item_text in items:
            item = QListWidgetItem(list_widget)
            
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(2, 2, 2, 2)
            
            chk_exclude = QCheckBox("Exclude")
            chk_exclude.setChecked(item_text in excluded_set)
            
            chk_include = QCheckBox("Require")
            chk_include.setChecked(item_text in included_set)
            
            chk_exclude.toggled.connect(
                lambda c, t=item_text, o=chk_include: self.on_check(t, c, o, "exclude", label))
            chk_include.toggled.connect(
                lambda c, t=item_text, o=chk_exclude: self.on_check(t, c, o, "include", label))
            
            lbl = QLabel(item_text)
            lbl.setWordWrap(True)
            row_layout.addWidget(lbl, stretch=1) 
            
            if price_source:
                price_val = price_source.get_price(item_text)
                if price_val > 0:
                    price_lbl = QLabel(f"{price_val:.1f}c")
                    price_lbl.setFixedWidth(60)
                    price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    price_lbl.setStyleSheet("font-weight: bold;") 
                    row_layout.addWidget(price_lbl)
            
            row_layout.addWidget(chk_exclude)
            row_layout.addWidget(chk_include)
            
            item.setSizeHint(row_widget.sizeHint())
            list_widget.setItemWidget(item, row_widget)
            
        layout.addWidget(list_widget)
        return widget

    def on_check(self, text, checked, other_checkbox, mode, category):
        if checked:
            other_checkbox.setChecked(False)
            
        if category == "Encounter Types":
            ex_set = self.excluded_types
            in_set = self.included_types
        elif category in ["Currency", "Div Cards", "Uniques"]:
            ex_set = self.excluded_rewards
            in_set = self.included_rewards
        else:
            ex_set = self.excluded_tiers
            in_set = self.included_tiers
            
        if mode == "exclude":
            if checked:
                ex_set.add(text)
                in_set.discard(text)
            else:
                ex_set.discard(text)
        else:
            if checked:
                in_set.add(text)
                ex_set.discard(text)
            else:
                in_set.discard(text)

    def get_config_updates(self):
        return {
            "excluded_types": list(self.excluded_types),
            "included_types": list(self.included_types),
            "excluded_rewards": list(self.excluded_rewards),
            "included_rewards": list(self.included_rewards),
            "excluded_tiers": [int(x) for x in self.excluded_tiers if x.isdigit()],
            "included_tiers": [int(x) for x in self.included_tiers if x.isdigit()]
        }

