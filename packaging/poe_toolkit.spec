# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent.resolve()
SRC = ROOT / "src"

# Only immutable defaults and runtime assets belong in the bundle. In particular,
# config/config.json, user_config.json, caches, browser profiles, and node_modules
# are mutable/user-specific and must never be collected.
datas = [
    (str(SRC / "utils" / "default_config.json"), "utils"),
    (str(ROOT / "config" / "user_config.template.json"), "config"),
    (str(ROOT / "data" / "poedust_cache.json"), "data"),
    (str(ROOT / "trade_service" / "trade_monitor.js"), "trade_service"),
    (str(ROOT / "trade_service" / "page_worker.js"), "trade_service"),
    (str(ROOT / "trade_service" / "package.json"), "trade_service"),
    (str(ROOT / "trade_service" / "package-lock.json"), "trade_service"),
    (str(ROOT / "trade_service" / "start_brave_debugging.bat"), "trade_service"),
]

hiddenimports = [
    "cv2",
    "mss",
    "numpy",
    "pynput",
    "pytesseract",
]

analysis = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests", "unittest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="POE Toolkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="POE Toolkit",
)
