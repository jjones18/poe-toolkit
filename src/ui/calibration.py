"""
Calibration system for POE Toolkit.

Supports calibrating active screen regions:
- Stash grid (explicit Standard 12x12 or Quad 24x24 profiles)
- Tab bar (for OCR tab detection)
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable


class CalibrationType(Enum):
    """Types of calibration supported."""
    STASH_GRID = auto()           # 2 points: top-left, bottom-right
    TAB_BAR = auto()              # 2 points: region to OCR for tab names


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

    def __init__(self, config: dict, save_callback: Callable[[], None] = None):
        self.config = config
        self.save_callback = save_callback
        self.active_type: Optional[CalibrationType] = None
        self.active_stash_profile: StashGridProfile = StashGridProfile.STANDARD
        self.step: int = 0
        self.point1: Optional[tuple] = None
        self.on_complete: Optional[Callable[[CalibrationType, dict], None]] = None
        self.on_message: Optional[Callable[[str], None]] = None

    def start_calibration(
        self,
        cal_type: CalibrationType,
        stash_profile: StashGridProfile | str = StashGridProfile.STANDARD,
    ) -> str:
        self.active_type = cal_type
        self.active_stash_profile = StashGridProfile.from_value(stash_profile)
        self.step = 1
        self.point1 = None
        config = CALIBRATION_CONFIGS[cal_type]
        return self._format_step(config.step1_msg)

    def handle_click(self, x: int, y: int) -> Optional[str]:
        if self.active_type is None:
            return None
        config = CALIBRATION_CONFIGS[self.active_type]
        if self.step == 1:
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
        self._save_calibration(result)
        self.cancel()

    def cancel(self):
        self.active_type = None
        self.step = 0
        self.point1 = None

    def is_active(self) -> bool:
        return self.active_type is not None

    def _format_step(self, message: str) -> str:
        return message.format(profile_label=self.active_stash_profile.label)

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
        else:
            calibration = self.config.setdefault("calibration", {})
            calibration[key] = result
        if self.save_callback:
            self.save_callback()

    def get_calibration(
        self,
        cal_type: CalibrationType,
        stash_profile: StashGridProfile | str | None = None,
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
