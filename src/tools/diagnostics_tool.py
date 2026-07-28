"""Central redacted Diagnostics and Data Freshness page."""

from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.diagnostics_service import DiagnosticsService
from tools.base_tool import BaseTool
from utils.config import ConfigManager
from utils.workers import WorkerFailure, WorkerRegistry


class DiagnosticsWidget(QWidget):
    """Render redacted state and run explicit dependency checks off the GUI thread."""

    def __init__(
        self,
        config: dict,
        *,
        trade_service=None,
        runtime_provider=None,
        diagnostics: DiagnosticsService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config
        self._worker_registry = WorkerRegistry(max_threads=1)
        self.diagnostics = diagnostics or DiagnosticsService(
            config,
            trade_service=trade_service,
            runtime_provider=runtime_provider,
        )
        self.snapshot = {}
        self._setup_ui()
        self.refresh_view()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("Diagnostics & Data Freshness")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        note = QLabel(
            "This page reports configuration state without displaying account names, "
            "session tokens, or cached item contents."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        layout.addWidget(self.summary_text, 1)

        first_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setToolTip("Re-read local diagnostics and cache metadata")
        self.refresh_btn.clicked.connect(self.request_refresh)
        first_row.addWidget(self.refresh_btn)

        self.dependencies_btn = QPushButton("Test Dependencies")
        self.dependencies_btn.clicked.connect(self.test_dependencies)
        first_row.addWidget(self.dependencies_btn)

        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.clicked.connect(self.clear_caches)
        first_row.addWidget(self.clear_cache_btn)

        self.export_btn = QPushButton("Export Redacted Diagnostics")
        self.export_btn.clicked.connect(self.export_diagnostics)
        first_row.addWidget(self.export_btn)
        first_row.addStretch()
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        for label, key in (
            ("Open Cache Directory", "cache_dir"),
            ("Open Log Directory", "log_dir"),
            ("Open Data Directory", "data_dir"),
            ("Open Profile Directory", "profile_dir"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, path_key=key: self.open_directory(path_key))
            second_row.addWidget(button)
        second_row.addStretch()
        layout.addLayout(second_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    @staticmethod
    def _readiness(value) -> str:
        if value is True:
            return "ready"
        if value is False:
            return "not ready"
        return "not tested"

    @staticmethod
    def _format_age(seconds) -> str:
        if seconds is None:
            return "unknown"
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h"

    def _format_snapshot(self, snapshot: dict) -> str:
        application = snapshot.get("application", {})
        game_id = application.get("active_game", "poe1")
        game_label = ConfigManager.get_game_profile(game_id).get("label", game_id)
        credentials = snapshot.get("credentials", {})
        runtime = snapshot.get("runtime", {})
        zone = runtime.get("zone_monitor", {})
        paths = snapshot.get("paths", {})
        dependencies = snapshot.get("dependencies", {}).get("items", {})

        lines = [
            "APPLICATION",
            f"  Game: {game_label}",
            f"  League: {application.get('active_league', 'unknown')}",
            "",
            "CREDENTIALS (values redacted)",
            f"  Account: {credentials.get('account', 'not configured')}",
            f"  Session: {credentials.get('session', 'not configured')}",
            f"  Validation: {credentials.get('validation', 'not tested')}",
            "",
            "DEPENDENCIES",
        ]
        for key in ("node", "npm", "npm_dependencies", "tesseract", "devtools"):
            item = dependencies.get(key, {"ready": None, "detail": "not tested"})
            lines.append(
                f"  {key}: {self._readiness(item.get('ready'))} — {item.get('detail', '')}"
            )

        workers = runtime.get("workers", [])
        lines.extend([
            "",
            "RUNTIME",
            f"  Trade service: {runtime.get('trade_service', 'stopped')}",
            f"  Workers: {', '.join(workers) if workers else 'none'}",
            f"  Zone monitor: {zone.get('state', 'not running')} — {zone.get('zone', 'Unknown')}",
            f"  Last error: {runtime.get('last_error') or 'none'}",
            "",
            "CACHE FRESHNESS",
        ])
        for cache in snapshot.get("caches", []):
            state = "missing"
            if cache.get("exists"):
                state = "stale" if cache.get("stale") else "present"
            if cache.get("error"):
                state = f"error: {cache['error']}"
            lines.extend([
                f"  {cache.get('label', cache.get('key'))}: {state}",
                f"    source={cache.get('source')} game={cache.get('game')} "
                f"league={cache.get('league')} schema={cache.get('schema')} "
                f"items={cache.get('item_count')} age={self._format_age(cache.get('age_seconds'))}",
                f"    status={cache.get('status')} "
                f"estimated={'yes' if cache.get('estimated') else 'no'}",
                f"    deletion={'allowed' if cache.get('clearable') else 'display-only'}",
                f"    {cache.get('path')}",
            ])

        lines.extend(["", "PATHS"])
        for key in (
            "config_file",
            "cache_dir",
            "log_dir",
            "data_dir",
            "profile_dir",
            "client_log",
        ):
            value = paths.get(key, "") or "not configured"
            if key == "client_log":
                value += " (exists)" if paths.get("client_log_exists") else " (missing)"
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def refresh_view(self):
        self._apply_snapshot(self.diagnostics.collect_snapshot())

    def _apply_snapshot(self, snapshot: dict):
        self.snapshot = snapshot
        self.summary_text.setPlainText(self._format_snapshot(self.snapshot))
        self.status_label.setText("Local diagnostics refreshed.")

    def _collect_snapshot(self, context):
        context.raise_if_cancelled()
        snapshot = self.diagnostics.collect_snapshot()
        context.raise_if_cancelled()
        return snapshot

    def request_refresh(self):
        started = self._worker_registry.start(
            "local-refresh",
            self._collect_snapshot,
            on_result=self._apply_snapshot,
            on_error=lambda failure: self.status_label.setText(
                f"Diagnostics refresh failed: {failure.message}"
            ),
            on_cancelled=lambda: self.status_label.setText(
                "Diagnostics refresh cancelled."
            ),
        )
        if not started:
            self.status_label.setText("Diagnostics refresh is already running.")
        return started

    def test_dependencies(self):
        started = self._worker_registry.start(
            "dependency-test",
            self.diagnostics.collect_dependencies,
            on_progress=lambda message: self.status_label.setText(str(message)),
            on_result=self._on_dependencies_result,
            on_error=self._on_dependency_error,
            on_cancelled=lambda: self.status_label.setText("Dependency test cancelled."),
            on_finished=lambda: QTimer.singleShot(0, self.request_refresh),
        )
        if not started:
            self.status_label.setText("Dependency test is already running.")

    def _on_dependencies_result(self, _result):
        self.status_label.setText("Dependency test completed.")

    def _on_dependency_error(self, failure: WorkerFailure):
        self.status_label.setText(f"Dependency test failed: {failure.message}")

    def open_directory(self, key: str):
        path_text = self.snapshot.get("paths", {}).get(key, "")
        if not path_text:
            self.status_label.setText(f"No {key} is configured.")
            return False
        path = Path(path_text)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.status_label.setText(f"Could not create directory: {error}")
            return False
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.status_label.setText(
            f"Opened {path}" if opened else f"Could not open {path}"
        )
        return opened

    def clear_caches(self):
        answer = QMessageBox.question(
            self,
            "Clear caches?",
            "Delete only clearable per-user cache files? Legacy checkout caches "
            "shown above are display-only until migration.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        try:
            removed = self.diagnostics.clear_existing_caches()
        except OSError as error:
            self.status_label.setText(f"Cache clear failed: {error}")
            return False
        self.refresh_view()
        self.status_label.setText(
            f"Cleared {len(removed)} cache file(s)." if removed else "No cache files existed."
        )
        return True

    def export_diagnostics(self):
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export Redacted Diagnostics",
            "poe-toolkit-diagnostics.json",
            "JSON Files (*.json)",
        )
        if not destination:
            return False
        try:
            path = self.diagnostics.export_redacted(destination, self.snapshot)
        except OSError as error:
            self.status_label.setText(f"Diagnostics export failed: {error}")
            return False
        self.status_label.setText(f"Exported redacted diagnostics to {path}")
        return True

    def refresh_shared_settings(self):
        self.request_refresh()

    def cleanup(self):
        return self._worker_registry.close(timeout_ms=20_000)


class DiagnosticsTool(BaseTool):
    """Always-available central diagnostics tool."""

    @property
    def name(self) -> str:
        return "Diagnostics"

    @property
    def icon(self) -> str:
        return "diagnostics"

    @property
    def description(self) -> str:
        return "Redacted runtime status and data freshness"

    def __init__(self, config: dict, trade_service=None, runtime_provider=None):
        self.config = config
        self.trade_service = trade_service
        self.runtime_provider = runtime_provider
        self.widget = None

    def create_widget(self, parent=None) -> QWidget:
        self.widget = DiagnosticsWidget(
            self.config,
            trade_service=self.trade_service,
            runtime_provider=self.runtime_provider,
            parent=parent,
        )
        return self.widget

    def cleanup(self):
        if self.widget is not None:
            return self.widget.cleanup()
        return True
