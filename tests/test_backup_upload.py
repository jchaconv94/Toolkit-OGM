import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import backup_upload  # noqa: E402
from backup_upload import BackupUploader, find_latest_backup, service_http_base  # noqa: E402


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class _Session:
    """Servicio simulado: guarda lo que recibe; puede fallar una parte."""

    def __init__(self, fail_part=None, fail_times=1, fail_status=None):
        self.calls = []
        self.parts = {}
        self.fail_part = fail_part
        self.fail_times = fail_times
        self.fail_status = fail_status

    def post(self, url, headers=None, timeout=None, json=None):
        self.calls.append(("POST", url, headers))
        return _Resp(200, {"ok": True})

    def put(self, url, data=None, headers=None, timeout=None):
        number = int(url.rsplit("/", 1)[1])
        self.calls.append(("PUT", url, headers))
        if number == self.fail_part and self.fail_times > 0:
            self.fail_times -= 1
            if self.fail_status:
                return _Resp(self.fail_status, {"error": "no"})
            raise backup_upload.requests.ConnectionError("corte")
        self.parts[number] = data
        return _Resp(200, {"partNumber": number, "etag": f"e{number}"})


class FindLatestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "backup"
        self.folder.mkdir()

    def _file(self, name, age_seconds, size=10):
        path = self.folder / name
        path.write_bytes(b"x" * size)
        t = time.time() - age_seconds
        os.utime(path, (t, t))
        return path

    def test_newest_finished_backup_wins(self):
        self._file("BKDA202609300812.Zip", 86400)
        newest = self._file("BKDA202610011300.zip", 3600)
        self._file("BKDA202610011500.zip", 10)  # todavía escribiéndose
        self._file("otro.zip", 1)
        self._file("BKDA202610011400.zip", 600, size=0)  # vacío
        self.assertEqual(find_latest_backup(self.tmp.name), newest)

    def test_without_folder_or_backups(self):
        self.assertIsNone(find_latest_backup(str(Path(self.tmp.name) / "no-existe")))
        self.assertIsNone(find_latest_backup(self.tmp.name))

    def test_service_base(self):
        self.assertEqual(service_http_base("wss://x.workers.dev/pc"), "https://x.workers.dev")


class UploaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name) / "backup"
        folder.mkdir()
        self.data = os.urandom(2500)
        path = folder / "BKDA202610011300.zip"
        path.write_bytes(self.data)
        t = time.time() - 3600
        os.utime(path, (t, t))
        self.sent = []

    def _uploader(self, session, part_size=1000, max_bytes=10_000):
        return BackupUploader("https://svc", "job-1", "tok", part_size, max_bytes,
                              send=self.sent.append, log=lambda _m: None, session=session, sleep=lambda _s: None)

    def test_uploads_in_parts_with_meta_and_progress(self):
        session = _Session()
        self.assertTrue(self._uploader(session).run(self.tmp.name, "030S05"))
        meta = self.sent[0]
        self.assertEqual(meta["t"], "backup_meta")
        self.assertEqual(meta["sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(meta["size"], 2500)
        self.assertEqual(b"".join(session.parts[n] for n in sorted(session.parts)), self.data)
        self.assertEqual([m["sent"] for m in self.sent if m["t"] == "backup_progress"], [1000, 2000, 2500])
        self.assertTrue(all(c[2]["X-Job-Token"] == "tok" for c in session.calls))
        self.assertTrue(session.calls[-1][1].endswith("/complete"))

    def test_network_cut_retries_only_that_part(self):
        session = _Session(fail_part=2, fail_times=2)
        self.assertTrue(self._uploader(session).run(self.tmp.name, "030S05"))
        puts = [c[1].rsplit("/", 1)[1] for c in session.calls if c[0] == "PUT"]
        self.assertEqual(puts, ["1", "2", "2", "2", "3"])

    def test_forbidden_part_does_not_retry_and_reports(self):
        session = _Session(fail_part=1, fail_status=403)
        self.assertFalse(self._uploader(session).run(self.tmp.name, "030S05"))
        self.assertEqual(sum(1 for c in session.calls if c[0] == "PUT"), 1)
        self.assertEqual(self.sent[-1]["t"], "backup_error")

    def test_too_big_or_missing_is_reported(self):
        self.assertFalse(self._uploader(_Session(), max_bytes=100).run(self.tmp.name, "030S05"))
        self.assertIn("pesa", self.sent[-1]["reason"])
        self.assertFalse(self._uploader(_Session()).run(str(Path(self.tmp.name) / "nada"), "030S05"))
        self.assertIn("No hay backups", self.sent[-1]["reason"])


if __name__ == "__main__":
    unittest.main()
