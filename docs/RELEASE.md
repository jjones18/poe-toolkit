# POE Toolkit 1.8.0 release readiness

Milestone 8 adds locked Python/Node dependency metadata, a PyInstaller one-directory build, local Linux/Windows verification, frozen-package smoke verification, optional-feature degradation, and fresh setup documentation.

## Required evidence before tagging

- `uv sync --locked --extra full --extra test` succeeds on supported Linux and Windows Python versions.
- Python unit tests run with `QT_QPA_PLATFORM=offscreen`.
- Python `compileall` passes for `src`, `tests`, and `scripts`.
- Node `npm ci`, `npm test`, `npm run check`, and `npm audit --audit-level=high` pass in `trade_service`.
- `python scripts/check_version_consistency.py` reports `1.8.0`.
- `python scripts/check_packaging_assets.py` verifies the exact immutable PyInstaller data manifest.
- `python scripts/check_no_mutable_checkout_data.py` finds no runtime state or credential-like material.
- `python src/main.py --package-smoke` constructs and cleanly closes the source application offscreen.
- `uv build` produces a wheel/sdist whose installed wheel passes `poe-toolkit --package-smoke` with immutable dust and Trade Sniper assets present.
- PyInstaller builds `packaging/poe_toolkit.spec` on Linux and Windows.
- `python scripts/run_frozen_smoke.py dist` executes the generated binary’s `--package-smoke` path and inspects the distribution for forbidden mutable assets.
- Share only artifacts that passed the frozen smoke test locally.

## Mutable runtime guarantee

Runtime config, credentials, caches, logs, Brave profile state, and Node dependency installs are per-user data. Frozen and wheel distributions include immutable defaults, templates, dust data, and Trade Sniper source/lock assets, but never include the legacy `config/config.json`, any `user_config.json`, caches, Brave profile, or `node_modules`. Installed Trade Sniper assets are copied to the per-user data directory; its visible **Install** action runs deterministic `npm ci` there.

## Version source

`src/utils/__init__.py:APP_VERSION` is the application version source. `pyproject.toml` reads it dynamically; release checks validate README/docs and the Node service compatibility marker against it.

## Release commands

```bash
uv sync --locked --extra full --extra test --extra packaging
uv run --locked python -m unittest discover -s tests
uv run --locked python -m compileall -q src tests scripts
uv run --locked python scripts/check_version_consistency.py
uv run --locked python scripts/check_packaging_assets.py
uv run --locked python scripts/check_no_mutable_checkout_data.py
uv build
uv run --locked pyinstaller --noconfirm --clean packaging/poe_toolkit.spec
uv run --locked python scripts/run_frozen_smoke.py dist
(
  cd trade_service
  npm ci
  npm test
  npm run check
  npm audit --audit-level=high
)
```
