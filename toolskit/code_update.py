"""Actualizaciones de código: bajan solo el código del Toolkit (menos de 1 MB) en lugar del instalador.

Cada versión publicada trae, además del instalador:
- `ToolkitOGM-app-<versión>.zip`: el código del Toolkit (lo que va en `_internal/app/app.zip`);
- `ToolkitOGM-app-<versión>.json`: el manifiesto (versión, runtime, huella y tamaño del zip);
- `ToolkitOGM-app-<versión>.json.sig`: la firma Ed25519 del manifiesto.

Si el manifiesto está bien firmado y es para el runtime instalado, el zip se descarga en
`%LOCALAPPDATA%\\ToolkitOGM\\app\\<versión>` y `app_loader` lo abre la próxima vez que arranca el
Toolkit. Si el runtime cambió (otra versión de Python o de alguna librería), no sirve: queda el
instalador completo, como siempre.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import app_loader
from app_version import is_newer_version, version_tuple

APP_ASSET = re.compile(r"^ToolkitOGM-app-(\d+\.\d+\.\d+(?:\.\d+)?)\.zip$", re.IGNORECASE)
MAX_APP_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024


class CodeUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeUpdateInfo:
    version: str
    zip_url: str
    manifest_url: str
    signature_url: str


def find_code_update(payload, current_version: str) -> CodeUpdateInfo | None:
    """La versión más nueva publicada con su actualización de código completa (zip, manifiesto y firma)."""
    best = None
    for release in payload if isinstance(payload, list) else [payload]:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        assets = {str(a.get("name") or ""): str(a.get("browser_download_url") or "") for a in release.get("assets") or []}
        for name, url in assets.items():
            match = APP_ASSET.fullmatch(name)
            if not match or not is_newer_version(match.group(1), current_version):
                continue
            manifest = assets.get(name[:-4] + ".json")
            signature = assets.get(name[:-4] + ".json.sig")
            if url and manifest and signature:
                info = CodeUpdateInfo(match.group(1), url, manifest, signature)
                if best is None or version_tuple(info.version) > version_tuple(best.version):
                    best = info
    return best


class CodeUpdater:
    def __init__(self, session, *, validate_url: Callable[[str], None], user_agent: str,
                 root: Path | None = None, bundle: Path | None = None, log: Callable[[str], None] = lambda m: None):
        self.session = session
        self.validate_url = validate_url
        self.user_agent = user_agent
        self.root = root or app_loader.updates_root()
        self.bundle = bundle or app_loader.bundle_dir()
        self.log = log

    def supported(self) -> bool:
        """Solo el programa instalado con el código aparte (`runtime.json`) puede usarlas."""
        return bool(self.bundle and app_loader.read_runtime(self.bundle).get("runtime"))

    def ready(self, version: str) -> bool:
        return bool(self.bundle) and app_loader.verify_folder(self.root / version,
                                                              app_loader.read_runtime(self.bundle)) is not None

    def _get(self, url: str, limit: int, digest=None, out=None, progress=None, total=0) -> bytes:
        self.validate_url(url)
        response = self.session.get(url, headers={"User-Agent": self.user_agent}, timeout=(10, 60),
                                    stream=True, allow_redirects=True)
        response.raise_for_status()
        self.validate_url(response.url)
        data, size = bytearray(), 0
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise CodeUpdateError("La descarga pasa el tamaño permitido.")
            if digest is not None:
                digest.update(chunk)
            if out is not None:
                out.write(chunk)
            else:
                data.extend(chunk)
            if progress:
                progress(size, total)
        return bytes(data)

    def install(self, info: CodeUpdateInfo, progress: Callable[[int, int], None] | None = None) -> str | None:
        """Descarga y deja lista la actualización. None si no es para este runtime (queda el instalador)."""
        runtime = app_loader.read_runtime(self.bundle) if self.bundle else {}
        if not runtime.get("runtime"):
            return None
        if self.ready(info.version):
            return info.version
        manifest = self._get(info.manifest_url, MAX_MANIFEST_BYTES)
        signature = self._get(info.signature_url, 1024)
        data = app_loader.check_manifest(manifest, signature, runtime)
        if data is None:
            self.log(f"La actualización de código {info.version} no es para este programa instalado: "
                     "se usará el instalador completo.")
            return None
        if data["version"] != info.version or data["app"]["size"] > MAX_APP_BYTES:
            raise CodeUpdateError("El manifiesto de la actualización no coincide con la versión publicada.")

        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.root / f".descarga-{info.version}"
        final = self.root / info.version
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir()
        try:
            digest = hashlib.sha256()
            with open(temp / "app.zip", "wb") as out:
                self._get(info.zip_url, data["app"]["size"], digest, out, progress, data["app"]["size"])
            if (temp / "app.zip").stat().st_size != data["app"]["size"] or digest.hexdigest() != data["app"]["sha256"]:
                raise CodeUpdateError("La huella del código descargado no coincide. Se descartó.")
            (temp / "manifest.json").write_bytes(manifest)
            (temp / "manifest.sig").write_bytes(signature)
            shutil.rmtree(final, ignore_errors=True)
            os.replace(temp, final)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        if not self.ready(info.version):
            shutil.rmtree(final, ignore_errors=True)
            raise CodeUpdateError("La actualización descargada no pasó la verificación.")
        self.log(f"Actualización de código {info.version} lista: se aplicará al volver a abrir el Toolkit.")
        return info.version

    def cleanup(self, running_version: str):
        """Borra las actualizaciones viejas: se queda la que está abierta y las más nuevas."""
        try:
            folders = [p for p in self.root.iterdir() if p.is_dir()]
        except OSError:
            return
        for folder in folders:
            name = folder.name
            stale = name.startswith(".descarga-") or (
                re.fullmatch(r"\d+(\.\d+){1,3}", name) and version_tuple(name) < version_tuple(running_version))
            if stale:
                shutil.rmtree(folder, ignore_errors=True)
