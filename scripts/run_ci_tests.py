from __future__ import annotations

import os
from pathlib import Path
import sys
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


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if os.environ.get("GITHUB_ACTIONS") == "true":
        for kind, outcomes in (
            ("failure", result.failures),
            ("error", result.errors),
        ):
            for test, traceback in outcomes:
                title = _escape_command_property(f"unittest {kind}: {test}")
                details = _escape_command_data(traceback)
                print(f"::error title={title}::{details}", flush=True)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
