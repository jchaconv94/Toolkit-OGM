import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from updater_controller import AppUpdaterController


class UpdaterRetryTests(unittest.TestCase):
    def _controller(self):
        controller = object.__new__(AppUpdaterController)
        controller.RETRY_INTERVAL_SECONDS = 0.05
        controller.stop_event = threading.Event()
        controller.retry_lock = threading.Lock()
        controller.retry_timer = None
        controller.retry_triggered = threading.Event()
        controller.check_async = lambda **_kwargs: controller.retry_triggered.set()
        return controller

    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=True)
    def test_failed_check_schedules_only_one_retry(self, _cfg_get, _log):
        controller = self._controller()
        controller._schedule_retry()
        first_timer = controller.retry_timer
        controller._schedule_retry()

        self.assertIs(controller.retry_timer, first_timer)
        self.assertTrue(controller.retry_triggered.wait(timeout=1))
        controller.stop()

    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=True)
    def test_stop_cancels_pending_retry(self, _cfg_get, _log):
        controller = self._controller()
        controller.RETRY_INTERVAL_SECONDS = 1
        controller._schedule_retry()
        controller.stop()

        self.assertTrue(controller.stop_event.is_set())
        self.assertIsNone(controller.retry_timer)
        self.assertFalse(controller.retry_triggered.wait(timeout=0.1))


if __name__ == "__main__":
    unittest.main()
