#!/usr/bin/env python3
"""Fail-closed diagnostic input probe for an exact focused PoE window.

Coordinates are always window-local and tied to an explicit reference size.
The default action moves only. A click requires ``--confirm-one-click`` and
sends exactly one button press/release after all normal runtime guards pass.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from services.game_input_service import (  # noqa: E402
    GameInputService,
    GameInputUnavailable,
    KWinEisBackend,
    WindowRelativePoint,
    focused_game_window_snapshot,
    preferred_backend_name,
)


def _kwin_cursor_pos() -> tuple[int, int]:
    """Read compositor cursor coordinates through a one-shot KWin script."""
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus:
        raise RuntimeError("qdbus6/qdbus is required for native cursor verification")

    token = uuid.uuid4().hex
    marker = f"POE_TOOLKIT_CURSOR_{token}"
    plugin = f"poe-toolkit-cursor-{token}"
    script_path = Path(tempfile.gettempdir()) / f"{plugin}.js"
    script_path.write_text(
        "const p = workspace.cursorPos;\n"
        f'console.info("{marker} x=" + p.x + " y=" + p.y);\n',
        encoding="utf-8",
    )
    script_id = None
    try:
        loaded = subprocess.run(
            [
                qdbus,
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                str(script_path),
                plugin,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        script_id = loaded.stdout.strip()
        subprocess.run(
            [
                qdbus,
                "org.kde.KWin",
                f"/Scripting/Script{script_id}",
                "org.kde.kwin.Script.run",
            ],
            check=True,
            capture_output=True,
            timeout=2,
        )
        pattern = re.compile(rf"{re.escape(marker)} x=(-?\d+) y=(-?\d+)")
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            journal = subprocess.run(
                [
                    "journalctl",
                    "--user",
                    "-b",
                    "-n",
                    "120",
                    "--no-pager",
                    "-o",
                    "cat",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            match = pattern.search(journal.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
            time.sleep(0.03)
        raise RuntimeError("Timed out reading KWin compositor cursor position")
    finally:
        if script_id is not None:
            subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    f"/Scripting/Script{script_id}",
                    "org.kde.kwin.Script.stop",
                ],
                capture_output=True,
                timeout=2,
            )
            subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.unloadScript",
                    plugin,
                ],
                capture_output=True,
                timeout=2,
            )
        script_path.unlink(missing_ok=True)


def _input_service() -> GameInputService:
    if preferred_backend_name() == "kwin-eis":
        return GameInputService(
            backend=KWinEisBackend(cursor_reader=_kwin_cursor_pos)
        )
    return GameInputService()
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "move", "click"))
    parser.add_argument("--game", choices=("poe1", "poe2"), default="poe1")
    parser.add_argument("--x", type=int, help="Window-local target X")
    parser.add_argument("--y", type=int, help="Window-local target Y")
    parser.add_argument("--reference-width", type=int)
    parser.add_argument("--reference-height", type=int)
    parser.add_argument("--button", choices=("left", "right"), default="left")
    parser.add_argument(
        "--confirm-one-click",
        action="store_true",
        help="Required for click; confirms exactly one guarded click",
    )
    return parser


def _target(args: argparse.Namespace, parser: argparse.ArgumentParser) -> WindowRelativePoint:
    missing = [
        name
        for name in ("x", "y", "reference_width", "reference_height")
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(
            "move/click require --x, --y, --reference-width, and --reference-height"
        )
    try:
        return WindowRelativePoint(
            x=args.x,
            y=args.y,
            reference_width=args.reference_width,
            reference_height=args.reference_height,
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    service = _input_service()
    capability = service.capability()
    focused = focused_game_window_snapshot(args.game)

    report = {
        "action": args.action,
        "backend": asdict(capability),
        "focused_game_window": asdict(focused) if focused else None,
    }

    if args.action == "status":
        print(json.dumps(report, sort_keys=True))
        service.close()
        return 0

    target = _target(args, parser)
    report["target"] = asdict(target)
    if args.action == "click" and not args.confirm_one_click:
        parser.error("click requires --confirm-one-click")

    try:
        session = service.session(args.game)
        if args.action == "move":
            session.move_to(target)
        elif args.button == "left":
            session.left_click(target)
        else:
            session.right_click(target)
        report["result"] = "ok"
        if preferred_backend_name() == "kwin-eis":
            report["kwin_cursor"] = list(_kwin_cursor_pos())
        print(json.dumps(report, sort_keys=True))
        return 0
    except GameInputUnavailable as error:
        report["result"] = "blocked"
        report["error"] = str(error)
        print(json.dumps(report, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
