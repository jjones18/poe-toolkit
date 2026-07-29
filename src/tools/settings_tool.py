"""
Global settings page for shared account and per-game configuration.
"""

import copy

import requests
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QGroupBox, QFileDialog, QMessageBox
)

from tools.base_tool import BaseTool
from utils.config import ConfigManager, ConfigSaveError
from utils.workers import WorkerRegistry, bounded_http_request


LEAGUE_ENDPOINTS = {
    "poe1": "https://www.pathofexile.com/api/trade/data/leagues",
    "poe2": "https://www.pathofexile.com/api/trade2/data/leagues",
}

LEAGUE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def fetch_league_options(context, session=None):
    """Fetch both games' league lists using bounded, cancellable requests."""
    owns_session = session is None
    http = session or requests.Session()
    try:
        http.headers.update({"User-Agent": LEAGUE_USER_AGENT})
        league_options = {}
        for completed, (game_id, url) in enumerate(LEAGUE_ENDPOINTS.items(), start=1):
            response = bounded_http_request(
                http,
                "GET",
                url,
                token=context.token,
                timeout=(5.0, 10.0),
            )
            response.raise_for_status()
            data = response.json()
            leagues = []
            for entry in data.get("result", []):
                league = (entry.get("id") or entry.get("text") or "").strip()
                if league:
                    leagues.append(league)
            league_options[game_id] = leagues
            context.report_progress({"completed": completed, "total": len(LEAGUE_ENDPOINTS)})
        return league_options
    finally:
        if owns_session:
            http.close()


class SettingsWidget(QWidget):
    """Settings UI for shared account credentials and game-specific leagues."""

    owns_shared_settings = True

    game_changed = pyqtSignal(str)
    settings_saved = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        ConfigManager.normalize(self.config)
        self._game_values = {
            game_id: {
                "league": ConfigManager.get_game_league(self.config, game_id),
                "client_log_path": ConfigManager.get_client_log_path(
                    self.config, game_id
                ),
            }
            for game_id in ConfigManager.GAME_PROFILES
        }
        self._displayed_game = None
        self._worker_registry = WorkerRegistry(max_threads=1)
        self.setup_ui()
        self.status_label.setText("Using saved league lists; refresh manually when needed.")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Shared account settings plus per-game league and Client.txt selections")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(subtitle)

        account_group = QGroupBox("Account (shared by PoE 1 and PoE 2)")
        account_form = QFormLayout(account_group)

        self.session_input = QLineEdit()
        self.session_input.setAccessibleName("POESESSID session credential")
        self.session_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.session_input.setText(ConfigManager.get_session_id(self.config))
        self.session_input.setPlaceholderText("POESESSID")
        account_form.addRow("POESESSID:", self.session_input)

        self.account_input = QLineEdit()
        self.account_input.setAccessibleName("Path of Exile account name")
        self.account_input.setText(ConfigManager.get_account_name(self.config))
        self.account_input.setPlaceholderText("AccountName#1234")
        account_form.addRow("Account:", self.account_input)

        layout.addWidget(account_group)

        games_group = QGroupBox("Game Settings")
        games_form = QFormLayout(games_group)

        self.active_game_combo = QComboBox()
        self.active_game_combo.setAccessibleName("Active toolkit mode")
        for game_id, profile in ConfigManager.GAME_PROFILES.items():
            self.active_game_combo.addItem(profile["label"], game_id)
        active_game = ConfigManager.get_active_game(self.config)
        self.active_game_combo.setCurrentIndex(self.active_game_combo.findData(active_game))
        games_form.addRow("Active toolkit:", self.active_game_combo)

        self.league_combo = QComboBox()
        self.league_combo.setEditable(False)
        self.league_label = QLabel("League:")
        games_form.addRow(self.league_label, self.league_combo)

        client_log_row = QHBoxLayout()
        self.client_log_input = QLineEdit()
        client_log_row.addWidget(self.client_log_input, 1)

        self.client_log_browse_btn = QPushButton("Browse...")
        self.client_log_browse_btn.clicked.connect(self.browse_client_log_path)
        client_log_row.addWidget(self.client_log_browse_btn)
        self.client_log_label = QLabel("Client.txt path:")
        games_form.addRow(self.client_log_label, client_log_row)

        self.refresh_leagues_btn = QPushButton("Refresh League Lists")
        self.refresh_leagues_btn.clicked.connect(self.fetch_leagues)
        games_form.addRow("", self.refresh_leagues_btn)

        layout.addWidget(games_group)

        self.show_game_settings(active_game)
        self.active_game_combo.currentIndexChanged.connect(self.on_active_game_changed)

        note = QLabel(
            "League lists are public and refresh only when requested. Credential "
            "validation happens when an account tool uses the private stash API."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(note)

        button_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setAccessibleName("Save settings")
        self.save_btn.setShortcut("Ctrl+S")
        self.save_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
        self.save_btn.clicked.connect(self.save_settings)
        button_row.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset to Defaults...")
        self.reset_btn.setAccessibleName("Reset settings fields to defaults")
        self.reset_btn.setToolTip("Load defaults into the form; nothing changes on disk until Save Settings")
        self.reset_btn.clicked.connect(self.confirm_reset_to_defaults)
        button_row.addWidget(self.reset_btn)
        button_row.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #66ff66;")
        button_row.addWidget(self.status_label)
        layout.addLayout(button_row)

        layout.addStretch()

    def populate_league_combo(self, combo: QComboBox, selected: str, leagues: list[str]):
        combo.blockSignals(True)
        combo.clear()
        selected = (selected or "").strip()
        seen = set()
        for league in leagues:
            league = str(league).strip()
            if league and league not in seen:
                combo.addItem(league)
                seen.add(league)
        if selected:
            idx = combo.findText(selected)
            if idx < 0:
                combo.insertItem(0, selected)
                idx = 0
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def capture_game_settings(self):
        """Retain unsaved values for the currently displayed game."""
        if self._displayed_game not in self._game_values:
            return
        self._game_values[self._displayed_game]["league"] = self.current_combo_text(
            self.league_combo
        )
        self._game_values[self._displayed_game]["client_log_path"] = (
            self.client_log_input.text().strip()
        )

    def show_game_settings(self, game_id: str):
        """Display the league and Client.txt values owned by one game."""
        if game_id not in ConfigManager.GAME_PROFILES:
            game_id = "poe1"
        self._displayed_game = game_id
        values = self._game_values[game_id]
        self.populate_league_combo(
            self.league_combo,
            values["league"],
            ConfigManager.get_game_league_options(self.config, game_id),
        )
        self.client_log_input.setText(values["client_log_path"])
        profile = ConfigManager.get_game_profile(game_id)
        self.league_label.setText(f"{profile['label']} league:")
        self.client_log_label.setText(f"{profile['label']} Client.txt:")
        self.client_log_input.setPlaceholderText(
            f"Path to {profile['full_name']}/logs/Client.txt"
        )

    def on_active_game_changed(self):
        self.capture_game_settings()
        self.show_game_settings(self.active_game_combo.currentData())

    def sync_game_values_to_config(self, target_config=None):
        target_config = target_config if target_config is not None else self.config
        self.capture_game_settings()
        for game_id, values in self._game_values.items():
            ConfigManager.set_game_league(
                target_config, game_id, values["league"]
            )
            ConfigManager.set_client_log_path(
                target_config,
                values["client_log_path"],
                game_id,
            )

    def restore_active_game(self, game_id: str):
        """Restore a mode selection rejected by the application reload gate."""
        index = self.active_game_combo.findData(game_id)
        if index < 0:
            return
        signals_were_blocked = self.active_game_combo.blockSignals(True)
        try:
            self.active_game_combo.setCurrentIndex(index)
        finally:
            self.active_game_combo.blockSignals(signals_were_blocked)
        self.show_game_settings(game_id)

    def clear_league_combos(self, warning: str):
        self.league_combo.blockSignals(True)
        self.league_combo.clear()
        self.league_combo.blockSignals(False)
        if self._displayed_game in self._game_values:
            self._game_values[self._displayed_game]["league"] = ""
        self.status_label.setStyleSheet("color: #ffaa66;")
        self.status_label.setText(warning)

    def fetch_leagues(self):
        started = self._worker_registry.start(
            "league-refresh",
            fetch_league_options,
            on_progress=self.on_league_fetch_progress,
            on_result=self.on_leagues_fetched,
            on_error=lambda failure: self.on_league_fetch_error(
                f"Could not fetch league list: {failure.message}"
            ),
            on_finished=lambda: self.refresh_leagues_btn.setEnabled(True),
        )
        if not started:
            return False
        self.refresh_leagues_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.status_label.setText("Fetching current leagues...")
        return True

    def on_league_fetch_progress(self, progress: dict):
        self.status_label.setText(
            f"Fetching current leagues... {progress['completed']}/{progress['total']}"
        )

    def on_leagues_fetched(self, league_options: dict):
        self.capture_game_settings()
        poe1_leagues = league_options.get("poe1", [])
        poe2_leagues = league_options.get("poe2", [])
        ConfigManager.set_game_league_options(self.config, "poe1", poe1_leagues)
        ConfigManager.set_game_league_options(self.config, "poe2", poe2_leagues)
        poe1_leagues = ConfigManager.get_game_league_options(self.config, "poe1")
        poe2_leagues = ConfigManager.get_game_league_options(self.config, "poe2")

        current_game = self._displayed_game or ConfigManager.get_active_game(self.config)
        self.populate_league_combo(
            self.league_combo,
            self._game_values[current_game]["league"],
            ConfigManager.get_game_league_options(self.config, current_game),
        )
        self.status_label.setStyleSheet("color: #66ff66;")
        self.status_label.setText(
            f"Loaded leagues: PoE1 {len(poe1_leagues)}, PoE2 {len(poe2_leagues)}"
        )

    def on_league_fetch_error(self, message: str):
        self.status_label.setStyleSheet("color: #ffaa66;")
        self.status_label.setText(message)

    def current_combo_text(self, combo: QComboBox) -> str:
        return combo.currentText().strip() if combo.count() else ""

    def browse_client_log_path(self):
        """Browse for the active game's local Client.txt file."""
        game_id = self._displayed_game or ConfigManager.get_active_game(self.config)
        game_name = ConfigManager.get_game_profile(game_id)["full_name"]
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {game_name} Client.txt",
            self.client_log_input.text().strip(),
            "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            self.client_log_input.setText(path)

    def confirm_reset_to_defaults(self):
        """Confirm a non-destructive reset of the editable settings fields."""
        answer = QMessageBox.question(
            self,
            "Reset Settings Fields",
            "Reset toolkit mode, leagues, and Client.txt paths to their defaults?\n\n"
            "Account credentials are preserved. Nothing is written until you choose Save Settings.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        return self.reset_to_defaults()

    def reset_to_defaults(self):
        """Load safe non-secret defaults into the form without persisting them."""
        defaults = copy.deepcopy(ConfigManager.DEFAULTS)
        ConfigManager.normalize(defaults)
        self._game_values = {
            game_id: {
                "league": ConfigManager.get_game_league(defaults, game_id),
                "client_log_path": ConfigManager.get_client_log_path(defaults, game_id),
            }
            for game_id in ConfigManager.GAME_PROFILES
        }
        default_game = ConfigManager.get_active_game(defaults)
        previous = self.active_game_combo.blockSignals(True)
        try:
            self.active_game_combo.setCurrentIndex(
                self.active_game_combo.findData(default_game)
            )
        finally:
            self.active_game_combo.blockSignals(previous)
        self.show_game_settings(default_game)
        self.status_label.setStyleSheet("color: #ffaa66;")
        self.status_label.setText("Defaults loaded; credentials preserved. Choose Save Settings to apply.")
        return True

    def save_settings(self):
        old_game = ConfigManager.get_active_game(self.config)
        new_game = self.active_game_combo.currentData()
        candidate = copy.deepcopy(self.config)

        ConfigManager.set_account_credentials(
            candidate,
            self.session_input.text().strip(),
            self.account_input.text().strip(),
        )
        self.sync_game_values_to_config(candidate)
        ConfigManager.set_active_game(candidate, new_game)
        try:
            ConfigManager.save(candidate)
        except ConfigSaveError as error:
            self.status_label.setStyleSheet("color: #ff6666;")
            self.status_label.setText(f"Save failed: {error}")
            return False

        self.config.clear()
        self.config.update(candidate)

        self.status_label.setStyleSheet("color: #66ff66;")
        self.status_label.setText("Saved")
        self.settings_saved.emit()
        if new_game != old_game:
            self.game_changed.emit(new_game)
        return True

    def sync_config(self):
        """Push visible field values into the shared config before app save."""
        ConfigManager.set_account_credentials(
            self.config,
            self.session_input.text().strip(),
            self.account_input.text().strip(),
        )
        self.sync_game_values_to_config()
        ConfigManager.set_active_game(self.config, self.active_game_combo.currentData())

    def cleanup(self):
        """Cancel and verify any in-flight league refresh before destruction."""
        return self._worker_registry.close(timeout_ms=20_000)


class SettingsTool(BaseTool):
    """Settings tool plugin."""

    @property
    def name(self) -> str:
        return "Settings"

    @property
    def icon(self) -> str:
        return "settings"

    @property
    def description(self) -> str:
        return "Shared account and per-game settings"

    def __init__(self, config: dict):
        self.config = config
        self.widget = None

    def create_widget(self, parent=None) -> QWidget:
        self.widget = SettingsWidget(self.config, parent)
        return self.widget

    def on_activated(self):
        pass

    def on_deactivated(self):
        pass

    def cleanup(self):
        if self.widget:
            return self.widget.cleanup()
        return True
