"""Process-owner and atomic run-publication regressions; synthetic local data only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import run_ledger


def windows_error(code):
    error = OSError("injected Windows file/process error")
    error.winerror = code
    return error


class ProcessOwnerTests(unittest.TestCase):
    def windows_api(self, *, result=258, open_error=None, wait_error=None):
        api = types.SimpleNamespace(
            SYNCHRONIZE=1048576, WAIT_OBJECT_0=0,
            OpenProcess=Mock(return_value=123, side_effect=open_error),
            WaitForSingleObject=Mock(return_value=result, side_effect=wait_error),
            CloseHandle=Mock(),
        )
        return api

    def test_windows_probe_never_sends_a_signal_and_releases_handle(self):
        for result, alive in [(258, True), (0, False), (0xFFFFFFFF, True)]:
            with self.subTest(result=result):
                api = self.windows_api(result=result)
                with patch.dict(sys.modules, {"_winapi": api}), patch.object(run_ledger.os, "name", "nt"), \
                        patch.object(run_ledger.os, "kill", side_effect=AssertionError("signal sent")):
                    self.assertEqual(alive, run_ledger._pid_alive(42))
                api.OpenProcess.assert_called_once_with(api.SYNCHRONIZE, False, 42)
                api.WaitForSingleObject.assert_called_once_with(123, 0)
                api.CloseHandle.assert_called_once_with(123)

    def test_unknown_process_state_keeps_existing_writer_lock(self):
        for code, alive in [(87, False), (5, True), (32, True)]:
            with self.subTest(code=code):
                api = self.windows_api(open_error=windows_error(code))
                with patch.dict(sys.modules, {"_winapi": api}):
                    self.assertEqual(alive, run_ledger._windows_pid_alive(42))
                api.CloseHandle.assert_not_called()
        api = self.windows_api(wait_error=OSError("inspection failed"))
        with patch.dict(sys.modules, {"_winapi": api}):
            self.assertTrue(run_ledger._windows_pid_alive(42))
        api.CloseHandle.assert_called_once_with(123)

    def test_invalid_pid_does_not_inspect_or_signal(self):
        api = self.windows_api()
        with patch.dict(sys.modules, {"_winapi": api}), patch.object(run_ledger.os, "name", "nt"), \
                patch.object(run_ledger.os, "kill", side_effect=AssertionError("signal sent")):
            for pid in [None, True, "42", 0, -1, 2**40]:
                self.assertFalse(run_ledger._pid_alive(pid))
        api.OpenProcess.assert_not_called()

    def test_real_process_remains_alive_after_probe_and_exit_is_detected(self):
        script = "import sys; print('ready', flush=True); sys.stdin.readline()"
        child = subprocess.Popen([sys.executable, "-B", "-c", script],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual("ready", child.stdout.readline().strip())
            self.assertTrue(run_ledger._pid_alive(child.pid))
            self.assertIsNone(child.poll(), "Owner probe affected the running process")
            child.communicate("\n", timeout=10)
            self.assertEqual(0, child.returncode)
            self.assertFalse(run_ledger._pid_alive(child.pid))
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_real_current_process_check_does_not_use_windows_kill(self):
        if os.name != "nt":
            self.skipTest("Windows process-handle integration")
        with patch.object(run_ledger.os, "kill", side_effect=AssertionError("signal sent")):
            self.assertTrue(run_ledger._pid_alive(os.getpid()))


class AtomicPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "pending"
        self.target = self.root / "published"
        self.source.mkdir()
        (self.source / "manifest.json").write_text("complete", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_transient_windows_denial_retries_atomic_publish(self):
        replace = os.replace
        calls = []

        def transient(source, target):
            calls.append((source, target))
            self.assertFalse(target.exists())
            if len(calls) <= 2:
                raise windows_error(5 if len(calls) == 1 else 32)
            replace(source, target)

        with patch.object(run_ledger.os, "name", "nt"), \
                patch.object(run_ledger.os, "replace", side_effect=transient), \
                patch.object(run_ledger.time, "sleep") as sleep:
            run_ledger._publish_run_directory(self.source, self.target)
        self.assertEqual(3, len(calls))
        self.assertEqual(2, sleep.call_count)
        self.assertEqual("complete", (self.target / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(self.source.exists())

    def test_persistent_denial_is_bounded_and_does_not_create_target(self):
        with patch.object(run_ledger.os, "name", "nt"), \
                patch.object(run_ledger.os, "replace", side_effect=windows_error(5)) as replace, \
                patch.object(run_ledger.time, "sleep") as sleep:
            with self.assertRaises(OSError):
                run_ledger._publish_run_directory(self.source, self.target)
        self.assertEqual(5, replace.call_count)
        self.assertEqual(4, sleep.call_count)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.source / "manifest.json").is_file())

    def test_existing_destination_is_preserved_before_and_during_retry(self):
        self.target.mkdir()
        sentinel = self.target / "original.txt"
        sentinel.write_text("original", encoding="utf-8")
        with patch.object(run_ledger.os, "replace") as replace:
            with self.assertRaises(run_ledger.RunLedgerError):
                run_ledger._publish_run_directory(self.source, self.target)
        replace.assert_not_called()
        self.assertEqual("original", sentinel.read_text(encoding="utf-8"))
        self.target = self.root / "racing-publication"

        def racing(source, target):
            target.mkdir()
            (target / "original.txt").write_text("other writer", encoding="utf-8")
            raise windows_error(5)

        with patch.object(run_ledger.os, "name", "nt"), \
                patch.object(run_ledger.os, "replace", side_effect=racing), \
                patch.object(run_ledger.time, "sleep") as sleep:
            with self.assertRaises(run_ledger.RunLedgerError):
                run_ledger._publish_run_directory(self.source, self.target)
        sleep.assert_not_called()
        self.assertEqual("other writer", (self.target / "original.txt").read_text(encoding="utf-8"))

    def test_other_errors_and_non_windows_errors_are_not_retried(self):
        for platform, error in [("nt", windows_error(112)), ("posix", windows_error(5))]:
            with self.subTest(platform=platform), patch.object(run_ledger.os, "name", platform), \
                    patch.object(run_ledger.os, "replace", side_effect=error) as replace, \
                    patch.object(run_ledger.time, "sleep") as sleep:
                with self.assertRaises(OSError):
                    run_ledger._publish_run_directory(self.source, self.target)
                self.assertEqual(1, replace.call_count)
                sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
