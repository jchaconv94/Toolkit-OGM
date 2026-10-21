import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
PACKAGING_DIR = ROOT / "packaging" / "windows"
for path in (TOOLKIT_DIR, PACKAGING_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app_loader  # noqa: E402
import build_app  # noqa: E402
import sign_code_update  # noqa: E402
import update_signature  # noqa: E402
from code_update import CodeUpdateError, CodeUpdater, find_code_update  # noqa: E402

SECRET = bytes(range(32))
PUBLIC = update_signature.public_key(SECRET).hex()
RUNTIME = "r" * 32


def zip_with(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def compiled(source: str) -> bytes:
    import importlib.util
    code = compile(source, "main.py", "exec")
    return importlib._bootstrap_external._code_to_hash_pyc(code, importlib.util.source_hash(source.encode()), False)


def signed_manifest(version, app_bytes, runtime=RUNTIME, secret=SECRET):
    manifest = json.dumps({"format": 1, "version": version, "runtime": runtime,
                           "app": {"sha256": hashlib.sha256(app_bytes).hexdigest(), "size": len(app_bytes)}},
                          sort_keys=True).encode()
    return manifest, update_signature.sign(secret, manifest)


class Install:
    """Un programa instalado de prueba: _internal con runtime.json y app/ (VERSION y app.zip)."""

    def __init__(self, tmp: Path, version="2.4.3", runtime=RUNTIME, public=PUBLIC):
        self.bundle = tmp / "_internal"
        (self.bundle / "app").mkdir(parents=True)
        (self.bundle / "app" / "VERSION").write_text(version + "\n")
        (self.bundle / "app" / "app.zip").write_bytes(zip_with({"main.pyc": compiled("SOURCE = 'instalador'\n")}))
        (self.bundle / "runtime.json").write_text(json.dumps({"runtime": runtime, "public_key": public}))
        self.root = tmp / "local" / "ToolkitOGM" / "app"
        self.root.mkdir(parents=True)

    def add_update(self, version, app_bytes=None, runtime=RUNTIME, secret=SECRET, tamper=False):
        app_bytes = app_bytes or zip_with({"main.pyc": compiled(f"SOURCE = '{version}'\n")})
        manifest, signature = signed_manifest(version, app_bytes, runtime, secret)
        folder = self.root / version
        folder.mkdir()
        (folder / "app.zip").write_bytes(app_bytes + (b"x" if tamper else b""))
        (folder / "manifest.json").write_bytes(manifest)
        (folder / "manifest.sig").write_bytes(signature)
        return folder


class SignatureTests(unittest.TestCase):
    def test_rfc8032_vectors(self):
        vectors = [
            ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
             "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
             "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
            ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
             "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
             "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
            ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
             "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
             "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
        ]
        for secret, public, message, signature in vectors:
            secret, public, message, signature = (bytes.fromhex(v) for v in (secret, public, message, signature))
            self.assertEqual(update_signature.public_key(secret), public)
            self.assertEqual(update_signature.sign(secret, message), signature)
            self.assertTrue(update_signature.verify(public, message, signature))
            self.assertFalse(update_signature.verify(public, message + b"!", signature))
            bad = bytearray(signature)
            bad[5] ^= 1
            self.assertFalse(update_signature.verify(public, message, bytes(bad)))

    def test_production_key_is_a_valid_point(self):
        key = (PACKAGING_DIR / "update_public_key.txt").read_text().strip()
        self.assertEqual(len(bytes.fromhex(key)), 32)
        self.assertIsNotNone(update_signature._decompress(bytes.fromhex(key)))


class BuildAppTests(unittest.TestCase):
    def test_runtime_modules_and_tests_stay_out_of_app_zip(self):
        names = [name for name, _ in build_app.app_modules()]
        for runtime in build_app.RUNTIME_MODULES:
            self.assertNotIn(runtime, names)
        self.assertIn("main", names)
        self.assertIn("tools", names)
        self.assertIn("tools.tool_registry", names)
        self.assertFalse(any(name.startswith("test_") for name in names))

    def test_zip_is_the_same_byte_by_byte_and_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.zip", Path(tmp) / "b.zip"
            build_app.build_zip(first)
            build_app.build_zip(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            names = zipfile.ZipFile(first).namelist()
            self.assertIn("tools/__init__.pyc", names)
            self.assertFalse(any(n.endswith(".py") for n in names))


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.install = Install(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def choose(self):
        return app_loader.choose(self.install.bundle, self.install.root)

    def test_newest_valid_update_is_chosen(self):
        self.install.add_update("2.4.4")
        self.install.add_update("2.4.5")
        self.assertEqual(self.choose().version, "2.4.5")

    def test_without_updates_the_installer_code_is_used(self):
        self.assertIsNone(self.choose())

    def test_update_not_newer_than_the_installer_is_ignored(self):
        self.install.add_update("2.4.3")
        self.install.add_update("2.4.1")
        self.assertIsNone(self.choose())

    def test_bad_signature_is_ignored(self):
        self.install.add_update("2.4.5", secret=bytes(32))
        self.install.add_update("2.4.4")
        self.assertEqual(self.choose().version, "2.4.4")

    def test_other_runtime_is_ignored(self):
        self.install.add_update("2.4.5", runtime="otro")
        self.assertIsNone(self.choose())

    def test_tampered_zip_is_ignored(self):
        self.install.add_update("2.4.5", tamper=True)
        self.assertIsNone(self.choose())

    def test_folder_name_must_match_the_signed_version(self):
        folder = self.install.add_update("2.4.5")
        folder.rename(self.install.root / "2.9.9")
        self.assertIsNone(self.choose())

    def test_two_failed_starts_mark_the_version_as_bad(self):
        self.install.add_update("2.4.4")
        self.install.add_update("2.4.5")
        state = app_loader.State(self.install.root)
        state.data["trying"]["2.4.5"] = 2
        state.save()
        self.assertEqual(self.choose().version, "2.4.4")
        self.assertIn("2.4.5", app_loader.State(self.install.root).data["bad"])

    def run_launcher(self):
        """Simula ToolkitOGM.exe: _MEIPASS, LOCALAPPDATA y el import de main desde el zip elegido."""
        env = {"LOCALAPPDATA": str(Path(self.tmp.name) / "local")}
        saved_path = list(sys.path)
        sys.modules.pop("main", None)
        try:
            with mock.patch.dict(os.environ, env), mock.patch.object(sys, "_MEIPASS", str(self.install.bundle), create=True):
                update = app_loader.prepare()
                module = app_loader.import_main(update)
                version = os.environ.get("TOOLKIT_VERSION_OVERRIDE")
                return module.SOURCE, version
        finally:
            sys.path[:] = saved_path
            sys.modules.pop("main", None)

    def test_launcher_opens_the_update_and_counts_the_start(self):
        self.install.add_update("2.4.5")
        self.assertEqual(self.run_launcher(), ("2.4.5", "2.4.5"))
        self.assertEqual(app_loader.State(self.install.root).failed_starts("2.4.5"), 1)
        # Arrancó bien: se olvida el intento.
        env = {"LOCALAPPDATA": str(Path(self.tmp.name) / "local"), "TOOLKIT_VERSION_OVERRIDE": "2.4.5"}
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "_MEIPASS", str(self.install.bundle), create=True):
            app_loader.mark_healthy()
        state = app_loader.State(self.install.root)
        self.assertEqual(state.failed_starts("2.4.5"), 0)
        self.assertEqual(state.data["healthy"], "2.4.5")

    def test_update_that_never_finishes_starting_goes_back_after_two_tries(self):
        self.install.add_update("2.4.5")
        self.assertEqual(self.run_launcher()[0], "2.4.5")
        self.assertEqual(self.run_launcher()[0], "2.4.5")
        self.assertEqual(self.run_launcher(), ("instalador", None))

    def test_update_that_cannot_be_imported_falls_back_in_the_same_start(self):
        self.install.add_update("2.4.5", zip_with({"main.pyc": compiled("raise ImportError('roto')\n")}))
        self.assertEqual(self.run_launcher(), ("instalador", None))
        self.assertIn("2.4.5", app_loader.State(self.install.root).data["bad"])

    def test_broken_newest_update_falls_back_to_the_last_good_one(self):
        self.install.add_update("2.4.4")
        self.install.add_update("2.4.5", zip_with({"main.pyc": compiled("raise ImportError('roto')\n")}))
        self.assertEqual(self.run_launcher(), ("2.4.4", "2.4.4"))
        state = app_loader.State(self.install.root)
        self.assertIn("2.4.5", state.data["bad"])
        self.assertEqual(state.failed_starts("2.4.4"), 1)

    def test_update_that_fails_when_running_reopens_the_toolkit_with_the_previous_code(self):
        self.install.add_update("2.4.5")
        update = app_loader.CodeUpdate("2.4.5", self.install.root / "2.4.5")
        broken = SimpleNamespace(run=lambda: (_ for _ in ()).throw(RuntimeError("falla")))
        env = {"LOCALAPPDATA": str(Path(self.tmp.name) / "local")}
        with mock.patch.dict(os.environ, env), mock.patch("subprocess.Popen") as popen:
            app_loader.run_main(broken, update)
        self.assertEqual(popen.call_args[0][0][0], sys.executable)
        self.assertIn("2.4.5", app_loader.State(self.install.root).data["bad"])
        # El código del instalador que falla no se reabre en bucle: el error sale como siempre.
        with mock.patch("subprocess.Popen") as popen, self.assertRaises(RuntimeError):
            app_loader.run_main(broken, None)
        popen.assert_not_called()

    def test_odd_state_file_never_stops_the_toolkit_from_opening(self):
        self.install.add_update("2.4.5")
        for content in ("[]", '"x"', "7", '{"trying": [], "bad": "2.4.5"}', '{"trying": {"2.4.5": "x"}}', "{roto"):
            (self.install.root / "state.json").write_text(content, encoding="utf-8")
            state = app_loader.State(self.install.root)
            self.assertEqual((type(state.data["trying"]), type(state.data["bad"])), (dict, list), content)
            self.assertEqual(self.choose().version, "2.4.5", content)
            (self.install.root / "state.json").write_text(content, encoding="utf-8")
            self.assertEqual(self.run_launcher(), ("2.4.5", "2.4.5"), content)
            (self.install.root / "state.json").write_text(content, encoding="utf-8")
            env = {"LOCALAPPDATA": str(Path(self.tmp.name) / "local"), "TOOLKIT_VERSION_OVERRIDE": "2.4.5"}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(sys, "_MEIPASS", str(self.install.bundle), create=True):
                app_loader.mark_healthy()

    def test_reopened_toolkit_skips_the_version_that_failed_even_without_state_file(self):
        self.install.add_update("2.4.4")
        self.install.add_update("2.4.5")
        update = app_loader.CodeUpdate("2.4.5", self.install.root / "2.4.5")
        broken = SimpleNamespace(run=lambda: (_ for _ in ()).throw(RuntimeError("falla")))
        env = {"LOCALAPPDATA": str(Path(self.tmp.name) / "local"), "TOOLKIT_VERSION_OVERRIDE": "2.4.5"}
        # state.json no se puede escribir: la marca de «mala» no queda en el archivo.
        with mock.patch.dict(os.environ, env), mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(app_loader.State, "save"):
            app_loader.run_main(broken, update)
        child_env = popen.call_args[1]["env"]
        self.assertEqual(child_env[app_loader.SKIP_ENV], "2.4.5")
        self.assertNotIn("TOOLKIT_VERSION_OVERRIDE", child_env)
        self.assertNotIn("2.4.5", app_loader.State(self.install.root).data["bad"])
        # El Toolkit que se vuelve a abrir no vuelve a la 2.4.5 (ni el reinicio para actualizar la ofrece).
        try:
            with mock.patch.dict(os.environ, {app_loader.SKIP_ENV: "2.4.5"}):
                self.assertEqual(self.run_launcher(), ("2.4.4", "2.4.4"))
            self.assertEqual(self.choose().version, "2.4.4")
        finally:
            app_loader._skipped = ""
        self.assertEqual(self.choose().version, "2.4.5")

    def test_inherited_version_override_is_cleared(self):
        with mock.patch.dict(os.environ, {"TOOLKIT_VERSION_OVERRIDE": "9.9.9"}):
            self.assertEqual(self.run_launcher(), ("instalador", None))


class FakeResponse:
    def __init__(self, data: bytes, url: str):
        self.data, self.url = data, url

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


class FakeSession:
    def __init__(self, files: dict):
        self.files, self.calls = files, []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        return FakeResponse(self.files[url], url)


def release(version, *names):
    return {"draft": False, "prerelease": False,
            "assets": [{"name": n, "browser_download_url": f"https://github.com/x/{n}"} for n in names]}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.install = Install(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, version="2.4.5", runtime=RUNTIME, app_bytes=b"codigo nuevo" * 100):
        manifest, signature = signed_manifest(version, app_bytes, runtime)
        base = f"https://github.com/x/ToolkitOGM-app-{version}"
        return {base + ".zip": app_bytes, base + ".json": manifest, base + ".json.sig": signature}

    def updater(self, files):
        return CodeUpdater(FakeSession(files), validate_url=lambda url: None, user_agent="prueba",
                           root=self.install.root, bundle=self.install.bundle)

    def test_finds_the_newest_complete_code_update(self):
        names = lambda v: (f"ToolkitOGM-app-{v}.zip", f"ToolkitOGM-app-{v}.json", f"ToolkitOGM-app-{v}.json.sig")
        payload = [release("2.4.5", *names("2.4.5")), release("2.4.6", *names("2.4.6")[:2]),
                   release("2.4.2", *names("2.4.2"))]
        info = find_code_update(payload, "2.4.3")
        self.assertEqual(info.version, "2.4.5")
        self.assertIsNone(find_code_update(payload, "2.4.5"))

    def test_downloads_only_the_code_and_leaves_it_ready(self):
        files = self.files()
        updater = self.updater(files)
        info = find_code_update([release("2.4.5", *(u.rsplit("/", 1)[1] for u in files))], "2.4.3")
        self.assertEqual(updater.install(info), "2.4.5")
        self.assertTrue(updater.ready("2.4.5"))
        self.assertEqual(app_loader.choose(self.install.bundle, self.install.root).version, "2.4.5")
        # Ya estaba: no vuelve a descargar.
        calls = len(updater.session.calls)
        self.assertEqual(updater.install(info), "2.4.5")
        self.assertEqual(len(updater.session.calls), calls)

    def test_version_that_failed_here_is_not_ready_and_goes_to_the_full_installer(self):
        files = self.files()
        updater = self.updater(files)
        info = find_code_update([release("2.4.5", *(u.rsplit("/", 1)[1] for u in files))], "2.4.3")
        self.assertEqual(updater.install(info), "2.4.5")
        state = app_loader.State(self.install.root)
        state.mark_bad("2.4.5")
        state.save()
        self.assertFalse(updater.ready("2.4.5"))
        calls = len(updater.session.calls)
        self.assertIsNone(updater.install(info))  # None: el actualizador sigue con el instalador completo
        self.assertEqual(len(updater.session.calls), calls)
        # Dos arranques sin terminar cuentan igual, aunque todavía no esté marcada.
        state = app_loader.State(self.install.root)
        state.data["bad"].clear()
        state.data["trying"]["2.4.5"] = app_loader.MAX_FAILED_STARTS
        state.save()
        self.assertFalse(updater.ready("2.4.5"))
        self.assertIsNone(updater.install(info))

    def test_other_runtime_means_full_installer(self):
        files = self.files(runtime="otro")
        updater = self.updater(files)
        info = find_code_update([release("2.4.5", *(u.rsplit("/", 1)[1] for u in files))], "2.4.3")
        self.assertIsNone(updater.install(info))
        self.assertFalse((self.install.root / "2.4.5").exists())

    def test_tampered_download_is_discarded(self):
        files = self.files()
        zip_url = next(u for u in files if u.endswith(".zip"))
        files[zip_url] = files[zip_url][:-1] + b"X"
        updater = self.updater(files)
        info = find_code_update([release("2.4.5", *(u.rsplit("/", 1)[1] for u in files))], "2.4.3")
        with self.assertRaises(CodeUpdateError):
            updater.install(info)
        self.assertFalse((self.install.root / "2.4.5").exists())
        self.assertEqual([p.name for p in self.install.root.iterdir()], [])

    def test_cleanup_keeps_the_running_and_newer_versions(self):
        for version in ("2.4.4", "2.4.5", "2.4.6"):
            self.install.add_update(version)
        (self.install.root / ".descarga-2.4.7").mkdir()
        self.updater({}).cleanup("2.4.5")
        self.assertEqual(sorted(p.name for p in self.install.root.iterdir() if p.is_dir()), ["2.4.5", "2.4.6"])


class SignScriptTests(unittest.TestCase):
    def test_signed_update_verifies_with_the_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / "build"
            (build / "app").mkdir(parents=True)
            (build / "app" / "app.zip").write_bytes(b"zip")
            (build / "app" / "VERSION").write_text("2.4.5\n")
            (build / "runtime.json").write_text(json.dumps({"runtime": RUNTIME, "public_key": PUBLIC}))
            out = Path(tmp) / "out"
            with mock.patch.dict(os.environ, {"UPDATE_SIGNING_KEY": SECRET.hex()}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sign_code_update.main(out, build), 0)
            manifest = (out / "ToolkitOGM-app-2.4.5.json").read_bytes()
            signature = (out / "ToolkitOGM-app-2.4.5.json.sig").read_bytes()
            data = app_loader.check_manifest(manifest, signature, {"runtime": RUNTIME, "public_key": PUBLIC})
            self.assertEqual(data["version"], "2.4.5")
            self.assertEqual(data["app"]["size"], 3)
            # Otra clave: no firma.
            with mock.patch.dict(os.environ, {"UPDATE_SIGNING_KEY": "11" * 32}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sign_code_update.main(Path(tmp) / "otra", build), 1)
            # Sin clave: avisa y no escribe nada.
            with mock.patch.dict(os.environ, {"UPDATE_SIGNING_KEY": ""}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sign_code_update.main(Path(tmp) / "nada", build), 0)
            self.assertFalse((Path(tmp) / "nada").exists())


if __name__ == "__main__":
    unittest.main()
