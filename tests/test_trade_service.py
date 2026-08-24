import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, call, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from services.trade_service import TradeService
from utils.workers import CancelledError, CancellationToken


class FakeStdin:
    def __init__(self, process):
        self.process = process
        self.writes = []
        self.flush_count = 0
        self.close_count = 0

    def write(self, text):
        self.writes.append(text)
        if text == "__shutdown__\n":
            self.process.returncode = 0

    def flush(self):
        self.flush_count += 1

    def close(self):
        self.close_count += 1


class FakeStdout:
    def __init__(self):
        self.close_count = 0

    def readline(self):
        return ""

    def close(self):
        self.close_count += 1


class FakeProcess:
    def __init__(self, pid=424242):
        self.pid = pid
        self.returncode = None
        self.stdin = FakeStdin(self)
        self.stdout: Any = None
        self.kill_count = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("node", timeout)
        return self.returncode

    def kill(self):
        self.kill_count += 1
        self.returncode = -signal.SIGKILL


class TradeServiceTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        register = patch("services.trade_service.atexit.register")
        register.start()
        self.addCleanup(register.stop)


class TradeServiceStopTests(TradeServiceTestCase):
    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    @patch("services.trade_service.platform.system", return_value="Linux")
    @patch("services.trade_service.os.getpgid", return_value=424242, create=True)
    @patch("services.trade_service.os.killpg", create=True)
    def test_cancelled_stop_skips_grace_wait_and_forces_process_group_shutdown(
        self, killpg, _getpgid, _platform_system
    ):
        service = TradeService()
        process = FakeProcess()
        process.stdin.write = lambda text: process.stdin.writes.append(text)
        service.process = process
        service._running = True
        token = CancellationToken()
        token.cancel()

        def record_signal(_pgid, sent_signal):
            if sent_signal == signal.SIGKILL:
                process.returncode = -signal.SIGKILL

        killpg.side_effect = record_signal

        self.assertTrue(service.stop(token))

        self.assertEqual(process.stdin.writes, ["__shutdown__\n"])
        killpg.assert_called_once_with(424242, signal.SIGKILL)

    @patch("services.trade_service.subprocess.run")
    @patch("services.trade_service.platform.system", return_value="Windows")
    def test_cancelled_windows_stop_uses_bounded_direct_tree_kill(
        self, _platform_system, run
    ):
        service = TradeService()
        process = FakeProcess(pid=4321)
        process.stdin.write = lambda text: process.stdin.writes.append(text)
        service.process = process
        service._running = True
        token = CancellationToken()
        token.cancel()

        def finish_process(*_args, **_kwargs):
            process.returncode = 0
            return subprocess.CompletedProcess([], 0)

        run.side_effect = finish_process

        self.assertTrue(service.stop(token))

        run.assert_called_once_with(
            ["taskkill", "/F", "/T", "/PID", "4321"],
            shell=False,
            capture_output=True,
            timeout=3,
            check=False,
        )

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    @patch("services.trade_service.platform.system", return_value="Linux")
    @patch("services.trade_service.os.getpgid", return_value=424242, create=True)
    @patch("services.trade_service.os.killpg", create=True)
    def test_stop_requests_graceful_browser_cleanup_before_signals(
        self, killpg, _getpgid, _platform_system
    ):
        service = TradeService()
        process = FakeProcess()
        service.process = process
        service._running = True
        statuses = []
        service.status_changed.connect(statuses.append)

        stopped = service.stop()

        self.assertTrue(stopped)
        self.assertEqual(process.stdin.writes, ["__shutdown__\n"])
        self.assertEqual(process.stdin.flush_count, 1)
        killpg.assert_not_called()
        self.assertEqual(statuses[-1], "stopped")
        self.assertIsNone(service.process)
        self.assertFalse(service._running)

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    @patch("services.trade_service.platform.system", return_value="Linux")
    @patch("services.trade_service.os.getpgid", return_value=424242, create=True)
    @patch("services.trade_service.os.killpg", create=True)
    def test_stop_escalates_to_sigterm_when_graceful_request_is_ignored(
        self, killpg, _getpgid, _platform_system
    ):
        service = TradeService()
        process = FakeProcess()
        process.stdin.write = lambda text: process.stdin.writes.append(text)
        service.process = process
        service._running = True

        def record_signal(_pgid, sent_signal):
            if sent_signal == signal.SIGTERM:
                process.returncode = -signal.SIGTERM

        killpg.side_effect = record_signal

        service.stop()

        self.assertEqual(process.stdin.writes, ["__shutdown__\n"])
        killpg.assert_called_once_with(424242, signal.SIGTERM)
        self.assertIsNone(service.process)

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    @patch("services.trade_service.platform.system", return_value="Linux")
    @patch("services.trade_service.os.getpgid", return_value=424242, create=True)
    @patch("services.trade_service.os.killpg", create=True)
    def test_stop_does_not_report_stopped_while_process_is_still_alive(
        self, _killpg, _getpgid, _platform_system
    ):
        service = TradeService()
        process = FakeProcess()
        process.stdin.write = lambda text: process.stdin.writes.append(text)
        service.process = process
        service._running = True
        statuses = []
        service.status_changed.connect(statuses.append)

        stopped = service.stop()

        self.assertFalse(stopped)
        self.assertIs(service.process, process)
        self.assertTrue(service._running)
        self.assertEqual(statuses[-1], "error")

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    @patch("services.trade_service.platform.system", return_value="Linux")
    @patch("services.trade_service.os.getpgid", return_value=424242, create=True)
    @patch("services.trade_service.os.killpg", create=True)
    def test_force_cleanup_requests_graceful_browser_cleanup_before_killing(
        self, killpg, _getpgid, _platform_system
    ):
        service = TradeService()
        process = FakeProcess()
        service.process = process
        service._running = True

        service._force_cleanup()

        self.assertEqual(process.stdin.writes, ["__shutdown__\n"])
        killpg.assert_not_called()
        self.assertIsNone(service.process)
        self.assertFalse(service._running)

    @patch("services.trade_service.subprocess.run")
    @patch("services.trade_service.platform.system", return_value="Windows")
    def test_force_cleanup_uses_bounded_direct_windows_tree_kill(
        self, _platform_system, run
    ):
        service = TradeService()
        process = FakeProcess(pid=4321)
        process.stdin.write = lambda text: process.stdin.writes.append(text)
        service.process = process
        service._running = True

        def taskkill(command, **_kwargs):
            if "/F" in command:
                process.returncode = 0
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = taskkill

        service._force_cleanup()

        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["taskkill", "/T", "/PID", "4321"],
                    shell=False,
                    capture_output=True,
                    timeout=3,
                    check=False,
                ),
                call(
                    ["taskkill", "/F", "/T", "/PID", "4321"],
                    shell=False,
                    capture_output=True,
                    timeout=3,
                    check=False,
                ),
            ],
        )
        self.assertIsNone(service.process)
        self.assertFalse(service._running)

    def test_stop_releases_owner_closes_pipes_and_joins_output_reader(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            owner_file = Path(temp_dir) / "trade-service.lock"
            owner_file.write_text(str(os.getpid()), encoding="utf-8")
            service = TradeService(owner_file=str(owner_file))
            process = FakeProcess()
            process.stdout = FakeStdout()
            output_thread = Mock()
            service.process = process
            service.output_thread = output_thread
            service._running = True

            service.stop()

            self.assertFalse(owner_file.exists())
            self.assertEqual(process.stdin.close_count, 1)
            self.assertEqual(process.stdout.close_count, 1)
            output_thread.join.assert_called_once_with(timeout=2)
            self.assertIsNone(service.output_thread)


class TradeServiceStartTests(TradeServiceTestCase):
    @patch("services.trade_service.threading.Thread")
    @patch("services.trade_service.subprocess.Popen")
    @patch.object(TradeService, "check_dependencies", return_value=("v24.18.0", "11"))
    def test_start_launches_node_directly_without_shell_wrapper(
        self, _dependencies, popen, thread
    ):
        process = FakeProcess()
        process.stdout = object()
        popen.return_value = process
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        owner_file = os.path.join(temp_dir.name, "trade-service.lock")
        service = TradeService(
            service_dir=os.path.join(PROJECT_ROOT, "trade_service"),
            owner_file=owner_file,
        )

        service.start(
            auto_resume=True,
            auto_resume_delay_s=90,
            cooldown_s=5,
            poll_interval_ms=10,
            confirmation_retry_ms=20,
            game_id="poe1",
            zone_gate_enabled=True,
            client_log_path="/games/Path of Exile/logs/Client.txt",
            allowed_zones=["FutureLeagueHub", "bad-zone"],
        )

        command, = popen.call_args.args
        kwargs = popen.call_args.kwargs
        self.assertEqual(
            command,
            [
                "node",
                "trade_monitor.js",
                "--cooldown=5",
                "--auto-resume-delay=90",
                "--poll-interval-ms=10",
                "--confirmation-retry-ms=20",
                "--game=poe1",
                "--client-log=/games/Path of Exile/logs/Client.txt",
                "--allowed-zone=FutureLeagueHub",
                "--zone-gate",
                "--auto-resume",
                f"--controller-pid={os.getpid()}",
            ],
        )
        self.assertFalse(kwargs["shell"])
        if os.name == "nt":
            self.assertNotIn("start_new_session", kwargs)
            self.assertNotIn("creationflags", kwargs)
        else:
            self.assertTrue(kwargs["start_new_session"])
            self.assertNotIn("creationflags", kwargs)
        thread.return_value.start.assert_called_once_with()

    @patch("services.trade_service.threading.Thread")
    @patch("services.trade_service.subprocess.Popen")
    @patch.object(TradeService, "check_dependencies", return_value=("v24.18.0", "11"))
    def test_start_refuses_live_owner_for_same_installation(
        self, _dependencies, popen, _thread
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            owner_file = Path(temp_dir) / "trade-service.lock"
            owner_file.write_text(str(os.getpid()), encoding="utf-8")
            service = TradeService(
                service_dir=os.path.join(PROJECT_ROOT, "trade_service"),
                owner_file=str(owner_file),
            )
            statuses = []
            logs = []
            service.status_changed.connect(statuses.append)
            service.log_output.connect(logs.append)

            service.start()

            popen.assert_not_called()
            self.assertEqual(statuses[-1], "error")
            self.assertTrue(any("already owns" in line for line in logs))

    @patch("services.trade_service.threading.Thread")
    @patch("services.trade_service.subprocess.Popen")
    @patch.object(TradeService, "check_dependencies", return_value=("v24.18.0", "11"))
    def test_start_reclaims_stale_owner_without_scanning_other_processes(
        self, _dependencies, popen, thread
    ):
        process = FakeProcess()
        process.stdout = object()
        popen.return_value = process

        with tempfile.TemporaryDirectory() as temp_dir:
            owner_file = Path(temp_dir) / "trade-service.lock"
            owner_file.write_text("999999999", encoding="utf-8")
            service = TradeService(
                service_dir=os.path.join(PROJECT_ROOT, "trade_service"),
                owner_file=str(owner_file),
            )

            with patch.object(service, "_pid_is_alive", return_value=False):
                service.start()

            popen.assert_called_once()
            thread.return_value.start.assert_called_once_with()
            self.assertEqual(owner_file.read_text(encoding="utf-8"), str(os.getpid()))


class TradeServiceDependencyTests(TradeServiceTestCase):
    @patch("services.trade_service.run_cancellable_process")
    def test_dependency_probes_are_direct_bounded_and_cancellable(self, run_process):
        run_process.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="v24.18.0\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="11.0.0\n", stderr=""),
        ]
        service = TradeService()

        token = CancellationToken()
        self.assertEqual(service.check_dependencies(token), ("v24.18.0", "11.0.0"))

        self.assertEqual(run_process.call_args_list[0].args[0], ["node", "--version"])
        self.assertEqual(run_process.call_args_list[1].args[0][-1], "--version")
        for invocation in run_process.call_args_list:
            self.assertEqual(invocation.kwargs["timeout"], 5)
            self.assertFalse(invocation.kwargs["shell"])
            self.assertIs(invocation.kwargs["token"], token)

    def test_bundled_trade_files_are_materialized_in_writable_runtime_dir(self):
        with tempfile.TemporaryDirectory() as bundle_dir, tempfile.TemporaryDirectory() as runtime_dir:
            for name in TradeService.BUNDLE_FILES:
                Path(bundle_dir, name).write_text(f"bundled:{name}", encoding="utf-8")
            stale = Path(runtime_dir, "trade_monitor.js")
            stale.write_text("stale", encoding="utf-8")
            service = TradeService(service_dir=runtime_dir)
            service.bundle_dir = bundle_dir

            self.assertTrue(service.prepare_service_files())

            for name in TradeService.BUNDLE_FILES:
                self.assertEqual(
                    Path(runtime_dir, name).read_text(encoding="utf-8"),
                    f"bundled:{name}",
                )

    @patch("services.trade_service.run_cancellable_process")
    def test_npm_ci_is_direct_bounded_and_cancellable(self, run_process):
        run_process.return_value = subprocess.CompletedProcess([], 0, stdout="installed", stderr="")
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "package.json").write_text("{}", encoding="utf-8")
            service = TradeService(service_dir=temp_dir)

            token = CancellationToken()
            self.assertTrue(service.install_dependencies(token))

        command = run_process.call_args.args[0]
        self.assertEqual(command[-1], "ci")
        self.assertEqual(run_process.call_args.kwargs["timeout"], 120)
        self.assertFalse(run_process.call_args.kwargs["shell"])
        self.assertIs(run_process.call_args.kwargs["token"], token)

    @patch("services.trade_service.run_cancellable_process", side_effect=CancelledError())
    def test_dependency_cancellation_is_not_converted_to_missing_node(self, _run_process):
        with self.assertRaises(CancelledError):
            TradeService().check_dependencies(CancellationToken())


class TradeServiceOutputTests(TradeServiceTestCase):
    def test_intentional_stop_does_not_emit_duplicate_process_ended_status(self):
        service = TradeService()
        process = FakeProcess()
        process.returncode = 0

        class EndedStdout:
            @staticmethod
            def readline():
                return ""

        process.stdout = EndedStdout()
        service.process = process
        service._running = True
        service._stopping = True
        statuses = []
        logs = []
        service.status_changed.connect(statuses.append)
        service.log_output.connect(logs.append)

        service._read_output()

        self.assertEqual(statuses, [])
        self.assertNotIn("Trade service ended.", logs)


if __name__ == "__main__":
    unittest.main()
