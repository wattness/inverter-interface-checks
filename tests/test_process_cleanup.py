"""Independent process states; no native library or real signal is used."""

import subprocess
import unittest
from unittest.mock import Mock, patch

from inverter_interface_checks.process import stop_process


class ProcessCleanup(unittest.TestCase):
    def test_exited_worker_permission_error_does_not_abort_cleanup(self):
        for returned in (0, -9):
            with self.subTest(returncode=returned):
                child = Mock(pid=123, poll=Mock(return_value=returned), wait=Mock(return_value=returned))
                with patch("inverter_interface_checks.process.os.name", "posix"), patch(
                    "inverter_interface_checks.process.signal.SIGKILL", 9, create=True
                ), patch(
                    "inverter_interface_checks.process.os.killpg", side_effect=PermissionError(1, "denied"), create=True
                ):
                    stop_process(child)
                child.wait.assert_called_once_with(timeout=5)

    def test_live_worker_permission_error_remains_an_error(self):
        child = Mock(pid=123, poll=Mock(return_value=None),
                     wait=Mock(side_effect=subprocess.TimeoutExpired("worker", 5)))
        with patch("inverter_interface_checks.process.os.name", "posix"), patch(
            "inverter_interface_checks.process.signal.SIGKILL", 9, create=True
        ), patch(
            "inverter_interface_checks.process.os.killpg", side_effect=PermissionError(1, "denied"), create=True
        ):
            with self.assertRaises(PermissionError):
                stop_process(child)
        child.wait.assert_called_once_with(timeout=5)

    def test_child_exiting_during_cleanup_is_confirmed_before_acceptance(self):
        child = Mock(pid=123, poll=Mock(return_value=None), wait=Mock(return_value=0))
        with patch("inverter_interface_checks.process.os.name", "posix"), patch(
            "inverter_interface_checks.process.signal.SIGKILL", 9, create=True
        ), patch(
            "inverter_interface_checks.process.os.killpg", side_effect=PermissionError(1, "denied"), create=True
        ):
            stop_process(child)
        child.wait.assert_called_once_with(timeout=5)

    def test_missing_process_group_keeps_existing_cleanup_behavior(self):
        child = Mock(pid=123)
        with patch("inverter_interface_checks.process.os.name", "posix"), patch(
            "inverter_interface_checks.process.signal.SIGKILL", 9, create=True
        ), patch(
            "inverter_interface_checks.process.os.killpg", side_effect=ProcessLookupError(3, "missing"), create=True
        ):
            stop_process(child)
        child.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
