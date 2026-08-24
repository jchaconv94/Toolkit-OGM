import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from app_version import is_newer_version, normalize_version, version_tuple
from update_manager import (
    INSTALLER_ARGUMENTS,
    UPDATER_HELPER_NAME,
    UpdateError,
    UpdateManager,
    UpdateSecurityError,
)


class _UpdateServer:
    def __init__(self, installer_bytes: bytes, *, advertised_digest: str | None = None):
        self.installer_bytes = installer_bytes
        self.advertised_digest = advertised_digest or hashlib.sha256(installer_bytes).hexdigest()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/releases":
                    payload = [{
                        "draft": False,
                        "prerelease": False,
                        "body": "Mejoras de estabilidad.",
                        "html_url": f"{owner.base_url}/release/2.0.14",
                        "published_at": "2026-08-21T12:00:00Z",
                        "assets": [{
                            "name": "ToolkitOGM-Setup-2.0.14.exe",
                            "browser_download_url": f"{owner.base_url}/installer.exe",
                            "size": len(owner.installer_bytes),
                            "digest": f"sha256:{owner.advertised_digest}",
                        }],
                    }]
                    body = json.dumps(payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/installer.exe":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(owner.installer_bytes)))
                    self.end_headers()
                    self.wfile.write(owner.installer_bytes)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class VersionTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(is_newer_version("2.0.13", "2.0.12"))
        self.assertFalse(is_newer_version("2.0.12", "2.0.12"))
        self.assertEqual(version_tuple("v2.1.0"), (2, 1, 0, 0))
        self.assertEqual(normalize_version("v2.0.13"), "2.0.13")

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_version("2.0")


class UpdateManagerIntegrationTests(unittest.TestCase):
    def _manager(self, server, directory, **kwargs):
        return UpdateManager(
            api_url=f"{server.base_url}/releases",
            current_version="2.0.13",
            download_dir=directory,
            allowed_download_hosts={"127.0.0.1"},
            allow_http_for_tests=True,
            **kwargs,
        )

    def test_check_download_verify_and_launch(self):
        installer_bytes = b"Toolkit SISMED test installer\n" * 4096
        launched = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with _UpdateServer(installer_bytes) as server:
                manager = self._manager(
                    server,
                    temp_dir,
                    launcher=lambda path, args: launched.append((path, args)) or True,
                )
                info = manager.check_for_update()
                self.assertIsNotNone(info)
                self.assertEqual(info.version, "2.0.14")

                progress = []
                installer = manager.download_update(
                    info,
                    lambda downloaded, total: progress.append((downloaded, total)),
                )
                self.assertTrue(manager.verify_installer(installer, info))
                self.assertEqual(installer.read_bytes(), installer_bytes)
                self.assertEqual(progress[-1], (len(installer_bytes), len(installer_bytes)))

                manager.launch_installer(installer)
                self.assertEqual(len(launched), 1)
                self.assertIn("/AUTOUPDATE", launched[0][1])

    def test_corrupted_download_is_deleted(self):
        installer_bytes = b"installer-corrupto"
        wrong_digest = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            with _UpdateServer(installer_bytes, advertised_digest=wrong_digest) as server:
                manager = self._manager(server, temp_dir)
                info = manager.check_for_update()
                with self.assertRaises(UpdateSecurityError):
                    manager.download_update(info)
                self.assertFalse((Path(temp_dir) / info.installer_name).exists())
                self.assertFalse((Path(temp_dir) / f"{info.installer_name}.part").exists())

    def test_same_version_is_not_offered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with _UpdateServer(b"installer") as server:
                manager = UpdateManager(
                    api_url=f"{server.base_url}/releases",
                    current_version="2.0.14",
                    download_dir=temp_dir,
                    allowed_download_hosts={"127.0.0.1"},
                    allow_http_for_tests=True,
                )
                self.assertIsNone(manager.check_for_update())

    def test_native_helper_waits_backs_up_verifies_and_can_restore(self):
        source = (ROOT / "packaging" / "windows" / "ToolkitUpdater.cs").read_text(
            encoding="utf-8"
        )

        self.assertIn("WaitForExit(ParentWaitMilliseconds)", source)
        self.assertIn("CreateVerifiedBackup", source)
        self.assertIn("RecoverPreviousInstallation", source)
        self.assertIn("HasExpectedVersion", source)
        self.assertIn("installer.WaitForExit()", source)
        self.assertIn('"/DIR=" + Quote(installDirectory)', source)
        self.assertIn("/AUTOUPDATE", source)
        self.assertIn("/SAFEUPDATE", source)
        self.assertNotIn("/SUPPRESSMSGBOXES", source)
        self.assertLess(source.index("WaitForParent"), source.index("RunInstaller("))

    def test_inno_setup_preserves_existing_installation_directory(self):
        source = (ROOT / "packaging" / "windows" / "ToolkitOGM.iss").read_text(
            encoding="utf-8"
        )

        self.assertIn("UsePreviousAppDir=yes", source)
        self.assertIn("PrivilegesRequiredOverridesAllowed=commandline", source)
        self.assertNotIn("UsePreviousAppDir=no", source)
        self.assertNotIn("[InstallDelete]", source)

    @unittest.skipUnless(os.name == "nt", "El lanzador diferido solo existe en Windows")
    def test_default_launcher_starts_hidden_detached_helper(self):
        calls = []

        def fake_process_launcher(command, **kwargs):
            calls.append((command, kwargs))
            return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            update_dir = root / "updates"
            install_dir = root / "installed"
            update_dir.mkdir()
            install_dir.mkdir()
            installer = update_dir / "ToolkitOGM-Setup-2.0.15.exe"
            helper = install_dir / UPDATER_HELPER_NAME
            app = install_dir / "ToolkitOGM.exe"
            installer.write_bytes(b"installer")
            helper.write_bytes(b"helper")
            app.write_bytes(b"application")
            manager = UpdateManager(
                current_version="2.0.14",
                download_dir=update_dir,
                process_launcher=fake_process_launcher,
                helper_path=helper,
                install_dir=install_dir,
            )
            manager.launch_installer(installer)

        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(Path(command[0]).parent, update_dir.resolve())
        self.assertNotEqual(Path(command[0]), helper.resolve())
        self.assertTrue(Path(command[0]).name.startswith("ToolkitUpdateHost-"))
        self.assertEqual(Path(command[1]), installer.resolve())
        self.assertTrue(command[2].isdigit())
        self.assertEqual(Path(command[3]).name, "launcher.log")
        self.assertEqual(Path(command[4]), install_dir.resolve())
        self.assertEqual(command[5], "2.0.15")
        self.assertNotIn("powershell.exe", " ".join(command).lower())
        self.assertTrue(kwargs["creationflags"])
        self.assertIsNotNone(kwargs["stdin"])

    @unittest.skipUnless(os.name == "nt", "El lanzador diferido solo existe en Windows")
    def test_default_launcher_reports_process_creation_failure(self):
        def failed_process_launcher(*_args, **_kwargs):
            raise OSError("bloqueado")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            update_dir = root / "updates"
            install_dir = root / "installed"
            update_dir.mkdir()
            install_dir.mkdir()
            installer = update_dir / "ToolkitOGM-Setup-2.0.15.exe"
            helper = install_dir / UPDATER_HELPER_NAME
            installer.write_bytes(b"installer")
            helper.write_bytes(b"helper")
            (install_dir / "ToolkitOGM.exe").write_bytes(b"application")
            manager = UpdateManager(
                current_version="2.0.14",
                download_dir=update_dir,
                process_launcher=failed_process_launcher,
                helper_path=helper,
                install_dir=install_dir,
            )
            with self.assertRaises(UpdateError):
                manager.launch_installer(installer)
            self.assertEqual(list(update_dir.glob("ToolkitUpdateHost-*.exe")), [])

    @unittest.skipUnless(os.name == "nt", "El lanzador diferido solo existe en Windows")
    def test_update_files_inside_installation_are_rejected_before_launch(self):
        calls = []

        def fake_process_launcher(*args, **kwargs):
            calls.append((args, kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "installed"
            update_dir = install_dir / "updates"
            update_dir.mkdir(parents=True)
            installer = update_dir / "ToolkitOGM-Setup-2.0.15.exe"
            helper = install_dir / UPDATER_HELPER_NAME
            installer.write_bytes(b"installer")
            helper.write_bytes(b"helper")
            (install_dir / "ToolkitOGM.exe").write_bytes(b"application")
            manager = UpdateManager(
                current_version="2.0.14",
                download_dir=update_dir,
                process_launcher=fake_process_launcher,
                helper_path=helper,
                install_dir=install_dir,
            )

            with self.assertRaisesRegex(UpdateError, "no puede estar dentro"):
                manager.launch_installer(installer)

            self.assertEqual(calls, [])
            self.assertEqual(list(update_dir.glob("ToolkitUpdateHost-*.exe")), [])

    @unittest.skipUnless(os.name == "nt", "El lanzador diferido solo existe en Windows")
    def test_missing_native_helper_is_reported_before_closing_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = Path(temp_dir) / "ToolkitOGM-Setup-2.0.15.exe"
            installer.write_bytes(b"installer")
            manager = UpdateManager(
                current_version="2.0.14",
                download_dir=temp_dir,
                helper_path=Path(temp_dir) / UPDATER_HELPER_NAME,
                install_dir=temp_dir,
            )

            with self.assertRaisesRegex(UpdateError, "auxiliar de actualizacion"):
                manager.launch_installer(installer)


if __name__ == "__main__":
    unittest.main()
