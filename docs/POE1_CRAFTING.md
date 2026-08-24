# PoE 1 Basic Crafting

## Scope

The Crafting tool is a generic currency-action surface with PoE 1 socket and link actions implemented first:

- Jeweller's Orb: craft until the item has at least the selected socket count.
- Orb of Fusing: craft until the largest linked socket group is at least the selected link count.
- PoE 2 displays the page for future expansion but disables calibration, hotkeys, and input controls.

The action registry, calibrated point roles, clipboard parser, shared game-input service, and Qt-timer controller are separated so more currencies and games can be added without renaming the module. See `GAME_INPUT_DEBUGGING.md` for the reusable input and preview contract.

## Currency-tab calibration

The initial layout definition is `poe1_currency_general_v1`. One two-click calibration records the outer yellow Currency-tab content bounds. Three normalized points are derived from those bounds:

- Jeweller's Orb
- Orb of Fusing
- Central crafting item

The confirmation overlay displays the bounds and labeled point markers before anything is saved. Each point can then be overridden with a one-click fine-tune action. Persisted bounds and overrides are game-window-local coordinates tied to the calibration window size; overrides are discarded whenever the outer bounds are recalibrated.

Calibration is stored per game under `calibration.currency_tab_profiles`. Mutable calibration and settings remain in the private per-user config, not the checkout.

## Normal and advanced controls

The default Crafting view keeps the controls needed for a safe run visible: action, target, Verification-only, attempt budget, compact layout/input/hotkey readiness, final status, and Stop Current Run.

Less-frequent controls are collapsed without changing their state:

- **Calibration & target setup** contains bounds calibration, point fine-tuning, and no-input target previews.
- **Advanced input settings** contains the measured settle delay, hotkey selectors, and full backend diagnostics.
- **Run details** contains the complete per-run message history; the latest result remains visible when this section is collapsed.

Verification-only intentionally resets on every application launch. Collapsing a section does not arm input, alter a setting, or weaken any focus, budget, currency-decrement, or emergency-stop gate.

## Run sequence

1. Use **Preview Targets — no input** and confirm every click-through marker before arming a run.
2. Crafting must remain the selected Toolkit page so its global hotkeys are armed.
3. Return to the exact PoE 1 window.
4. Press the configured Start hotkey (Numpad Plus by default).
5. The controller moves to the selected currency and uses Ctrl+C.
6. It validates the exact currency identity and reads the available stack count.
7. It moves to the crafting item, uses Ctrl+C, and parses the `Sockets:` line.
8. In Verification-only mode it stops here without a right click.
9. In crafting mode, every counted attempt reselects the verified currency and performs exactly one Shift+left-click on the verified item.
10. After every unsuccessful attempt it copies/parses the item and then requires the currency stack to have decreased by exactly one before another attempt is allowed.

Socket and link goals are at-least targets. A six-link therefore satisfies a five-link target. A link run is blocked unless the item already has at least as many sockets as the requested link target.

## Safety invariants

- Verification-only is enabled on every widget construction and is never persisted as disabled.
- Start and every delayed action require the exact PoE title and process identity.
- KDE Wayland uses KWin EIS/libei; XTest, pynput, xdotool, and ydotool are not used or accepted as fallbacks.
- Every input target is game-window-local, tied to a reference window size, and rejected after a resolution/geometry change.
- The exact focused game identity and geometry are revalidated after movement and before button/key events.
- KWin must report that every EIS pointer move converged to the requested compositor coordinate within tolerance.
- Calibrated points are probed through clipboard text before any currency is selected.
- KDE Wayland clipboard probes establish their unique sentinel through Klipper D-Bus and wait until Qt observes it before sending Ctrl+C. EIS key-step timing uses the measured 5 ms reliable value rather than a conservative arbitrary delay.
- Currency identity must match the selected action exactly.
- Missing, stale, or malformed clipboard data stops the run.
- Unlimited mode is still capped by the currency count copied during preflight.
- Optional attempt budgets are additionally capped by that currency count.
- A successful application clears the controller's transient currency-selected state. Escape cleanup is reserved for failures between currency selection and application, so normal budget/target completion does not close the stash.
- Numpad Minus and the in-page Stop action release injected modifiers.
- Delayed callbacks carry a per-run generation token, so timers from a stopped run cannot enter a later run.
- If a failure occurs after currency selection but before a confirmed application, Toolkit sends Escape only while PoE remains focused. If focus was lost, it sends no input to another application and explicitly warns the user to press Escape before clicking in PoE.
- Recalibrating outer bounds clears stale absolute point overrides.
- No OCR, network request, or POESESSID is used by the crafting loop.

## Verification status

Automated verification covers real clipboard fixtures, target semantics, currency identity, layout scaling and overrides, calibration persistence, unsupported PoE 2 gating, stale timer invalidation, held-currency cleanup, exact focus failure, and verification-only no-click behavior.

The live acceptance gate is intentionally non-destructive:

1. Open PoE 1 Currency tab and place a socketed item in the central crafting area.
2. Calibrate outer bounds and confirm all markers.
3. Keep Verification-only enabled.
4. Press Start from the game.
5. Confirm the log reports the expected currency stack and the item's socket/link state, with no currency spent.
6. Only after that pass, perform a deliberately small live crafting run.

Do not run desktop-input acceptance tests while the user is actively playing.
