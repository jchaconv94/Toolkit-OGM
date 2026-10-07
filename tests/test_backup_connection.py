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
