from __future__ import annotations

import json
from pathlib import Path
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 test extra
    from importlib import import_module
    tomllib = import_module("tomli")

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

utils_text = (ROOT / "src" / "utils" / "__init__.py").read_text(encoding="utf-8")
match = re.search(r"APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", utils_text)
if not match:
    raise SystemExit("APP_VERSION is missing")
version = match.group(1)

project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
if "version" not in project["project"].get("dynamic", []):
    errors.append("pyproject version is not dynamic")
version_attr = project.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {}).get("attr")
if version_attr != "utils.APP_VERSION":
    errors.append("pyproject dynamic version source mismatch")

readme = (ROOT / "README.md").read_text(encoding="utf-8")
if f"Version-{version}-blue" not in readme:
    errors.append("README badge mismatch")
for rel in ("docs/RELEASE.md", "docs/WINDOWS_SETUP.md"):
    if version not in (ROOT / rel).read_text(encoding="utf-8"):
        errors.append(f"{rel} version mismatch")

package = json.loads((ROOT / "trade_service" / "package.json").read_text(encoding="utf-8"))
if package.get("poeToolkitVersion") != version:
    errors.append("trade service compatibility version mismatch")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"version consistency ok: {version}")
