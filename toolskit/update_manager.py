from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from app_version import get_current_version, is_newer_version, version_tuple


DEFAULT_RELEASES_API_URL = (
    "https://api.github.com/repos/jchaconv94/ToolkitSISMED/releases?per_page=20"
)
INSTALLER_PATTERN = re.compile(
    r"^ToolkitOGM-Setup-(\d+\.\d+\.\d+(?:\.\d+)?)\.exe$",
    re.IGNORECASE,
)
SHA256_PATTERN = re.compile(r"\b([a-fA-F0-9]{64})\b")
MAX_INSTALLER_BYTES = 600 * 1024 * 1024
INSTALLER_ARGUMENTS = (
    "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART "
    "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /AUTOUPDATE"
)
UPDATER_HELPER_NAME = "ToolkitUpdater.exe"


class UpdateError(RuntimeError):
    pass


class UpdateSecurityError(UpdateError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_name: str
    download_url: str
    expected_sha256: str
    size_bytes: int
    release_notes: str
    release_url: str
    published_at: str


def default_update_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "ToolkitOGM" / "updates"


class UpdateManager:
    def __init__(
        self,
        *,
        api_url: str | None = None,
        current_version: str | None = None,
        download_dir: str | os.PathLike | None = None,
        session=None,
        allowed_download_hosts: set[str] | None = None,
        allow_http_for_tests: bool = False,
        launcher: Callable[[str, str], bool] | None = None,
        process_launcher=None,
        helper_path: str | os.PathLike | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.api_url = (
            api_url
            or os.environ.get("TOOLKIT_UPDATE_API_URL", "").strip()
            or DEFAULT_RELEASES_API_URL
        )
        self.current_version = current_version or get_current_version()
        self.download_dir = Path(download_dir) if download_dir else default_update_directory()
        self.session = session or requests.Session()
        self.allowed_download_hosts = allowed_download_hosts or {
            "github.com",
            "objects.githubusercontent.com",
            "release-assets.githubusercontent.com",
        }
        self.allow_http_for_tests = allow_http_for_tests
        self.launcher = launcher
        self.process_launcher = process_launcher or subprocess.Popen
        self.helper_path = Path(helper_path) if helper_path else None
        self.logger = logger or (lambda _message: None)

    def _log(self, message: str) -> None:
        try:
            self.logger(message)
        except Exception:
            pass

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"ToolkitSISMED-Updater/{self.current_version}",
        }

    def _validate_url(self, url: str, *, api: bool = False) -> None:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            if not (self.allow_http_for_tests and parsed.scheme == "http"):
                raise UpdateSecurityError("La descarga no usa una conexion HTTPS segura.")
        if not api and host not in self.allowed_download_hosts:
            raise UpdateSecurityError(f"Servidor de descarga no autorizado: {host or 'desconocido'}")

    def _request_json(self):
        self._validate_url(self.api_url, api=True)
        try:
            response = self.session.get(
                self.api_url,
                headers=self._headers(),
                timeout=(10, 30),
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise UpdateError(f"No se pudo consultar GitHub: {exc}") from exc
        except ValueError as exc:
            raise UpdateError("GitHub devolvio una respuesta que no se pudo leer.") from exc

    @staticmethod
    def _digest_from_text(value: str) -> str | None:
        match = SHA256_PATTERN.search(str(value or ""))
        return match.group(1).lower() if match else None

    def _checksum_from_sidecar(self, url: str) -> str | None:
        self._validate_url(url)
        try:
            response = self.session.get(
                url,
                headers={"User-Agent": f"ToolkitSISMED-Updater/{self.current_version}"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            return self._digest_from_text(response.text)
        except requests.RequestException as exc:
            self._log(f"No se pudo leer el checksum auxiliar: {exc}")
            return None

    def _resolve_digest(self, release: dict, installer_asset: dict) -> str:
        digest = str(installer_asset.get("digest") or "")
        if digest.lower().startswith("sha256:"):
            resolved = self._digest_from_text(digest)
            if resolved:
                return resolved

        body_digest = self._digest_from_text(release.get("body") or "")
        if body_digest:
            return body_digest

        installer_name = str(installer_asset.get("name") or "")
        sidecar_name = f"{installer_name}.sha256".lower()
        for asset in release.get("assets") or []:
            if str(asset.get("name") or "").lower() != sidecar_name:
                continue
            sidecar_url = str(asset.get("browser_download_url") or "")
            checksum = self._checksum_from_sidecar(sidecar_url)
            if checksum:
                return checksum

        raise UpdateSecurityError(
            "La actualizacion no tiene una huella SHA-256 verificable. No se descargara."
        )

    def _release_candidates(self, payload) -> list[tuple[str, dict, dict]]:
        releases = payload if isinstance(payload, list) else [payload]
        candidates: list[tuple[str, dict, dict]] = []
        for release in releases:
            if not isinstance(release, dict):
                continue
            if release.get("draft") or release.get("prerelease"):
                continue
            for asset in release.get("assets") or []:
                name = str(asset.get("name") or "")
                match = INSTALLER_PATTERN.fullmatch(name)
                if not match:
                    continue
                version = match.group(1)
                if is_newer_version(version, self.current_version):
                    candidates.append((version, release, asset))
        return candidates

    def check_for_update(self) -> UpdateInfo | None:
        self._log(f"Consultando actualizaciones. Version instalada: {self.current_version}")
        payload = self._request_json()
        candidates = self._release_candidates(payload)
        if not candidates:
            self._log("No hay una version mas reciente disponible.")
            return None

        version, release, asset = max(candidates, key=lambda item: version_tuple(item[0]))
        download_url = str(asset.get("browser_download_url") or "")
        self._validate_url(download_url)

        try:
            size_bytes = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        if size_bytes <= 0 or size_bytes > MAX_INSTALLER_BYTES:
            raise UpdateSecurityError("El tamano informado del instalador no es valido.")

        info = UpdateInfo(
            version=version,
            installer_name=str(asset.get("name") or ""),
            download_url=download_url,
            expected_sha256=self._resolve_digest(release, asset),
            size_bytes=size_bytes,
            release_notes=str(release.get("body") or "").strip(),
            release_url=str(release.get("html_url") or "").strip(),
            published_at=str(release.get("published_at") or "").strip(),
        )
        self._log(f"Actualizacion encontrada: {info.version}")
        return info

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower()

    def verify_installer(self, path: str | os.PathLike, info: UpdateInfo) -> bool:
        installer_path = Path(path)
        if not installer_path.is_file():
            return False
        if installer_path.stat().st_size != info.size_bytes:
            return False
        return self._file_sha256(installer_path) == info.expected_sha256.lower()

    def download_update(
        self,
        info: UpdateInfo,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        self._validate_url(info.download_url)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.download_dir / info.installer_name
        partial_path = final_path.with_suffix(final_path.suffix + ".part")

        if self.verify_installer(final_path, info):
            if progress_callback:
                progress_callback(info.size_bytes, info.size_bytes)
            self._log(f"Instalador ya descargado y verificado: {final_path}")
            return final_path

        try:
            final_path.unlink(missing_ok=True)
            partial_path.unlink(missing_ok=True)
            response = self.session.get(
                info.download_url,
                headers={"User-Agent": f"ToolkitSISMED-Updater/{self.current_version}"},
                timeout=(10, 90),
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
            self._validate_url(response.url)

            downloaded = 0
            digest = hashlib.sha256()
            with partial_path.open("wb") as destination:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_BYTES:
                        raise UpdateSecurityError("La descarga excedio el tamano maximo permitido.")
                    digest.update(chunk)
                    destination.write(chunk)
                    if progress_callback:
                        progress_callback(downloaded, info.size_bytes)

            if downloaded != info.size_bytes:
                raise UpdateSecurityError(
                    f"La descarga quedo incompleta ({downloaded} de {info.size_bytes} bytes)."
                )
            if digest.hexdigest().lower() != info.expected_sha256.lower():
                raise UpdateSecurityError(
                    "La huella SHA-256 no coincide. El instalador fue descartado."
                )

            os.replace(partial_path, final_path)
            self._log(f"Instalador descargado y verificado: {final_path}")
            return final_path
        except requests.RequestException as exc:
            raise UpdateError(f"No se pudo descargar la actualizacion: {exc}") from exc
        finally:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup_downloads(self) -> None:
        if not self.download_dir.is_dir():
            return
        for path in self.download_dir.glob("ToolkitOGM-Setup-*.exe*"):
            try:
                path.unlink()
            except OSError:
                continue

    def _updater_helper_path(self) -> Path:
        if self.helper_path:
            return self.helper_path.resolve()
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / UPDATER_HELPER_NAME
        return Path(__file__).resolve().parent / UPDATER_HELPER_NAME

    def launch_installer(self, installer_path: str | os.PathLike) -> None:
        path = str(Path(installer_path).resolve())
        if not Path(path).is_file():
            raise UpdateError("No se encontro el instalador descargado.")

        if self.launcher is not None:
            if not self.launcher(path, INSTALLER_ARGUMENTS):
                raise UpdateError("Windows no permitio iniciar el instalador.")
            return

        if os.name != "nt":
            raise UpdateError("La instalacion automatica solo esta disponible en Windows.")

        self.download_dir.mkdir(parents=True, exist_ok=True)
        launcher_log = self.download_dir / "launcher.log"
        helper = self._updater_helper_path()
        if not helper.is_file():
            raise UpdateError(
                "La instalacion de ToolKit SISMED no contiene el auxiliar de actualizacion. "
                "Instale manualmente la version mas reciente."
            )
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        command = [
            str(helper),
            path,
            str(os.getpid()),
            str(launcher_log.resolve()),
        ]
        try:
            self.process_launcher(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise UpdateError(
                "No se pudo preparar el instalador. Reinicie ToolKit SISMED e intentelo nuevamente."
            ) from exc

        self._log(
            "Auxiliar de actualizacion iniciado. El instalador se abrira despues de cerrar ToolKit SISMED."
        )
