"""Copia en la nube: la PC sube sola cada backup nuevo del SISMED (2.3.9 la de la mañana; 2.3.10 todos)."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import backup_connection  # noqa: E402
import backup_upload  # noqa: E402
from backup_upload import BackupUploader, BackupWatcher, find_latest_backup  # noqa: E402


class LatestBackupTests(unittest.TestCase):
    """Desde la 2.3.10 la copia es cada backup nuevo, no solo el de la mañana."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "backup"
        self.folder.mkdir()
        self.now = datetime(2026, 10, 16, 15, 0).timestamp()

    def _file(self, name, minutes_ago):
        path = self.folder / name
        path.write_bytes(b"x" * 10)
        t = self.now - minutes_ago * 60
        os.utime(path, (t, t))
        return path

    def test_takes_the_one_at_13_after_the_morning_one(self):
        self._file("BKDA202610150805.zip", 60 * 24)
        self._file("BKDA202610160812.zip", 400)
        self._file("BKDA202610161300.zip", 120)
        self.assertEqual(find_latest_backup(self.tmp.name, self.now).name, "BKDA202610161300.zip")

    def test_while_the_new_one_is_being_written_it_stays_with_the_previous(self):
        self._file("BKDA202610160812.zip", 400)
        self._file("BKDA202610161459.zip", 0.5)
        self.assertEqual(find_latest_backup(self.tmp.name, self.now).name, "BKDA202610160812.zip")


class _SlowSession:
    """Lee el cuerpo despacio, como una red lenta; así se puede cancelar a la mitad."""

    def __init__(self):
        self.reads = 0

    def post(self, url, headers=None, timeout=None, json=None):
        class R:
            status_code = 200

            def json(self):
                return {"ok": True}
        return R()

    def put(self, url, data=None, headers=None, timeout=None):
        while data.read(1024):
            self.reads += 1
            time.sleep(0.01)
        raise AssertionError("no debió terminar")


class CancelTests(unittest.TestCase):
    def test_cancel_cuts_the_part_in_course_and_reports_why(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "backup"
        folder.mkdir()
        path = folder / "BKDA202610160812.zip"
        path.write_bytes(os.urandom(200_000))
        t = time.time() - 3600
        os.utime(path, (t, t))
        sent = []
        uploader = BackupUploader("https://svc", "job", "tok", 200_000, 10**9, send=sent.append,
                                  log=lambda _m: None, session=_SlowSession(), sleep=lambda _s: None, parallel=1)
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault("ok", uploader.run(tmp.name, "06502", path=path)))
        worker.start()
        time.sleep(0.15)
        started = time.monotonic()
        uploader.cancel("Se detuvo para atender un pedido de la web")
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(result["ok"])
        self.assertEqual(sent[-1]["t"], "backup_error")
        self.assertIn("pedido de la web", sent[-1]["reason"])


def _zip(path: Path, text: str = "datos"):
    """Un backup de prueba: un zip completo, como el que deja el SISMED."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("datos.dbf", text)


class _Ws:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(json.loads(text))


class CopyOfferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name) / "backup"
        folder.mkdir()
        today = datetime.now().strftime("%Y%m%d")
        self.path = folder / f"BKDA{today}0001.zip"
        _zip(self.path, "copia de prueba")
        t = time.time() - 600
        os.utime(self.path, (t, t))
        self.state = Path(self.tmp.name) / "conocidos.json"
        self.conn = self._connection()
        self.ws = _Ws()

    def _connection(self):
        conn = backup_connection.BackupConnection(
            log=lambda _m: None, get_keys=lambda: "06502-AAAA", get_device_id=lambda: "d",
            get_equipo=lambda: "PC", get_base_dir=lambda: self.tmp.name)
        conn._watcher = BackupWatcher(state_path=self.state, created=lambda st: st.st_mtime)
        return conn

    def test_offers_the_latest_backup_once(self):
        self.conn._offer_copy(self.ws)
        self.assertEqual(len(self.ws.sent), 1)
        offer = self.ws.sent[0]
        self.assertEqual((offer["t"], offer["code"], offer["name"]), ("copy_offer", "06502", self.path.name))
        self.assertEqual(len(offer["sha256"]), 64)
        self.conn._offer_copy(self.ws)  # ya ofrecida: no se repite hasta saber qué pasó
        self.assertEqual(len(self.ws.sent), 1)

    def test_a_newer_backup_is_offered_even_after_the_previous_one_was_uploaded(self):
        self.conn._offer_copy(self.ws)
        self.conn._copy_skipped({"code": "06502", "reason": "La nube ya tiene esta copia"})
        newer = self.path.with_name(self.path.name.replace("0001", "1300"))
        _zip(newer, "backup de la tarde")
        t = time.time() - 300
        os.utime(newer, (t, t))
        self.conn._offer_copy(self.ws)
        self.assertEqual([m["name"] for m in self.ws.sent], [self.path.name, newer.name])

    def test_no_second_offer_while_the_first_waits_for_an_answer(self):
        self.conn._offer_copy(self.ws)
        newer = self.path.with_name(self.path.name.replace("0001", "1300"))
        _zip(newer, "backup de la tarde")
        t = time.time() - 300
        os.utime(newer, (t, t))
        self.conn._offer_copy(self.ws)
        self.assertEqual([m["name"] for m in self.ws.sent], [self.path.name])
        self.conn._copy_skipped({"code": "06502", "reason": "La nube ya tiene esta copia"})
        self.conn._offer_copy(self.ws)
        self.assertEqual([m["name"] for m in self.ws.sent], [self.path.name, newer.name])

    def test_what_a_web_request_uploaded_is_not_offered_again(self):
        target = path = self.path

        class FakeUploader:
            def __init__(self, **kwargs):
                self.path = None

            def run(self, base_dir, code, path=None):
                self.path = target
                return True

        original = backup_connection.BackupUploader
        backup_connection.BackupUploader = FakeUploader
        self.addCleanup(setattr, backup_connection, "BackupUploader", original)
        self.conn._start_backup(self.ws, {"t": "backup", "job": "j9", "code": "06502", "token": "t"})
        for _ in range(50):
            if ("06502", path.name) in self.conn._copy_seen and not self.conn._upload_lock.locked():
                break
            time.sleep(0.02)
        self.assertTrue(self.conn._copy_seen[("06502", path.name)][1])
        self.conn._offer_copy(self.ws)
        self.assertEqual(self.ws.sent, [])

    def test_if_the_cloud_has_it_it_is_not_offered_again_otherwise_it_retries_later(self):
        self.conn._offer_copy(self.ws)
        self.conn._copy_skipped({"code": "06502", "reason": "La nube ya tiene esta copia"})
        self.assertEqual(self.conn._copy_seen[("06502", self.path.name)][1], True)

        other = self._connection()
        other._watcher = BackupWatcher(state_path=Path(self.tmp.name) / "otro.json", created=lambda st: st.st_mtime)
        other._offer_copy(self.ws)
        other._copy_skipped({"code": "06502", "reason": "La nube está cerca del límite gratuito"})
        at, finished = other._copy_seen[("06502", self.path.name)]
        self.assertFalse(finished)
        self.assertFalse(other._copy_due("06502", self.path.name, at + 60))
        self.assertTrue(other._copy_due("06502", self.path.name, at + backup_connection.COPY_RETRY_SECONDS + 1))

    def test_copy_go_uploads_that_file_with_one_connection_and_marks_it_done(self):
        calls = {}

        class FakeUploader:
            def __init__(self, **kwargs):
                calls["kwargs"] = kwargs

            def run(self, base_dir, code, path=None):
                calls["run"] = (code, path)
                return True

            def cancel(self, reason=""):
                pass

        original = backup_connection.BackupUploader
        backup_connection.BackupUploader = FakeUploader
        self.addCleanup(setattr, backup_connection, "BackupUploader", original)
        self.conn._offer_copy(self.ws)
        self.conn._start_copy(self.ws, {"t": "copy_go", "job": "j1", "code": "06502", "token": "t", "partSize": 5, "parallel": 1})
        for _ in range(50):
            if not self.conn._upload_lock.locked() and "run" in calls:
                break
            time.sleep(0.02)
        self.assertEqual(calls["run"], ("06502", self.path))
        self.assertEqual(calls["kwargs"]["parallel"], 1)
        self.assertEqual(self.conn._copy_seen[("06502", self.path.name)][1], True)
        self.assertFalse(self.conn._upload_lock.locked())

    def test_a_web_request_cuts_the_copy_in_course(self):
        events = []

        class SlowCopy:
            def cancel(self, reason=""):
                events.append(("cancel", reason))
                threading.Timer(0.1, self.conn_release).start()

        copy = SlowCopy()
        self.conn._upload_lock.acquire()
        copy.conn_release = self.conn._upload_lock.release
        self.conn._copy_uploader = copy

        class FakeUploader:
            def __init__(self, **kwargs):
                pass

            def run(self, base_dir, code, path=None):
                events.append(("request", code))
                return True

        original = backup_connection.BackupUploader
        backup_connection.BackupUploader = FakeUploader
        self.addCleanup(setattr, backup_connection, "BackupUploader", original)
        self.conn._start_backup(self.ws, {"t": "backup", "job": "j2", "code": "06502", "token": "t"})
        for _ in range(100):
            if ("request", "06502") in events:
                break
            time.sleep(0.02)
        self.assertEqual(events[0][0], "cancel")
        self.assertIn("pedido de la web", events[0][1])
        self.assertIn(("request", "06502"), events)


if __name__ == "__main__":
    unittest.main()


class WatcherTests(unittest.TestCase):
    """El más reciente es el último que apareció en la carpeta, no el de fecha más alta (2026-10-18)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "backup"
        self.folder.mkdir()
        self.state = Path(self.tmp.name) / "conocidos.json"
        self.now = [1000.0]

    def watcher(self, created=None):
        # Por omisión, cada archivo es uno recién hecho por el SISMED: se crea y se escribe con el mismo
        # reloj de la PC. Así la prueba no depende de que `os.utime` cambie solo la modificación (en
        # Windows la creación quedaba en hoy y el archivo parecía copiado de otra PC).
        created = created or (lambda st: st.st_mtime)
        return BackupWatcher(state_path=self.state, clock=lambda: self.now[0], created=created)

    def add(self, name, text="datos", mtime=None):
        path = self.folder / name
        _zip(path, text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_first_time_only_the_newest_by_date_is_offered(self):
        self.add("BKDA202610150700.zip", mtime=time.time() - 86400)
        newest = self.add("BKDA202610160700.zip", mtime=time.time() - 60)
        w = self.watcher()
        self.assertEqual(w.candidate(self.tmp.name), newest)
        w.mark_done(newest.name)
        self.assertIsNone(w.candidate(self.tmp.name))

    def test_after_moving_the_date_back_the_real_newest_wins(self):
        # Fin de mes: la PC estuvo en el 25 y la regresaron al 17. El backup del «25» apareció antes.
        w = self.watcher()
        forward = self.add("BKDA202610250800.zip", mtime=time.time() + 8 * 86400)
        self.assertEqual(w.candidate(self.tmp.name), forward)
        w.mark_done(forward.name)
        real = self.add("BKDA202610170730.zip", "otro", mtime=time.time())
        self.assertEqual(w.candidate(self.tmp.name), real)
        self.assertEqual(w.latest(self.tmp.name), real)

    def test_the_order_survives_a_restart_and_what_appeared_meanwhile_is_new(self):
        w = self.watcher()
        first = self.add("BKDA202610170700.zip", mtime=time.time() - 3600)
        self.assertEqual(w.candidate(self.tmp.name), first)
        w.mark_done(first.name)
        # El Toolkit se cierra; mientras tanto el SISMED hace el backup de las 13:00 con la fecha cambiada.
        later = self.add("BKDA202610101300.zip", "tarde", mtime=time.time() - 30 * 86400)
        again = self.watcher()
        self.assertEqual(again.candidate(self.tmp.name), later)

    def test_waits_while_the_newest_is_being_written(self):
        w = self.watcher()
        done = self.add("BKDA202610170700.zip", mtime=time.time() - 3600)
        self.assertEqual(w.candidate(self.tmp.name), done)
        w.mark_done(done.name)
        partial = self.folder / "BKDA202610171300.zip"
        partial.write_bytes(b"PK\x03\x04 a medio escribir")
        self.assertIsNone(w.candidate(self.tmp.name))
        self.assertIsNone(w.latest(self.tmp.name))
        _zip(partial, "terminado")
        self.assertEqual(w.candidate(self.tmp.name), partial)

    def test_a_broken_backup_that_no_longer_grows_is_skipped(self):
        w = self.watcher()
        good = self.add("BKDA202610170700.zip", mtime=time.time() - 3600)
        self.assertEqual(w.latest(self.tmp.name), good)
        broken = self.folder / "BKDA202610171300.zip"
        broken.write_bytes(b"no es un zip")
        self.assertIsNone(w.latest(self.tmp.name))
        self.now[0] += backup_upload.BROKEN_AFTER_SECONDS + 1
        self.assertEqual(w.latest(self.tmp.name), good)

    def test_an_old_backup_copied_into_the_folder_is_ignored(self):
        def created(st):
            # Simula Windows: el «copiado» se creó hoy, su contenido es de hace 10 días.
            return time.time() if st.st_mtime < time.time() - 5 * 86400 else st.st_mtime
        w = self.watcher(created=created)
        good = self.add("BKDA202610170700.zip", mtime=time.time() - 3600)
        self.assertEqual(w.candidate(self.tmp.name), good)
        w.mark_done(good.name)
        self.add("BKDA202610070700.zip", "viejo", mtime=time.time() - 10 * 86400)
        self.assertIsNone(w.candidate(self.tmp.name))
        self.assertEqual(w.latest(self.tmp.name), good)
