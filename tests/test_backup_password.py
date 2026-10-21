"""Backups del SISMED con contraseña: la copia en la nube tiene que reconocerlos como completos.

Hasta la 2.3.18 se comprobaban con `zipfile.testzip`, que no puede leer un zip con contraseña: el
backup quedaba como dañado y la copia nunca subía (caso del hospital, octubre 2026). Aquí los zips
se arman con cifrado ZipCrypto de verdad, como los del SISMED, y se abren con su contraseña para
comprobar que lo son.
"""

import json
import os
import struct
import sys
import tempfile
import time
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import backup_connection  # noqa: E402
import backup_upload  # noqa: E402
from backup_upload import BackupWatcher, _zip_ok  # noqa: E402

PASSWORD = b"clave-del-sismed"


def _crc_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        table.append(c)
    return table


_TABLE = _crc_table()


class _ZipCrypto:
    """Cifrado tradicional de PKWARE (el que usan los backups con contraseña)."""

    def __init__(self, password: bytes):
        self.keys = [0x12345678, 0x23456789, 0x34567890]
        for byte in password:
            self._update(byte)

    def _crc(self, crc, byte):
        return (crc >> 8) ^ _TABLE[(crc ^ byte) & 0xFF]

    def _update(self, byte):
        k0, k1, k2 = self.keys
        k0 = self._crc(k0, byte)
        k1 = ((k1 + (k0 & 0xFF)) * 134775813 + 1) & 0xFFFFFFFF
        k2 = self._crc(k2, (k1 >> 24) & 0xFF)
        self.keys = [k0, k1, k2]

    def encrypt(self, data: bytes) -> bytes:
        out = bytearray()
        for byte in data:
            t = (self.keys[2] | 2) & 0xFFFF
            out.append(byte ^ (((t * (t ^ 1)) >> 8) & 0xFF))
            self._update(byte)
        return bytes(out)


def encrypted_zip(path: Path, files: dict, password: bytes = PASSWORD):
    """Un zip con contraseña y comprimido, armado a mano como lo deja el SISMED."""
    body, central = bytearray(), bytearray()
    for name, data in files.items():
        raw_name = name.encode()
        crc = zlib.crc32(data) & 0xFFFFFFFF
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        compressed = packer.compress(data) + packer.flush()
        crypto = _ZipCrypto(password)
        header = os.urandom(11) + bytes([crc >> 24])
        encrypted = crypto.encrypt(header + compressed)
        offset = len(body)
        body += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x1, 8, 0, 0x5355, crc, len(encrypted), len(data),
                            len(raw_name), 0) + raw_name + encrypted
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x1, 8, 0, 0x5355, crc, len(encrypted),
                               len(data), len(raw_name), 0, 0, 0, 0, 0, offset) + raw_name
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(files), len(files), len(central), len(body), 0)
    path.write_bytes(bytes(body + central + end))
    return path


SISMED_FILES = {
    "DATOS/MMEDICAM.DBF": b"medicamento " * 4000,
    "DATOS/MSTKALMDE.DBF": os.urandom(20000),
    "DATOS/TFORMDET.DBF": b"ici " * 9000,
}


class PasswordZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = encrypted_zip(Path(self.tmp.name) / "BKDA202610211300.zip", SISMED_FILES)

    def test_the_helper_makes_a_real_password_protected_zip(self):
        with zipfile.ZipFile(self.path) as archive:
            self.assertTrue(all(i.flag_bits & 0x1 for i in archive.infolist()))
            for name, data in SISMED_FILES.items():
                self.assertEqual(archive.read(name, pwd=PASSWORD), data)
            # Lo que se usaba hasta la 2.3.18: no puede leerlo sin la contraseña.
            with self.assertRaises(RuntimeError):
                archive.testzip()

    def test_a_complete_password_protected_backup_counts_as_finished(self):
        self.assertTrue(_zip_ok(self.path))

    def test_a_backup_cut_anywhere_is_not_finished(self):
        data = self.path.read_bytes()
        cut = Path(self.tmp.name) / "cortado.zip"
        for size in (10, 200, len(data) // 3, len(data) // 2, len(data) - 30, len(data) - 1):
            cut.write_bytes(data[:size])
            self.assertFalse(_zip_ok(cut), size)

    def test_an_index_that_points_outside_the_file_is_not_finished(self):
        data = bytearray(self.path.read_bytes())
        # La cabecera local del segundo archivo, dañada.
        with zipfile.ZipFile(self.path) as archive:
            second = archive.infolist()[1].header_offset
        data[second:second + 4] = b"XXXX"
        broken = Path(self.tmp.name) / "danado.zip"
        broken.write_bytes(bytes(data))
        self.assertFalse(_zip_ok(broken))

    def test_without_password_the_contents_are_still_checked(self):
        plain = Path(self.tmp.name) / "BKDA202610211400.zip"
        with zipfile.ZipFile(plain, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("DATOS/MMEDICAM.DBF", b"x" * 50000)
        self.assertTrue(_zip_ok(plain))
        data = bytearray(plain.read_bytes())
        data[60] ^= 0xFF  # un byte de los datos comprimidos
        plain.write_bytes(bytes(data))
        self.assertFalse(_zip_ok(plain))


class HospitalDaysTests(unittest.TestCase):
    """Simula varios días del hospital: backups con contraseña al primer ingreso y a las 13:00."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "backup"
        self.folder.mkdir()
        self.state = Path(self.tmp.name) / "backups_conocidos.json"
        self.clock = [0.0]

    def watcher(self):
        return BackupWatcher(state_path=self.state, clock=lambda: self.clock[0], created=lambda st: st.st_mtime)

    def backup(self, name, mtime):
        path = encrypted_zip(self.folder / name, {"DATOS/MMEDICAM.DBF": name.encode() * 500})
        os.utime(path, (mtime, mtime))
        return path

    def test_each_new_backup_is_offered_right_away(self):
        day = time.time() - 3 * 86400
        w = self.watcher()
        first = self.backup("BKDA202610190705.zip", day)
        self.assertEqual(w.candidate(self.tmp.name), first, "el del 19 a primera hora")
        w.mark_done(first.name)
        self.assertIsNone(w.candidate(self.tmp.name), "ya subió: no se repite")

        # A las 13:00 el SISMED empieza a escribir otro: mientras no termina, no se ofrece nada.
        afternoon = self.folder / "BKDA202610191300.zip"
        complete = encrypted_zip(Path(self.tmp.name) / "completo.zip", {"DATOS/MMEDICAM.DBF": os.urandom(30000)})
        written = complete.read_bytes()
        afternoon.write_bytes(written[: len(written) // 2])
        self.assertIsNone(w.candidate(self.tmp.name), "a medio escribir")
        afternoon.write_bytes(complete.read_bytes())
        os.utime(afternoon, (day + 6 * 3600, day + 6 * 3600))
        self.assertEqual(w.candidate(self.tmp.name), afternoon, "el de las 13:00, apenas terminó")
        w.mark_done(afternoon.name)

        # Se apaga la PC; al día siguiente el Toolkit vuelve a abrir y el SISMED hace el del 20.
        next_day = self.backup("BKDA202610200712.zip", day + 86400)
        self.assertEqual(self.watcher().candidate(self.tmp.name), next_day, "el del 20, tras reiniciar")

    def test_the_connection_offers_the_password_protected_backup(self):
        path = self.backup("BKDA202610211300.zip", time.time() - 600)
        conn = backup_connection.BackupConnection(
            log=lambda _m: None, get_keys=lambda: "06502-AAAA", get_device_id=lambda: "d",
            get_equipo=lambda: "PC", get_base_dir=lambda: self.tmp.name)
        conn._watcher = self.watcher()
        sent = []

        class Ws:
            def send(self, text):
                sent.append(json.loads(text))

        conn._offer_copy(Ws())
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["t"], "copy_offer")
        self.assertEqual(sent[0]["name"], path.name)
        self.assertEqual(sent[0]["size"], path.stat().st_size)
        self.assertEqual(sent[0]["sha256"], backup_upload.sha256_file(path))

    def test_a_web_request_takes_the_newest_by_appearance_not_the_pc_date(self):
        w = self.watcher()
        forward = self.backup("BKDA202610250800.zip", time.time() + 4 * 86400)  # fecha adelantada
        self.assertEqual(w.latest(self.tmp.name), forward)
        real = self.backup("BKDA202610211300.zip", time.time())
        self.assertEqual(w.latest(self.tmp.name), real)


if __name__ == "__main__":
    unittest.main()
