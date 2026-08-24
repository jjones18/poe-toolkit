# Safe Game Input and Target Preview

## Purpose

POE Toolkit centralizes synthetic input in `src/services/game_input_service.py`. Tool modules must not instantiate `pynput`, XTest, `xdotool`, or `ydotool` directly.

This rule is especially important on KDE Plasma Wayland with PoE running through Proton/XWayland. On the current mixed-monitor layout, XTest and uinput coordinates can diverge from KWin's compositor coordinates and from the coordinates PoE uses for hit-testing.

## Backends

- KDE Wayland: `KWinEisBackend` and `KWinEisClient` use KWin's `org.kde.KWin.EIS.RemoteDesktop` interface plus libei.
- Windows and Linux X11: `PynputBackend` remains the platform fallback.
- KDE Wayland never falls back to pynput, XTest, xdotool, or ydotool. Missing DBus/libei support is an actionable, fail-closed error.

KWin EIS input is absolute in compositor desktop coordinates. The low-level client validates every target against the absolute-pointer regions advertised by libei before sending it. It negotiates KWin's complete capability set because current KWin versions do not advertise the keyboard device for a narrower request; Toolkit exposes only absolute pointer, button, and keyboard operations.

## Window identity and coordinate contract

All module targets use `WindowRelativePoint(x, y, reference_width, reference_height)`:

1. Calibration records points relative to the exact game window and stores the window size used during calibration.
2. Before input, `focused_game_window_snapshot()` requires the exact title, allowed process name, PID, and positive geometry for the requested game.
3. A target is rejected if the current window size differs from its reference size or if it resolves outside the window.
4. The service moves through the selected platform backend.
5. The exact focused window identity and geometry are checked again after movement and immediately before a button/key event.
6. On KWin, production input and the diagnostic probe both require one-shot `workspace.cursorPos` feedback proving the EIS move converged within tolerance.
7. Input-service shutdown releases held buttons/modifiers and disconnects EIS.

Recalibrate after changing game resolution, UI scale, display arrangement, or borderless/windowed mode. The service deliberately does not guess a scale transformation for destructive input.

## Target previews

`TargetPreviewOverlay` is the non-destructive first acceptance gate. It:

- renders labeled crosshair-circle markers in game-window-local space;
- injects no mouse or keyboard input;
- is permanently click-through;
- does not accept focus;
- uses an X11 override-redirect hint so it remains above the Proton/XWayland game under KWin;
- clears when the tool is deactivated or the preview is explicitly cleared.

Modules should expose preview before move-only diagnostics, and move-only diagnostics before clicks.

## Agent/debug probe

`scripts/game_input_probe.py` provides a reusable fail-closed diagnostic path. Coordinates are window-local and always include the expected reference size.

Inspect capability and the exact focused window:

```bash
uv run --extra full python scripts/game_input_probe.py status --game poe1
```

Move without clicking:

```bash
uv run --extra full python scripts/game_input_probe.py move \
  --game poe1 --x 1720 --y 720 \
  --reference-width 3440 --reference-height 1440
```

Send exactly one guarded left click:

```bash
uv run --extra full python scripts/game_input_probe.py click \
  --game poe1 --x 1720 --y 720 \
  --reference-width 3440 --reference-height 1440 \
  --button left --confirm-one-click
```

On KWin, both normal Toolkit input and the debug probe perform a synchronous compositor-native cursor check using a one-shot read-only KWin script (`workspace.cursorPos`). The temporary script has a unique name, is stopped/unloaded, and is deleted after every read. A click or key event is blocked unless KWin reports that the EIS move converged within tolerance.

Do not run move/click acceptance while the user is actively moving the mouse or playing. Physical cursor movement during the verification interval causes a fail-closed rejection.

## New-module checklist

1. Define semantic target roles in the module.
2. Calibrate and persist window-local coordinates plus reference width/height.
3. Render all resolved targets through `OverlayManager.enable_target_preview()`.
4. Add a verification-only workflow that performs no click.
5. Obtain a `GuardedGameInput` session from the application-owned `GameInputService`; never construct a tool-local input backend.
6. Revalidate clipboard/game state after every action when the module can change game data.
7. Provide module stop and global emergency-stop paths.
8. Clear previews and release input during deactivate, cleanup, mode change, and application close.
9. Unit-test backend selection, unavailable capabilities, out-of-window targets, reference-size mismatch, focus/identity changes, stale callbacks, and zero-click verification.
10. Perform live acceptance in this order: preview, move-only, one harmless click, verification-only module run, bounded real run.
