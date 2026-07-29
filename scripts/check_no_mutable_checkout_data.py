from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MUTABLE_PATHS = (
    "config/user_config.json",
    "src/config/user_config.json",
    "trade_service/brave-profile",
    "trade_service/node_modules",
    "price_cache.json",
    "dust_cache.json",
)
TEXT_SUFFIXES = {
    ".bat", ".cfg", ".ini", ".js", ".json", ".md", ".ps1", ".py",
    ".toml", ".txt", ".yaml", ".yml",
}
SENSITIVE_JSON_KEYS = {
    "api_key", "apikey", "authorization", "password", "poesessid",
    "private_key", "session_id", "token",
}
SAFE_PLACEHOLDERS = {"", "changeme", "example", "redacted", "[redacted]"}
SECRET_PATTERNS = (
    re.compile(r"POESESSID\s*=\s*[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"Authorization\s*:\s*(?:Bearer|Basic)\s+[A-Za-z0-9+/._=-]{16,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / entry.decode("utf-8") for entry in result.stdout.split(b"\0") if entry]


def _unsafe_json_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in SAFE_PLACEHOLDERS:
            return False
        if normalized.startswith("<") and normalized.endswith(">"):
            return False
        if normalized.startswith("your_"):
            return False
        return True
    return True


def find_sensitive_json(payload: object, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in SENSITIVE_JSON_KEYS and _unsafe_json_value(value):
                findings.append(path)
            findings.extend(find_sensitive_json(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(find_sensitive_json(value, f"{prefix}[{index}]"))
    return findings


def scan_file(path: Path) -> list[str]:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    if path.stat().st_size > 5_000_000:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    findings = ["credential-like text" for pattern in SECRET_PATTERNS if pattern.search(text)]
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return findings
        findings.extend(f"non-empty sensitive JSON key: {key}" for key in find_sensitive_json(payload))
    return findings


def main() -> None:
    for rel in MUTABLE_PATHS:
        if (ROOT / rel).exists():
            raise SystemExit(f"mutable runtime artifact present in checkout: {rel}")

    failures: list[str] = []
    for path in repository_files():
        for finding in scan_file(path):
            failures.append(f"{path.relative_to(ROOT)}: {finding}")
    if failures:
        raise SystemExit("possible secret material detected:\n" + "\n".join(sorted(failures)))
    print("mutable runtime/secret check ok")


if __name__ == "__main__":
    main()
