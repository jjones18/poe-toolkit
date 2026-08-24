"""Versioned PoE currency-tab layout definitions and calibrated point resolution."""

from .models import ScreenPoint
from services.game_input_service import WindowRelativePoint, WindowSnapshot


POE1_LAYOUT_ID = "poe1_currency_general_v1"
POINT_LABELS = {
    "jewellers_orb": "Jeweller's Orb",
    "orb_of_fusing": "Orb of Fusing",
    "crafting_item": "Crafting Item",
}
POINT_COLORS = {
    "jewellers_orb": "#ffd166",
    "orb_of_fusing": "#66ccff",
    "crafting_item": "#66ff99",
}
# Normalized against the yellow outer Currency-tab content bounds shown by PoE 1.
# Bounds calibration scales these values across resolution and UI scale changes.
POE1_NORMALIZED_POINTS = {
    "jewellers_orb": (0.161, 0.418),
    "orb_of_fusing": (0.251, 0.418),
    "crafting_item": (0.520, 0.516),
}


def get_currency_profile(config: dict, game_id: str = "poe1") -> dict:
    profiles = config.get("calibration", {}).get("currency_tab_profiles", {})
    profile = profiles.get(game_id, {}) if isinstance(profiles, dict) else {}
    return profile if isinstance(profile, dict) else {}


def validate_bounds(bounds: dict | None) -> bool:
    return bool(
        isinstance(bounds, dict)
        and isinstance(bounds.get("x"), (int, float))
        and isinstance(bounds.get("y"), (int, float))
        and isinstance(bounds.get("width"), (int, float))
        and isinstance(bounds.get("height"), (int, float))
        and bounds.get("width", 0) >= 400
        and bounds.get("height", 0) >= 400
    )


def derive_currency_points(bounds: dict, overrides: dict | None = None) -> dict[str, ScreenPoint]:
    if not validate_bounds(bounds):
        raise ValueError("Currency-tab bounds are missing or too small")
    overrides = overrides if isinstance(overrides, dict) else {}
    points = {}
    for role, (nx, ny) in POE1_NORMALIZED_POINTS.items():
        override = overrides.get(role, {})
        if isinstance(override, dict) and isinstance(override.get("x"), (int, float)) and isinstance(override.get("y"), (int, float)):
            point = ScreenPoint(int(round(override["x"])), int(round(override["y"])))
        else:
            point = ScreenPoint(
                int(round(bounds["x"] + bounds["width"] * nx)),
                int(round(bounds["y"] + bounds["height"] * ny)),
            )
        points[role] = point
    return points


def resolve_currency_points(config: dict, game_id: str = "poe1") -> dict[str, ScreenPoint]:
    profile = get_currency_profile(config, game_id)
    bounds = profile.get("bounds")
    if not isinstance(bounds, dict):
        raise ValueError("Currency-tab bounds are missing or too small")
    return derive_currency_points(bounds, profile.get("overrides"))


def resolve_currency_targets(
    config: dict,
    game_id: str = "poe1",
) -> dict[str, WindowRelativePoint]:
    """Resolve safe game-window-relative targets for input injection."""
    profile = get_currency_profile(config, game_id)
    if profile.get("coordinate_space") != "game_window":
        raise ValueError(
            "Currency calibration uses legacy desktop coordinates; recalibrate "
            "the Currency-tab bounds before previewing or injecting input"
        )
    reference = profile.get("reference_window")
    if not isinstance(reference, dict):
        raise ValueError("Currency calibration is missing its reference game-window size")
    width = reference.get("width")
    height = reference.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        raise ValueError("Currency calibration has an invalid reference game-window size")
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Currency calibration has an invalid reference game-window size")

    points = resolve_currency_points(config, game_id)
    return {
        role: WindowRelativePoint(point.x, point.y, width, height)
        for role, point in points.items()
    }


def targets_to_desktop_markers(
    targets: dict[str, WindowRelativePoint],
    window: WindowSnapshot,
) -> list[dict]:
    markers = []
    for role, target in targets.items():
        point = target.to_desktop(window)
        markers.append({
            "x": point.x,
            "y": point.y,
            "label": POINT_LABELS[role],
            "color": POINT_COLORS[role],
        })
    return markers


def preview_markers(points: dict[str, ScreenPoint]) -> list[dict]:
    return [
        {
            "x": point.x,
            "y": point.y,
            "label": POINT_LABELS[role],
            "color": POINT_COLORS[role],
        }
        for role, point in points.items()
    ]
