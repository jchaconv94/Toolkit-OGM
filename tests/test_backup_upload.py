import hashlib
import os
import sys
import tempfile
import threading
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

    def __init__(self, fail_part=None, fail_times=1, fail_status=None, delay=0.0):
        self.calls = []
        self.lock = threading.Lock()
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.completed = None
        self.parts = {}
        self.bodies = []
        self.fail_part = fail_part
        self.fail_times = fail_times
        self.fail_status = fail_status

    def post(self, url, headers=None, timeout=None, json=None):
        self.calls.append(("POST", url, headers))
        if url.endswith("/complete"):
            self.completed = json
        return _Resp(200, {"ok": True})

    def put(self, url, data=None, headers=None, timeout=None):
        number = int(url.rsplit("/", 1)[1])
        with self.lock:
            self.calls.append(("PUT", url, headers))
            failing = number == self.fail_part and self.fail_times > 0
            if failing:
                self.fail_times -= 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
        finally:
            with self.lock:
                self.active -= 1
        if failing:
            if self.fail_status:
                return _Resp(self.fail_status, {"error": "no"})
            raise backup_upload.requests.ConnectionError("corte")
        self.bodies.append(data)
        self.parts[number] = data.read() if hasattr(data, "read") else data
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

    def _uploader(self, session, part_size=1000, max_bytes=10_000, parallel=1):
        return BackupUploader("https://svc", "job-1", "tok", part_size, max_bytes,
                              send=self.sent.append, log=lambda _m: None, session=session, sleep=lambda _s: None,
                              parallel=parallel)

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

    def test_several_parts_at_once_are_assembled_in_order(self):
        session = _Session(delay=0.2)
        self.assertTrue(self._uploader(session, parallel=3).run(self.tmp.name, "030S05"))
        self.assertGreaterEqual(session.max_active, 2)
        self.assertEqual(b"".join(session.parts[n] for n in sorted(session.parts)), self.data)
        self.assertEqual([p["partNumber"] for p in session.completed["parts"]], [1, 2, 3])
        progress = [m["sent"] for m in self.sent if m["t"] == "backup_progress"]
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 2500)

    def test_a_part_that_cannot_be_sent_stops_the_rest(self):
        session = _Session(fail_part=1, fail_status=403, delay=0.05)
        self.assertFalse(self._uploader(session, parallel=2).run(self.tmp.name, "030S05"))
        self.assertEqual(self.sent[-1]["t"], "backup_error")
        self.assertIsNone(session.completed)

    def test_the_backup_details_also_go_with_the_start_of_the_upload(self):
        session = _Session()
        starts = []
        original = session.post

        def post(url, headers=None, timeout=None, json=None):
            if url.endswith("/start"):
                starts.append(json)
            return original(url, headers=headers, timeout=timeout, json=json)

        session.post = post
        self.assertTrue(self._uploader(session).run(self.tmp.name, "030S05"))
        self.assertEqual(starts[0]["name"], "BKDA202610011300.zip")
        self.assertEqual(starts[0]["size"], 2500)
        self.assertEqual(starts[0]["sha256"], hashlib.sha256(self.data).hexdigest())

    def test_an_older_service_that_asks_for_the_details_is_retried(self):
        session = _Session()
        answers = iter([409, 409, 200])
        original = session.post

        def post(url, headers=None, timeout=None, json=None):
            if url.endswith("/start"):
                status = next(answers)
                if status == 409:
                    return _Resp(409, {"error": "Falta informar el backup (nombre y tamaño)"})
            return original(url, headers=headers, timeout=timeout, json=json)

        session.post = post
        self.assertTrue(self._uploader(session).run(self.tmp.name, "030S05"))

    def test_if_the_cloud_already_has_it_nothing_is_uploaded(self):
        session = _Session()
        original = session.post

        def post(url, headers=None, timeout=None, json=None):
            if url.endswith("/start"):
                return _Resp(200, {"ok": True, "reused": True})
            return original(url, headers=headers, timeout=timeout, json=json)

        session.post = post
        uploader = self._uploader(session)
        self.assertTrue(uploader.run(self.tmp.name, "030S05"))
        self.assertFalse(any(c[0] == "PUT" for c in session.calls))
        self.assertFalse(any(m["t"] == "backup_error" for m in self.sent))
        self.assertEqual(uploader.path.name, "BKDA202610011300.zip")

    def test_parallel_is_kept_between_1_and_8(self):
        self.assertEqual(self._uploader(_Session(), parallel=0).parallel, 1)
        self.assertEqual(self._uploader(_Session(), parallel=50).parallel, 8)

    def test_parts_go_as_file_so_they_are_sent_in_blocks(self):
        session = _Session()
        self.assertTrue(self._uploader(session).run(self.tmp.name, "030S05"))
        self.assertTrue(all(hasattr(body, "read") for body in session.bodies))

    def test_too_big_or_missing_is_reported(self):
        self.assertFalse(self._uploader(_Session(), max_bytes=100).run(self.tmp.name, "030S05"))
        self.assertIn("pesa", self.sent[-1]["reason"])
        self.assertFalse(self._uploader(_Session()).run(str(Path(self.tmp.name) / "nada"), "030S05"))
        self.assertIn("No hay backups", self.sent[-1]["reason"])


class ProgressTests(unittest.TestCase):
    def test_reports_inside_a_part_only_upwards_and_at_most_every_interval(self):
        now = [0.0]
        seen = []
        progress = backup_upload._Progress(100, seen.append, every=2.0, clock=lambda: now[0])
        progress.start(1)
        progress.add(1, 10)          # todavía no pasaron 2 s
        now[0] = 2.5
        progress.add(1, 10)          # 20
        progress.start(1)            # un reintento vuelve a cero: no se avisa menos
        now[0] = 5.0
        progress.add(1, 5)
        progress.finish(1, 60)       # al terminar una parte se avisa siempre
        self.assertEqual(seen, [20, 60])


class SlowLinkTests(unittest.TestCase):
    """Con la red real: un servicio que recibe lento (como un internet de subida lento).

    Mientras envía, urllib3 solo espera el tiempo de conexión. Una parte enviada como bytes
    debía salir entera en ese tiempo; como archivo, cada bloque tiene el suyo.
    """

    def setUp(self):
        import socket
        import threading

        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.addCleanup(self.server.close)
        self.port = self.server.getsockname()[1]

        def handle(conn):
            received = b""
            try:
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                while b"\r\n\r\n" not in received:
                    received += conn.recv(65536)
                head, body = received.split(b"\r\n\r\n", 1)
                length = int(next(line.split(b":")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")))
                got = len(body)
                while got < length:
                    data = conn.recv(65536)
                    if not data:
                        return
                    got += len(data)
                    time.sleep(0.02)  # unos 3 MB/s
                answer = b'{"partNumber": 1, "etag": "e1"}'
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(answer)).encode() + b"\r\nConnection: close\r\n\r\n" + answer)
            except OSError:
                pass
            finally:
                conn.close()

        def serve():
            while True:
                try:
                    conn, _ = self.server.accept()
                except OSError:
                    return
                threading.Thread(target=handle, args=(conn,), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()
        original = backup_upload.REQUEST_TIMEOUT
        backup_upload.REQUEST_TIMEOUT = (1, 60)
        self.addCleanup(setattr, backup_upload, "REQUEST_TIMEOUT", original)

    def test_slow_upload_of_a_big_part_does_not_time_out(self):
        uploader = BackupUploader(f"http://127.0.0.1:{self.port}", "job-1", "tok", 8 * 1024 * 1024, 10**9,
                                  send=lambda _m: None, log=lambda _m: None, sleep=lambda _s: None)
        part = uploader._upload_part(1, b"x" * (8 * 1024 * 1024))
        self.assertEqual(part, {"partNumber": 1, "etag": "e1"})



if __name__ == "__main__":
    unittest.main()
