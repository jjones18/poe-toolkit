from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def find_executable(dist: Path) -> Path:
    candidates = (
        dist / "POE Toolkit" / "POE Toolkit.exe",
        dist / "POE Toolkit" / "POE Toolkit",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Frozen POE Toolkit executable not found under {dist}")


def assert_no_mutable_assets(dist: Path) -> None:
    forbidden = {
        "brave-profile",
        "node_modules",
        "price_cache.json",
        "dust_cache.json",
        "user_config.json",
    }
    for path in dist.rglob("*"):
        if any(part in forbidden for part in path.parts):
            raise RuntimeError(f"Mutable runtime asset bundled: {path.relative_to(dist)}")
        if path.name == "config.json" and path.parent.name == "config":
            raise RuntimeError(f"Legacy mutable config bundled: {path.relative_to(dist)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", default="dist", type=Path)
    args = parser.parse_args()
    dist = args.dist.resolve()
    assert_no_mutable_assets(dist)
    executable = find_executable(dist)
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [str(executable), "--package-smoke"],
        cwd=executable.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"Frozen package smoke failed with exit code {result.returncode}")
    print(f"frozen package smoke ok: {executable}")


if __name__ == "__main__":
    main()
