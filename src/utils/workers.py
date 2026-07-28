"""Shared cooperative background-worker primitives for the Qt application.

Worker operations receive a :class:`WorkerContext` and must interact with the
GUI only through its signals/callbacks. Cancellation is cooperative: bounded
external calls and ``context.sleep`` provide predictable cancellation points.
"""

from dataclasses import dataclass
import os
from numbers import Real
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QRunnable, QThreadPool, pyqtSignal


DEFAULT_HTTP_TIMEOUT = (5.0, 15.0)
DEFAULT_OCR_TIMEOUT = 15.0


class CancelledError(Exception):
    """Raised at a cooperative cancellation point."""


class CancellationToken:
    """Thread-safe cooperative cancellation state with interruptible waits."""

    def __init__(self):
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait until cancelled or timeout; return whether cancellation occurred."""
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancelledError("Operation cancelled")


@dataclass(frozen=True)
class WorkerFailure:
    """Safe, structured description of an operation failure."""

    exception_type: str
    message: str

    @classmethod
    def from_exception(cls, error: Exception) -> "WorkerFailure":
        return cls(type(error).__name__, str(error))


class WorkerSignals(QObject):
    """Signals emitted by :class:`CancellableWorker`."""

    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()
    finished = pyqtSignal()


class WorkerContext:
    """Operation-facing API for progress and cooperative cancellation."""

    def __init__(self, token: CancellationToken, progress_callback: Callable[[Any], None]):
        self.token = token
        self._progress_callback = progress_callback

    def report_progress(self, value: Any) -> None:
        self.token.raise_if_cancelled()
        self._progress_callback(value)

    def sleep(self, seconds: float) -> None:
        """Wait for ``seconds`` but wake immediately when cancelled."""
        if self.token.wait(max(0.0, seconds)):
            raise CancelledError("Operation cancelled")

    def raise_if_cancelled(self) -> None:
        self.token.raise_if_cancelled()


class CancellableWorker(QRunnable):
    """Run one operation in a Qt thread pool using cooperative cancellation."""

    def __init__(
        self,
        operation: Callable[[WorkerContext], Any],
        token: Optional[CancellationToken] = None,
    ):
        super().__init__()
        self.operation = operation
        self.token = token or CancellationToken()
        self.signals = WorkerSignals()
        # Python owns the runnable until its registry releases it. This avoids
        # wrappers disappearing while queued signals are still in flight.
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self.token.cancel()

    def run(self) -> None:
        context = WorkerContext(self.token, self.signals.progress.emit)
        try:
            context.raise_if_cancelled()
            result = self.operation(context)
            context.raise_if_cancelled()
            self.signals.result.emit(result)
        except CancelledError:
            self.signals.cancelled.emit()
        except Exception as error:
            self.signals.error.emit(WorkerFailure.from_exception(error))
        finally:
            self.signals.finished.emit()


class WorkerRegistry:
    """Own named workers in a dedicated pool and verify their shutdown."""

    def __init__(self, max_threads: int = 4):
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(1, max_threads))
        self._workers: dict[str, CancellableWorker] = {}
        self._closed = False

    @property
    def active_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._workers))

    def _guard(self, callback):
        if callback is None:
            return None

        def guarded(*args):
            if not self._closed:
                callback(*args)

        return guarded

    def start(
        self,
        name: str,
        operation: Callable[[WorkerContext], Any],
        *,
        on_progress=None,
        on_result=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
    ) -> bool:
        """Start one named task, rejecting closed registries and duplicates."""
        if self._closed or name in self._workers:
            return False

        worker = CancellableWorker(operation)
        callbacks = (
            (worker.signals.progress, on_progress),
            (worker.signals.result, on_result),
            (worker.signals.error, on_error),
            (worker.signals.cancelled, on_cancelled),
            (worker.signals.finished, on_finished),
        )
        for signal, callback in callbacks:
            guarded = self._guard(callback)
            if guarded is not None:
                signal.connect(guarded)
        worker.signals.finished.connect(
            lambda task_name=name, task=worker: self._finalize(task_name, task)
        )

        self._workers[name] = worker
        self._pool.start(worker)
        return True

    def _finalize(self, name: str, worker: CancellableWorker) -> None:
        if self._workers.get(name) is worker:
            self._workers.pop(name, None)

    def cancel(self, name: str) -> bool:
        worker = self._workers.get(name)
        if worker is None:
            return False
        worker.cancel()
        return True

    def cancel_all(self) -> None:
        for worker in tuple(self._workers.values()):
            worker.cancel()

    def close(self, timeout_ms: int = 5000) -> bool:
        """Cancel work and close only after shutdown is verified.

        A timeout rolls the registry back to open state because its owning widget
        is preserved by the UI and must remain functional for a later retry.
        """
        self._closed = True
        self.cancel_all()
        stopped = self._pool.waitForDone(max(0, timeout_ms))
        if stopped:
            for worker in tuple(self._workers.values()):
                for signal in (
                    worker.signals.progress,
                    worker.signals.result,
                    worker.signals.error,
                    worker.signals.cancelled,
                    worker.signals.finished,
                ):
                    try:
                        signal.disconnect()
                    except TypeError:
                        pass
            self._workers.clear()
        else:
            self._closed = False
        return stopped


def stop_legacy_qthread(thread, timeout_ms: int = 5000, stop=None) -> bool:
    """Request bounded cooperative shutdown for a legacy ``QThread``.

    The caller must preserve the owning widget when this returns ``False``;
    force-terminating a thread that may own network or Qt resources is unsafe.
    """
    if thread is None:
        return True
    try:
        if not thread.isRunning():
            return True
        if stop is not None:
            stop()
        request_interruption = getattr(thread, "requestInterruption", None)
        if callable(request_interruption):
            request_interruption()
        return bool(thread.wait(timeout_ms))
    except (RuntimeError, TypeError):
        return False


def disconnect_qt_signals(sender, signal_names) -> None:
    """Disconnect known signals, including callbacks already queued by Qt."""
    for signal_name in signal_names:
        signal = getattr(sender, signal_name, None)
        if signal is None or not hasattr(signal, "disconnect"):
            continue
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            # Deleted senders and signals with no connections are already safe.
            pass


def discard_queued_meta_calls(receiver) -> None:
    """Discard queued signal/slot callbacks for a verified-cleanup receiver."""
    try:
        QCoreApplication.removePostedEvents(receiver, QEvent.Type.MetaCall)
    except (RuntimeError, TypeError):
        pass


def _require_positive_timeout(timeout, *, allow_pair: bool) -> None:
    values = timeout if allow_pair and isinstance(timeout, tuple) else (timeout,)
    if allow_pair and isinstance(timeout, tuple) and len(timeout) != 2:
        raise ValueError("Timeout pair must contain connect and read values")
    if any(isinstance(value, bool) or not isinstance(value, Real) or value <= 0 for value in values):
        raise ValueError("Timeout values must be positive and bounded")


def bounded_http_request(
    session,
    method: str,
    url: str,
    *,
    token: Optional[CancellationToken] = None,
    timeout=DEFAULT_HTTP_TIMEOUT,
    **kwargs,
):
    """Perform an HTTP request with a mandatory connect/read timeout."""
    _require_positive_timeout(timeout, allow_pair=True)
    token = token or CancellationToken()
    token.raise_if_cancelled()
    response = session.request(method, url, timeout=timeout, **kwargs)
    token.raise_if_cancelled()
    return response


def _stop_process(process: subprocess.Popen, grace_seconds: float = 1.0):
    """Terminate a child process group and return its final captured output."""
    if process.poll() is None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            elif os.name == "nt":
                stopped = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=grace_seconds,
                    check=False,
                    shell=False,
                )
                if stopped.returncode != 0:
                    process.terminate()
            else:
                process.terminate()
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
        return process.communicate()


def run_cancellable_process(
    command,
    *,
    token: Optional[CancellationToken] = None,
    timeout: float,
    poll_interval: float = 0.1,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a subprocess with a deadline and cooperative process-group cancellation."""
    _require_positive_timeout(timeout, allow_pair=False)
    token = token or CancellationToken()
    token.raise_if_cancelled()

    capture_output = kwargs.pop("capture_output", False)
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout/stderr may not be used with capture_output")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        process_group_flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | process_group_flag

    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + timeout
    interval = max(0.001, poll_interval)
    while True:
        if token.is_cancelled:
            _stop_process(process)
            raise CancelledError("Operation cancelled")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stdout, stderr = _stop_process(process)
            raise subprocess.TimeoutExpired(
                command,
                timeout,
                output=stdout,
                stderr=stderr,
            )
        try:
            stdout, stderr = process.communicate(timeout=min(interval, remaining))
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired:
            continue


def bounded_ocr_call(
    ocr: Callable[..., Any],
    image,
    *,
    token: Optional[CancellationToken] = None,
    timeout: float = DEFAULT_OCR_TIMEOUT,
    **kwargs,
):
    """Call a pytesseract-compatible OCR function with its timeout argument."""
    _require_positive_timeout(timeout, allow_pair=False)
    token = token or CancellationToken()
    token.raise_if_cancelled()
    result = ocr(image, timeout=timeout, **kwargs)
    token.raise_if_cancelled()
    return result
