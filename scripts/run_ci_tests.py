from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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


def _run_suite() -> int:
    faulthandler.enable(all_threads=True)
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


def _run_supervised() -> int:
    output_path = Path(
        os.environ.get("RUNNER_TEMP", tempfile.gettempdir())
    ) / "poe-toolkit-test-output.log"
    with output_path.open("w", encoding="utf-8") as output:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child"],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    combined = output_path.read_text(encoding="utf-8", errors="replace")
    sys.stdout.write(combined)
    sys.stdout.flush()
    if completed.returncode:
        _emit_error(
            "unittest subprocess failure",
            f"The unittest subprocess exited with code {completed.returncode}.",
        )
        _emit_error(
            "unittest subprocess output tail",
            combined[-2_000:] or "The unittest subprocess produced no output.",
        )
    return completed.returncode


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") == "true" and "--child" not in sys.argv[1:]:
        return _run_supervised()
    return _run_suite()


if __name__ == "__main__":
    raise SystemExit(main())
