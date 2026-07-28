"""Deterministic screen/window geometry helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RectSpec:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: "RectSpec") -> bool:
        return not (
            self.right <= other.x or other.right <= self.x or
            self.bottom <= other.y or other.bottom <= self.y
        )

    def intersection_area(self, other: "RectSpec") -> int:
        if not self.intersects(other):
            return 0
        return max(0, min(self.right, other.right) - max(self.x, other.x)) * max(
            0, min(self.bottom, other.bottom) - max(self.y, other.y)
        )


def clamp_window_geometry(
    saved: dict | None,
    screens: list[RectSpec],
    default: RectSpec = RectSpec(100, 100, 1100, 800),
    min_titlebar_visible: int = 30,
) -> RectSpec:
    """Clamp saved window geometry into connected available screens.

    Handles negative monitor coordinates and disconnected saved positions without Qt.
    """
    if not screens:
        return default
    saved = saved or {}
    width = _int(saved.get("width"), default.width)
    height = _int(saved.get("height"), default.height)
    x = _int(saved.get("x"), default.x)
    y = _int(saved.get("y"), default.y)

    target = RectSpec(x, y, max(1, width), max(1, height))
    best = max(screens, key=lambda screen: target.intersection_area(screen))
    if target.intersection_area(best) == 0:
        best = min(screens, key=lambda screen: (abs(target.x - screen.x) + abs(target.y - screen.y)))

    clamped_width = min(max(1, width), max(1, best.width))
    clamped_height = min(max(1, height), max(1, best.height))
    min_x = best.x
    max_x = best.x + best.width - clamped_width
    min_y = best.y
    max_y = best.y + best.height - min(min_titlebar_visible, clamped_height)
    clamped_x = min(max(x, min_x), max_x)
    clamped_y = min(max(y, min_y), max_y)
    return RectSpec(clamped_x, clamped_y, clamped_width, clamped_height)


def _int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
