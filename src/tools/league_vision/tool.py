"""
League Vision Tool - OCR-based screen scanning for league mechanics.
"""

import copy
import json
import os
import shutil
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QCheckBox, QMessageBox, QPlainTextEdit,
    QDialog, QDialogButtonBox, QFormLayout, QFileDialog, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt

from tools.base_tool import BaseTool
from tools.league_vision.scanner import ScannerWorker, ScanResult
from utils.config import ConfigSaveError
from utils.workers import bounded_ocr_call, stop_legacy_qthread
from services.zone_monitor import ZoneMonitor
from utils.config import ConfigManager


class LeagueVisionWidget(QWidget):
    """Main widget for League Vision tool."""

    FEATURE_PATHS = {
        "map_check.enabled": "Map Safety Check",
        "essence.enabled": "Essence Detection",
        "ritual.enabled": "Ritual Detection",
        "eldritch_altars.enabled": "Eldritch Altar Rewards",
        "expedition.enabled": "Expedition Remnant Warnings",
    }

    EDITABLE_COLLECTIONS = (
        ("Dangerous Map Mods", ("map_check", "bad_mods"), "list"),
        ("Altar Rewards", ("eldritch_altars", "tiers"), "dict"),
        ("Expedition Warnings", ("expedition", "bad_mods"), "list"),
        ("Expedition Immunities", ("expedition", "immune_warning"), "list"),
        ("Syndicate Goals", ("syndicate_goals",), "dict"),
    )

    def __init__(self, config: dict, overlay=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.vision_config = config.setdefault("league_vision", {})
        self.overlay = overlay

        self.scanner = None
        self.zone_monitor = None

        self.setup_ui()
        self.setup_zone_monitor()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title
        title = QLabel("League Vision")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("OCR-based screen scanning for league mechanics")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(subtitle)

        # Setup Group
        setup_group = QGroupBox("Setup")
        setup_layout = QVBoxLayout(setup_group)

        # Client Log Path (managed in Settings)
        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Client.txt Path:"))
        self.log_path_label = QLabel(ConfigManager.get_client_log_path(self.config) or "Not Set")
        self.log_path_label.setStyleSheet("color: #aaaaaa;")
        log_row.addWidget(self.log_path_label, 1)
        manage_label = QLabel("Edit in Settings")
        manage_label.setStyleSheet("color: #888888; font-style: italic;")
        log_row.addWidget(manage_label)
        setup_layout.addLayout(log_row)

        # Calibrate Button
        self.calibrate_btn = QPushButton("Calibrate Map Device Button")
        self.calibrate_btn.clicked.connect(self.calibrate_button)
        setup_layout.addWidget(self.calibrate_btn)

        layout.addWidget(setup_group)

        # Features Group
        features_group = QGroupBox("Features")
        features_layout = QVBoxLayout(features_group)

        # Feature checkboxes
        self.chk_map_safety = QCheckBox("Map Safety Check (blocks dangerous mods)")
        self.chk_map_safety.setChecked(self.vision_config.get("map_check", {}).get("enabled", True))
        features_layout.addWidget(self.chk_map_safety)

        self.chk_essence = QCheckBox("Essence Detection (Misery, Envy, Dread, Scorn)")
        self.chk_essence.setChecked(self.vision_config.get("essence", {}).get("enabled", True))
        features_layout.addWidget(self.chk_essence)

        self.chk_ritual = QCheckBox("Ritual Detection (Opulent, Apocalyptic, etc.)")
        self.chk_ritual.setChecked(self.vision_config.get("ritual", {}).get("enabled", True))
        features_layout.addWidget(self.chk_ritual)

        self.chk_altars = QCheckBox("Eldritch Altar Rewards")
        self.chk_altars.setChecked(self.vision_config.get("eldritch_altars", {}).get("enabled", True))
        features_layout.addWidget(self.chk_altars)

        self.chk_expedition = QCheckBox("Expedition Remnant Warnings")
        self.chk_expedition.setChecked(self.vision_config.get("expedition", {}).get("enabled", True))
        features_layout.addWidget(self.chk_expedition)

        self.chk_syndicate = QCheckBox("Syndicate Member Guidance")
        self.chk_syndicate.setChecked(bool(self.vision_config.get("syndicate_enabled", len(self.vision_config.get("syndicate_goals", {})) > 0)))
        features_layout.addWidget(self.chk_syndicate)

        self._feature_checkboxes = {
            "map_check.enabled": self.chk_map_safety,
            "essence.enabled": self.chk_essence,
            "ritual.enabled": self.chk_ritual,
            "eldritch_altars.enabled": self.chk_altars,
            "expedition.enabled": self.chk_expedition,
            "syndicate_enabled": self.chk_syndicate,
        }
        for path, checkbox in self._feature_checkboxes.items():
            checkbox.toggled.connect(lambda checked, feature_path=path: self.on_feature_toggled(feature_path, checked))

        layout.addWidget(features_group)

        settings_group = QGroupBox("Scanner Settings")
        settings_layout = QFormLayout(settings_group)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["low_cpu", "balanced", "fast"])
        self.profile_combo.setCurrentText(self.vision_config.get("ocr_profile", "balanced"))
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        settings_layout.addRow("OCR Profile:", self.profile_combo)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 255)
        self.threshold_spin.setValue(int(self.vision_config.get("ocr_threshold", 70)))
        self.threshold_spin.valueChanged.connect(lambda value: self.update_setting_live(("ocr_threshold",), value))
        settings_layout.addRow("Threshold:", self.threshold_spin)
        self.advanced_ocr_chk = QCheckBox("Use custom interval/timeout values instead of profile defaults")
        self.advanced_ocr_chk.setChecked(bool(self.vision_config.get("ocr_advanced", False)))
        self.advanced_ocr_chk.toggled.connect(lambda checked: self.update_setting_live(("ocr_advanced",), checked, "Advanced OCR settings"))
        settings_layout.addRow("Advanced:", self.advanced_ocr_chk)
        self.mouse_interval_spin = QSpinBox()
        self.mouse_interval_spin.setRange(25, 5000)
        self.mouse_interval_spin.setSuffix(" ms")
        self.mouse_interval_spin.setValue(int(self.vision_config.get("scan_interval_mouse", 150)))
        self.mouse_interval_spin.valueChanged.connect(lambda value: self.update_setting_live(("scan_interval_mouse",), value, "Mouse scan interval"))
        settings_layout.addRow("Mouse Interval:", self.mouse_interval_spin)
        self.center_interval_spin = QSpinBox()
        self.center_interval_spin.setRange(25, 10000)
        self.center_interval_spin.setSuffix(" ms")
        self.center_interval_spin.setValue(int(self.vision_config.get("scan_interval_center", 500)))
        self.center_interval_spin.valueChanged.connect(lambda value: self.update_setting_live(("scan_interval_center",), value, "Center scan interval"))
        settings_layout.addRow("Center Interval:", self.center_interval_spin)
        self.ocr_timeout_spin = QDoubleSpinBox()
        self.ocr_timeout_spin.setRange(0.5, 60.0)
        self.ocr_timeout_spin.setDecimals(1)
        self.ocr_timeout_spin.setSuffix(" s")
        self.ocr_timeout_spin.setValue(float(self.vision_config.get("ocr_timeout", 10.0)))
        self.ocr_timeout_spin.valueChanged.connect(lambda value: self.update_setting_live(("ocr_timeout",), value, "OCR timeout"))
        settings_layout.addRow("OCR Timeout:", self.ocr_timeout_spin)
        self.tesseract_path_edit = QLineEdit(self.vision_config.get("tesseract_path", "tesseract"))
        self.tesseract_path_edit.editingFinished.connect(self.on_tesseract_path_edited)
        settings_layout.addRow("Tesseract Path:", self.tesseract_path_edit)
        advanced_label = QLabel("Profile changes apply live unless custom advanced values are enabled.")
        advanced_label.setStyleSheet("color: #888888; font-style: italic;")
        settings_layout.addRow("Note:", advanced_label)
        layout.addWidget(settings_group)

        editors_layout = QHBoxLayout()
        for title, path, kind in self.EDITABLE_COLLECTIONS:
            btn = QPushButton(f"Edit {title}")
            btn.clicked.connect(lambda _=False, t=title, p=path, k=kind: self.edit_collection(t, p, k))
            editors_layout.addWidget(btn)
        layout.addLayout(editors_layout)
        import_export_layout = QHBoxLayout()
        self.import_settings_btn = QPushButton("Import Vision JSON")
        self.import_settings_btn.clicked.connect(self.import_settings)
        import_export_layout.addWidget(self.import_settings_btn)
        self.export_settings_btn = QPushButton("Export Vision JSON")
        self.export_settings_btn.clicked.connect(self.export_settings)
        import_export_layout.addWidget(self.export_settings_btn)
        layout.addLayout(import_export_layout)

        # Debug tools (debug mode is controlled globally via Settings menu)
        debug_layout = QHBoxLayout()

        self.ocr_preview_btn = QPushButton("Test OCR on Current Screen")
        self.ocr_preview_btn.clicked.connect(self.test_ocr)
        debug_layout.addWidget(self.ocr_preview_btn)
        debug_layout.addStretch()

        layout.addLayout(debug_layout)

        # Controls
        controls_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Scanner")
        self.start_btn.setStyleSheet("background-color: #2a7a2a; font-weight: bold;")
        self.start_btn.clicked.connect(self.toggle_scanner)
        controls_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Scanner")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scanner)
        controls_layout.addWidget(self.stop_btn)

        self.clear_blocker_btn = QPushButton("Clear Blocker")
        self.clear_blocker_btn.setStyleSheet("background-color: #7a2a2a;")
        self.clear_blocker_btn.clicked.connect(self.clear_blocker)
        controls_layout.addWidget(self.clear_blocker_btn)

        self.toggle_mode_btn = QPushButton("Toggle Mode")
        self.toggle_mode_btn.setToolTip("Force switch between Mouse and Center scan mode")
        self.toggle_mode_btn.clicked.connect(self.toggle_scan_mode)
        controls_layout.addWidget(self.toggle_mode_btn)

        layout.addLayout(controls_layout)

        # Status
        status_layout = QHBoxLayout()

        self.zone_label = QLabel("Zone: Unknown")
        self.zone_label.setStyleSheet("color: #888888;")
        status_layout.addWidget(self.zone_label)

        status_layout.addStretch()

        self.mode_label = QLabel("Mode: Stopped")
        self.mode_label.setStyleSheet("color: #888888;")
        status_layout.addWidget(self.mode_label)

        layout.addLayout(status_layout)

        # Log Area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        layout.addWidget(self.log_area)

        layout.addStretch()

    def setup_zone_monitor(self):
        """Initialize zone monitoring from the Settings-managed Client.txt path."""
        self.refresh_settings(restart_monitor=True, log_changes=False)

    def refresh_settings(self, restart_monitor: bool = True, log_changes: bool = True):
        """Refresh visible/path-backed settings after the Settings page changes."""
        self.vision_config = self.config.setdefault("league_vision", {})
        self.sync_controls_from_config()
        log_path = ConfigManager.get_client_log_path(self.config)
        self.log_path_label.setText(log_path or "Not Set")
        if restart_monitor:
            self.restart_zone_monitor(log_path, log_changes=log_changes)

    def sync_controls_from_config(self):
        """Synchronize editable controls with the current in-memory config."""
        controls = [
            self.chk_map_safety, self.chk_essence, self.chk_ritual, self.chk_altars,
            self.chk_expedition, self.chk_syndicate, self.profile_combo, self.threshold_spin,
            self.advanced_ocr_chk, self.mouse_interval_spin, self.center_interval_spin,
            self.ocr_timeout_spin, self.tesseract_path_edit,
        ]
        blockers = [(control, control.blockSignals(True)) for control in controls]
        try:
            self.chk_map_safety.setChecked(self.vision_config.get("map_check", {}).get("enabled", True))
            self.chk_essence.setChecked(self.vision_config.get("essence", {}).get("enabled", True))
            self.chk_ritual.setChecked(self.vision_config.get("ritual", {}).get("enabled", True))
            self.chk_altars.setChecked(self.vision_config.get("eldritch_altars", {}).get("enabled", True))
            self.chk_expedition.setChecked(self.vision_config.get("expedition", {}).get("enabled", True))
            self.chk_syndicate.setChecked(bool(self.vision_config.get("syndicate_enabled", len(self.vision_config.get("syndicate_goals", {})) > 0)))
            self.profile_combo.setCurrentText(self.vision_config.get("ocr_profile", "balanced"))
            self.threshold_spin.setValue(int(self.vision_config.get("ocr_threshold", 70)))
            self.advanced_ocr_chk.setChecked(bool(self.vision_config.get("ocr_advanced", False)))
            self.mouse_interval_spin.setValue(int(self.vision_config.get("scan_interval_mouse", 150)))
            self.center_interval_spin.setValue(int(self.vision_config.get("scan_interval_center", 500)))
            self.ocr_timeout_spin.setValue(float(self.vision_config.get("ocr_timeout", 10.0)))
            self.tesseract_path_edit.setText(self.vision_config.get("tesseract_path", "tesseract"))
        finally:
            for control, previous in blockers:
                control.blockSignals(previous)

    def restart_zone_monitor(self, log_path: str, log_changes: bool = True):
        """Restart Client.txt tailing if the configured path changed."""
        current_path = self.zone_monitor.log_path if self.zone_monitor else ""
        if current_path == log_path:
            return
        if self.zone_monitor:
            self.zone_monitor.stop()
            self.zone_monitor = None
        self.zone_label.setText("Zone: Unknown")
        if log_path and os.path.exists(log_path):
            self.zone_monitor = ZoneMonitor(log_path)
            self.zone_monitor.zone_changed.connect(self.on_zone_changed)
            if self.zone_monitor.start():
                self.log("Zone monitor started.")
        elif log_changes:
            self.log("Client.txt path is not set or does not exist. Update it in Settings.")

    def on_zone_changed(self, zone: str):
        """Handle zone change."""
        self.zone_label.setText(f"Zone: {zone}")
        if self.scanner:
            self.scanner.set_zone(zone)
        self.log(f"Zone changed: {zone}")

    def log(self, message: str):
        self.log_area.append(message)

    def persist_config(self, action: str = "settings") -> bool:
        try:
            ConfigManager.save(self.config)
        except ConfigSaveError as error:
            self.log(f"ERROR: Could not save League Vision {action}: {error}")
            return False
        return True

    def _set_nested(self, path, value):
        target = self.vision_config
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value

    def _get_nested(self, path, default=None):
        target = self.vision_config
        for key in path:
            if not isinstance(target, dict) or key not in target:
                return default
            target = target[key]
        return target

    def update_setting_live(self, path, value, label=None):
        previous = copy.deepcopy(self.vision_config)
        self._set_nested(path, value)
        if self.persist_config(label or ".".join(path)):
            self.apply_live_settings()
            self.log(f"Saved {label or '.'.join(path)} (applied live)")
            return True
        self.vision_config.clear()
        self.vision_config.update(previous)
        self.sync_controls_from_config()
        return False

    def on_feature_toggled(self, feature_path: str, checked: bool):
        previous = copy.deepcopy(self.vision_config)
        if feature_path == "syndicate_enabled":
            self.vision_config["syndicate_enabled"] = checked
        else:
            section, key = feature_path.split(".", 1)
            self.vision_config.setdefault(section, {})[key] = checked
        if self.persist_config(self.FEATURE_PATHS.get(feature_path, feature_path)):
            self.apply_live_settings()
            self.log(f"Saved {self.FEATURE_PATHS.get(feature_path, feature_path)}: {'enabled' if checked else 'disabled'} (applied live)")
            return True
        self.vision_config.clear()
        self.vision_config.update(previous)
        self.sync_controls_from_config()
        return False

    def on_profile_changed(self, profile: str):
        self.update_setting_live(("ocr_profile",), profile, "OCR profile")

    def on_tesseract_path_edited(self):
        path = self.tesseract_path_edit.text().strip() or "tesseract"
        self.update_setting_live(("tesseract_path",), path, "Tesseract path")

    def apply_live_settings(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.update_config(self.get_scanner_config())

    def capture_screen_geometry(self):
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if not screen:
            return {"width": 1920, "height": 1080}
        size = screen.size()
        return {"width": int(size.width()), "height": int(size.height())}

    def validate_tesseract_path(self, tesseract_path: str) -> bool:
        ok = (os.path.isabs(tesseract_path) and os.path.exists(tesseract_path)) or (not os.path.isabs(tesseract_path) and shutil.which(tesseract_path) is not None)
        if not ok:
            self.log(f"WARNING: Tesseract not found at {tesseract_path}")
        return ok

    def edit_collection(self, title: str, path, kind: str):
        current = self._get_nested(path, [] if kind == "list" else {})
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit {title}")
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlainText(json.dumps(current, indent=2, sort_keys=True))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            value = json.loads(editor.toPlainText() or ("[]" if kind == "list" else "{}"))
        except json.JSONDecodeError as error:
            QMessageBox.warning(self, "Invalid JSON", str(error))
            return
        if kind == "list" and not isinstance(value, list):
            QMessageBox.warning(self, "Invalid JSON", f"{title} must be a JSON list.")
            return
        if kind == "dict" and not isinstance(value, dict):
            QMessageBox.warning(self, "Invalid JSON", f"{title} must be a JSON object.")
            return
        self.update_setting_live(path, value, title)

    def _validate_import_settings(self, payload: dict) -> str | None:
        """Validate imported settings before replacing or persisting live config.

        Unknown future keys are preserved as JSON data, but known keys that feed
        controls or scanner math must already have consumable types/ranges.
        """
        def fail(path, expected):
            return f"{path} must be {expected}."

        def is_bool(value):
            return isinstance(value, bool)

        def is_int(value):
            return isinstance(value, int) and not isinstance(value, bool)

        def is_number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        def list_of_strings(path, value):
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                return fail(path, "a list of strings")
            return None

        def dict_of_strings(path, value):
            if not isinstance(value, dict):
                return fail(path, "an object with string keys and string values")
            for key, item in value.items():
                if not isinstance(key, str) or not isinstance(item, str):
                    return fail(f"{path}.{key}", "a string value")
            return None

        def rect(path, value):
            if not isinstance(value, dict):
                return fail(path, "an object with integer x, y, w, and h fields")
            for key in ("x", "y", "w", "h"):
                if key not in value or not is_int(value[key]) or value[key] < 0:
                    return fail(f"{path}.{key}", "a non-negative integer")
            return None

        def int_range(path, value, minimum, maximum):
            if not is_int(value) or value < minimum or value > maximum:
                return fail(path, f"an integer from {minimum} to {maximum}")
            return None

        def number_range(path, value, minimum, maximum):
            if not is_number(value) or value < minimum or value > maximum:
                return fail(path, f"a number from {minimum} to {maximum}")
            return None

        scalar_validators = {
            "tesseract_path": lambda value: None if isinstance(value, str) and value.strip() else fail("tesseract_path", "a non-empty string"),
            "ocr_threshold": lambda value: int_range("ocr_threshold", value, 1, 255),
            "ocr_profile": lambda value: None if value in {"low_cpu", "balanced", "fast"} else fail("ocr_profile", "one of: low_cpu, balanced, fast"),
            "ocr_advanced": lambda value: None if is_bool(value) else fail("ocr_advanced", "true or false"),
            "debug_mode": lambda value: None if is_bool(value) else fail("debug_mode", "true or false"),
            "scan_interval_mouse": lambda value: int_range("scan_interval_mouse", value, 25, 5000),
            "scan_interval_center": lambda value: int_range("scan_interval_center", value, 25, 10000),
            "ocr_timeout": lambda value: number_range("ocr_timeout", value, 0.5, 60.0),
            "scan_mode": lambda value: None if isinstance(value, str) else fail("scan_mode", "a string"),
            "scan_strategy": lambda value: None if isinstance(value, str) else fail("scan_strategy", "a string"),
            "syndicate_enabled": lambda value: None if is_bool(value) else fail("syndicate_enabled", "true or false"),
            "map_device_button": lambda value: rect("map_device_button", value),
            "syndicate_goals": lambda value: dict_of_strings("syndicate_goals", value),
        }
        for key, validator in scalar_validators.items():
            if key in payload:
                error = validator(payload[key])
                if error:
                    return error

        for section in ("map_check", "essence", "ritual", "eldritch_altars", "expedition"):
            if section in payload and not isinstance(payload[section], dict):
                return fail(section, "a JSON object")

        for section in ("map_check", "essence", "ritual", "eldritch_altars", "expedition"):
            cfg = payload.get(section)
            if not isinstance(cfg, dict):
                continue
            if "enabled" in cfg and not is_bool(cfg["enabled"]):
                return fail(f"{section}.enabled", "true or false")

        for section in ("essence", "ritual"):
            cfg = payload.get(section)
            if isinstance(cfg, dict) and "keywords" in cfg:
                error = list_of_strings(f"{section}.keywords", cfg["keywords"])
                if error:
                    return error

        map_cfg = payload.get("map_check")
        if isinstance(map_cfg, dict):
            for key in ("bad_mods", "required_context"):
                if key in map_cfg:
                    error = list_of_strings(f"map_check.{key}", map_cfg[key])
                    if error:
                        return error

        altar_cfg = payload.get("eldritch_altars")
        if isinstance(altar_cfg, dict):
            if "bad_mods" in altar_cfg:
                error = list_of_strings("eldritch_altars.bad_mods", altar_cfg["bad_mods"])
                if error:
                    return error
            if "min_tier_to_highlight" in altar_cfg:
                error = int_range("eldritch_altars.min_tier_to_highlight", altar_cfg["min_tier_to_highlight"], 1, 99)
                if error:
                    return error
            if "tiers" in altar_cfg:
                tiers = altar_cfg["tiers"]
                if not isinstance(tiers, dict):
                    return fail("eldritch_altars.tiers", "an object mapping tier numbers to lists of strings")
                for tier, rewards in tiers.items():
                    try:
                        int(tier)
                    except (TypeError, ValueError):
                        return fail(f"eldritch_altars.tiers.{tier}", "an integer-like tier key")
                    error = list_of_strings(f"eldritch_altars.tiers.{tier}", rewards)
                    if error:
                        return error

        expedition_cfg = payload.get("expedition")
        if isinstance(expedition_cfg, dict):
            for key in ("bad_mods", "immune_warning"):
                if key in expedition_cfg:
                    error = list_of_strings(f"expedition.{key}", expedition_cfg[key])
                    if error:
                        return error

        for section, keys, minimum, maximum in (
            ("scan_region_hover", ("width", "height"), 1, 10000),
            ("resolution_override", ("width", "height"), 1, 10000),
        ):
            cfg = payload.get(section)
            if cfg is None:
                continue
            if not isinstance(cfg, dict):
                return fail(section, "a JSON object")
            if section == "resolution_override" and "enabled" in cfg and not is_bool(cfg["enabled"]):
                return fail("resolution_override.enabled", "true or false")
            if section == "resolution_override" and cfg.get("enabled") is True:
                for key in keys:
                    if key not in cfg:
                        return fail(f"resolution_override.{key}", "a required positive integer when enabled")
            for key in keys:
                if key in cfg:
                    error = int_range(f"{section}.{key}", cfg[key], minimum, maximum)
                    if error:
                        return error
            for key in ("x_offset", "x_offset_right", "y_offset"):
                if key in cfg and not is_number(cfg[key]):
                    return fail(f"{section}.{key}", "a number")

        scan_region = payload.get("scan_region")
        if scan_region is not None:
            if not isinstance(scan_region, dict):
                return fail("scan_region", "a JSON object")
            for key in ("x_offset", "y_offset", "width_pct", "height_pct"):
                if key in scan_region:
                    error = number_range(f"scan_region.{key}", scan_region[key], 0.0, 1.0)
                    if error:
                        return error

        return None

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import League Vision JSON", "", "JSON Files (*.json);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Import Failed", str(error))
            return
        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Import Failed", "League Vision settings must be a JSON object.")
            return
        validation_error = self._validate_import_settings(payload)
        if validation_error:
            QMessageBox.warning(self, "Import Failed", validation_error)
            return False
        previous = copy.deepcopy(self.vision_config)
        self.vision_config.clear()
        self.vision_config.update(payload)
        if self.persist_config("import"):
            self.refresh_settings(restart_monitor=False, log_changes=False)
            self.apply_live_settings()
            self.log(f"Imported League Vision settings from {path}")
            return True
        self.vision_config.clear()
        self.vision_config.update(previous)
        self.sync_controls_from_config()
        return False

    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export League Vision JSON", "league_vision.json", "JSON Files (*.json);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.vision_config, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except OSError as error:
            QMessageBox.warning(self, "Export Failed", str(error))
            return
        self.log(f"Exported League Vision settings to {path}")

    def calibrate_button(self):
        """Start calibration for map device button."""
        if not self.overlay:
            QMessageBox.warning(self, "Error", "Overlay not available.")
            return

        self.calibration_clicks = []
        self.overlay.set_calibration_mode(True, "Click TOP-LEFT of the 'Activate' button")
        self.overlay.calibration_clicked.connect(self.on_calibration_click)
        self.log("Calibration started. Click TOP-LEFT corner of Activate button.")

    def on_calibration_click(self, x: int, y: int):
        """Handle calibration click."""
        self.calibration_clicks.append((x, y))

        if len(self.calibration_clicks) == 1:
            self.overlay.set_calibration_mode(True, "Click BOTTOM-RIGHT of the 'Activate' button")
            self.log(f"Top-left: ({x}, {y}). Now click bottom-right.")
        elif len(self.calibration_clicks) == 2:
            self.overlay.set_calibration_mode(False)
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)

            x1, y1 = self.calibration_clicks[0]
            x2, y2 = self.calibration_clicks[1]

            rect = {
                "x": min(x1, x2),
                "y": min(y1, y2),
                "w": abs(x2 - x1),
                "h": abs(y2 - y1)
            }

            had_previous_button = "map_device_button" in self.vision_config
            previous_button = copy.deepcopy(self.vision_config.get("map_device_button"))
            self.vision_config["map_device_button"] = rect
            if self.persist_config("map-device calibration"):
                self.log(f"Map device button calibrated and saved: {rect}")
                QMessageBox.information(self, "Calibration Complete",
                                      f"Button position saved!\nRect: {rect}")
            else:
                if had_previous_button:
                    self.vision_config["map_device_button"] = previous_button
                else:
                    self.vision_config.pop("map_device_button", None)
                self.log(f"ERROR: Map device calibration was not saved: {rect}")
                QMessageBox.warning(self, "Calibration Save Failed",
                                    "Button position was captured but could not be saved. See log for details.")

    def set_debug_mode(self, enabled: bool):
        """Set debug mode (called from main window global toggle)."""
        self.vision_config["debug_mode"] = enabled
        self.log(f"Debug mode {'enabled' if enabled else 'disabled'}")
        if enabled:
            self.log("OCR output will be logged to debug.log and shown in log area")

        # Update running scanner if active
        if self.scanner and self.scanner.isRunning():
            self.scanner.debug_mode = enabled

    def test_ocr(self):
        """Perform a single OCR test and show results."""
        import cv2
        import pytesseract
        from tools.league_vision.vision_core import VisionCore

        tesseract_path = self.vision_config.get("tesseract_path", "tesseract")
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        from tools.league_vision.scanner import exact_window_title_for_game, is_exact_poe_window_title, POE_GAME_MATCHES
        game_id = ConfigManager.get_active_game(self.config)
        vision = VisionCore(
            window_title=exact_window_title_for_game(game_id),
            exact_title=True,
            process_names=POE_GAME_MATCHES[game_id]["process_names"],
            title_matcher=lambda title: is_exact_poe_window_title(title, game_id),
        )
        rect = vision.get_window_rect()

        if not rect:
            self.log("ERROR: Could not find Path of Exile window")
            return

        self.log(f"Window found: {rect}")

        # Capture center region
        region = {
            "top": int(rect["top"] + (rect["height"] * 0.1)),
            "left": int(rect["left"] + (rect["width"] * 0.2)),
            "width": int(rect["width"] * 0.6),
            "height": int(rect["height"] * 0.8)
        }

        img = vision.capture_region(region)
        if img is None:
            self.log("ERROR: Failed to capture screen")
            return

        self.log(f"Captured region: {region}")

        # Process OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh_val = self.vision_config.get("ocr_threshold", 70)
        _, thresh = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)

        try:
            text = bounded_ocr_call(pytesseract.image_to_string, thresh, timeout=self.vision_config.get("ocr_timeout", 10.0))
            self.log("=== OCR RESULT ===")
            self.log(text[:1000] if len(text) > 1000 else text)
            self.log("=== END OCR ===")

            # Check for keywords
            bad_mods = self.vision_config.get("map_check", {}).get("bad_mods", [])
            for mod in bad_mods:
                if mod.lower() in text.lower():
                    self.log(f"FOUND BAD MOD: {mod}")

            contexts = self.vision_config.get("map_check", {}).get("required_context", [])
            for ctx in contexts:
                if ctx.lower() in text.lower():
                    self.log(f"FOUND CONTEXT: {ctx}")

        except Exception as e:
            self.log(f"OCR Error: {e}")

    def get_scanner_config(self):
        """Build scanner config from current settings."""
        config = self.vision_config.copy()

        # Use global debug mode from main config
        config["debug_mode"] = self.config.get("debug_mode", False)
        config["active_game"] = ConfigManager.get_active_game(self.config)
        config["screen_geometry"] = self.capture_screen_geometry()

        # Update enabled states from checkboxes
        if "map_check" not in config:
            config["map_check"] = {}
        config["map_check"]["enabled"] = self.chk_map_safety.isChecked()

        if "essence" not in config:
            config["essence"] = {"keywords": ["Misery", "Envy", "Dread", "Scorn"]}
        config["essence"]["enabled"] = self.chk_essence.isChecked()

        if "ritual" not in config:
            config["ritual"] = {"keywords": ["Opulent", "Apocalyptic", "Glacial", "Volatile"]}
        config["ritual"]["enabled"] = self.chk_ritual.isChecked()

        if "eldritch_altars" not in config:
            config["eldritch_altars"] = {}
        config["eldritch_altars"]["enabled"] = self.chk_altars.isChecked()

        if "expedition" not in config:
            config["expedition"] = {}
        config["expedition"]["enabled"] = self.chk_expedition.isChecked()

        config["syndicate_enabled"] = self.chk_syndicate.isChecked()
        # Syndicate - if disabled, clear the goals in scanner copy only so saved goals remain editable.
        if not self.chk_syndicate.isChecked():
            config["syndicate_goals"] = {}

        return config

    def toggle_scanner(self):
        """Start the scanner."""
        if self.scanner and self.scanner.isRunning():
            return

        config = self.get_scanner_config()
        tesseract_path = config.get("tesseract_path", "tesseract")
        if not self.validate_tesseract_path(tesseract_path):
            message = (
                f"Tesseract not found at {tesseract_path}. Install Tesseract OCR or update "
                "League Vision's Tesseract Path setting before starting the scanner."
            )
            self.log(f"ERROR: {message}")
            QMessageBox.warning(self, "Tesseract Not Found", message)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return False
        self.scanner = ScannerWorker(config)
        self.scanner.result_signal.connect(self.on_scan_result)
        self.scanner.status_signal.connect(self.log)
        self.scanner.mode_signal.connect(self.on_mode_changed)

        # Connect debug signals to overlay
        if self.overlay:
            if config.get("debug_mode"):
                self.scanner.debug_rect_signal.connect(self.on_debug_rect)
                self.scanner.debug_box_signal.connect(self.on_debug_box)
                self.scanner.clear_debug_signal.connect(self.on_clear_debug)

        # Connect stop hotkey signal
        self.scanner.stop_requested_signal.connect(self.on_scanner_stop_requested)

        if self.zone_monitor:
            self.scanner.set_zone(self.zone_monitor.get_current_zone())

        self.scanner.start()

        # Debug data is routed through OverlayManager, which owns the single
        # Show Overlay gate. Starting the scanner must not force overlays on.
        if self.overlay and config.get("debug_mode"):
            self.log("Debug overlay data enabled - visibility follows Show Overlay")

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log("Scanner started.")

    def stop_scanner(self):
        """Stop the scanner with bounded fail-closed shutdown."""
        scanner = self.scanner
        if scanner:
            stopped = stop_legacy_qthread(scanner, timeout_ms=5000, stop=scanner.stop)
            if not stopped:
                self.log("ERROR: Scanner did not stop within 5000 ms; keeping scanner attached.")
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                return False
            if self.scanner is scanner:
                self.scanner = None

        # Clear debug rect
        if self.overlay:
            self.overlay.clear_debug()

        self.mode_label.setText("Mode: Stopped")
        self.mode_label.setStyleSheet("color: #888888;")

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log("Scanner stopped.")
        return True

    def on_debug_rect(self, x: int, y: int, w: int, h: int, color: str):
        """Handle debug rect from scanner."""
        if self.overlay:
            self.overlay.set_debug_rect(x, y, w, h, color)

    def on_debug_box(self, x: int, y: int, w: int, h: int, color: str):
        """Handle debug box from scanner (keyword highlight)."""
        if self.overlay:
            self.overlay.add_debug_box(x, y, w, h, color)

    def on_clear_debug(self):
        """Handle clear debug signal from scanner."""
        if self.overlay:
            self.overlay.clear_debug()

    def on_scanner_stop_requested(self):
        """Handle stop hotkey from scanner."""
        self.stop_scanner()

    def on_mode_changed(self, mode: str):
        """Handle scanner mode change."""
        self.mode_label.setText(f"Mode: {mode}")
        if mode == "MOUSE":
            self.mode_label.setStyleSheet("color: #00ffff; font-weight: bold;")  # Cyan
        else:
            self.mode_label.setStyleSheet("color: #ffff00; font-weight: bold;")  # Yellow

    def clear_blocker(self):
        """Manually clear any active blocker overlay."""
        if self.overlay:
            self.overlay.clear_blockers()
            self.log("Blocker cleared.")

    def toggle_scan_mode(self):
        """Toggle between mouse and center scan mode."""
        if self.scanner and self.scanner.isRunning():
            new_mode = self.scanner.toggle_mode()
            self.log(f"Manual override: {new_mode.upper()} mode")
        else:
            self.log("Scanner not running - start scanner first")

    def on_scan_result(self, result: ScanResult):
        """Handle scan result."""
        self.log(f"[{result.color.upper()}] {result.message}")

        if self.overlay:
            self.overlay.show_alert(result.message, result.color)

            if result.is_blocking and result.blocker_rect:
                self.overlay.create_blocker(result.blocker_rect, "UNSAFE")

    def cleanup(self):
        """Clean up resources."""
        scanner_stopped = self.stop_scanner() if self.scanner else True

        if self.zone_monitor:
            self.zone_monitor.stop()

        if self.overlay and scanner_stopped:
            self.overlay.clear_blockers()
        return scanner_stopped


class LeagueVisionTool(BaseTool):
    """League Vision Tool plugin."""

    @property
    def name(self) -> str:
        return "Vision"

    @property
    def icon(self) -> str:
        return "vision"

    @property
    def description(self) -> str:
        return "OCR-based screen scanning for league mechanics"

    def __init__(self, config: dict, overlay=None):
        self.config = config
        self.overlay = overlay
        self.widget = None

    def create_widget(self, parent=None) -> QWidget:
        self.widget = LeagueVisionWidget(self.config, self.overlay, parent)
        return self.widget

    def on_activated(self):
        if self.widget:
            self.widget.refresh_settings()

    def on_deactivated(self):
        pass

    def cleanup(self):
        if self.widget:
            return self.widget.cleanup()
        return True

