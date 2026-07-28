# POE Toolkit Modernization Roadmap

> **For Hermes:** Use test-driven development for every behavior change. Preserve unrelated dirty-tree work, avoid live Path of Exile/browser testing, and verify each milestone locally before committing.

**Goal:** Modernize POE Toolkit in a risk-first order while prioritizing the actively used Trade Sniper and application-wide settings/lifecycle behavior before repairing less-used individual tools.

**Architecture direction:** Application-wide services and shared settings should be owned by the main application, not disposable tool widgets. Background work should be cancellable and never block Qt's GUI thread. Mutable user data belongs in per-user config/cache/data directories, while the source checkout remains read-only.

**Tech stack:** Python 3, PyQt6, Node.js, Puppeteer/CDP, unittest/node:test.

---

## Final recommended order

1. **Milestone 1 — Trade Sniper and shared application behavior**
2. **Milestone 2 — Configuration, worker, and diagnostics foundations**
3. **Milestone 3 — Price/data correctness shared by valuation tools**
4. **Milestone 4 — League Vision repair**
5. **Milestone 5 — Kalguur Dust repair**
6. **Milestone 6 — Ultimatum repair**
7. **Milestone 7 — Overlay/calibration and dormant feature cleanup**
8. **Milestone 8 — Packaging, CI, accessibility, and release readiness**

This order intentionally defers tools that are not actively used. It first protects the currently used Trade Sniper and prevents shared Settings/Main Window behavior from corrupting or unexpectedly stopping it.

---

# Milestone 1 — Trade Sniper and shared application behavior

**Status:** Complete and locally verified for the v1.2.0 focused milestone.

**Verification record:** 30 Python tests, 14 Node tests, Python compilation, Node syntax checks, offscreen mode/lifecycle smoke, CRLF-aware whitespace validation, and staged credential/profile-path review all passed. No live Path of Exile page or running Trade Sniper process was used during verification.

**Deferred by design:** Milestones 2–8 remain backlog work. Individual League Vision, Kalguur, and Ultimatum repairs beyond the shared-settings boundary—as well as the unrelated runtime config and dust-cache working-tree changes—are not part of this milestone commit.

## 1.1 Replace broad orphan-process killing

**Problem:** `TradeService.start()` kills every process matching `node.*trade_monitor.js`, including another checkout or legitimate toolkit instance. SIGKILL can bypass browser-worker disarming.

**Files:**
- Modify: `src/services/trade_service.py`
- Test: `tests/test_trade_service.py`

**Tasks:**
- Add installation-scoped ownership/PID metadata.
- Refuse or safely recover only a stale owner for the same installation.
- Never kill a process solely because its command contains `trade_monitor.js`.
- Verify path/owner identity before any escalation.
- Preserve cooperative `__shutdown__` browser-worker cleanup.

**Acceptance:** Starting this installation cannot kill a monitor from another installation or unmanaged Node process.

## 1.2 Make TradeService application-owned

**Problem:** Mode changes rebuild disposable widgets; Trade Sniper cleanup currently stops a running monitor. Every widget also creates global signal/atexit side effects through a new `TradeService` instance.

**Files:**
- Modify: `src/ui/main_window.py`
- Modify: `src/tools/trade_sniper/tool.py`
- Modify: `src/services/trade_service.py`
- Test: new/extended offscreen main-window lifecycle tests

**Tasks:**
- Create one `TradeService` owned by the main application.
- Inject it into reconstructed Trade Sniper widgets.
- Widget cleanup disconnects UI/timers but does not stop the application service.
- Application close performs verified service shutdown.
- Reconstructed widgets display the existing service's actual state.
- Join output threads and close pipes after process exit.

**Acceptance:** Switching PoE 1/PoE 2 mode does not stop an active Trade Sniper, and only application exit/explicit Stop ends it.

## 1.3 Make Settings the sole owner of shared account/game/league values

**Problem:** Settings can save a new league and later-created/stale league-tool widgets can overwrite it during `MainWindow.save_config()`.

**Files:**
- Modify: `src/tools/settings_tool.py`
- Modify: `src/ui/main_window.py`
- Modify: `src/tools/league_tools/tool.py`
- Modify: `src/tools/league_tools/ultimatum/tool.py`
- Modify: `src/tools/league_tools/kalguur_dust/tool.py`
- Test: new shared-settings ownership tests

**Tasks:**
- Child tools stop persisting shared credentials/league copies.
- Settings writes account, session, active game, and per-game leagues.
- Settings save refreshes read-only dependent labels/views.
- Failed league refresh preserves last-known selections.
- League lists use cached/manual refresh rather than automatic private requests on every widget rebuild.

**Acceptance:** A value saved in Settings cannot be reverted by a stale hidden tool widget.

## 1.4 Verify DevTools readiness rather than raw port presence

**Problem:** Any listener on port 9222 is displayed as Brave Connected; Start ignores browser/trade-tab readiness.

**Files:**
- Modify: `src/tools/trade_sniper/tool.py`
- Test: `tests/test_trade_sniper_settings.py` or new readiness tests

**Tasks:**
- Query `/json/version` with a bounded timeout and validate CDP metadata.
- Query `/json/list` and identify compatible PoE 1/PoE 2 trade tabs.
- Distinguish browser unavailable, DevTools ready, trade tab found, and monitor ready.
- Keep network probes locally scoped to `127.0.0.1`.
- Do not enable Start on an unrelated listener.

**Acceptance:** An arbitrary TCP listener cannot appear as a compatible Brave/Chromium debug session.

## 1.5 Remove GUI-thread blocking operations

**Problem:** dependency probing, `npm install`, and service stop can block Qt for seconds or minutes.

**Files:**
- Modify: `src/tools/trade_sniper/tool.py`
- Modify: `src/services/trade_service.py`
- Test: offscreen worker/state tests

**Tasks:**
- Run dependency check, install, and explicit Stop through bounded worker jobs.
- Disable duplicate controls and show Checking/Installing/Stopping states.
- Add subprocess timeouts to dependency checks.
- Keep application-close shutdown verified even if it must block final exit.

**Acceptance:** Button-triggered install/stop/dependency checks do not block the GUI event loop.

## 1.6 Move Brave profile out of the repository

**Problem:** cookies, browser state, cache, and history live under `trade_service/brave-profile`.

**Files:**
- Modify: `src/tools/trade_sniper/tool.py`
- Modify: `trade_service/start_brave_debugging.bat`
- Test: profile path/migration tests
- Document: migration behavior

**Tasks:**
- Resolve an OS-standard per-user application-data location.
- Migrate the legacy profile only while no debug browser is using it.
- Preserve login state.
- Leave no browser profile requirement in the source checkout.

**Acceptance:** New launches use per-user app data and an existing legacy login is preserved through migration.

## 1.7 Milestone verification and release

- Run all Python unit tests offscreen.
- Run `npm test` and Node syntax checks.
- Run offscreen mode-switch smoke tests.
- Review diff for secrets, generated files, and unrelated changes.
- Update version/docs intentionally.
- Commit the complete focused milestone.
- Push and verify remote `master` matches the local commit.

---

# Milestone 2 — Shared configuration, workers, and diagnostics

**Status:** Sections 2.1 and 2.2 are complete in release 1.3.0, Section 2.3 in release 1.4.0, and Section 2.4 in release 1.5.0. Section 2.5 remains the next application-wide task.

**Verification:** 102 Python tests, 14 Node tests, Python compilation, installer/template syntax checks, and the isolated offscreen UI smoke passed before release 1.5.0.

## 2.1 Secure and relocate configuration

**Implementation:** Complete. The runtime now uses OS-standard per-user paths, migrates the ignored legacy file without overwriting an existing destination, enforces private Linux modes, and updates Windows/Linux installers to create the private destination directly.

- Move user config to an OS-standard per-user directory.
- Enforce mode `0600` on Linux and user-only ACLs on Windows.
- Keep credentials out of repository files and diagnostics exports.
- Preserve/migrate existing user configuration.

## 2.2 Atomic configuration writes and recovery

**Implementation:** Complete. The checked-in base is read-only at runtime; the complete mutable override is schema-versioned and atomically persisted with a last-known-good backup. Parse/save failures are visible, and unrecoverable configs block replacement.

- Write temporary file, flush/fsync, then atomic replace.
- Keep a last-known-good/timestamped backup.
- Surface parse/save failures in the UI.
- Never silently replace malformed config with defaults on exit.
- Add explicit config schema version and migrations.

## 2.3 Standard cancellable-worker framework

**Implementation:** Complete in release 1.4.0 for shared/application-owned
paths. `utils.workers` provides cooperative cancellation, interruptible waits,
structured progress/result/error/cancelled/finished signals, named duplicate
suppression, bounded HTTP/OCR/subprocess adapters, and verified pool shutdown.
Settings league refresh and Trade Sniper generic tasks use the framework;
reload and application close fail closed when cleanup cannot be verified.
Module-specific scanner migration remains intentionally deferred to those
module milestones. The currently unused `PriceService`/`NinjaPriceFetcher`
worker path remains deferred to Milestone 3, where its unbounded requests,
rate-limit waits, and cache semantics can be migrated together rather than
hidden behind a nominally cancellable wrapper.

- Cooperative cancellation token/event.
- Bounded HTTP and OCR operations.
- Interruptible rate-limit waits.
- Progress, completion, cancellation, and error signals.
- Verified shutdown before widgets are deleted.
- No GUI API calls from worker threads.

## 2.4 Central Diagnostics/Data Freshness page

**Implementation:** Complete in release 1.5.0. An always-available, redacted
Diagnostics page reports active game/league, credential presence, explicit
dependency readiness, shared runtime/worker state, Client.txt/zone state,
per-user directories, and legacy price/dust cache provenance and freshness.
Dependency and local DevTools probes run only on explicit request through the
shared cancellable-worker registry. Cache deletion is allowlisted and confirmed;
exports are recursively scrubbed of configured account/session values. Legacy
cache paths remain visible until their relocation in Section 2.5.

Display without exposing secrets:
- Active game and league.
- Credential configured/validation state.
- DevTools/Brave, Node/npm, and Tesseract readiness.
- Active services/workers and last error.
- Price/dust cache source, league, age, schema, and item count.
- Client.txt path and current zone-monitor state.
- Config/cache/log/profile directories.

Actions:
- Test dependencies.
- Refresh data.
- Open logs/data directories.
- Clear cache.
- Export redacted diagnostics.

## 2.5 Mutable data cleanup

- Move logs, caches, screenshots, and browser profiles out of the repository.
- Remove/ignore generated `debug_tab_capture_*.png` and runtime `dust_cache.json`.
- Make debug screenshots opt-in and automatically rotate/delete them.

---

# Milestone 3 — Price and data correctness

## 3.1 League-aware price cache

- Key cache by game, league, endpoint/source, and schema version.
- Invalidate in-memory fetchers when league changes.
- Store cache metadata and expose freshness.
- Guard cache read/write errors and continue with in-memory data.

## 3.2 Correct unknown-price handling

- Distinguish known, zero, and unknown prices.
- Never map unknown price to infinite efficiency.
- Exclude unknown prices by default.
- Add an optional `Include unknown-price items` setting.
- Render unknown values as `—`.

## 3.3 Centralize price fetching

- Either integrate the currently unused `PriceService` or remove it.
- Share one league-aware service rather than independent downloads per tool.
- Return explicit partial/failure status rather than caching silent empty results.

## 3.4 Dust-data provenance

- Prefer valid local cache before automatic external fallback where appropriate.
- Show source and timestamp.
- Clearly label bundled 2025 fallback data as estimated/stale.
- Validate source schema before accepting/caching data.

---

# Milestone 4 — League Vision

- Persist feature checkboxes immediately or with debounce.
- Apply changes live or label them `next scanner start`.
- Save map-device calibration immediately; do not claim saved before persistence.
- Move all Tesseract calls behind timeouts.
- Keep screen geometry and GUI operations on Qt's main thread.
- Validate malformed altar tier keys instead of crashing.
- Validate Tesseract before constructing the worker so warnings are not lost.
- Separate exact PoE 1 and PoE 2 window/process matching.
- Expose editors/import-export for dangerous map mods, altar rewards, expedition warnings, syndicate goals, threshold, and Tesseract path.
- Provide Low CPU/Balanced/Fast OCR profiles plus advanced settings.
- Add scanner cancellation and shutdown tests.

---

# Milestone 5 — Kalguur Dust

- Move dust/price downloads off the GUI thread.
- Add preparation/scan progress, Cancel, Retry, and rate-limit status.
- Stop and wait for tab/scan/OCR workers during cleanup.
- Add HTTP and Tesseract timeouts.
- Persist Min Dust/Chaos consistently.
- Use centralized league-aware prices and correct unknown-price behavior.
- Move OCR screenshots/cache/logs to per-user cache directories.
- Display dust-data and price-data provenance/freshness.
- Preserve selected stash tabs and useful scan presets.
- Add parser/filter/cache/worker tests.

---

# Milestone 6 — Ultimatum

- Stop and wait for tab/scan workers during cleanup.
- Add network timeouts and cancellable rate-limit handling.
- Use centralized league-aware prices.
- Make Settings the only owner of shared league/account fields.
- Add progress, cancellation, retry, and actionable errors.
- Clarify include/exclude override semantics in the filter UI.
- Add valuation/filter/worker tests.

---

# Milestone 7 — Overlay, calibration, and dormant features

## 7.1 Explicit stash calibration type

- Ask Standard or Quad instead of inferring from total width.
- Maintain separate Standard and Quad profiles.
- Show a full-grid preview before saving.
- Add deterministic calibration-math tests.

## 7.2 Overlay consistency

- Ensure Show Overlay controls highlight, debug, calibration, and alert layers consistently.
- Avoid an overlay remaining visible while the toggle says off.
- Handle multi-monitor screen geometry and window restoration safely.

## 7.3 Unique Tab workflow decision

README advertises a clipboard workflow, but the calibration values are not consumed and `pyperclip` is unused.

Choose one:
- Implement the complete manual-confirmation workflow around the documented API limitation, or
- Remove the claim, dependency, and dead calibration entries until implemented.

---

# Milestone 8 — Packaging, testing, accessibility, and release readiness

## 8.1 Test/CI foundation

- Commit current Python and Node regression tests.
- Add CI for Python tests, Node tests, syntax checks, and secret scanning.
- Cover config corruption/atomicity, worker cleanup, mode reload, cache league separation, calibration, installers, and version consistency.

## 8.2 Reproducible installation

- Add `pyproject.toml` and a Python lock strategy.
- Use virtual environments on Windows as well as Linux.
- Use `npm ci` when the lockfile exists.
- Pin/limit dependency versions intentionally.
- Verify signatures/hashes for downloaded installers or remove direct executable fallback.

## 8.3 Version/schema consistency

- Use one application version source.
- Separate application version from config schema and Node component version where necessary.
- Add explicit migrations and automated consistency checks.
- Correct README/version badge drift.

## 8.4 UX/accessibility

- Centralize styles in `src/ui/theme.py`.
- Add accessible names, keyboard shortcuts, visible focus states, and usable contrast.
- Remove fragile fixed-width assumptions for high DPI/larger fonts/localization.
- Keep saved windows visible across monitor-layout changes.
- Standardize immediate/debounced settings persistence and `Reset to defaults` behavior.

---

# Deferred/low-priority cleanup inventory

- Remove or integrate unused `PriceService`.
- Remove or consolidate legacy `OverlayWindow` alongside `OverlayManager`.
- Replace silent exception swallowing with structured degraded-capability reporting.
- Unify duplicate global and League Vision debug-mode settings.
- Refresh stale account labels when Settings changes.
- Label PoE1-only tools clearly when applicable.
- Make default league values fetched/validated rather than hardcoded to old leagues.
- Prefer exact game/process/window matching instead of broad `Path of Exile` substrings.

---

# Commit strategy

- **Commit A:** Existing Trade Sniper lifecycle/timing work plus Milestone 1 fixes and tests, after complete verification.
- **Commit B:** Configuration/worker/diagnostics foundations.
- **Commit C:** Shared price/data correctness.
- **Later commits:** One individual tool milestone each, keeping League Vision, Kalguur, and Ultimatum reviews separable.

Do not mix deferred individual-tool rewrites into Commit A merely because those files are already dirty. Review and stage the intended changes explicitly.
