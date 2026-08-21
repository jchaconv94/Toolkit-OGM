import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from updater_controller import AppUpdaterController
from update_manager import UpdateError


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


class UpdaterInstallFlowTests(unittest.TestCase):
    def _controller(self, manager, events):
        controller = object.__new__(AppUpdaterController)
        controller.manager = manager
        controller.installer_path = Path("ToolkitOGM-Setup-2.0.15.exe")
        controller.current_info = SimpleNamespace(version="2.0.15")
        controller._close_dialog = lambda _dialog: events.append("close-dialog")
        controller._set_state = lambda state, *_args: events.append(f"state:{state}")
        controller._snack = lambda _message: events.append("snack")
        controller.stop = lambda: events.append("stop-updater")
        controller.on_installer_launched = lambda: events.append("shutdown-app")
        return controller

    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_set")
    def test_install_schedules_helper_before_closing_app(self, _cfg_set, _log):
        events = []
        manager = SimpleNamespace(
            launch_installer=lambda _path: events.append("schedule-helper")
        )
        controller = self._controller(manager, events)

        controller._install_now(object())

        self.assertEqual(
            events,
            [
                "close-dialog",
                "state:installing",
                "schedule-helper",
                "stop-updater",
                "shutdown-app",
            ],
        )

    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_set")
    def test_install_keeps_app_open_when_helper_cannot_start(self, _cfg_set, _log):
        events = []

        def fail(_path):
            raise UpdateError("No se pudo preparar")

        controller = self._controller(SimpleNamespace(launch_installer=fail), events)

        controller._install_now(object())

        self.assertIn("state:ready", events)
        self.assertIn("snack", events)
        self.assertNotIn("shutdown-app", events)


if __name__ == "__main__":
    unittest.main()
