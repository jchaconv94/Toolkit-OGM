import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parents[1] / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from update_shutdown import arm_update_exit_watchdog


class UpdateShutdownTests(unittest.TestCase):
    def test_watchdog_forces_exit_with_requested_code(self):
        exited = threading.Event()
        exit_codes = []
        waits = []

        def fake_exit(code):
            exit_codes.append(code)
            exited.set()

        thread = arm_update_exit_watchdog(
            delay_seconds=3,
            exit_code=7,
            exit_process=fake_exit,
            wait=waits.append,
        )

        self.assertTrue(exited.wait(1))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(thread.daemon)
        self.assertEqual(waits, [3.0])
        self.assertEqual(exit_codes, [7])

    def test_watchdog_never_waits_a_negative_duration(self):
        waits = []
        thread = arm_update_exit_watchdog(
            delay_seconds=-10,
            exit_process=lambda _code: None,
            wait=waits.append,
        )

        thread.join(timeout=1)
        self.assertEqual(waits, [0.0])

    def test_watchdog_terminates_a_real_process_promptly(self):
        script = (
            "import sys, time; "
            f"sys.path.insert(0, {str(TOOLKIT_DIR)!r}); "
            "from update_shutdown import arm_update_exit_watchdog; "
            "arm_update_exit_watchdog(delay_seconds=0.2); "
            "time.sleep(10)"
        )

        started_at = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            timeout=3,
        )
        elapsed = time.monotonic() - started_at

        self.assertEqual(result.returncode, 0)
        self.assertLess(elapsed, 2)


if __name__ == "__main__":
    unittest.main()
