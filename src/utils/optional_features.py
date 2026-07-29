"""Optional dependency probes with actionable degraded-feature errors."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec


@dataclass(frozen=True)
class OptionalFeature:
    key: str
    label: str
    modules: tuple[str, ...]
    extra: str
    system_dependencies: tuple[str, ...] = ()

    @property
    def install_hint(self) -> str:
        parts = [f"Install the Python extra: pip install .[{self.extra}]"]
        if self.system_dependencies:
            parts.append("Also install: " + ", ".join(self.system_dependencies))
        return "; ".join(parts) + "."

FEATURES: dict[str, OptionalFeature] = {
    "ocr_capture": OptionalFeature("ocr_capture", "OCR and screen capture", ("cv2", "numpy", "pytesseract", "mss"), "capture", ("Tesseract OCR executable",)),
    "overlay_input": OptionalFeature("overlay_input", "Overlay click detection", ("pynput",), "overlay-input"),
    "win32_platform": OptionalFeature("win32_platform", "Windows window/process integration", ("win32gui", "win32process"), "platform"),
    "x11_platform": OptionalFeature("x11_platform", "Linux X11 window integration", ("Xlib",), "platform"),
}

class OptionalFeatureUnavailable(RuntimeError):
    def __init__(self, feature: OptionalFeature, missing: list[str]):
        self.feature = feature
        self.missing = tuple(missing)
        super().__init__(f"{feature.label} is unavailable; missing Python module(s): {', '.join(missing)}. {feature.install_hint}")

def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        # Test doubles and partially imported optional packages can have no spec.
        return False


def missing_modules(feature_key: str) -> list[str]:
    feature = FEATURES[feature_key]
    return [module for module in feature.modules if not _module_available(module)]

def is_feature_available(feature_key: str) -> bool:
    return not missing_modules(feature_key)

def require_feature(feature_key: str) -> None:
    missing = missing_modules(feature_key)
    if missing:
        raise OptionalFeatureUnavailable(FEATURES[feature_key], missing)

def import_optional(feature_key: str, module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        missing = missing_modules(feature_key) or [module_name]
        raise OptionalFeatureUnavailable(FEATURES[feature_key], missing) from exc

def feature_status() -> dict[str, dict[str, object]]:
    return {key: {"available": not (missing := missing_modules(key)), "missing": missing, "hint": feature.install_hint, "label": feature.label} for key, feature in FEATURES.items()}
