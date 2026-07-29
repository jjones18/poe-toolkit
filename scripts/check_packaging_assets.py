from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "poe_toolkit.spec"
EXPECTED_ASSETS = {
    "src/utils/default_config.json",
    "config/user_config.template.json",
    "data/poedust_cache.json",
    "trade_service/start_brave_debugging.bat",
    "trade_service/package-lock.json",
    "trade_service/package.json",
    "trade_service/page_worker.js",
    "trade_service/trade_monitor.js",
}
FORBIDDEN_PARTS = {
    "brave-profile",
    "config.json",  # legacy mutable config/config.json
    "node_modules",
    "price_cache.json",
    "dust_cache.json",
    "user_config.json",
}


def _string_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _string_parts(node.left) + _string_parts(node.right)
    if isinstance(node, ast.Call) and node.args:
        return _string_parts(node.args[0])
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if node.id == "SRC":
            return ["src"]
        if node.id == "ROOT":
            return []
        raise ValueError(f"Unsupported PyInstaller path root: {node.id}")
    raise ValueError(f"Unsupported PyInstaller path expression: {ast.dump(node)}")


def bundled_sources(spec_text: str) -> set[str]:
    tree = ast.parse(spec_text, filename=str(SPEC_PATH))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "datas" for target in node.targets
        ):
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                raise ValueError("PyInstaller datas must be a literal list or tuple")
            sources: set[str] = set()
            for item in node.value.elts:
                if not isinstance(item, ast.Tuple) or not item.elts:
                    raise ValueError("Each PyInstaller data entry must be a tuple")
                parts = [part for part in _string_parts(item.elts[0]) if part not in {"."}]
                if not parts:
                    raise ValueError("Unable to inspect a PyInstaller data source")
                sources.add("/".join(parts))
            return sources
    raise ValueError("PyInstaller spec does not define datas")


def main() -> None:
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    sources = bundled_sources(spec_text)
    if sources != EXPECTED_ASSETS:
        missing = sorted(EXPECTED_ASSETS - sources)
        unexpected = sorted(sources - EXPECTED_ASSETS)
        raise SystemExit(f"packaging asset mismatch; missing={missing}, unexpected={unexpected}")

    for rel in sorted(EXPECTED_ASSETS):
        if not (ROOT / rel).is_file():
            raise SystemExit(f"missing packaging asset: {rel}")
    for source in sources:
        if source == "config/config.json" or any(
            part in source.split("/") for part in FORBIDDEN_PARTS
        ):
            raise SystemExit(f"mutable asset included in package: {source}")
    print("packaging assets ok")


if __name__ == "__main__":
    main()
