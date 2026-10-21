import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import activity  # noqa: E402
import app_loader  # noqa: E402
import update_restart  # noqa: E402
from update_restart import (MAX_ATTEMPTS, RETRY_SECONDS, RestartWatcher, Situation, decide,  # noqa: E402
                            record_attempt)


def situation(**changes):
    base = dict(now=1_000_000.0, pending="2.4.5", hidden_for=3600.0, busy=[], updater_state="code-ready",
                attempts={})
    base.update(changes)
    return Situation(**base)


class DecideTests(unittest.TestCase):
    def test_restarts_when_hidden_idle_and_ready(self):
        self.assertTrue(decide(situation(), idle=1200)[0])

    def test_never_with_the_window_visible(self):
        ok, reason = decide(situation(hidden_for=None), idle=1200)
        self.assertFalse(ok)
        self.assertIn("a la vista", reason)

    def test_waits_until_hidden_long_enough(self):
        self.assertFalse(decide(situation(hidden_for=1199), idle=1200)[0])
        self.assertTrue(decide(situation(hidden_for=1200), idle=1200)[0])

    def test_never_while_something_is_working(self):
        for work in (["Sync SISMED"], ["Backup SISMED"], ["Editar TMOVIM"], ["Copia del backup"]):
            ok, reason = decide(situation(busy=work), idle=1200)
            self.assertFalse(ok)
            self.assertIn(work[0], reason)

    def test_never_while_the_updater_is_busy(self):
        for state in ("checking", "downloading", "installing"):
            self.assertFalse(decide(situation(updater_state=state), idle=1200)[0])

    def test_nothing_pending_means_nothing_to_do(self):
        self.assertFalse(decide(situation(pending=None), idle=1200)[0])

    def test_retries_are_spaced_and_capped(self):
        now = 1_000_000.0
        once = {"2.4.5": [1, now - 60]}
        self.assertFalse(decide(situation(attempts=once), idle=1200)[0])
        later = {"2.4.5": [1, now - RETRY_SECONDS - 1]}
        self.assertTrue(decide(situation(attempts=later), idle=1200)[0])
        capped = {"2.4.5": [MAX_ATTEMPTS, now - 10 * RETRY_SECONDS]}
        self.assertFalse(decide(situation(attempts=capped), idle=1200)[0])
        # Otra versión no hereda los intentos.
        self.assertTrue(decide(situation(pending="2.4.6", attempts=capped), idle=1200)[0])

    def test_clock_moved_back_allows_a_retry_but_the_cap_still_holds(self):
        future = {"2.4.5": [1, 1_000_000.0 + 3600]}
        self.assertTrue(decide(situation(attempts=future), idle=1200)[0])

    def test_record_attempt_counts_and_keeps_few_versions(self):
        attempts = {}
        for i, version in enumerate(["2.4.1", "2.4.2", "2.4.3", "2.4.4", "2.4.5", "2.4.6"]):
            attempts = record_attempt(attempts, version, float(i))
        attempts = record_attempt(attempts, "2.4.6", 10.0)
        self.assertEqual(attempts["2.4.6"], [2, 10.0])
        self.assertLessEqual(len(attempts), 5)
        self.assertNotIn("2.4.1", attempts)


class WatcherTests(unittest.TestCase):
    def test_checks_again_right_before_restarting(self):
        states = [situation(), situation(busy=["Sync SISMED"])]
        restarted = []
        watcher = RestartWatcher(lambda: states.pop(0), lambda v: restarted.append(v) or True, lambda m: None)
        with mock.patch.dict(os.environ, {"TOOLKIT_RESTART_IDLE_SECONDS": "1200"}):
            self.assertFalse(watcher.check_once())
        self.assertEqual(restarted, [])

    def test_restarts_with_the_pending_version(self):
        restarted = []
        watcher = RestartWatcher(lambda: situation(), lambda v: restarted.append(v) or True, lambda m: None)
        with mock.patch.dict(os.environ, {"TOOLKIT_RESTART_IDLE_SECONDS": "1200"}):
            self.assertTrue(watcher.check_once())
        self.assertEqual(restarted, ["2.4.5"])

    def test_logs_only_changes_and_survives_errors(self):
        logs = []
        watcher = RestartWatcher(lambda: situation(hidden_for=None), lambda v: True, logs.append)
        for _ in range(3):
            watcher.check_once()
        self.assertEqual(len(logs), 1)

        def boom():
            raise RuntimeError("falla")
        watcher = RestartWatcher(boom, lambda v: True, logs.append)
        with mock.patch.dict(os.environ, {"TOOLKIT_RESTART_CHECK_SECONDS": "1"}):
            thread = threading.Thread(target=watcher.run, daemon=True)
            thread.start()
            thread.join(2.5)
            watcher.stop()
        self.assertTrue(any("no se pudo revisar" in m for m in logs))


class ActivityTests(unittest.TestCase):
    def test_busy_marks_and_clears_even_on_errors(self):
        self.assertEqual(activity.active(), [])
        with activity.busy("Generar ICI"):
            with activity.busy("Generar ICI"):
                self.assertEqual(activity.active(), ["Generar ICI"])
            self.assertEqual(activity.active(), ["Generar ICI"])
        self.assertEqual(activity.active(), [])
        with self.assertRaises(ValueError), activity.busy("Editar TMOVIM"):
            raise ValueError
        self.assertEqual(activity.active(), [])

    def test_background_jobs_count_while_they_run(self):
        release = threading.Event()
        started = threading.Event()

        def job():
            started.set()
            release.wait(5)

        thread = activity.background("Disponibilidad", job)
        started.wait(5)
        self.assertEqual(activity.active(), ["Disponibilidad"])
        release.set()
        thread.join(5)
        self.assertEqual(activity.active(), [])

    def test_test_file_hook(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "ocupado"
            with mock.patch.dict(os.environ, {"TOOLKIT_TEST_ACTIVITY_FILE": str(flag)}):
                self.assertEqual(activity.active(), [])
                flag.write_text("x")
                self.assertEqual(activity.active(), ["prueba"])


class SyncMarksItsWorkTests(unittest.TestCase):
    def test_each_sync_cycle_counts_as_work(self):
        try:
            from sismed_sync import SismedSyncManager
        except Exception as exc:  # noqa: BLE001 - depende de librerías de Windows
            self.skipTest(f"sismed_sync no se puede importar aquí: {exc}")
        seen = []
        manager = SismedSyncManager()

        def perform_sync():
            seen.append(activity.active())
            manager._stop_event.set()

        with mock.patch.object(manager, "perform_sync", perform_sync), \
                mock.patch.object(manager, "_set_run_state"), mock.patch.object(manager, "_stop_backup_connection"), \
                mock.patch.object(manager, "log"):
            manager._sync_loop()
        self.assertEqual(seen, [["Sync SISMED"]])
        self.assertEqual(activity.active(), [])


class SyncAfterRestartTests(unittest.TestCase):
    """El reinicio silencioso deja Sync SISMED (y la conexión de los backups) como estaba."""

    def test_the_new_toolkit_is_told_how_sync_was(self):
        on = update_restart.restart_args(True)
        off = update_restart.restart_args(False)
        self.assertEqual(on[:2], list(update_restart.RESTART_ARGS))
        self.assertIs(update_restart.sync_choice(["ToolkitOGM.exe", *on, "--wait-pid", "12"]), True)
        self.assertIs(update_restart.sync_choice(["ToolkitOGM.exe", *off, "--wait-pid", "12"]), False)
        # Al encender Windows o abrirlo a mano manda la casilla «Iniciar al encender».
        self.assertIsNone(update_restart.sync_choice(["ToolkitOGM.exe", "--autorun"]))

    def tool(self, auto_start: bool):
        try:
            from tools.sync_sismed_tool import SyncSismedTool
        except Exception as exc:  # noqa: BLE001 - depende de flet
            self.skipTest(f"sync_sismed_tool no se puede importar aquí: {exc}")
        tool = SyncSismedTool()
        tool.sync_manager = SimpleNamespace(is_running=False)
        started = []
        patches = [
            mock.patch.object(tool, "_init_components"),
            mock.patch.object(tool, "_load_saved_preferences"),
            mock.patch.object(tool, "_record_autostart_result"),
            mock.patch.object(tool, "_cfg_bool", lambda name, default=False: auto_start),
            mock.patch.object(tool, "_start_sync_if_valid", lambda page, source: started.append(source) or True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return tool, started

    def test_sync_started_by_hand_comes_back_after_the_restart(self):
        tool, started = self.tool(auto_start=False)
        self.assertTrue(tool.start_from_saved(None, resume=True))
        self.assertEqual(started, ["autostart"])

    def test_sync_stopped_on_purpose_stays_stopped(self):
        tool, started = self.tool(auto_start=True)
        self.assertFalse(tool.start_from_saved(None, resume=False))
        self.assertEqual(started, [])
        tool._record_autostart_result.assert_called_with("kept-off-after-update-restart")

    def test_a_normal_start_follows_the_checkbox(self):
        tool, started = self.tool(auto_start=False)
        self.assertFalse(tool.start_from_saved(None))
        tool, started = self.tool(auto_start=True)
        self.assertTrue(tool.start_from_saved(None))
        self.assertEqual(started, ["autostart"])

    def test_main_passes_the_sync_state_to_the_new_toolkit(self):
        text = (TOOLKIT_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn("update_restart.restart_args(sync_running)", text)
        self.assertIn("resume=update_restart.sync_choice(sys.argv)", text)
        self.assertNotIn("*update_restart.RESTART_ARGS", text)


class WaitForPreviousTests(unittest.TestCase):
    def test_ignores_missing_or_bad_arguments(self):
        app_loader.wait_for_previous(["ToolkitOGM.exe", "--autorun"])
        app_loader.wait_for_previous(["ToolkitOGM.exe", "--wait-pid"])
        app_loader.wait_for_previous(["ToolkitOGM.exe", "--wait-pid", "x"])


class ToolsMarkTheirWorkTests(unittest.TestCase):
    def test_no_tool_starts_an_unmarked_thread(self):
        for path in (TOOLKIT_DIR / "tools").glob("*_tool.py"):
            self.assertNotIn("threading.Thread(", path.read_text(encoding="utf-8"), path.name)
        for name in ("backup_connection.py", "sismed_sync.py"):
            text = (TOOLKIT_DIR / name).read_text(encoding="utf-8")
            self.assertIn("activity.", text, name)


if __name__ == "__main__":
    unittest.main()
