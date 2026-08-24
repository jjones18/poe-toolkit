"""Qt-timer crafting state machine with clipboard and foreground safety gates."""

import os
import shutil
import subprocess
import sys
import time
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from utils import platform_utils
from services.game_input_service import GameInputService, GameInputUnavailable
from .models import CraftingMode, CraftingRunResult
from .parser import ClipboardParseError, goal_is_met, parse_poe1_currency_stack, parse_poe1_socket_state


CURRENCY_BY_MODE = {
    CraftingMode.SOCKETS: ("jewellers_orb", "Jeweller's Orb"),
    CraftingMode.LINKS: ("orb_of_fusing", "Orb of Fusing"),
}


class CraftingController(QObject):
    status_changed = pyqtSignal(str)
    running_changed = pyqtSignal(bool)
    completed = pyqtSignal(object)

    def __init__(self, game_id="poe1", input_factory=None, parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self._owned_input_service = None
        if input_factory is None:
            self._owned_input_service = GameInputService()
            input_factory = lambda: self._owned_input_service.session(self.game_id)
        self.input_factory = input_factory
        self.input = None
        self.running = False
        self.goal = None
        self.points = {}
        self.attempts = 0
        self.currency_count = 0
        self.apply_delay_ms = 80
        self.clipboard_timeout_ms = 700
        self._clipboard_deadline = 0.0
        self._clipboard_sentinel = ""
        self._clipboard_callback = None
        self._pending_copy_point = None
        self._sentinel_deadline = 0.0
        self._run_generation = 0
        self._currency_selected = False

    def _schedule(self, delay_ms, callback):
        """Run a delayed callback only for the currently active run."""
        generation = self._run_generation

        def guarded_callback():
            if self.running and self._run_generation == generation:
                callback()

        QTimer.singleShot(int(delay_ms), guarded_callback)

    def _is_poe_focused(self) -> bool:
        try:
            identity = platform_utils.get_foreground_window_identity()
            return (
                platform_utils.is_exact_poe_window_title(identity.get("title", ""), self.game_id)
                and platform_utils.is_exact_poe_process_name(identity.get("process_name", ""), self.game_id)
            )
        except Exception:
            return False

    def start(self, goal, points, *, apply_delay_ms=80, clipboard_timeout_ms=700) -> bool:
        if self.running:
            self.status_changed.emit("A crafting run is already active")
            return False
        if self.game_id != "poe1":
            self.status_changed.emit("Basic socket/link crafting currently supports PoE 1 only")
            return False
        if not self._is_poe_focused():
            self.status_changed.emit("Start blocked: the exact Path of Exile 1 window is not focused")
            return False
        try:
            self.input = self.input_factory()
        except GameInputUnavailable as error:
            self.status_changed.emit(str(error))
            return False
        self.goal = goal
        self.points = dict(points)
        self.apply_delay_ms = max(30, int(apply_delay_ms))
        self.clipboard_timeout_ms = max(200, int(clipboard_timeout_ms))
        self.attempts = 0
        self.currency_count = 0
        self._currency_selected = False
        self._pending_copy_point = None
        self._run_generation += 1
        self.running = True
        self.running_changed.emit(True)
        role, currency_name = CURRENCY_BY_MODE[goal.mode]
        self.status_changed.emit(f"Preflight: reading {currency_name}")
        self._copy_at(self.points[role], lambda text: self._on_currency_copied(text, currency_name))
        return True

    def stop(self, reason="Stopped by user"):
        if not self.running:
            return False
        self._finish(False, reason)
        return True

    def _ensure_active(self) -> bool:
        if not self.running:
            return False
        if not self._is_poe_focused():
            self._finish(False, "Stopped: Path of Exile 1 lost focus")
            return False
        return True

    def _copy_at(self, point, callback):
        if not self._ensure_active():
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._finish(False, "Clipboard is unavailable")
            return
        self._clipboard_sentinel = f"__POE_TOOLKIT_CRAFTING_{uuid.uuid4()}__"
        self._clipboard_callback = callback
        self._pending_copy_point = point
        try:
            self._publish_clipboard_sentinel(clipboard)
        except Exception as error:
            self._finish(False, f"Could not prepare clipboard probe: {error}")
            return
        self._sentinel_deadline = time.monotonic() + 0.5
        self._schedule(5, self._await_clipboard_sentinel)

    def _publish_clipboard_sentinel(self, clipboard):
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        kde_wayland = (
            sys.platform.startswith("linux")
            and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            and ("KDE" in desktop or bool(os.environ.get("KDE_FULL_SESSION")))
        )
        if not kde_wayland:
            clipboard.setText(self._clipboard_sentinel)
            return
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if not qdbus:
            raise RuntimeError(
                "qdbus is required for reliable KDE Wayland clipboard probes"
            )
        subprocess.run(
            [
                qdbus,
                "org.kde.klipper",
                "/klipper",
                "org.kde.klipper.klipper.setClipboardContents",
                self._clipboard_sentinel,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )

    def _await_clipboard_sentinel(self):
        if not self.running:
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._finish(False, "Clipboard is unavailable")
            return
        if clipboard.text() != self._clipboard_sentinel:
            if time.monotonic() >= self._sentinel_deadline:
                self._finish(
                    False,
                    "Clipboard probe sentinel could not be established",
                )
                return
            self._schedule(5, self._await_clipboard_sentinel)
            return
        point, self._pending_copy_point = self._pending_copy_point, None
        try:
            self.input.copy_at(point)
        except Exception as error:
            self._finish(False, f"Input failed: {error}")
            return
        self._clipboard_deadline = (
            time.monotonic() + self.clipboard_timeout_ms / 1000.0
        )
        self._schedule(20, self._poll_clipboard)

    def _poll_clipboard(self):
        if not self.running:
            return
        text = QApplication.clipboard().text()
        if text and text != self._clipboard_sentinel:
            callback, self._clipboard_callback = self._clipboard_callback, None
            callback(text)
            return
        if time.monotonic() >= self._clipboard_deadline:
            self._finish(False, "Clipboard probe timed out; check the calibrated point and Currency tab")
            return
        self._schedule(20, self._poll_clipboard)

    def _on_currency_copied(self, text, expected_name):
        try:
            currency = parse_poe1_currency_stack(text, expected_name)
        except ClipboardParseError as error:
            self._finish(False, f"Currency preflight failed: {error}")
            return
        self.currency_count = currency.stack_count
        self.status_changed.emit(f"Verified {currency.name}: {currency.stack_count} available; reading item")
        self._copy_at(self.points["crafting_item"], self._on_item_preflight)

    def _on_item_preflight(self, text):
        try:
            state = parse_poe1_socket_state(text)
        except ClipboardParseError as error:
            self._finish(False, f"Item preflight failed: {error}")
            return
        if self.goal.mode is CraftingMode.LINKS and state.socket_count < self.goal.target:
            self._finish(
                False,
                f"Link target {self.goal.target} requires at least {self.goal.target} sockets; item has {state.socket_count}",
                state,
            )
            return
        self.status_changed.emit(
            f"Verified item: {state.socket_count} sockets, largest link {state.max_link_group}"
        )
        if self.goal.verify_only:
            self._finish(True, "Layout verified without spending currency", state)
        elif goal_is_met(state, self.goal.mode, self.goal.target):
            self._finish(True, "Target was already met; no currency spent", state)
        else:
            self._schedule(40, self._start_crafting)

    def _attempt_limit(self) -> int:
        if self.goal.max_attempts > 0:
            return min(self.currency_count, self.goal.max_attempts)
        return self.currency_count

    def _start_crafting(self):
        if not self._ensure_active():
            return
        _role, currency_name = CURRENCY_BY_MODE[self.goal.mode]
        self.status_changed.emit(f"Crafting with {currency_name}…")
        self._schedule(60, self._apply_once)

    def _apply_once(self):
        if not self._ensure_active():
            return
        if self.attempts >= self._attempt_limit():
            reason = "Attempt budget reached" if self.goal.max_attempts > 0 else "Available currency exhausted"
            self._finish(False, reason)
            return
        role, currency_name = CURRENCY_BY_MODE[self.goal.mode]
        try:
            self.input.right_click(self.points[role])
            self._currency_selected = True
            self.input.shift_left_click(self.points["crafting_item"])
            # PoE consumes one application and clears this transient selection
            # when the Shift+click sequence releases Shift. The next counted
            # attempt must explicitly reselect the currency.
            self._currency_selected = False
        except Exception as error:
            self._finish(False, f"Crafting with {currency_name} failed: {error}")
            return
        self.attempts += 1
        self._schedule(
            self.apply_delay_ms,
            lambda: self._copy_at(self.points["crafting_item"], self._on_item_after_apply),
        )

    def _on_item_after_apply(self, text):
        try:
            state = parse_poe1_socket_state(text)
        except ClipboardParseError as error:
            self._finish(False, f"Stopped after {self.attempts} attempt(s): {error}")
            return
        self.status_changed.emit(
            f"Attempt {self.attempts}: {state.socket_count} sockets, largest link {state.max_link_group}"
        )
        if goal_is_met(state, self.goal.mode, self.goal.target):
            self._finish(True, f"Target reached after {self.attempts} attempt(s)", state)
            return
        expected_remaining = self.currency_count - self.attempts
        if expected_remaining <= 0:
            self._finish(False, "Available currency exhausted", state)
            return
        role, currency_name = CURRENCY_BY_MODE[self.goal.mode]
        self._copy_at(
            self.points[role],
            lambda currency_text: self._on_currency_after_apply(
                currency_text,
                currency_name,
                expected_remaining,
                state,
            ),
        )

    def _on_currency_after_apply(
        self,
        text,
        expected_name,
        expected_remaining,
        state,
    ):
        try:
            currency = parse_poe1_currency_stack(text, expected_name)
        except ClipboardParseError as error:
            self._finish(
                False,
                f"Could not verify currency use after attempt {self.attempts}: {error}",
                state,
            )
            return
        if currency.stack_count != expected_remaining:
            self._finish(
                False,
                "Currency stack did not decrease as expected after "
                f"attempt {self.attempts}: expected {expected_remaining}, "
                f"found {currency.stack_count}",
                state,
            )
            return
        if self.attempts >= self._attempt_limit():
            self._finish(
                False,
                f"Attempt budget reached after {self.attempts} confirmed application(s)",
                state,
            )
            return
        self._schedule(self.apply_delay_ms, self._apply_once)

    def _finish(self, success, reason, state=None):
        if not self.running:
            return
        self.running = False
        self._run_generation += 1
        if self._currency_selected:
            if self._is_poe_focused() and self.input is not None:
                try:
                    self.input.cancel_selection()
                    self._currency_selected = False
                except Exception as error:
                    reason = f"{reason}; could not clear held currency: {error}"
            else:
                reason = (
                    f"{reason}; currency may remain selected in PoE — "
                    "press Escape before clicking"
                )
        if self.input is not None:
            try:
                self.input.release_all()
            except Exception:
                pass
        self._clipboard_callback = None
        self._pending_copy_point = None
        result = CraftingRunResult(bool(success), self.attempts, str(reason), state)
        self.status_changed.emit(reason)
        self.running_changed.emit(False)
        self.completed.emit(result)

    def close(self):
        self.stop("Stopped because Crafting input is closing")
        if self._owned_input_service is not None:
            return self._owned_input_service.close()
        return True
