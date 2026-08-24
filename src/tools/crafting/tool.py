"""Generic Crafting module UI and lifecycle."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from services.game_input_service import GameInputService
from tools.base_tool import BaseTool
from utils.config import ConfigManager

from .controller import CraftingController
from .hotkeys import CraftingHotkeys, SUPPORTED_HOTKEYS
from .layout import POINT_LABELS, get_currency_profile, resolve_currency_targets
from .models import CraftingGoal, CraftingMode


class CraftingWidget(QWidget):
    calibration_requested = pyqtSignal(str, str, str)
    target_preview_requested = pyqtSignal(str, object)
    target_preview_clear_requested = pyqtSignal()

    def __init__(
        self,
        config: dict,
        save_callback=None,
        game_input_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self._initializing = True
        self.config = config
        self.save_callback = save_callback
        self.game_id = ConfigManager.get_active_game(config)
        self.crafting_config = config.setdefault("crafting", {}).setdefault("poe1", {})
        self._owns_game_input_service = game_input_service is None
        self.game_input_service = game_input_service or GameInputService()
        self.controller = CraftingController(
            self.game_id,
            input_factory=lambda: self.game_input_service.session(self.game_id),
            parent=self,
        )
        self.hotkeys = CraftingHotkeys(parent=self)
        self._active = False
        self._input_available = False
        self._hotkeys_available = False
        self._setup_ui()
        self._connect_runtime()
        self.refresh_calibration()
        self._refresh_input_capability()
        self._update_action_ui()
        self._apply_game_support_state()
        self._initializing = False

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Crafting")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        subtitle = QLabel(
            "Generic currency crafting workflows — basic sockets and links currently support PoE 1"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(subtitle)

        self.layout_summary = QLabel("Layout: checking…")
        self.layout_summary.setWordWrap(True)
        layout.addWidget(self.layout_summary)
        self.calibration_group = QGroupBox("PoE 1 Currency Tab Layout")
        calibration_layout = QVBoxLayout(self.calibration_group)
        self.calibration_status = QLabel()
        self.calibration_status.setWordWrap(True)
        calibration_layout.addWidget(self.calibration_status)
        button_grid = QGridLayout()
        button_grid.setColumnStretch(0, 1)
        button_grid.setColumnStretch(1, 1)
        button_grid.setColumnStretch(2, 1)
        self.calibrate_bounds_button = QPushButton("Calibrate Outer Bounds")
        self.calibrate_bounds_button.setToolTip(
            "Click the top-left and bottom-right yellow outer Currency-tab content bounds"
        )
        self.calibrate_bounds_button.clicked.connect(
            lambda: self.calibration_requested.emit(
                "poe1", "bounds", "Currency Tab Bounds"
            )
        )
        button_grid.addWidget(self.calibrate_bounds_button, 0, 0)
        self.override_buttons = {}
        override_positions = {
            "jewellers_orb": (0, 1),
            "orb_of_fusing": (0, 2),
            "crafting_item": (1, 0),
        }
        for role, position in override_positions.items():
            button = QPushButton(f"Fine-tune {POINT_LABELS[role]}")
            button.clicked.connect(
                lambda _checked=False, r=role: self.calibration_requested.emit(
                    "poe1", r, POINT_LABELS[r]
                )
            )
            button_grid.addWidget(button, *position)
            self.override_buttons[role] = button
        self.preview_targets_button = QPushButton("Preview Targets — no input")
        self.preview_targets_button.setToolTip(
            "Show click-through markers at every resolved target without moving or clicking"
        )
        self.preview_targets_button.clicked.connect(self._preview_targets)
        button_grid.addWidget(self.preview_targets_button, 1, 1)
        self.clear_preview_button = QPushButton("Clear Preview")
        self.clear_preview_button.clicked.connect(
            self.target_preview_clear_requested.emit
        )
        button_grid.addWidget(self.clear_preview_button, 1, 2)
        calibration_layout.addLayout(button_grid)
        self.setup_toggle = self._add_collapsible(
            layout,
            "Calibration & target setup",
            self.calibration_group,
        )

        action_group = QGroupBox("Basic Crafting")
        action_form = QFormLayout(action_group)
        self.action_combo = QComboBox()
        self.action_combo.addItem("Sockets — Jeweller's Orb", CraftingMode.SOCKETS.value)
        self.action_combo.addItem("Links — Orb of Fusing", CraftingMode.LINKS.value)
        saved_mode = self.crafting_config.get("mode", CraftingMode.LINKS.value)
        self.action_combo.setCurrentIndex(
            max(0, self.action_combo.findData(saved_mode))
        )
        self.action_combo.currentIndexChanged.connect(self._update_action_ui)
        action_form.addRow("Action:", self.action_combo)

        self.target_spin = QSpinBox()
        self.target_spin.setRange(2, 6)
        self.target_spin.setValue(int(self.crafting_config.get("target", 5)))
        self.target_spin.valueChanged.connect(self._save_settings)
        action_form.addRow("Craft until at least:", self.target_spin)

        self.verify_only = QCheckBox(
            "Verification only — probe currency and item; spend nothing"
        )
        self.verify_only.setChecked(True)
        self.verify_only.setToolTip("Intentionally resets on every application launch")
        action_form.addRow(self.verify_only)

        budget_row = QHBoxLayout()
        self.unlimited_check = QCheckBox(
            "Unlimited until target or currency stack ends"
        )
        self.unlimited_check.setChecked(
            bool(self.crafting_config.get("unlimited", True))
        )
        self.max_attempts = QSpinBox()
        self.max_attempts.setRange(1, 100000)
        self.max_attempts.setValue(
            int(self.crafting_config.get("max_attempts", 1500))
        )
        self.max_attempts.setEnabled(not self.unlimited_check.isChecked())
        self.unlimited_check.toggled.connect(self.max_attempts.setDisabled)
        self.unlimited_check.toggled.connect(self._save_settings)
        self.max_attempts.valueChanged.connect(self._save_settings)
        budget_row.addWidget(self.unlimited_check)
        budget_row.addWidget(self.max_attempts)
        budget_row.addStretch()
        action_form.addRow("Attempt budget:", budget_row)

        layout.addWidget(action_group)

        self.runtime_summary = QLabel("Checking input and hotkeys…")
        self.runtime_summary.setWordWrap(True)
        layout.addWidget(self.runtime_summary)

        self.advanced_group = QGroupBox("Advanced Input Settings")
        advanced_layout = QVBoxLayout(self.advanced_group)
        delay_form = QFormLayout()
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(30, 1000)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(
            int(self.crafting_config.get("apply_delay_ms", 80))
        )
        self.delay_spin.valueChanged.connect(self._save_settings)
        delay_form.addRow("Craft/clipboard settle delay:", self.delay_spin)
        advanced_layout.addLayout(delay_form)

        hotkey_group = QGroupBox(
            "Global Hotkeys (active only while this page is selected)"
        )
        hotkey_form = QFormLayout(hotkey_group)
        self.start_hotkey = QComboBox()
        self.stop_hotkey = QComboBox()
        self.start_hotkey.addItems(SUPPORTED_HOTKEYS)
        self.stop_hotkey.addItems(SUPPORTED_HOTKEYS)
        self.start_hotkey.setCurrentText(
            self.crafting_config.get("start_hotkey", "Numpad Plus")
        )
        self.stop_hotkey.setCurrentText(
            self.crafting_config.get("stop_hotkey", "Numpad Minus")
        )
        self.start_hotkey.currentTextChanged.connect(self._hotkeys_changed)
        self.stop_hotkey.currentTextChanged.connect(self._hotkeys_changed)
        hotkey_form.addRow("Start:", self.start_hotkey)
        hotkey_form.addRow("Stop:", self.stop_hotkey)
        self.input_status = QLabel()
        self.input_status.setWordWrap(True)
        hotkey_form.addRow("Input backend:", self.input_status)
        self.hotkey_status = QLabel(
            "Hotkeys inactive until this page is selected"
        )
        self.hotkey_status.setWordWrap(True)
        hotkey_form.addRow(self.hotkey_status)
        advanced_layout.addWidget(hotkey_group)
        self.advanced_toggle = self._add_collapsible(
            layout,
            "Advanced input settings",
            self.advanced_group,
        )

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 14px; color: #dddddd;")
        layout.addWidget(self.status_label)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        self.log_toggle = self._add_collapsible(
            layout,
            "Run details",
            self.log_output,
        )
        self.stop_button = QPushButton("Stop Current Run")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(
            lambda: self.controller.stop("Stopped from Crafting page")
        )
        layout.addWidget(self.stop_button)

    @staticmethod
    def _add_collapsible(layout, title, content, expanded=False):
        toggle = QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        content.setVisible(expanded)
        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(
            lambda checked, button=toggle: button.setArrowType(
                Qt.ArrowType.DownArrow
                if checked
                else Qt.ArrowType.RightArrow
            )
        )
        layout.addWidget(toggle)
        layout.addWidget(content)
        return toggle

    def _connect_runtime(self):
        self.controller.status_changed.connect(self._log)
        self.controller.running_changed.connect(self.stop_button.setEnabled)
        self.controller.completed.connect(self._on_completed)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.availability_changed.connect(
            self._on_hotkey_availability
        )
        self._hotkeys_changed()

    def _mode(self):
        return CraftingMode(self.action_combo.currentData())

    def _update_action_ui(self):
        mode = self._mode()
        old = self.target_spin.value()
        self.target_spin.setRange(
            1 if mode is CraftingMode.SOCKETS else 2, 6
        )
        default = 6 if mode is CraftingMode.SOCKETS else 5
        self.target_spin.setValue(
            old if self.target_spin.minimum() <= old <= 6 else default
        )
        self._save_settings()

    def _save_settings(self, *_args):
        if not hasattr(self, "action_combo"):
            return
        self.crafting_config.update({
            "mode": self.action_combo.currentData(),
            "target": self.target_spin.value(),
            "unlimited": self.unlimited_check.isChecked(),
            "max_attempts": self.max_attempts.value(),
            "apply_delay_ms": self.delay_spin.value(),
            "start_hotkey": self.start_hotkey.currentText(),
            "stop_hotkey": self.stop_hotkey.currentText(),
        })
        if not self._initializing and callable(self.save_callback):
            self.save_callback()

    def _hotkeys_changed(self, *_args):
        if not hasattr(self, "start_hotkey"):
            return
        start = self.start_hotkey.currentText()
        stop = self.stop_hotkey.currentText()
        if start == stop:
            self._hotkeys_available = False
            self.hotkey_status.setText(
                "Start and Stop must use different keys"
            )
            self.hotkey_status.setStyleSheet("color: #ff6666;")
            if self._active:
                self.hotkeys.stop()
            self._refresh_runtime_summary()
            return
        self.hotkeys.configure(start, stop)
        self._save_settings()
        if self._active:
            self.hotkeys.stop()
            self.hotkeys.start()
        self._refresh_runtime_summary()

    def _on_hotkey_availability(self, available, detail):
        self._hotkeys_available = bool(available)
        if available:
            backend_detail = f" ({detail})" if detail else ""
            self.hotkey_status.setText(
                f"Armed{backend_detail}: "
                f"{self.start_hotkey.currentText()} starts; "
                f"{self.stop_hotkey.currentText()} stops"
            )
            self.hotkey_status.setStyleSheet("color: #66ff66;")
        else:
            self.hotkey_status.setText(
                f"Global hotkeys unavailable: {detail}"
            )
            self.hotkey_status.setStyleSheet("color: #ff6666;")
        self._refresh_runtime_summary()

    def _on_hotkey(self, action):
        if action == "stop":
            self.controller.stop("Stopped by global hotkey")
            return
        if self.controller.running:
            return
        if self.start_hotkey.currentText() == self.stop_hotkey.currentText():
            self._log(
                "Start blocked: configure different Start and Stop hotkeys"
            )
            return
        try:
            targets = resolve_currency_targets(self.config, "poe1")
        except ValueError as error:
            self._log(f"Start blocked: {error}")
            return
        goal = CraftingGoal(
            mode=self._mode(),
            target=self.target_spin.value(),
            max_attempts=(
                0 if self.unlimited_check.isChecked()
                else self.max_attempts.value()
            ),
            verify_only=self.verify_only.isChecked(),
        )
        self.target_preview_clear_requested.emit()
        self.controller.start(
            goal,
            targets,
            apply_delay_ms=self.delay_spin.value(),
        )

    def _refresh_input_capability(self):
        try:
            capability = self.game_input_service.capability()
            self._input_available = bool(capability.available)
            detail = capability.detail or (
                "available" if capability.available else "unavailable"
            )
            self.input_status.setText(f"{capability.backend}: {detail}")
            self.input_status.setStyleSheet(
                "color: #66ff66;"
                if capability.available
                else "color: #ff6666;"
            )
        except Exception as error:
            self._input_available = False
            self.input_status.setText(f"unavailable: {error}")
            self.input_status.setStyleSheet("color: #ff6666;")
        self._refresh_runtime_summary()

    def _refresh_runtime_summary(self):
        if not hasattr(self, "runtime_summary"):
            return
        backend = self.input_status.text().partition(":")[0] or "input"
        input_text = (
            f"Input ready: {backend}"
            if self._input_available
            else f"Input unavailable: {backend}"
        )
        if self._active:
            hotkey_text = (
                "Hotkeys armed"
                if self._hotkeys_available
                else "Hotkeys unavailable"
            )
        else:
            hotkey_text = "Select this page to arm hotkeys"
        self.runtime_summary.setText(
            f"{input_text} • {hotkey_text} • "
            f"Start {self.start_hotkey.currentText()} • "
            f"Stop {self.stop_hotkey.currentText()}"
        )
        ready = self._input_available and (
            not self._active or self._hotkeys_available
        )
        self.runtime_summary.setStyleSheet(
            "color: #66ff66;" if ready else "color: #ff6666;"
        )

    def _preview_targets(self):
        try:
            targets = resolve_currency_targets(self.config, "poe1")
        except ValueError as error:
            self._log(f"Preview blocked: {error}")
            return False
        self.target_preview_requested.emit("poe1", targets)
        self._log(
            "Requested click-through target preview; no input sent"
        )
        return True

    def _on_completed(self, result):
        state = result.final_state
        suffix = ""
        if state is not None:
            suffix = (
                f" Final: {state.socket_count} sockets, "
                f"largest link {state.max_link_group}."
            )
        self._log(
            f"{'SUCCESS' if result.success else 'STOPPED'}: "
            f"{result.reason}.{suffix}"
        )

    def _log(self, message):
        self.status_label.setText(str(message))
        self.log_output.appendPlainText(str(message))

    def refresh_calibration(self):
        self.preview_targets_button.setEnabled(False)
        if self.game_id != "poe1":
            self.layout_summary.setText("Layout unavailable for PoE 2")
            self.layout_summary.setStyleSheet("color: #ffaa66;")
            self.calibration_status.setText(
                "PoE 2 crafting is not enabled yet. This page is reserved for future actions."
            )
            self.calibration_status.setStyleSheet("color: #ffaa66;")
            return
        profile = get_currency_profile(self.config, "poe1")
        bounds = profile.get("bounds")
        if not bounds:
            self.layout_summary.setText("Layout not calibrated")
            self.layout_summary.setStyleSheet("color: #ffaa66;")
            self.calibration_status.setText(
                "Not calibrated. Calibrate the outer yellow Currency-tab content bounds first."
            )
            self.calibration_status.setStyleSheet("color: #ffaa66;")
            for button in self.override_buttons.values():
                button.setEnabled(False)
            return
        try:
            targets = resolve_currency_targets(self.config, "poe1")
        except ValueError as error:
            self.layout_summary.setText(f"Layout invalid: {error}")
            self.layout_summary.setStyleSheet("color: #ff6666;")
            self.calibration_status.setText(str(error))
            self.calibration_status.setStyleSheet("color: #ff6666;")
            for button in self.override_buttons.values():
                button.setEnabled(False)
            return
        overrides = profile.get("overrides", {})
        reference = profile.get("reference_window", {})
        self.layout_summary.setText(
            "Layout ready • "
            f"{reference.get('width', '?')}×{reference.get('height', '?')} • "
            f"{len(targets)} targets"
        )
        self.layout_summary.setStyleSheet("color: #66ff66;")
        lines = [
            f"Local bounds: ({bounds['x']}, {bounds['y']}) "
            f"{bounds['width']}×{bounds['height']}",
            f"Reference window: {reference.get('width', '?')}×"
            f"{reference.get('height', '?')}",
        ]
        for role, target in targets.items():
            source = "override" if role in overrides else "derived"
            lines.append(
                f"{POINT_LABELS[role]}: local ({target.x}, {target.y}) "
                f"[{source}]"
            )
        self.calibration_status.setText("\n".join(lines))
        self.calibration_status.setStyleSheet("color: #66ff66;")
        for button in self.override_buttons.values():
            button.setEnabled(True)
        self.preview_targets_button.setEnabled(True)

    def _apply_game_support_state(self):
        if self.game_id == "poe1":
            return
        self.runtime_summary.setText("PoE 2 crafting input is disabled")
        self.runtime_summary.setStyleSheet("color: #ffaa66;")
        self.setup_toggle.setEnabled(False)
        self.advanced_toggle.setEnabled(False)
        self.calibrate_bounds_button.setEnabled(False)
        for button in self.override_buttons.values():
            button.setEnabled(False)
        for control in (
            self.action_combo,
            self.target_spin,
            self.verify_only,
            self.unlimited_check,
            self.max_attempts,
            self.delay_spin,
            self.start_hotkey,
            self.stop_hotkey,
            self.preview_targets_button,
            self.clear_preview_button,
        ):
            control.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._log("PoE 2 crafting is not enabled.")

    def sync_config(self):
        self._save_settings()

    def refresh_shared_settings(self):
        self.refresh_calibration()
        self._refresh_input_capability()

    def activate(self):
        self._active = True
        if self.game_id != "poe1":
            self._log("PoE 2 crafting is not enabled.")
            return
        if self.start_hotkey.currentText() != self.stop_hotkey.currentText():
            self.hotkeys.start()
        self._refresh_runtime_summary()

    def deactivate(self):
        self._active = False
        self.controller.stop(
            "Stopped because Crafting page was deactivated"
        )
        self.hotkeys.stop()
        self._hotkeys_available = False
        self.target_preview_clear_requested.emit()
        self.hotkey_status.setText(
            "Hotkeys inactive until this page is selected"
        )
        self.hotkey_status.setStyleSheet("")
        self._refresh_runtime_summary()

    def cleanup(self):
        self.deactivate()
        if not self.controller.close():
            return False
        if self._owns_game_input_service:
            return self.game_input_service.close()
        return True


class CraftingTool(BaseTool):
    @property
    def name(self):
        return "Crafting"

    @property
    def icon(self):
        return "crafting"

    @property
    def description(self):
        return "Calibrated currency crafting workflows"

    def __init__(
        self,
        config: dict,
        save_callback=None,
        game_input_service=None,
    ):
        self.config = config
        self.save_callback = save_callback
        self.game_input_service = game_input_service
        self.widget = None

    def create_widget(self, parent=None):
        self.widget = CraftingWidget(
            self.config,
            self.save_callback,
            self.game_input_service,
            parent,
        )
        return self.widget

    def on_activated(self):
        if self.widget is not None:
            self.widget.activate()

    def on_deactivated(self):
        if self.widget is not None:
            self.widget.deactivate()

    def cleanup(self):
        return self.widget.cleanup() if self.widget is not None else True
