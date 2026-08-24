"""
Calibration system for POE Toolkit.

Supports calibrating active screen regions:
- Stash grid (explicit Standard 12x12 or Quad 24x24 profiles)
- Tab bar (for OCR tab detection)
- Versioned currency-tab bounds and optional per-point overrides
"""

import copy
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable


class CalibrationType(Enum):
    """Types of calibration supported."""
    STASH_GRID = auto()           # 2 points: top-left, bottom-right
    TAB_BAR = auto()              # 2 points: region to OCR for tab names
    CURRENCY_TAB_BOUNDS = auto()  # 2 points: outer currency-tab content bounds
    CRAFTING_POINT = auto()       # 1 point: optional override for a derived point


class StashGridProfile(Enum):
    """Explicit stash grid sizes. Never infer from pixel width."""
    STANDARD = "standard"
    QUAD = "quad"

    @property
    def label(self) -> str:
        return "Standard (12x12)" if self is StashGridProfile.STANDARD else "Quad (24x24)"

    @property
    def grid_size(self) -> int:
        return 12 if self is StashGridProfile.STANDARD else 24

    @classmethod
    def from_value(cls, value) -> "StashGridProfile":
        if isinstance(value, StashGridProfile):
            return value
        normalized = str(value or cls.STANDARD.value).strip().lower()
        if normalized in {"quad", "24", "24x24", "true"}:
            return cls.QUAD
        return cls.STANDARD


@dataclass
class CalibrationConfig:
    """Configuration for a calibration type."""
    name: str
    description: str
    step1_msg: str
    step2_msg: str
    config_key: str  # Key in user_config to save to


CALIBRATION_CONFIGS = {
    CalibrationType.STASH_GRID: CalibrationConfig(
        name="Stash Grid",
        description="Calibrate the stash inventory grid position for item highlighting",
        step1_msg="Click TOP-LEFT corner of the {profile_label} stash grid",
        step2_msg="Click BOTTOM-RIGHT corner of the {profile_label} stash grid",
        config_key="stash_grid_profiles",
    ),
    CalibrationType.TAB_BAR: CalibrationConfig(
        name="Tab Bar Region",
        description="Calibrate where stash tab names appear for OCR detection",
        step1_msg="Click TOP-LEFT of the tab bar\n(where tab names like 'Currency', 'Maps' appear)",
        step2_msg="Click BOTTOM-RIGHT of the tab bar region",
        config_key="tab_bar",
    ),
    CalibrationType.CURRENCY_TAB_BOUNDS: CalibrationConfig(
        name="Currency Tab Bounds",
        description="Calibrate outer content bounds used to derive currency crafting points",
        step1_msg="Click TOP-LEFT of the yellow outer Currency-tab content bounds",
        step2_msg="Click BOTTOM-RIGHT of the yellow outer Currency-tab content bounds",
        config_key="currency_tab_profiles",
    ),
    CalibrationType.CRAFTING_POINT: CalibrationConfig(
        name="Crafting Point Override",
        description="Fine-tune one derived currency-tab point",
        step1_msg="Click the center of {point_label}",
        step2_msg="",
        config_key="currency_tab_profiles",
    ),
}


def calculate_stash_grid_calibration(p1: tuple, p2: tuple, profile: StashGridProfile) -> dict:
    """Deterministically calculate a stash grid calibration from two corners."""
    x1, y1 = p1
    x2, y2 = p2
    left = int(min(x1, x2))
    top = int(min(y1, y2))
    right = int(max(x1, x2))
    bottom = int(max(y1, y2))
    width = right - left
    height = bottom - top
    grid_size = profile.grid_size
    cell_width = width / grid_size if grid_size else 0
    cell_height = height / grid_size if grid_size else 0
    cell_size = int(round((cell_width + cell_height) / 2))
    return {
        "x": left,
        "y": top,
        "width": width,
        "height": height,
        "x2": right,
        "y2": bottom,
        "x_offset": left,
        "y_offset": top,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "cell_size": cell_size,
        "grid_cols": grid_size,
        "grid_rows": grid_size,
        "profile": profile.value,
        "is_quad_calibrated": profile is StashGridProfile.QUAD,
    }


class CalibrationManager:
    """Manages calibration workflows for different screen regions."""

    def __init__(self, config: dict, save_callback: Callable[[], bool | None] = None):
        self.config = config
        self.save_callback = save_callback
        self.active_type: Optional[CalibrationType] = None
        self.active_stash_profile: StashGridProfile = StashGridProfile.STANDARD
        self.step: int = 0
        self.point1: Optional[tuple] = None
        self.active_game_id: str = "poe1"
        self.active_point_role: Optional[str] = None
        self.active_point_label: str = "crafting point"
        self.on_complete: Optional[Callable[[CalibrationType, dict], None]] = None
        self.on_message: Optional[Callable[[str], None]] = None

    def start_calibration(
        self,
        cal_type: CalibrationType,
        stash_profile: StashGridProfile | str = StashGridProfile.STANDARD,
        *,
        game_id: str = "poe1",
        point_role: str | None = None,
        point_label: str | None = None,
    ) -> str:
        self.active_type = cal_type
        self.active_stash_profile = StashGridProfile.from_value(stash_profile)
        self.active_game_id = str(game_id or "poe1")
        self.active_point_role = point_role
        self.active_point_label = str(point_label or "crafting point")
        self.step = 1
        self.point1 = None
        config = CALIBRATION_CONFIGS[cal_type]
        return self._format_step(config.step1_msg)

    def handle_click(self, x: int, y: int) -> Optional[str]:
        if self.active_type is None:
            return None
        config = CALIBRATION_CONFIGS[self.active_type]
        if self.step == 1:
            if self.active_type == CalibrationType.CRAFTING_POINT:
                result = {
                    "x": int(x),
                    "y": int(y),
                    "x2": int(x),
                    "y2": int(y),
                    "width": 0,
                    "height": 0,
                    "game_id": self.active_game_id,
                    "point_role": self.active_point_role,
                    "point_label": self.active_point_label,
                }
                if self.on_complete:
                    self.on_complete(self.active_type, result)
                return None
            self.point1 = (x, y)
            self.step = 2
            return self._format_step(config.step2_msg)
        if self.step == 2:
            result = self._calculate_calibration(self.point1, (x, y))
            if self.on_complete:
                self.on_complete(self.active_type, result)
            return None
        return None

    def confirm_calibration(self, result: dict):
        """Confirm and save the pending calibration after UI preview confirmation."""
        previous = copy.deepcopy(self.config)
        try:
            saved = self._save_calibration(result)
        except Exception:
            self.config.clear()
            self.config.update(previous)
            self.cancel()
            raise
        if not saved:
            self.config.clear()
            self.config.update(previous)
        self.cancel()
        return saved

    def cancel(self):
        self.active_type = None
        self.step = 0
        self.point1 = None
        self.active_point_role = None
        self.active_point_label = "crafting point"

    def is_active(self) -> bool:
        return self.active_type is not None

    def _format_step(self, message: str) -> str:
        return message.format(
            profile_label=self.active_stash_profile.label,
            point_label=self.active_point_label,
        )

    def _calculate_calibration(self, p1: tuple, p2: tuple) -> dict:
        x1, y1 = p1
        x2, y2 = p2
        left = int(min(x1, x2))
        top = int(min(y1, y2))
        right = int(max(x1, x2))
        bottom = int(max(y1, y2))
        width = right - left
        height = bottom - top
        result = {
            "x": left,
            "y": top,
            "width": width,
            "height": height,
            "x2": right,
            "y2": bottom,
        }
        if self.active_type == CalibrationType.STASH_GRID:
            return calculate_stash_grid_calibration(p1, p2, self.active_stash_profile)
        if self.active_type == CalibrationType.CURRENCY_TAB_BOUNDS:
            result["game_id"] = self.active_game_id
            result["layout_id"] = "poe1_currency_general_v1"
        return result

    def _ensure_legacy_stash_profile_migrated(self):
        overlay = self.config.get("overlay", {})
        if "x_offset" not in overlay:
            return
        calibration = self.config.setdefault("calibration", {})
        profiles = calibration.setdefault("stash_grid_profiles", {})
        legacy_profile = StashGridProfile.QUAD if overlay.get("is_quad_calibrated", False) else StashGridProfile.STANDARD
        key = legacy_profile.value
        if key not in profiles:
            cell_size = overlay.get("cell_size", 52)
            grid_size = legacy_profile.grid_size
            profiles[key] = {
                "x": overlay.get("x_offset", 18),
                "y": overlay.get("y_offset", 160),
                "x_offset": overlay.get("x_offset", 18),
                "y_offset": overlay.get("y_offset", 160),
                "cell_size": cell_size,
                "cell_width": float(cell_size),
                "cell_height": float(cell_size),
                "width": int(round(cell_size * grid_size)),
                "height": int(round(cell_size * grid_size)),
                "x2": int(round(overlay.get("x_offset", 18) + cell_size * grid_size)),
                "y2": int(round(overlay.get("y_offset", 160) + cell_size * grid_size)),
                "grid_cols": grid_size,
                "grid_rows": grid_size,
                "profile": key,
                "is_quad_calibrated": legacy_profile is StashGridProfile.QUAD,
                "migrated_from_overlay": True,
            }
            calibration.setdefault("active_stash_profile", key)

    def _save_calibration(self, result: dict):
        if self.active_type is None:
            return
        config_info = CALIBRATION_CONFIGS[self.active_type]
        key = config_info.config_key
        if self.active_type == CalibrationType.STASH_GRID:
            profile = StashGridProfile.from_value(result.get("profile", self.active_stash_profile.value))
            calibration = self.config.setdefault("calibration", {})
            profiles = calibration.setdefault("stash_grid_profiles", {})
            saved = dict(result)
            saved["profile"] = profile.value
            saved["grid_cols"] = profile.grid_size
            saved["grid_rows"] = profile.grid_size
            profiles[profile.value] = saved
            calibration["active_stash_profile"] = profile.value
            # Maintain legacy overlay fields for existing consumers.
            overlay = self.config.setdefault("overlay", {})
            overlay["x_offset"] = saved["x_offset"]
            overlay["y_offset"] = saved["y_offset"]
            overlay["cell_size"] = saved["cell_size"]
            overlay["is_quad_calibrated"] = profile is StashGridProfile.QUAD
        elif self.active_type == CalibrationType.CURRENCY_TAB_BOUNDS:
            calibration = self.config.setdefault("calibration", {})
            profiles = calibration.setdefault("currency_tab_profiles", {})
            currency_profile = profiles.setdefault(self.active_game_id, {})
            window_rect = result.get("window_rect")
            if not isinstance(window_rect, dict):
                raise ValueError("Currency calibration is missing the game-window reference")
            left = int(window_rect["left"])
            top = int(window_rect["top"])
            reference_width = int(window_rect["width"])
            reference_height = int(window_rect["height"])
            if reference_width <= 0 or reference_height <= 0:
                raise ValueError("Currency calibration has an invalid game-window reference")
            saved = {
                "x": int(result["x"]) - left,
                "y": int(result["y"]) - top,
                "x2": int(result["x2"]) - left,
                "y2": int(result["y2"]) - top,
                "width": int(result["width"]),
                "height": int(result["height"]),
            }
            currency_profile["bounds"] = saved
            currency_profile["layout_id"] = result.get(
                "layout_id", "poe1_currency_general_v1"
            )
            currency_profile["coordinate_space"] = "game_window"
            currency_profile["reference_window"] = {
                "width": reference_width,
                "height": reference_height,
            }
            # Recalibration invalidates any prior fine-tuned points.
            currency_profile["overrides"] = {}
        elif self.active_type == CalibrationType.CRAFTING_POINT:
            if not self.active_point_role:
                raise ValueError("Crafting point calibration has no role")
            calibration = self.config.setdefault("calibration", {})
            profiles = calibration.setdefault("currency_tab_profiles", {})
            currency_profile = profiles.setdefault(self.active_game_id, {})
            window_rect = result.get("window_rect")
            reference = currency_profile.get("reference_window")
            if (
                currency_profile.get("coordinate_space") != "game_window"
                or not isinstance(window_rect, dict)
                or not isinstance(reference, dict)
            ):
                raise ValueError("Calibrate Currency-tab bounds before fine-tuning points")
            if (
                int(window_rect.get("width", 0)) != int(reference.get("width", -1))
                or int(window_rect.get("height", 0)) != int(reference.get("height", -1))
            ):
                raise ValueError("Game window size changed; recalibrate Currency-tab bounds")
            overrides = currency_profile.setdefault("overrides", {})
            overrides[self.active_point_role] = {
                "x": int(result["x"]) - int(window_rect["left"]),
                "y": int(result["y"]) - int(window_rect["top"]),
            }
        else:
            calibration = self.config.setdefault("calibration", {})
            calibration[key] = result
        if self.save_callback:
            return self.save_callback() is not False
        return True

    def get_calibration(
        self,
        cal_type: CalibrationType,
        stash_profile: StashGridProfile | str | None = None,
        *,
        game_id: str = "poe1",
        point_role: str | None = None,
    ) -> Optional[dict]:
        config_info = CALIBRATION_CONFIGS[cal_type]
        key = config_info.config_key
        if cal_type == CalibrationType.STASH_GRID:
            self._ensure_legacy_stash_profile_migrated()
            calibration = self.config.get("calibration", {})
            profile = StashGridProfile.from_value(
                stash_profile or calibration.get("active_stash_profile") or StashGridProfile.STANDARD.value
            )
            saved = calibration.get("stash_grid_profiles", {}).get(profile.value)
            if saved:
                return saved
            overlay = self.config.get("overlay", {})
            if "x_offset" in overlay:
                legacy = StashGridProfile.QUAD if overlay.get("is_quad_calibrated", False) else StashGridProfile.STANDARD
                if legacy == profile:
                    return self.config.get("calibration", {}).get("stash_grid_profiles", {}).get(profile.value)
            return None
        if cal_type == CalibrationType.CURRENCY_TAB_BOUNDS:
            return (
                self.config.get("calibration", {})
                .get("currency_tab_profiles", {})
                .get(game_id, {})
                .get("bounds")
            )
        if cal_type == CalibrationType.CRAFTING_POINT:
            return (
                self.config.get("calibration", {})
                .get("currency_tab_profiles", {})
                .get(game_id, {})
                .get("overrides", {})
                .get(point_role)
            )
        return self.config.get("calibration", {}).get(key)

    def is_calibrated(
        self,
        cal_type: CalibrationType,
        stash_profile: StashGridProfile | str | None = None,
    ) -> bool:
        return self.get_calibration(cal_type, stash_profile) is not None


def get_calibration_status_text(manager: CalibrationManager) -> str:
    """Generate a status string showing calibration state."""
    lines = []
    for profile in StashGridProfile:
        saved = manager.get_calibration(CalibrationType.STASH_GRID, profile)
        if saved:
            lines.append(
                f"  Stash Grid - {profile.label}: Done "
                f"({saved.get('grid_cols', profile.grid_size)}x{saved.get('grid_rows', profile.grid_size)}, "
                f"cell {saved.get('cell_size')})"
            )
        else:
            lines.append(f"  Stash Grid - {profile.label}: Not set")
    tab_status = "Done" if manager.is_calibrated(CalibrationType.TAB_BAR) else "Not set"
    lines.append(f"  {CALIBRATION_CONFIGS[CalibrationType.TAB_BAR].name}: {tab_status}")
    return "\n".join(lines)
