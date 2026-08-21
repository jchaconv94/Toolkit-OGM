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
from update_manager import UpdateError, UpdateInfo


class _FakePage:
    def __init__(self):
        self.overlay = []
        self.opened = []
        self.snack_bar = None
        self.update_count = 0

    def open(self, control):
        self.opened.append(control)

    def update(self):
        self.update_count += 1


def _update_info(version="2.1.3"):
    return UpdateInfo(
        version=version,
        installer_name=f"ToolkitOGM-Setup-{version}.exe",
        download_url=f"https://github.com/example/ToolkitOGM-Setup-{version}.exe",
        expected_sha256="a" * 64,
        size_bytes=10 * 1024 * 1024,
        release_notes="Mejoras del actualizador.",
        release_url="https://github.com/example/release",
        published_at="2026-08-21T12:00:00Z",
    )


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


class UpdaterBehaviorTests(unittest.TestCase):
    def _controller(self, *, info=None, notifications=None, navigation=None):
        notification_sink = notifications if notifications is not None else []
        navigation_sink = navigation if navigation is not None else []
        manager = SimpleNamespace(
            current_version="2.1.2",
            check_for_update=lambda: info,
        )
        return AppUpdaterController(
            _FakePage(),
            on_installer_launched=lambda: None,
            notify_callback=lambda title, message: notification_sink.append((title, message)),
            navigate_to_settings=lambda: navigation_sink.append("settings"),
            manager=manager,
        )

    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=True)
    def test_enabling_auto_check_wakes_scheduler_and_checks_now(self, _get, _log, set_value):
        controller = self._controller()
        checks = []
        controller.check_async = lambda **kwargs: checks.append(kwargs)

        controller._change_auto_check(SimpleNamespace(control=SimpleNamespace(value=True)))

        set_value.assert_called_with("update_auto_check", True)
        self.assertTrue(controller.scheduler_wake_event.is_set())
        self.assertEqual(checks, [{"manual": False}])

    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=True)
    def test_enabling_auto_download_starts_known_update(self, _get, _log, set_value):
        info = _update_info()
        controller = self._controller(info=info)
        controller.current_info = info
        downloads = []
        controller.download_async = lambda selected: downloads.append(selected)

        controller._change_auto_download(SimpleNamespace(control=SimpleNamespace(value=True)))

        set_value.assert_called_with("update_auto_download", True)
        self.assertEqual(downloads, [info])

    @patch("updater_controller.cfg_set_many")
    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=False)
    def test_enabling_auto_download_also_enables_required_auto_check(
        self,
        _get,
        _log,
        set_value,
        set_many,
    ):
        controller = self._controller()
        checks = []
        controller.check_async = lambda **kwargs: checks.append(kwargs)

        controller._change_auto_download(SimpleNamespace(control=SimpleNamespace(value=True)))

        self.assertTrue(controller.auto_check.value)
        set_many.assert_called_with({
            "update_auto_check": True,
            "update_auto_download": True,
        })
        set_value.assert_not_called()
        self.assertEqual(checks, [{"manual": False}])

    @patch("updater_controller.cfg_set_many")
    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    @patch("updater_controller.cfg_get", return_value=True)
    def test_disabling_auto_check_also_disables_auto_download(
        self,
        _get,
        _log,
        set_value,
        set_many,
    ):
        controller = self._controller()

        controller._change_auto_check(SimpleNamespace(control=SimpleNamespace(value=False)))

        self.assertFalse(controller.auto_download.value)
        set_many.assert_called_with({
            "update_auto_check": False,
            "update_auto_download": False,
        })
        set_value.assert_not_called()

    @patch("updater_controller.cfg_get", return_value=False)
    def test_available_state_shows_header_badge(self, _get):
        controller = self._controller()

        controller._set_state("available", "Versión 2.1.3 disponible", "Lista para descargar")
        self.assertTrue(controller.appbar_badge.label_visible)
        self.assertEqual(controller.appbar_button.tooltip, "Versión 2.1.3 disponible")

        controller._set_state("current", "Actualizado", "Versión actual")
        self.assertFalse(controller.appbar_badge.label_visible)

    @patch("updater_controller.cfg_get", return_value=False)
    def test_header_click_checks_and_offers_download(self, _get):
        controller = self._controller()
        calls = []
        controller._snack = lambda message: calls.append(("snack", message))
        controller.check_async = lambda **kwargs: calls.append(("check", kwargs))

        controller.appbar_action()

        self.assertEqual(calls[0][0], "snack")
        self.assertEqual(
            calls[1],
            ("check", {"manual": True, "offer_download": True}),
        )

    @patch("updater_controller.cfg_get", return_value=False)
    def test_header_available_update_opens_offer_instead_of_direct_download(self, _get):
        info = _update_info()
        controller = self._controller(info=info)
        controller.state = "available"
        controller.current_info = info
        calls = []
        controller._show_available_dialog = lambda **kwargs: calls.append(kwargs)

        controller.appbar_action()

        self.assertEqual(calls, [{"navigate_before_download": True}])

    @patch("updater_controller.cfg_get", return_value=False)
    def test_accepting_header_offer_navigates_before_downloading(self, _get):
        controller = self._controller()
        info = _update_info()
        dialog = SimpleNamespace(open=True)
        events = []
        controller._safe_update = lambda *_controls: None
        controller._open_settings = lambda: events.append("settings")
        controller.download_async = lambda selected: events.append(("download", selected.version))

        controller._download_from_dialog(
            dialog,
            info,
            navigate_to_settings=True,
        )

        self.assertFalse(dialog.open)
        self.assertEqual(events, ["settings", ("download", "2.1.3")])

    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    def test_background_detection_notifies_when_auto_download_is_off(self, _log, _set):
        info = _update_info()
        notifications = []
        config = {
            "update_auto_check": True,
            "update_auto_download": False,
        }
        with patch("updater_controller.cfg_get", side_effect=lambda key: config.get(key)):
            controller = self._controller(info=info, notifications=notifications)
            downloads = []
            controller.download_async = lambda selected: downloads.append(selected)
            controller._check_worker(False)

        self.assertEqual(controller.state, "available")
        self.assertEqual(downloads, [])
        self.assertEqual(len(notifications), 1)
        self.assertIn("2.1.3", notifications[0][1])

    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    def test_background_detection_downloads_when_auto_download_is_on(self, _log, _set):
        info = _update_info()
        notifications = []
        config = {
            "update_auto_check": True,
            "update_auto_download": True,
        }
        with patch("updater_controller.cfg_get", side_effect=lambda key: config.get(key)):
            controller = self._controller(info=info, notifications=notifications)
            downloads = []
            controller.download_async = lambda selected: downloads.append(selected)
            controller._check_worker(False)

        self.assertEqual(downloads, [info])
        self.assertEqual(len(notifications), 1)
        self.assertIn("automáticamente", notifications[0][1])

    @patch("updater_controller.cfg_set")
    @patch("updater_controller.append_runtime_log")
    def test_manual_check_reports_when_already_current(self, _log, _set):
        messages = []
        with patch("updater_controller.cfg_get", return_value=False):
            controller = self._controller(info=None)
            controller._snack = lambda message: messages.append(message)
            controller._check_worker(True)

        self.assertEqual(controller.state, "current")
        self.assertEqual(messages, ["ToolKit SISMED ya tiene la versión más reciente."])

    @patch("updater_controller.cfg_get", return_value=False)
    def test_request_guard_prevents_duplicate_checks(self, _get):
        controller = self._controller()

        self.assertTrue(controller._reserve_request("check"))
        self.assertFalse(controller._reserve_request("check"))
        controller._release_request("check")
        self.assertTrue(controller._reserve_request("check"))

    @patch("updater_controller.cfg_get", return_value=False)
    def test_request_guard_prevents_download_during_check(self, _get):
        controller = self._controller()

        self.assertTrue(controller._reserve_request("check"))
        self.assertFalse(controller._reserve_request("download"))
        controller._release_request("check")
        self.assertTrue(controller._reserve_request("download"))

    @patch("updater_controller.cfg_get", return_value=True)
    def test_scheduler_wake_event_does_not_wait_for_full_interval(self, _get):
        controller = self._controller()
        controller.INTERACTIVE_INITIAL_DELAY_SECONDS = 60
        controller.CHECK_INTERVAL_SECONDS = 60
        checked = threading.Event()
        controller.check_async = lambda **_kwargs: checked.set()

        controller.start()
        controller.scheduler_wake_event.set()

        self.assertTrue(checked.wait(timeout=1))
        controller.stop()

    @patch("updater_controller.cfg_get", return_value=False)
    def test_start_does_not_create_two_scheduler_threads(self, _get):
        controller = self._controller()
        controller.INTERACTIVE_INITIAL_DELAY_SECONDS = 60

        controller.start()
        first_thread = controller.scheduler_thread
        controller.start()

        self.assertIs(controller.scheduler_thread, first_thread)
        controller.stop()


if __name__ == "__main__":
    unittest.main()
