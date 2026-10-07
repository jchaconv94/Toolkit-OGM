import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import backup_connection  # noqa: E402
from sismed_sync import SismedSyncManager  # noqa: E402


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _conn(keys="030S05-AAAA-BBBB-CCCC"):
    return backup_connection.BackupConnection(log=lambda _m: None, get_keys=lambda: keys,
                                              get_device_id=lambda: "win-A", get_equipo=lambda: "PC")


class EnabledCodesTests(unittest.TestCase):
    def test_asks_only_with_public_key(self):
        with patch.object(backup_connection, "supabase_public_key", return_value=""), \
                patch.object(backup_connection.requests, "post") as post:
            self.assertEqual(_conn().enabled_codes(["030S05"]), [])
        post.assert_not_called()

    def test_returns_enabled_codes(self):
        with patch.object(backup_connection, "supabase_public_key", return_value="pk"), \
                patch.object(backup_connection.requests, "post", return_value=_Resp(200, ["030s05"])) as post:
            self.assertEqual(_conn().enabled_codes(["030S05", "06519"]), ["030S05"])
        self.assertEqual(post.call_args.kwargs["json"], {"p_codes": ["030S05", "06519"]})
        self.assertEqual(post.call_args.kwargs["headers"]["apikey"], "pk")

    def test_missing_function_keeps_it_off(self):
        with patch.object(backup_connection, "supabase_public_key", return_value="pk"), \
                patch.object(backup_connection.requests, "post", return_value=_Resp(404, {})):
            self.assertEqual(_conn().enabled_codes(["030S05"]), [])

    def test_without_key_there_is_nothing_to_connect(self):
        self.assertEqual(_conn(keys="")._keys(), {})
        self.assertEqual(_conn()._keys(), {"030S05": "030S05-AAAA-BBBB-CCCC"})


class RetryAfterLinkTests(unittest.TestCase):
    def test_wakes_only_once_after_a_rejection(self):
        conn = _conn()
        self.assertFalse(conn.retry_after_link())  # nada pendiente: no despierta
        conn._waiting_for_link = True
        self.assertTrue(conn.retry_after_link())
        self.assertTrue(conn._wake.is_set())
        self.assertFalse(conn.retry_after_link())  # una sola vez por rechazo

    def test_does_nothing_while_connected(self):
        conn = _conn()
        conn._waiting_for_link = True
        conn.connected = True
        self.assertFalse(conn.retry_after_link())

    def test_wake_cuts_the_long_wait(self):
        import threading
        import time
        conn = _conn()
        conn._waiting_for_link = True
        threading.Timer(0.2, conn.retry_after_link).start()
        started = time.monotonic()
        self.assertFalse(conn._wait(30))
        self.assertLess(time.monotonic() - started, 5)

    def test_stop_ends_the_wait(self):
        conn = _conn()
        conn.stop()
        self.assertTrue(conn._wait(30))


class DiagnosticLogTests(unittest.TestCase):
    def _conn(self, lines):
        return backup_connection.BackupConnection(log=lines.append, get_keys=lambda: "", get_device_id=lambda: "d", get_equipo=lambda: "PC")

    def test_each_problem_is_logged_once(self):
        lines = []
        conn = self._conn(lines)
        conn._report("unreachable", "sin red")
        conn._report("unreachable", "sin red")
        conn._report("rejected", "rechazada")
        conn._report("unreachable", "sin red")
        self.assertEqual(lines, ["sin red", "rechazada", "sin red"])

    def test_unreachable_service_is_logged_with_its_reason(self):
        lines = []
        conn = self._conn(lines)

        class FakeApp:
            def __init__(self, *_a, on_error=None, **_k):
                self.on_error = on_error

            def run_forever(self, **_k):
                self.on_error(self, ConnectionRefusedError("Connection refused"))

        with patch.object(backup_connection, "websocket") as ws, patch.object(backup_connection, "get_current_version", return_value="2.2.9"), \
                patch.object(backup_connection, "proxy_options", return_value={}):
            ws.WebSocketApp = FakeApp
            self.assertEqual(conn._connect({"06578": "K"}), "error")
            self.assertEqual(conn._connect({"06578": "K"}), "error")
        self.assertEqual(len(lines), 1)
        self.assertIn("Connection refused", lines[0])
        self.assertIn("workers.dev", lines[0])


class ProxyTests(unittest.TestCase):
    def _with(self, proxies, bypass=False):
        with patch.object(backup_connection.urllib.request, "getproxies", return_value=proxies), \
                patch.object(backup_connection.urllib.request, "proxy_bypass", return_value=bypass):
            return backup_connection.proxy_options()

    def test_no_proxy(self):
        self.assertEqual(self._with({}), {})

    def test_system_proxy_is_used(self):
        self.assertEqual(self._with({"https": "http://10.0.0.5:3128"}),
                         {"http_proxy_host": "10.0.0.5", "http_proxy_port": 3128, "proxy_type": "http"})

    def test_windows_style_without_scheme_and_with_credentials(self):
        self.assertEqual(self._with({"http": "proxy.minsa:8080"})["http_proxy_host"], "proxy.minsa")
        opts = self._with({"https": "http://ana:cl%40ve@proxy:80"})
        self.assertEqual(opts["http_proxy_auth"], ("ana", "cl@ve"))

    def test_bypass_and_socks_are_ignored(self):
        self.assertEqual(self._with({"https": "http://10.0.0.5:3128"}, bypass=True), {})
        self.assertEqual(self._with({"https": "socks5://10.0.0.5:1080"}), {})


class SyncIntegrationTests(unittest.TestCase):
    def test_sync_starts_and_stops_the_connection(self):
        manager = SismedSyncManager()
        with patch.object(backup_connection.BackupConnection, "start") as start, \
                patch.object(backup_connection.BackupConnection, "stop") as stop:
            manager._start_backup_connection()
            manager._stop_backup_connection()
        start.assert_called_once()
        stop.assert_called_once()



if __name__ == "__main__":
    unittest.main()
