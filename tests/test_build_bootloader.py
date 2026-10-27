import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_DIR = ROOT / "packaging" / "windows"
if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

import build_bootloader  # noqa: E402


class PickSdistTests(unittest.TestCase):
    def test_takes_the_source_archive_with_its_pypi_hash(self):
        release = {"urls": [
            {"packagetype": "bdist_wheel", "filename": "pyinstaller-6.22.3-py3-none-win_amd64.whl",
             "url": "https://files/whl", "digests": {"sha256": "aa"}},
            {"packagetype": "sdist", "filename": "pyinstaller-6.22.3.tar.gz",
             "url": "https://files/sdist", "digests": {"sha256": "BB"}},
        ]}
        self.assertEqual(build_bootloader.pick_sdist(release, "6.22.3"),
                         {"filename": "pyinstaller-6.22.3.tar.gz", "url": "https://files/sdist", "sha256": "bb"})

    def test_fails_without_source_or_without_hash(self):
        with self.assertRaises(SystemExit):
            build_bootloader.pick_sdist({"urls": []}, "6.22.3")
        with self.assertRaises(SystemExit):
            build_bootloader.pick_sdist({"urls": [{"packagetype": "sdist", "filename": "p.tar.gz", "url": "u",
                                                   "digests": {}}]}, "6.22.3")


class VerifiedTests(unittest.TestCase):
    def test_accepts_matching_hash_and_rejects_another(self):
        data = b"codigo de pyinstaller"
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(build_bootloader.verified(data, digest.upper(), "p.tar.gz"), data)
        with self.assertRaises(SystemExit):
            build_bootloader.verified(data + b"!", digest, "p.tar.gz")


class InstallTests(unittest.TestCase):
    def _folders(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        built, target = Path(temp.name) / "built", Path(temp.name) / "target"
        built.mkdir()
        target.mkdir()
        return built, target

    def test_replaces_the_four_stock_bootloaders_and_reports_both_hashes(self):
        built, target = self._folders()
        for name in build_bootloader.BOOTLOADERS:
            (built / name).write_bytes(b"propio " + name.encode())
            (target / name).write_bytes(b"de serie " + name.encode())
        report = build_bootloader.install(built, target)
        self.assertEqual([row["file"] for row in report], list(build_bootloader.BOOTLOADERS))
        for row in report:
            name = row["file"]
            self.assertEqual((target / name).read_bytes(), b"propio " + name.encode())
            self.assertEqual(row["stock_sha256"], hashlib.sha256(b"de serie " + name.encode()).hexdigest())
            self.assertEqual(row["built_sha256"], hashlib.sha256(b"propio " + name.encode()).hexdigest())

    def test_fails_if_the_built_file_is_the_same_as_the_installed_one(self):
        built, target = self._folders()
        for name in build_bootloader.BOOTLOADERS:
            (built / name).write_bytes(b"igual")
            (target / name).write_bytes(b"igual")
        with self.assertRaises(SystemExit):
            build_bootloader.install(built, target)


if __name__ == "__main__":
    unittest.main()
