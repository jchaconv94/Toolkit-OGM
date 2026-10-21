import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import activity  # noqa: E402
import app_loader  # noqa: E402
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
