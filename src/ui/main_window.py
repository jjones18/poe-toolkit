"""
Main application window with sidebar navigation.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFrame, QMessageBox,
    QMenuBar, QMenu, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction, QGuiApplication

from ui.overlay_manager import OverlayManager
from ui.theme import apply_dark_theme, SIDEBAR_BUTTON_STYLE, SIDEBAR_FRAME_STYLE
from ui.calibration import (
    CalibrationManager, CalibrationType, CALIBRATION_CONFIGS, StashGridProfile,
    get_calibration_status_text
)
from ui.geometry_utils import RectSpec, clamp_window_geometry
from utils import APP_VERSION
from utils.config import ConfigManager, ConfigSaveError
from utils.coordinate_mapper import StashGridMapper
from services.trade_service import TradeService
from services.price_service import PriceService


class SidebarButton(QPushButton):
    """Custom button for sidebar navigation."""
    
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAccessibleName(f"Open {text}")
        self.setCheckable(True)
        self.setMinimumHeight(50)
        self.setStyleSheet(SIDEBAR_BUTTON_STYLE)


class _UnavailableTool:
    """Navigation placeholder that keeps tool/button/stack indices aligned."""

    def __init__(self, name: str, message: str):
        self.name = name
        self.description = message
        self.widget = None

    def create_widget(self):
        label = QLabel(self.description)
        label.setWordWrap(True)
        label.setAccessibleName(f"{self.name} unavailable details")
        label.setStyleSheet("color: #ffcc99; padding: 24px; font-size: 13px;")
        self.widget = label
        return label

    def cleanup(self):
        return True

    def on_activated(self):
        pass

    def on_deactivated(self):
        pass


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""
    
    def __init__(self, trade_service: TradeService | None = None,
                 price_service: PriceService | None = None):
        super().__init__()
        self.setWindowTitle("POE Toolkit")
        self.setMinimumSize(900, 700)
        
        # Load config
        self.config = ConfigManager.load()
        self.trade_service = trade_service or TradeService()
        active_game = ConfigManager.get_active_game(self.config)
        active_league = ConfigManager.get_game_league(self.config, active_game)
        self.price_service = price_service or PriceService(active_game, active_league)
        self.price_service.set_context(active_game, active_league)
        
        # Restore window geometry safely across monitor changes.
        geometry = self._safe_restored_geometry(self.config.get("window", {}))
        self.setGeometry(geometry.x, geometry.y, geometry.width, geometry.height)
        
        # Create overlay
        self.overlay = OverlayManager()
        
        # Create mapper for overlay
        overlay_config = self.config.get("overlay", {})
        self.mapper = StashGridMapper(
            offset_x=overlay_config.get("x_offset", 18),
            offset_y=overlay_config.get("y_offset", 160),
            cell_size=overlay_config.get("cell_size", 53)
        )
        
        # Create calibration manager
        self.calibration_manager = CalibrationManager(
            self.config,
            save_callback=self._persist_config_callback
        )
        self.calibration_manager.on_complete = self.on_calibration_complete
        
        # Apply dark theme
        apply_dark_theme(self.parent() if self.parent() else self)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main layout: sidebar + content
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar
        sidebar = self.create_sidebar()
        main_layout.addWidget(sidebar)
        
        # Content area
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background-color: #1e1e1e;")
        main_layout.addWidget(self.content_stack, 1)
        
        # Load tools
        self.tools = []
        self.load_tools()
        self._loaded_game_id = ConfigManager.get_active_game(self.config)

        # Select first tool by default
        if self.sidebar_buttons:
            self.sidebar_buttons[0].setChecked(True)
            self.on_tool_selected(0)
        self._show_config_load_status()

    def _show_config_load_status(self):
        """Expose config recovery/failure state after the status UI exists."""
        if ConfigManager.last_error:
            self.status_label.setStyleSheet("color: #ff6666;")
            self.status_label.setText(f"Config error: {ConfigManager.last_error}")
        elif ConfigManager.last_warning:
            self.status_label.setStyleSheet("color: #ffaa66;")
            self.status_label.setText(f"Config warning: {ConfigManager.last_warning}")

    @staticmethod
    def _available_screen_rects():
        rects = []
        app = QGuiApplication.instance()
        if app is None:
            return rects
        for screen in app.screens():
            geometry = screen.availableGeometry()
            rects.append(RectSpec(
                geometry.x(), geometry.y(), geometry.width(), geometry.height()
            ))
        return rects

    @classmethod
    def _safe_restored_geometry(cls, win_config):
        return clamp_window_geometry(
            win_config,
            cls._available_screen_rects(),
            RectSpec(100, 100, 1100, 800),
        )
    
    def create_sidebar(self) -> QWidget:
        """Create the sidebar navigation panel."""
        sidebar = QFrame()
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(260)
        sidebar.setStyleSheet(SIDEBAR_FRAME_STYLE)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)
        
        # Logo/Title
        title = QLabel("POE Toolkit")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0e0; padding: 8px 8px 0px 8px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #e0e0e0; font-size: 10px; padding: 0px 8px 8px 8px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        game_label = QLabel("Toolkit Mode")
        game_label.setStyleSheet("color: #aaaaaa; font-size: 10px; padding: 4px 8px 0px 8px;")
        game_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(game_label)

        self.game_combo = QComboBox()
        self.game_combo.setAccessibleName("Active toolkit mode")
        self.game_combo.setToolTip("Switch between Path of Exile 1 and Path of Exile 2 toolsets")
        for game_id, profile in ConfigManager.GAME_PROFILES.items():
            self.game_combo.addItem(profile["label"], game_id)
        self.game_combo.setCurrentIndex(
            self.game_combo.findData(ConfigManager.get_active_game(self.config))
        )
        self.game_combo.currentIndexChanged.connect(self.on_game_combo_changed)
        layout.addWidget(self.game_combo)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3d3d3d;")
        layout.addWidget(sep)
        layout.addSpacing(12)
        
        # Tool buttons (will be populated by load_tools)
        self.sidebar_buttons = []
        self.tool_button_container = QVBoxLayout()
        layout.addLayout(self.tool_button_container)
        
        # Spacer
        layout.addStretch()
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #3d3d3d;")
        layout.addWidget(sep2)
        layout.addSpacing(8)
        
        # Overlay controls
        self.overlay_btn = SidebarButton("Show Overlay")
        self.overlay_btn.setAccessibleName("Show Overlay")
        self.overlay_btn.setToolTip("Toggle all overlay layers on or off (highlight, debug, calibration, alerts, blockers)")
        self.overlay_btn.setShortcut("Ctrl+O")
        self.overlay_btn.clicked.connect(self.toggle_overlay)
        layout.addWidget(self.overlay_btn)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666666; font-size: 10px; padding: 8px;")
        layout.addWidget(self.status_label)
        
        return sidebar
    
    def create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # Settings menu
        settings_menu = menubar.addMenu("Settings")
        
        # Calibration submenu
        calibration_menu = settings_menu.addMenu("Calibration")
        
        # Explicit stash grid profiles: no width inference.
        for profile in StashGridProfile:
            action = QAction(f"Stash Grid - {profile.label}...", self)
            action.setStatusTip(f"Calibrate and preview the full {profile.grid_size}x{profile.grid_size} stash grid before saving")
            action.setToolTip(action.statusTip())
            action.triggered.connect(
                lambda checked, sp=profile: self.start_calibration(CalibrationType.STASH_GRID, sp)
            )
            calibration_menu.addAction(action)

        tab_config = CALIBRATION_CONFIGS[CalibrationType.TAB_BAR]
        tab_action = QAction(f"{tab_config.name}...", self)
        tab_action.setStatusTip(tab_config.description)
        tab_action.setToolTip(tab_config.description)
        tab_action.triggered.connect(lambda checked: self.start_calibration(CalibrationType.TAB_BAR))
        calibration_menu.addAction(tab_action)
        
        # Add separator and status action
        calibration_menu.addSeparator()
        status_action = QAction("Show Calibration Status", self)
        status_action.triggered.connect(self.show_calibration_status)
        calibration_menu.addAction(status_action)
        
        # Separator before debug mode
        settings_menu.addSeparator()
        
        # Global debug mode toggle
        self.debug_mode_action = QAction("Debug Mode", self)
        self.debug_mode_action.setCheckable(True)
        self.debug_mode_action.setChecked(self.config.get("debug_mode", False))
        self.debug_mode_action.setStatusTip("Enable verbose debug logging for all tools")
        self.debug_mode_action.triggered.connect(self.toggle_debug_mode)
        settings_menu.addAction(self.debug_mode_action)
    
    def toggle_debug_mode(self, checked: bool):
        """Toggle global debug mode."""
        self.config["debug_mode"] = checked
        self.status_label.setText(f"Debug Mode: {'ON' if checked else 'OFF'}")
        
        # Notify all tools of debug mode change
        for tool in self.tools:
            if hasattr(tool, 'set_debug_mode'):
                tool.set_debug_mode(checked)
            if hasattr(tool, 'widget') and tool.widget:
                if hasattr(tool.widget, 'set_debug_mode'):
                    tool.widget.set_debug_mode(checked)
    
    def is_debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return self.config.get("debug_mode", False)
    
    def load_tools(self):
        """Load tools in navigation order, preserving one entry per slot."""
        from tools.diagnostics_tool import DiagnosticsTool
        from tools.settings_tool import SettingsTool
        from tools.trade_sniper import TradeSniperTool

        active_game = ConfigManager.get_active_game(self.config)
        tool_specs: list[tuple[type | None, dict]] = [
            (SettingsTool, {"config": self.config})
        ]

        if active_game == "poe1":
            try:
                from tools.league_tools import LeagueToolsTool
                tool_specs.append((LeagueToolsTool, {
                    "config": self.config,
                    "price_service": self.price_service,
                }))
            except Exception as exc:
                tool_specs.append((None, {"name": "League Tools", "error": exc}))
            try:
                from tools.league_vision import LeagueVisionTool
                tool_specs.append((LeagueVisionTool, {
                    "config": self.config,
                    "overlay": self.overlay,
                }))
            except Exception as exc:
                tool_specs.append((None, {"name": "League Vision", "error": exc}))

        # Trade is shared between PoE 1 and PoE 2. The active game controls
        # which trade URL is opened and which live-search tabs are monitored.
        tool_specs.append((TradeSniperTool, {
            "config": self.config,
            "service": self.trade_service,
        }))
        tool_specs.append((DiagnosticsTool, {
            "config": self.config,
            "trade_service": self.trade_service,
            "runtime_provider": self._diagnostic_runtime_state,
        }))

        for tool_class, kwargs in tool_specs:
            if tool_class is None:
                self._add_unavailable_tool(kwargs["name"], kwargs["error"])
                continue

            tool = None
            try:
                tool = tool_class(**kwargs)
                widget = tool.create_widget()
                self._register_tool(tool, widget)
            except Exception as error:
                if tool is not None:
                    cleanup = getattr(tool, "cleanup", None)
                    if callable(cleanup) and cleanup() is False:
                        raise RuntimeError(
                            f"{getattr(tool, 'name', tool_class.__name__)} failed to initialize "
                            "and its worker shutdown could not be verified"
                        ) from error
                self._add_unavailable_tool(
                    getattr(tool, "name", getattr(tool_class, "__name__", "Tool")),
                    error,
                )

    def _register_tool(self, tool, widget):
        """Atomically append one aligned tool/button/content entry."""
        index = len(self.tools)
        if len(self.sidebar_buttons) != index or self.content_stack.count() != index:
            raise RuntimeError("Tool navigation state is out of alignment")

        tool.widget = widget
        self.tools.append(tool)
        button = SidebarButton(tool.name)
        button.setToolTip(tool.description)
        if index < 9:
            button.setShortcut(f"Alt+{index + 1}")
            button.setToolTip(f"{tool.description} (Alt+{index + 1})")
        button.clicked.connect(lambda checked, i=index: self.on_tool_selected(i))
        self.tool_button_container.addWidget(button)
        self.sidebar_buttons.append(button)
        self.content_stack.addWidget(widget)

        if hasattr(widget, "game_changed"):
            widget.game_changed.connect(self.on_settings_game_changed)
        if hasattr(widget, "settings_saved"):
            widget.settings_saved.connect(self.on_settings_saved)
        if hasattr(widget, "overlay_update"):
            widget.overlay_update.connect(self.on_overlay_update)
        if hasattr(widget, "overlay_debug_text_update"):
            widget.overlay_debug_text_update.connect(self.overlay.set_debug_text)
        if hasattr(widget, "overlay_debug_rect_update"):
            widget.overlay_debug_rect_update.connect(self.overlay.set_debug_rect)
        if hasattr(widget, "overlay_guidance_update"):
            widget.overlay_guidance_update.connect(self.overlay.set_guidance_text)

    def _add_unavailable_tool(self, name: str, error: Exception):
        """Add an actionable placeholder without breaking navigation indices."""
        message = f"{name} unavailable: {error}"
        print(message)
        placeholder = _UnavailableTool(name, message)
        self._register_tool(placeholder, placeholder.create_widget())
        button = self.sidebar_buttons[-1]
        button.setText(f"⚠ {name}")
        button.setAccessibleName(f"Open unavailable {name} details")
        button.setToolTip(message)

    def _diagnostic_runtime_state(self) -> dict:
        """Return redacted runtime state without owning module-specific workers."""
        workers = []
        visible_errors = []
        zone_state = {"state": "not running", "zone": "Unknown"}

        status_text = self.status_label.text() if hasattr(self, "status_label") else ""
        if any(marker in status_text.lower() for marker in ("error", "failed")):
            visible_errors.append(status_text)

        for tool in self.tools:
            widget = getattr(tool, "widget", None)
            if widget is None:
                continue

            tool_status = getattr(widget, "status_label", None)
            read_status = getattr(tool_status, "text", None)
            if callable(read_status):
                tool_status_text = str(read_status())
                if any(
                    marker in tool_status_text.lower()
                    for marker in ("error", "failed")
                ):
                    visible_errors.append(f"{tool.name}: {tool_status_text}")

            registry = getattr(widget, "_worker_registry", None)
            active_names = getattr(registry, "active_names", ()) if registry else ()
            if isinstance(active_names, (tuple, list)):
                workers.extend(f"{tool.name}: {name}" for name in active_names)

            scanner = getattr(widget, "scanner", None)
            is_running = getattr(scanner, "isRunning", None)
            if callable(is_running) and is_running():
                workers.append(f"{tool.name}: scanner")

            monitor = getattr(widget, "zone_monitor", None)
            if monitor is not None and getattr(monitor, "running", False):
                get_zone = getattr(monitor, "get_current_zone", None)
                zone_state = {
                    "state": "running",
                    "zone": str(get_zone() if callable(get_zone) else "Unknown"),
                }

        return {
            "workers": workers,
            "zone_monitor": zone_state,
            "last_error": visible_errors[-1] if visible_errors else "",
            "price_service": self.price_service.runtime_state(),
        }

    def on_settings_game_changed(self, game_id: str):
        """Synchronize game mode, rolling back if old workers cannot stop."""
        previous_game = self._loaded_game_id
        idx = self.game_combo.findData(game_id)
        if idx >= 0 and self.game_combo.currentIndex() != idx:
            self.game_combo.blockSignals(True)
            self.game_combo.setCurrentIndex(idx)
            self.game_combo.blockSignals(False)
        if not self.reload_tools():
            ConfigManager.set_active_game(self.config, previous_game)
            self._persist_config()
            self._restore_game_combo(previous_game)
            self._restore_settings_game(previous_game)
            self.price_service.set_context(
                previous_game,
                ConfigManager.get_game_league(self.config, previous_game),
            )
            return False
        return True

    def on_settings_saved(self):
        """Refresh every view that mirrors application-owned shared settings."""
        game_id = ConfigManager.get_active_game(self.config)
        if game_id == self._loaded_game_id:
            self.price_service.set_context(
                game_id,
                ConfigManager.get_game_league(self.config, game_id),
            )
            widgets = [getattr(tool, 'widget', None) for tool in self.tools]
            self._refresh_shared_settings_views(widgets)
        self.status_label.setText("Settings saved")

    @staticmethod
    def _refresh_shared_settings_views(widgets):
        for widget in widgets:
            refresh = getattr(widget, "refresh_shared_settings", None)
            if callable(refresh):
                refresh()

    def on_game_combo_changed(self):
        """Switch between PoE 1 and PoE 2 toolsets."""
        game_id = self.game_combo.currentData()
        previous_game = ConfigManager.get_active_game(self.config)
        if not game_id or game_id == previous_game:
            return
        if not self.save_config():
            self._restore_game_combo(previous_game)
            return
        ConfigManager.set_active_game(self.config, game_id)
        if not self._persist_config():
            ConfigManager.set_active_game(self.config, previous_game)
            self._restore_game_combo(previous_game)
            return
        if not self.reload_tools():
            ConfigManager.set_active_game(self.config, previous_game)
            self._persist_config()
            self._restore_game_combo(previous_game)
            return
        profile = ConfigManager.get_game_profile(game_id)
        self.status_label.setText(f"Toolkit mode: {profile['label']}")

    def _restore_game_combo(self, game_id):
        """Restore a rejected mode selection without re-entering its signal handler."""
        index = self.game_combo.findData(game_id)
        if index < 0:
            return
        signals_were_blocked = self.game_combo.blockSignals(True)
        try:
            self.game_combo.setCurrentIndex(index)
        finally:
            self.game_combo.blockSignals(signals_were_blocked)

    def _restore_settings_game(self, game_id):
        """Restore any surviving Settings view after a rejected mode reload."""
        for tool in self.tools:
            widget = getattr(tool, "widget", None)
            restore = getattr(widget, "restore_active_game", None)
            if callable(restore):
                restore(game_id)

    def _cleanup_tools_verified(self):
        """Run tool cleanup and report whether every shutdown was verified."""
        cleanup_errors = []
        for tool in self.tools:
            try:
                if tool.cleanup() is False:
                    cleanup_errors.append(getattr(tool, "name", type(tool).__name__))
            except Exception as error:
                cleanup_errors.append(getattr(tool, "name", type(tool).__name__))
                print(f"Error cleaning up tool: {error}")

        if cleanup_errors:
            self.status_label.setStyleSheet("color: #ff6666;")
            self.status_label.setText(
                "Tool cleanup did not finish; operation aborted to protect active workers."
            )
            return False
        return True

    def clear_tools(self):
        """Remove loaded tool widgets only after every cleanup is verified."""
        if not self._cleanup_tools_verified():
            return False

        self.tools = []

        while self.content_stack.count():
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            widget.deleteLater()

        while self.tool_button_container.count():
            item = self.tool_button_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.sidebar_buttons = []
        return True

    def reload_tools(self):
        """Rebuild sidebar/content for the active game after verified cleanup."""
        if not self.clear_tools():
            return False
        game_id = ConfigManager.get_active_game(self.config)
        self.price_service.set_context(
            game_id,
            ConfigManager.get_game_league(self.config, game_id),
        )
        self.load_tools()
        self._loaded_game_id = ConfigManager.get_active_game(self.config)
        if self.sidebar_buttons:
            self.sidebar_buttons[0].setChecked(True)
            self.on_tool_selected(0)
        return True

    def on_tool_selected(self, index: int):
        """Handle tool selection from sidebar."""
        # Update button states
        for i, btn in enumerate(self.sidebar_buttons):
            btn.setChecked(i == index)
        
        # Deactivate previous tool
        current_idx = self.content_stack.currentIndex()
        if 0 <= current_idx < len(self.tools):
            self.tools[current_idx].on_deactivated()
        
        # Switch content
        self.content_stack.setCurrentIndex(index)
        
        # Activate new tool
        if 0 <= index < len(self.tools):
            self.tools[index].on_activated()
    
    def on_overlay_update(self, highlights: list):
        """Handle overlay content updates without overriding Show Overlay state."""
        self.overlay.clear_calibration_preview()
        if highlights:
            calibrated_is_quad = self.config.get("overlay", {}).get("is_quad_calibrated", False)
            self.overlay.set_highlights_from_items(
                highlights,
                self.mapper,
                self.mapper.cell_size,
                calibrated_is_quad
            )
        else:
            self.overlay.set_highlights([])
        self.overlay_btn.setChecked(self.overlay.isVisible())
    
    def toggle_overlay(self):
        """Toggle overlay visibility through OverlayManager's single state."""
        if self.overlay.isVisible():
            self.overlay.hide()
            self.overlay.clear_calibration_preview()
            self.overlay_btn.setChecked(False)
        else:
            overlay_config = self.config.get("overlay", {})
            is_quad = overlay_config.get("is_quad_calibrated", False)
            grid = 24 if is_quad else 12
            self.overlay.set_calibration_preview(
                self.mapper.offset_x,
                self.mapper.offset_y,
                self.mapper.cell_size,
                is_quad,
                cols=grid,
                rows=grid,
            )
            self.overlay.show()
            self.overlay_btn.setChecked(True)
    
    def start_calibration(self, cal_type: CalibrationType = CalibrationType.STASH_GRID,
                          stash_profile: StashGridProfile = StashGridProfile.STANDARD):
        """Start calibration for a specific region type."""
        msg = self.calibration_manager.start_calibration(cal_type, stash_profile)
        self.overlay.enable_for_calibration()
        self.overlay_btn.setChecked(True)
        self.overlay.set_calibration_mode(True, msg)
        try:
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)
        except TypeError:
            pass
        self.overlay.calibration_clicked.connect(self.on_calibration_click)

        config = CALIBRATION_CONFIGS[cal_type]
        suffix = f" - {stash_profile.label}" if cal_type == CalibrationType.STASH_GRID else ""
        self.status_label.setText(f"Calibrating: {config.name}{suffix}")
    
    def on_calibration_click(self, x: int, y: int):
        """Handle calibration clicks using CalibrationManager."""
        next_msg = self.calibration_manager.handle_click(x, y)
        
        if next_msg:
            # More steps needed
            self.overlay.set_calibration_mode(True, next_msg)
        else:
            # Calibration step 2 completed - now SHOW PREVIEW
            # The calibration manager logic was modified to wait for confirmation
            # But on_calibration_complete is called from inside the manager.
            # We need to show preview BEFORE the confirmation dialog.
            
            # Since on_calibration_complete is called with the result:
            pass

    def on_calibration_complete(self, cal_type: CalibrationType, result: dict):
        """Handle calibration completion."""
        config = CALIBRATION_CONFIGS[cal_type]
        
        # Show preview on overlay
        if cal_type == CalibrationType.STASH_GRID:
            is_quad = result.get('is_quad_calibrated', False)
            self.overlay.set_calibration_preview(
                result.get('x_offset', result.get('x', 0)),
                result.get('y_offset', result.get('y', 0)),
                result.get('cell_size', 52),
                is_quad,
                cols=result.get('grid_cols'),
                rows=result.get('grid_rows'),
                cell_width=result.get('cell_width'),
                cell_height=result.get('cell_height'),
            )
        else:
            # For other regions, show a simple rect preview
            self.overlay.set_calibration_region_preview(
                result['x'], result['y'], result['width'], result['height']
            )
        
        self.overlay.set_calibration_mode(False)
        
        # Update mapper if this was stash grid calibration (so the preview works if we use set_calibration_preview)
        if cal_type == CalibrationType.STASH_GRID:
            self.mapper.offset_x = result.get('x_offset', result.get('x', 0))
            self.mapper.offset_y = result.get('y_offset', result.get('y', 0))
            self.mapper.cell_size = result.get('cell_size', 52)
            
            profile = StashGridProfile.from_value(result.get('profile'))
            status_msg = (f"Profile: {profile.label}\n"
                          f"Grid: {result.get('grid_cols', profile.grid_size)} x {result.get('grid_rows', profile.grid_size)}\n"
                          f"Offset: ({self.mapper.offset_x}, {self.mapper.offset_y})\n"
                          f"Cell Size: {self.mapper.cell_size}")
        else:
            status_msg = (f"Region: ({result['x']}, {result['y']}) - "
                          f"({result['x2']}, {result['y2']})\n"
                          f"Size: {result['width']} x {result['height']}")

        # Show blocking dialog
        reply = QMessageBox.question(
            self,
            "Confirm Calibration",
            f"{config.name} calibrated!\n\n{status_msg}\n\n"
            "Is the full-grid preview correct? Calibration will only be saved if you choose Yes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        # Clear preview
        self.overlay.clear_calibration_preview()
        
        if reply == QMessageBox.StandardButton.Yes:
            # Confirm and save
            self.calibration_manager.confirm_calibration(result)
            self.status_label.setText(f"Calibrated: {config.name}")
        else:
            # Cancel
            self.calibration_manager.cancel()
            self.status_label.setText("Calibration cancelled")
            
        try:
            self.overlay.calibration_clicked.disconnect(self.on_calibration_click)
        except TypeError:
            pass
    
    def show_calibration_status(self):
        """Show current calibration status for all regions."""
        status = get_calibration_status_text(self.calibration_manager)
        QMessageBox.information(
            self,
            "Calibration Status",
            f"Current calibration status:\n\n{status}"
        )
    
    def save_config(self):
        """Save current configuration."""
        # Update window position
        self.config["window"] = {
            "x": self.x(),
            "y": self.y(),
            "width": self.width(),
            "height": self.height()
        }
        
        # Shared Settings is the final authority for account/game/league values,
        # so synchronize dependent widgets first and the owner last.
        widgets = [getattr(tool, 'widget', None) for tool in self.tools]
        for widget in self._ordered_config_widgets(widgets):
            if hasattr(widget, 'sync_config'):
                widget.sync_config()
            elif hasattr(widget, 'get_credentials'):
                credentials = widget.get_credentials()
                if credentials:
                    account = credentials.get("account_name", ConfigManager.get_account_name(self.config))
                    session_id = credentials.get("session_id", ConfigManager.get_session_id(self.config))
                    ConfigManager.set_account_credentials(self.config, session_id, account)
                    if credentials.get("league"):
                        ConfigManager.set_game_league(
                            self.config,
                            ConfigManager.get_active_game(self.config),
                            credentials["league"]
                        )
        
        return self._persist_config()

    def _persist_config_callback(self):
        """Calibration callback adapter, whose contract has no return value."""
        self._persist_config()

    def _persist_config(self):
        """Persist shared config and expose failures through the main status UI."""
        try:
            ConfigManager.save(self.config)
        except ConfigSaveError as error:
            if hasattr(self, "status_label"):
                self.status_label.setStyleSheet("color: #ff6666;")
                self.status_label.setText(f"Config save failed: {error}")
            return False
        return True

    @staticmethod
    def _ordered_config_widgets(widgets):
        """Return dependent config views first and the shared-settings owner last."""
        return sorted(
            (widget for widget in widgets if widget is not None),
            key=lambda widget: bool(getattr(widget, "owns_shared_settings", False)),
        )
    
    def closeEvent(self, event):
        """Handle application close after all tool workers stop."""
        if not self.save_config():
            event.ignore()
            return

        if not self._cleanup_tools_verified():
            event.ignore()
            return

        if not self.price_service.close(timeout_ms=20_000):
            event.ignore()
            return

        # Close overlay
        self.overlay.close()

        # The Trade service survives tool/mode reloads but belongs to the app.
        if self.trade_service.is_running:
            self.trade_service.stop()
        
        super().closeEvent(event)
