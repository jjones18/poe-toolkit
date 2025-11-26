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
        
        # found_data: { 'types': set(), 'rewards': set((name, count, sac_name, sac_count)), 'tiers': set() }
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
        
        # Get categories from price fetcher
        categories = {}
        if price_fetcher:
            categories = price_fetcher.categories
        
        # 1. Encounter Types
        self.type_tab = self.create_list_tab(
            "Encounter Types", 
            sorted(list(self.found_data.get('types', []))),
            self.excluded_types,
            self.included_types
        )
        self.tabs.addTab(self.type_tab, "Encounter Types")
        
        # Categorize Rewards - rewards are tuples of (reward_name, reward_count, sacrifice_name, sacrifice_count)
        currency_list = []
        div_list = []
        unique_list = []
        
        all_rewards = self.found_data.get('rewards', set())
        
        for reward_tuple in all_rewards:
            # Handle different tuple formats for backwards compatibility
            if isinstance(reward_tuple, tuple):
                if len(reward_tuple) == 4:
                    reward_name, reward_count, sacrifice_name, sacrifice_count = reward_tuple
                elif len(reward_tuple) == 2:
                    reward_name, reward_count = reward_tuple
                    sacrifice_name, sacrifice_count = None, 0
                else:
                    reward_name = reward_tuple[0] if reward_tuple else 'Unknown'
                    reward_count, sacrifice_name, sacrifice_count = 1, None, 0
            else:
                reward_name = reward_tuple
                reward_count, sacrifice_name, sacrifice_count = 1, None, 0
            
            cat = categories.get(reward_name, '')
            if cat in ['Currency', 'Fragment', 'Invitation']:
                currency_list.append((reward_name, reward_count, sacrifice_name, sacrifice_count))
            elif cat == 'DivinationCard':
                div_list.append((reward_name, reward_count, sacrifice_name, sacrifice_count))
            else:
                unique_list.append((reward_name, reward_count, sacrifice_name, sacrifice_count))
        
        # Sort by name then by count
        currency_list.sort(key=lambda x: (x[0], x[1]))
        div_list.sort(key=lambda x: (x[0], x[1]))
        unique_list.sort(key=lambda x: (x[0], x[1]))

        # 2. Currency Tab - show with quantities and profit
        self.curr_tab = self.create_reward_list_tab(
            "Currency", 
            currency_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher
        )
        self.tabs.addTab(self.curr_tab, "Currency")

        # 3. Div Cards Tab
        self.div_tab = self.create_reward_list_tab(
            "Div Cards", 
            div_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher
        )
        self.tabs.addTab(self.div_tab, "Div Cards")

        # 4. Uniques/Misc Tab - color code profit
        self.unique_tab = self.create_reward_list_tab(
            "Uniques", 
            unique_list,
            self.excluded_rewards,
            self.included_rewards,
            self.price_fetcher,
            color_code_profit=True
        )
        self.tabs.addTab(self.unique_tab, "Uniques")
        
        # 5. Monster Life
        tiers = sorted(list(self.found_data.get('tiers', [])), 
                      key=lambda x: int(x) if isinstance(x, int) else (int(x) if str(x).isdigit() else 0))
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

    def create_list_tab(self, label, items, excluded_set, included_set):
        """Create a simple list tab for encounter types and monster life (no prices)."""
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
            
            chk_include = QCheckBox("Include")
            chk_include.setChecked(item_text in included_set)
            
            chk_exclude.toggled.connect(
                lambda c, t=item_text, o=chk_include: self.on_check(t, c, o, "exclude", label))
            chk_include.toggled.connect(
                lambda c, t=item_text, o=chk_exclude: self.on_check(t, c, o, "include", label))
            
            lbl = QLabel(str(item_text))
            lbl.setWordWrap(True)
            row_layout.addWidget(lbl, stretch=1) 
            
            row_layout.addWidget(chk_exclude)
            row_layout.addWidget(chk_include)
            
            item.setSizeHint(row_widget.sizeHint())
            list_widget.setItemWidget(item, row_widget)
            
        layout.addWidget(list_widget)
        return widget

    def create_reward_list_tab(self, label, reward_tuples, excluded_set, included_set, 
                                price_source=None, color_code_profit=False):
        """
        Create a reward list tab that shows rewards with quantities and PROFIT values.
        reward_tuples: list of (reward_name, reward_count, sacrifice_name, sacrifice_count) tuples
        Filtering is done by reward NAME only (not quantity).
        color_code_profit: if True, show green for positive and red for negative profit
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        layout.addWidget(QLabel(f"Available {label}:"))
        
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        
        for reward_name, reward_count, sacrifice_name, sacrifice_count in reward_tuples:
            item = QListWidgetItem(list_widget)
            
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(2, 2, 2, 2)
            
            # Checkboxes filter by NAME only
            chk_exclude = QCheckBox("Exclude")
            chk_exclude.setChecked(reward_name in excluded_set)
            
            chk_include = QCheckBox("Include")
            chk_include.setChecked(reward_name in included_set)
            
            chk_exclude.toggled.connect(
                lambda c, t=reward_name, o=chk_include: self.on_check(t, c, o, "exclude", label))
            chk_include.toggled.connect(
                lambda c, t=reward_name, o=chk_exclude: self.on_check(t, c, o, "include", label))
            
            # Display: "Item Name x10" format
            if reward_count > 1:
                display_text = f"{reward_name} x{reward_count}"
            else:
                display_text = reward_name
            
            lbl = QLabel(display_text)
            lbl.setWordWrap(True)
            row_layout.addWidget(lbl, stretch=1) 
            
            # Profit Label - show PROFIT (reward_value - sacrifice_value)
            if price_source:
                reward_unit_price = price_source.get_price(reward_name)
                reward_total = reward_unit_price * reward_count
                
                sacrifice_unit_price = price_source.get_price(sacrifice_name) if sacrifice_name else 0
                sacrifice_total = sacrifice_unit_price * sacrifice_count
                
                profit = reward_total - sacrifice_total
                
                if color_code_profit:
                    # Color code: green for profit, red for loss
                    if profit >= 0:
                        color = "#4CAF50"  # Green
                        profit_text = f"+{profit:.1f}c"
                    else:
                        color = "#F44336"  # Red
                        profit_text = f"{profit:.1f}c"
                    style = f"font-weight: bold; color: {color};"
                else:
                    profit_text = f"{profit:.1f}c"
                    style = "font-weight: bold;"
                
                price_lbl = QLabel(profit_text)
                price_lbl.setFixedWidth(80)
                price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                price_lbl.setStyleSheet(style)
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
            # All reward tabs share the same sets
            ex_set = self.excluded_rewards
            in_set = self.included_rewards
        else:  # Monster Life %
            ex_set = self.excluded_tiers
            in_set = self.included_tiers
            
        if mode == "exclude":
            if checked:
                ex_set.add(text)
                in_set.discard(text)
            else:
                ex_set.discard(text)
        else:  # include
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
            "excluded_tiers": [int(x) for x in self.excluded_tiers if str(x).isdigit()],
            "included_tiers": [int(x) for x in self.included_tiers if str(x).isdigit()]
        }
