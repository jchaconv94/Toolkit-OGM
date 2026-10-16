"""Subida del backup del SISMED a ToolkitSISMED Web (Backups SISMED · etapa 2).

El SISMED genera solo su backup (`<instalación>\\backup\\BKDA<AAAAMMDD><HHMM>.zip`, con su
contraseña) al primer ingreso del día y a las 13:00. Cuando la web lo pide, el Toolkit:

1. toma el zip más reciente de esa carpeta **sin abrirlo ni modificarlo**;
2. calcula su huella SHA-256 y su tamaño y se los informa a la web;
3. lo sube por partes de 20 MiB al servicio `sismed-conexion`, que las guarda en R2;
   una parte que falla se reintenta sola, sin repetir las anteriores;
4. avisa que terminó. La web lo descarga, comprueba la huella y lo borra de R2.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BACKUP_NAME = re.compile(r"^BKD[AH]\d{8,12}\.zip$", re.IGNORECASE)
# Un zip modificado hace menos de esto puede estar escribiéndose todavía.
STILL_WRITING_SECONDS = 90
PART_RETRIES = 4
# (conexión, lectura). Ojo: mientras se envía el cuerpo, urllib3 solo espera el tiempo de
# conexión; por eso cada parte se manda como archivo, en bloques (ver `_upload_part`).
REQUEST_TIMEOUT = (15, 300)


def find_latest_backup(base_dir: str, now: float | None = None) -> Path | None:
    """El BKDA…zip más reciente de <base_dir>\\backup que ya terminó de escribirse."""
    folder = Path(str(base_dir or "").strip()) / "backup"
    if not folder.is_dir():
        return None
    now = time.time() if now is None else now
    candidates = []
    for entry in folder.iterdir():
        try:
            if not entry.is_file() or not BACKUP_NAME.match(entry.name):
                continue
            stat = entry.stat()
        except OSError:
            continue
        if stat.st_size <= 0 or now - stat.st_mtime < STILL_WRITING_SECONDS:
            continue
        candidates.append((stat.st_mtime, entry.name, entry))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def service_http_base(ws_url: str) -> str:
    """wss://servicio/pc → https://servicio"""
    base = re.sub(r"^ws", "http", ws_url, flags=re.IGNORECASE)
    return re.sub(r"/pc/?$", "", base)


class BackupUploadError(Exception):
    pass


class BackupUploader:
    def __init__(self, base_url: str, job: str, token: str, part_size: int, max_bytes: int,
                 send, log, session=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.job = job
        self.token = token
        self.part_size = int(part_size)
        self.max_bytes = int(max_bytes)
        self.send = send
        self.log = log
        self.http = session or requests.Session()
        self.sleep = sleep

    def _url(self, action: str) -> str:
        return f"{self.base_url}/backup/{self.job}/{action}"

    def _headers(self, extra: dict | None = None) -> dict:
        return {"X-Job-Token": self.token, **(extra or {})}

    def run(self, base_dir: str, code: str) -> bool:
        try:
            path = find_latest_backup(base_dir)
            if path is None:
                raise BackupUploadError("No hay backups del SISMED en la carpeta «backup» de esta PC")
            size = path.stat().st_size
            if size > self.max_bytes:
                raise BackupUploadError(f"El backup pesa {size // (1024 * 1024)} MB, más de lo permitido")
            sha = sha256_file(path)
            modified = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")
            self.send({"t": "backup_meta", "job": self.job, "name": path.name, "size": size,
                       "sha256": sha, "modified": modified})
            self.log(f"  📦 Enviando backup {path.name} ({size / 1048576:.1f} MB) de {code} a la web...")
            self._upload(path, size)
            self.log(f"  ✓ Backup {path.name} enviado y verificado por tamaño.")
            return True
        except BackupUploadError as exc:
            self._fail(str(exc))
        except Exception as exc:  # red caída, permiso vencido, etc.
            self._fail(f"No se pudo enviar el backup: {exc}")
        return False

    def _fail(self, reason: str):
        self.log(f"  ⚠ {reason}")
        try:
            self.send({"t": "backup_error", "job": self.job, "reason": reason})
        except Exception:
            pass

    def _post(self, action: str, **kwargs):
        response = self.http.post(self._url(action), headers=self._headers(kwargs.pop("headers", None)),
                                  timeout=REQUEST_TIMEOUT, **kwargs)
        if response.status_code != 200:
            raise BackupUploadError(self._error_text(response))
        return response.json()

    @staticmethod
    def _error_text(response) -> str:
        try:
            return str(response.json().get("error") or response.status_code)
        except Exception:
            return f"HTTP {response.status_code}"

    def _upload(self, path: Path, size: int):
        # La web recibe los datos del backup (backup_meta) antes de que empiece la subida.
        self._post("start")
        parts = []
        sent = 0
        with open(path, "rb") as fh:
            number = 1
            while True:
                chunk = fh.read(self.part_size)
                if not chunk:
                    break
                parts.append(self._upload_part(number, chunk))
                sent += len(chunk)
                self.send({"t": "backup_progress", "job": self.job, "sent": sent})
                number += 1
        if sent != size:
            raise BackupUploadError("El backup cambió mientras se enviaba; vuelva a pedirlo")
        self._post("complete", json={"parts": parts})

    def _upload_part(self, number: int, chunk: bytes) -> dict:
        last_error = ""
        for attempt in range(1, PART_RETRIES + 1):
            try:
                # Como archivo (BytesIO) y no como bytes: así http.client lo envía en bloques de
                # 16 KiB y cada bloque tiene sus 15 s. Con bytes se mandaba de un solo envío y la
                # parte entera debía salir en 15 s; con internet de subida lento fallaba con
                # «The write operation timed out» (Hospital II-E Bellavista, 2026-10-16).
                response = self.http.put(self._url(f"part/{number}"), data=io.BytesIO(chunk),
                                         headers=self._headers({"Content-Type": "application/octet-stream"}),
                                         timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    return {"partNumber": int(data["partNumber"]), "etag": str(data["etag"])}
                last_error = self._error_text(response)
                if response.status_code in (403, 404, 409, 413):
                    break  # no tiene arreglo reintentando
            except requests.RequestException as exc:
                last_error = str(exc)
            if attempt < PART_RETRIES:
                self.sleep(min(30, 2 ** attempt))
        raise BackupUploadError(f"La parte {number} no se pudo enviar: {last_error}")
