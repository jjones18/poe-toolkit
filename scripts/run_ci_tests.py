from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_RESULT_PREFIX = "__POE_TOOLKIT_MODULE_RESULT__="


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
    return _run_loaded_suite(suite)


def _run_named_module(module_name: str) -> int:
    faulthandler.enable(all_threads=True)
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromName(module_name)
    return _run_loaded_suite(suite)


def _run_loaded_suite(suite: unittest.TestSuite) -> int:
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
    script = str(Path(__file__).resolve())
    if os.name == "nt":
        commands = [
            [sys.executable, script, "--child-module", f"tests.{path.stem}"]
            for path in sorted((ROOT / "tests").glob("test_*.py"))
        ]
    else:
        commands = [[sys.executable, script, "--child"]]

    returncode = 0
    failed_command = None
    with output_path.open("w", encoding="utf-8") as output:
        for command in commands:
            if "--child-module" in command:
                heading = f"\n=== {command[-1]} ===\n"
                output.write(heading)
                output.flush()
                sys.stdout.write(heading)
                sys.stdout.flush()
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "POE_TOOLKIT_MODULE_SUPERVISED": "1"},
            )
            assert process.stdout is not None
            declared_result = None
            for line in process.stdout:
                output.write(line)
                output.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
                if line.startswith(MODULE_RESULT_PREFIX):
                    declared_result = int(line.removeprefix(MODULE_RESULT_PREFIX))
                    if os.name == "nt":
                        try:
                            process.terminate()
                        except OSError:
                            pass
                        break
            if declared_result is not None:
                process.stdout.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                returncode = declared_result
            else:
                returncode = process.wait()
            if returncode:
                failed_command = command
                break
    combined = output_path.read_text(encoding="utf-8", errors="replace")
    if returncode:
        failed_target = failed_command[-1] if failed_command else "test suite"
        _emit_error(
            "unittest subprocess failure",
            f"{failed_target} exited with code {returncode}.",
        )
        _emit_error(
            "unittest subprocess output tail",
            combined[-2_000:] or "The unittest subprocess produced no output.",
        )
    return returncode


def main() -> int:
    if "--child-module" in sys.argv[1:]:
        index = sys.argv.index("--child-module")
        try:
            module_name = sys.argv[index + 1]
        except IndexError:
            print("--child-module requires a module name", file=sys.stderr)
            return 2
        result = _run_named_module(module_name)
        if os.name == "nt":
            print(f"{MODULE_RESULT_PREFIX}{result}", flush=True)
            if os.environ.get("POE_TOOLKIT_MODULE_SUPERVISED") == "1":
                while True:
                    time.sleep(3600)
        return result
    if "--child" in sys.argv[1:]:
        return _run_suite()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return _run_supervised()
    return _run_suite()


if __name__ == "__main__":
    raise SystemExit(main())
