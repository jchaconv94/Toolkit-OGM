import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from update_shutdown import arm_update_exit_watchdog  # noqa: E402
from window_watch import WindowHeartbeat, flet_view_pids, kill_flet_views  # noqa: E402


class FletViewTests(unittest.TestCase):
    def test_only_flet_children_of_this_process(self):
        processes = [
            (100, 1, "ToolkitOGM.exe"),
            (200, 100, "flet.exe"),
            (201, 100, "FLET.EXE"),
            (300, 100, "ToolkitOGM-Setup-2.3.3.exe"),  # instalador de la actualización: nunca
            (400, 999, "flet.exe"),  # otro Toolkit u otra app
        ]
        self.assertEqual(flet_view_pids(100, processes), [200, 201])

    def test_kills_only_the_window(self):
        calls = []
        me = os.getpid()
        killed = kill_flet_views(
            list_processes=lambda: [(10, me, "flet.exe"), (11, me, "Setup.exe")],
            run=lambda args, **kwargs: calls.append(args),
        )
        self.assertEqual(killed, [10])
        self.assertEqual(calls, [["taskkill", "/F", "/PID", "10"]])

    def test_kill_errors_do_not_stop_the_exit(self):
        def boom(*_args, **_kwargs):
            raise OSError("taskkill no disponible")

        me = os.getpid()
        self.assertEqual(kill_flet_views(list_processes=lambda: [(10, me, "flet.exe")], run=boom), [10])


class ExitWatchdogTests(unittest.TestCase):
    def test_closes_the_window_before_exiting(self):
        order = []
        thread = arm_update_exit_watchdog(
            delay_seconds=0,
            wait=lambda _s: order.append("wait"),
            before_exit=lambda: order.append("kill"),
            exit_process=lambda code: order.append(f"exit:{code}"),
        )
        thread.join(2)
        self.assertEqual(order, ["wait", "kill", "exit:0"])

    def test_exits_even_if_closing_the_window_fails(self):
        order = []

        def boom():
            raise RuntimeError("falló")

        thread = arm_update_exit_watchdog(
            delay_seconds=0, wait=lambda _s: None, before_exit=boom,
            exit_process=lambda code: order.append(code),
        )
        thread.join(2)
        self.assertEqual(order, [0])

    def test_without_hook_behaves_as_before(self):
        order = []
        thread = arm_update_exit_watchdog(delay_seconds=0, wait=lambda _s: None, exit_process=order.append)
        thread.join(2)
        self.assertEqual(order, [0])


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.lines = []
        self.fail = False

        def ping():
            if self.fail:
                raise TimeoutError("sin respuesta")

        self.beat = WindowHeartbeat(ping, self.lines.append, clock=lambda: self.now)

    def test_logs_only_changes(self):
        self.assertTrue(self.beat.check())
        self.assertEqual(self.lines, [])

        self.fail = True
        self.assertFalse(self.beat.check())
        self.now += 300
        self.assertFalse(self.beat.check())
        self.assertEqual(len(self.lines), 1)
        self.assertIn("no responde", self.lines[0])
        self.assertIn("Cerrar completamente", self.lines[0])
        self.assertTrue(self.beat.frozen)

        self.fail = False
        self.now += 600
        self.assertTrue(self.beat.check())
        self.assertEqual(len(self.lines), 2)
        self.assertIn("volvió a responder", self.lines[1])
        self.assertIn("~15 min", self.lines[1])
        self.assertFalse(self.beat.frozen)

    def test_thread_stops(self):
        beat = WindowHeartbeat(lambda: None, self.lines.append, interval_seconds=0.01)
        beat.start()
        beat.stop()
        beat._thread.join(1)
        self.assertFalse(beat._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
