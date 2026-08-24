"""Read KWin compositor cursor coordinates for fail-closed input checks."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def read_kwin_cursor_position() -> tuple[int, int]:
    """Read ``workspace.cursorPos`` through a one-shot read-only KWin script."""
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
        # C2: poll with a single growing journalctl read instead of one
        # subprocess spawn per 30ms tick (up to ~50 spawns over the old
        # 1.5s deadline). Each retry widens the window and the sleep grows
        # with it, so a typical read resolves in 1-3 journalctl calls.
        delay = 0.03
        deadline = time.monotonic() + 1.5
        lines_seen = 40
        while time.monotonic() < deadline:
            journal = subprocess.run(
                [
                    "journalctl",
                    "--user",
                    "-b",
                    "-n",
                    str(lines_seen),
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
            lines_seen = min(lines_seen * 2, 2000)
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
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
