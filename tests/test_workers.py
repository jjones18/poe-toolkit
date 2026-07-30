import os
import sys
import threading
import time
import unittest
import subprocess
from unittest.mock import Mock
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from utils.workers import (
    CancelledError,
    CancellationToken,
    CancellableWorker,
    WorkerRegistry,
    bounded_http_request,
    bounded_ocr_call,
    run_cancellable_process,
    stop_legacy_qthread,
)
worker_utils = sys.modules["utils.workers"]


class LegacyQThreadShutdownTests(unittest.TestCase):
    def test_running_thread_gets_custom_stop_interruption_and_bounded_wait(self):
        thread = Mock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        custom_stop = Mock()

        stopped = stop_legacy_qthread(thread, timeout_ms=123, stop=custom_stop)

        self.assertFalse(stopped)
        custom_stop.assert_called_once_with()
        thread.requestInterruption.assert_called_once_with()
        thread.wait.assert_called_once_with(123)

    def test_already_stopped_thread_needs_no_shutdown_calls(self):
        thread = Mock()
        thread.isRunning.return_value = False

        self.assertTrue(stop_legacy_qthread(thread))

        thread.requestInterruption.assert_not_called()
        thread.wait.assert_not_called()


class CancellationTokenTests(unittest.TestCase):
    def test_wait_is_interrupted_by_cancellation(self):
        token = CancellationToken()
        timer = threading.Timer(0.02, token.cancel)
        timer.start()
        started = time.monotonic()
        try:
            self.assertTrue(token.wait(1.0))
        finally:
            timer.cancel()

        self.assertLess(time.monotonic() - started, 0.5)
        with self.assertRaises(CancelledError):
            token.raise_if_cancelled()

    def test_wait_reports_timeout_without_cancellation(self):
        token = CancellationToken()

        self.assertFalse(token.wait(0.001))
        self.assertFalse(token.is_cancelled)


class CancellableWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_success_emits_progress_result_and_finished(self):
        events = []

        def operation(context):
            context.report_progress({"completed": 1, "total": 2})
            return {"ok": True}

        worker = CancellableWorker(operation)
        worker.signals.progress.connect(lambda value: events.append(("progress", value)))
        worker.signals.result.connect(lambda value: events.append(("result", value)))
        worker.signals.cancelled.connect(lambda: events.append(("cancelled", None)))
        worker.signals.error.connect(lambda value: events.append(("error", value)))
        worker.signals.finished.connect(lambda: events.append(("finished", None)))

        worker.run()

        self.assertEqual(
            events,
            [
                ("progress", {"completed": 1, "total": 2}),
                ("result", {"ok": True}),
                ("finished", None),
            ],
        )

    def test_error_is_structured_and_finished_still_emits(self):
        errors = []
        finished = []

        def operation(_context):
            raise ValueError("simulated failure")

        worker = CancellableWorker(operation)
        worker.signals.error.connect(errors.append)
        worker.signals.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].exception_type, "ValueError")
        self.assertEqual(errors[0].message, "simulated failure")
        self.assertEqual(finished, [True])

    def test_cancelled_worker_does_not_run_operation_or_emit_result(self):
        operation = Mock(return_value="unexpected")
        events = []
        worker = CancellableWorker(operation)
        worker.signals.result.connect(lambda value: events.append(("result", value)))
        worker.signals.cancelled.connect(lambda: events.append(("cancelled", None)))
        worker.signals.finished.connect(lambda: events.append(("finished", None)))

        worker.cancel()
        worker.run()

        operation.assert_not_called()
        self.assertEqual(events, [("cancelled", None), ("finished", None)])


class WorkerRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_duplicate_names_are_rejected_until_task_finishes(self):
        registry = WorkerRegistry(max_threads=1)
        release = threading.Event()
        started = threading.Event()

        def operation(context):
            started.set()
            while not release.is_set():
                context.sleep(0.01)
            return True

        self.assertTrue(registry.start("refresh", operation))
        self.assertTrue(started.wait(1.0))
        self.assertFalse(registry.start("refresh", operation))
        release.set()
        self.assertTrue(registry.close(timeout_ms=1000))
        self.assertEqual(registry.active_names, ())

    def test_callbacks_are_delivered_on_the_gui_thread(self):
        registry = WorkerRegistry(max_threads=1)
        callback_threads = []

        self.assertTrue(
            registry.start(
                "thread-check",
                lambda _context: "done",
                on_result=lambda _value: callback_threads.append(QThread.currentThread()),
            )
        )
        deadline = time.monotonic() + 1.0
        while not callback_threads and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)

        self.assertEqual(callback_threads, [self.app.thread()])
        self.assertTrue(registry.close(timeout_ms=1000))

    def test_close_cancels_interruptible_wait_and_suppresses_callbacks(self):
        registry = WorkerRegistry(max_threads=1)
        started = threading.Event()
        callbacks = []

        def operation(context):
            started.set()
            context.sleep(30.0)
            return "late result"

        self.assertTrue(
            registry.start(
                "slow",
                operation,
                on_result=lambda value: callbacks.append(("result", value)),
                on_cancelled=lambda: callbacks.append(("cancelled", None)),
                on_finished=lambda: callbacks.append(("finished", None)),
            )
        )
        self.assertTrue(started.wait(1.0))

        started_at = time.monotonic()
        self.assertTrue(registry.close(timeout_ms=1000))

        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertEqual(registry.active_names, ())
        self.assertEqual(callbacks, [])

    def test_failed_close_reopens_registry_for_preserved_widget(self):
        registry = WorkerRegistry(max_threads=2)
        started = threading.Event()
        release = threading.Event()
        callbacks = []

        def stubborn_operation(_context):
            started.set()
            release.wait(1.0)
            return "ignored-after-cancel"

        self.assertTrue(
            registry.start(
                "stubborn",
                stubborn_operation,
                on_cancelled=lambda: callbacks.append("cancelled"),
                on_finished=lambda: callbacks.append("stubborn-finished"),
            )
        )
        self.assertTrue(started.wait(1.0))

        self.assertFalse(registry.close(timeout_ms=1))
        self.assertTrue(
            registry.start(
                "replacement",
                lambda _context: "replacement-result",
                on_result=lambda value: callbacks.append(value),
                on_finished=lambda: callbacks.append("replacement-finished"),
            )
        )

        release.set()
        deadline = time.monotonic() + 1.0
        expected = {
            "cancelled",
            "stubborn-finished",
            "replacement-result",
            "replacement-finished",
        }
        while not expected.issubset(callbacks) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)

        self.assertTrue(expected.issubset(callbacks))
        self.assertTrue(registry.close(timeout_ms=1000))


class BoundedOperationTests(unittest.TestCase):
    @patch("utils.workers.os.name", "nt")
    @patch("utils.workers.subprocess.run")
    def test_windows_process_stop_terminates_the_process_tree(self, taskkill):
        taskkill.return_value.returncode = 0
        process = Mock()
        process.pid = 1234
        process.poll.return_value = None
        process.communicate.return_value = ("", "")

        worker_utils._stop_process(process, grace_seconds=0.5)

        taskkill.assert_called_once_with(
            ["taskkill", "/PID", "1234", "/T", "/F"],
            capture_output=True,
            timeout=0.5,
            check=False,
            shell=False,
        )
        process.terminate.assert_not_called()

    @patch("utils.workers.subprocess.Popen")
    def test_subprocess_adapter_rejects_unbounded_timeout_before_spawn(self, popen):
        for timeout in (None, 0, -1):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    run_cancellable_process([sys.executable, "--version"], timeout=timeout)

        popen.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    @patch("utils.workers.subprocess.Popen")
    def test_subprocess_adapter_enforces_isolated_posix_process_group(self, popen):
        process = Mock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        popen.return_value = process

        run_cancellable_process(
            [sys.executable, "--version"],
            timeout=1,
            start_new_session=False,
        )

        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @patch("utils.workers.subprocess.Popen")
    def test_subprocess_adapter_capture_output_uses_pipes(self, popen):
        process = Mock()
        process.communicate.return_value = ("captured stdout", "captured stderr")
        process.returncode = 0
        popen.return_value = process

        result = run_cancellable_process(
            [sys.executable, "--version"],
            timeout=1.0,
            capture_output=True,
            text=True,
        )

        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        self.assertTrue(popen.call_args.kwargs["text"])
        self.assertEqual(result.stdout, "captured stdout")
        self.assertEqual(result.stderr, "captured stderr")

    @patch("utils.workers._stop_process", return_value=("", ""))
    @patch("utils.workers.subprocess.Popen")
    def test_subprocess_adapter_terminates_child_when_cancelled(
        self, popen, stop_process
    ):
        token = CancellationToken()
        process = Mock()

        def cancel_during_poll(*args, **kwargs):
            token.cancel()
            raise subprocess.TimeoutExpired([sys.executable], 0.01)

        process.communicate.side_effect = cancel_during_poll
        popen.return_value = process

        with self.assertRaises(CancelledError):
            run_cancellable_process(
                [sys.executable, "--version"],
                token=token,
                timeout=5.0,
                poll_interval=0.01,
            )

        stop_process.assert_called_once_with(process)

    @unittest.skipUnless(os.name == "posix", "POSIX real-child integration")
    def test_subprocess_adapter_terminates_real_child_when_cancelled(self):
        token = CancellationToken()
        timer = threading.Timer(0.05, token.cancel)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(CancelledError):
                run_cancellable_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    token=token,
                    timeout=5.0,
                    poll_interval=0.01,
                )
        finally:
            timer.cancel()

        self.assertLess(time.monotonic() - started, 1.0)

    @patch("utils.workers._stop_process", return_value=("", ""))
    @patch("utils.workers.time.monotonic", side_effect=(0.0, 0.005, 0.02))
    @patch("utils.workers.subprocess.Popen")
    def test_subprocess_adapter_enforces_deadline(
        self, popen, monotonic, stop_process
    ):
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired(
            [sys.executable], 0.005
        )
        popen.return_value = process

        with self.assertRaises(subprocess.TimeoutExpired):
            run_cancellable_process(
                [sys.executable, "--version"],
                timeout=0.01,
                poll_interval=0.005,
            )

        self.assertEqual(monotonic.call_count, 3)
        stop_process.assert_called_once_with(process)

    @unittest.skipUnless(os.name == "posix", "POSIX real-child integration")
    def test_subprocess_adapter_enforces_real_child_deadline(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_cancellable_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=0.03,
                poll_interval=0.01,
            )

    def test_http_adapter_rejects_unbounded_timeout(self):
        session = Mock()

        for timeout in (None, 0, (5.0, None), (5.0, 0)):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    bounded_http_request(
                        session,
                        "GET",
                        "https://example.invalid/data",
                        timeout=timeout,
                    )

        session.request.assert_not_called()

    def test_ocr_adapter_rejects_unbounded_timeout(self):
        ocr = Mock()

        for timeout in (None, 0, -1):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    bounded_ocr_call(ocr, object(), timeout=timeout)

        ocr.assert_not_called()

    def test_http_adapter_enforces_timeout_and_checks_cancellation(self):
        session = Mock()
        response = Mock()
        session.request.return_value = response
        token = CancellationToken()

        result = bounded_http_request(
            session,
            "GET",
            "https://example.invalid/data",
            token=token,
            timeout=(2.0, 7.0),
            headers={"Accept": "application/json"},
        )

        self.assertIs(result, response)
        session.request.assert_called_once_with(
            "GET",
            "https://example.invalid/data",
            timeout=(2.0, 7.0),
            headers={"Accept": "application/json"},
        )

        token.cancel()
        with self.assertRaises(CancelledError):
            bounded_http_request(session, "GET", "https://example.invalid/other", token=token)
        self.assertEqual(session.request.call_count, 1)

    def test_ocr_adapter_enforces_timeout_and_checks_cancellation(self):
        ocr = Mock(return_value="recognized")
        token = CancellationToken()
        image = object()

        result = bounded_ocr_call(
            ocr,
            image,
            token=token,
            timeout=4.0,
            config="--psm 7",
        )

        self.assertEqual(result, "recognized")
        ocr.assert_called_once_with(image, timeout=4.0, config="--psm 7")

        token.cancel()
        with self.assertRaises(CancelledError):
            bounded_ocr_call(ocr, image, token=token)
        self.assertEqual(ocr.call_count, 1)


if __name__ == "__main__":
    unittest.main()
