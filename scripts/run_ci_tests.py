from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _escape_command_data(value: object) -> str:
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _escape_command_property(value: object) -> str:
    return (
        _escape_command_data(value)
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _emit_error(title: str, details: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    safe_title = _escape_command_property(title)
    safe_details = _escape_command_data(details)
    print(f"::error title={safe_title}::{safe_details}", flush=True)


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    except Exception:
        details = traceback.format_exc()
        traceback.print_exc()
        _emit_error("unittest discovery error", details)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    for kind, outcomes in (
        ("failure", result.failures),
        ("error", result.errors),
    ):
        for test, details in outcomes:
            _emit_error(f"unittest {kind}: {test}", details)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
