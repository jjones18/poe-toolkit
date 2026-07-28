"""
Global settings page for shared account and per-game configuration.
"""

import requests
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QGroupBox, QFileDialog
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

        subtitle = QLabel("Shared account settings plus per-game league selections")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(subtitle)

        account_group = QGroupBox("Account (shared by PoE 1 and PoE 2)")
        account_form = QFormLayout(account_group)

        self.session_input = QLineEdit()
        self.session_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.session_input.setText(ConfigManager.get_session_id(self.config))
        self.session_input.setPlaceholderText("POESESSID")
        account_form.addRow("POESESSID:", self.session_input)

        self.account_input = QLineEdit()
        self.account_input.setText(ConfigManager.get_account_name(self.config))
        self.account_input.setPlaceholderText("AccountName#1234")
        account_form.addRow("Account:", self.account_input)

        layout.addWidget(account_group)

        games_group = QGroupBox("Game Settings")
        games_form = QFormLayout(games_group)

        self.active_game_combo = QComboBox()
        for game_id, profile in ConfigManager.GAME_PROFILES.items():
            self.active_game_combo.addItem(profile["label"], game_id)
        active_game = ConfigManager.get_active_game(self.config)
        self.active_game_combo.setCurrentIndex(self.active_game_combo.findData(active_game))
        games_form.addRow("Active toolkit:", self.active_game_combo)

        self.poe1_league_combo = QComboBox()
        self.poe1_league_combo.setEditable(False)
        self.populate_league_combo(
            self.poe1_league_combo,
            ConfigManager.get_game_league(self.config, "poe1"),
            ConfigManager.get_game_league_options(self.config, "poe1"),
        )
        games_form.addRow("PoE 1 league:", self.poe1_league_combo)

        self.poe2_league_combo = QComboBox()
        self.poe2_league_combo.setEditable(False)
        self.populate_league_combo(
            self.poe2_league_combo,
            ConfigManager.get_game_league(self.config, "poe2"),
            ConfigManager.get_game_league_options(self.config, "poe2"),
        )
        games_form.addRow("PoE 2 league:", self.poe2_league_combo)

        self.refresh_leagues_btn = QPushButton("Refresh League Lists")
        self.refresh_leagues_btn.clicked.connect(self.fetch_leagues)
        games_form.addRow("", self.refresh_leagues_btn)

        layout.addWidget(games_group)

        paths_group = QGroupBox("Local Paths")
        paths_form = QFormLayout(paths_group)

        client_log_row = QHBoxLayout()
        self.client_log_input = QLineEdit()
        self.client_log_input.setText(ConfigManager.get_client_log_path(self.config))
        self.client_log_input.setPlaceholderText("Path to Path of Exile/logs/Client.txt")
        client_log_row.addWidget(self.client_log_input, 1)

        self.client_log_browse_btn = QPushButton("Browse...")
        self.client_log_browse_btn.clicked.connect(self.browse_client_log_path)
        client_log_row.addWidget(self.client_log_browse_btn)
        paths_form.addRow("Client.txt path:", client_log_row)

        layout.addWidget(paths_group)

        note = QLabel(
            "League lists are public and refresh only when requested. Credential "
            "validation happens when an account tool uses the private stash API."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(note)

        button_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold; padding: 10px;")
        self.save_btn.clicked.connect(self.save_settings)
        button_row.addWidget(self.save_btn)
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

    def clear_league_combos(self, warning: str):
        for combo in (self.poe1_league_combo, self.poe2_league_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)
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
        poe1_leagues = league_options.get("poe1", [])
        poe2_leagues = league_options.get("poe2", [])
        ConfigManager.set_game_league_options(self.config, "poe1", poe1_leagues)
        ConfigManager.set_game_league_options(self.config, "poe2", poe2_leagues)
        poe1_leagues = ConfigManager.get_game_league_options(self.config, "poe1")
        poe2_leagues = ConfigManager.get_game_league_options(self.config, "poe2")

        self.populate_league_combo(
            self.poe1_league_combo,
            ConfigManager.get_game_league(self.config, "poe1"),
            poe1_leagues,
        )
        self.populate_league_combo(
            self.poe2_league_combo,
            ConfigManager.get_game_league(self.config, "poe2"),
            poe2_leagues,
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
        """Browse for the local Path of Exile Client.txt file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Path of Exile Client.txt",
            self.client_log_input.text().strip(),
            "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            self.client_log_input.setText(path)

    def save_settings(self):
        old_game = ConfigManager.get_active_game(self.config)
        new_game = self.active_game_combo.currentData()

        ConfigManager.set_account_credentials(
            self.config,
            self.session_input.text().strip(),
            self.account_input.text().strip(),
        )
        ConfigManager.set_game_league(self.config, "poe1", self.current_combo_text(self.poe1_league_combo))
        ConfigManager.set_game_league(self.config, "poe2", self.current_combo_text(self.poe2_league_combo))
        ConfigManager.set_active_game(self.config, new_game)
        ConfigManager.set_client_log_path(self.config, self.client_log_input.text())
        try:
            ConfigManager.save(self.config)
        except ConfigSaveError as error:
            self.status_label.setStyleSheet("color: #ff6666;")
            self.status_label.setText(f"Save failed: {error}")
            return False

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
        ConfigManager.set_game_league(self.config, "poe1", self.current_combo_text(self.poe1_league_combo))
        ConfigManager.set_game_league(self.config, "poe2", self.current_combo_text(self.poe2_league_combo))
        ConfigManager.set_active_game(self.config, self.active_game_combo.currentData())
        ConfigManager.set_client_log_path(self.config, self.client_log_input.text())

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
