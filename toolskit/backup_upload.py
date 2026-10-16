"""Subida del backup del SISMED a ToolkitSISMED Web (Backups SISMED · etapa 2).

El SISMED genera solo su backup (`<instalación>\\backup\\BKDA<AAAAMMDD><HHMM>.zip`, con su
contraseña) al primer ingreso del día y a las 13:00. Cuando la web lo pide, el Toolkit:

1. toma el zip más reciente de esa carpeta **sin abrirlo ni modificarlo**;
2. calcula su huella SHA-256 y su tamaño y se los informa a la web;
3. lo sube por partes (el tamaño y cuántas a la vez los dicta el servicio) a
   `sismed-conexion`, que las guarda en R2; una parte que falla se reintenta sola, sin
   repetir las demás;
4. avisa que terminó. La web lo descarga, comprueba la huella y lo borra de R2.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# Partes que se suben a la vez si el servicio no dice otra cosa. Una sola conexión no pasa de
# ~0,5 Mbps en la red del Hospital II-E Bellavista, que mide 4,1 Mbps de subida con varias
# (fast.com, 2026-10-16): con varias conexiones se aprovecha la línea.
DEFAULT_PARALLEL = 4
MAX_PARALLEL = 8
# Cada cuánto se avisa a la web cuánto se lleva enviado, también a mitad de una parte.
PROGRESS_EVERY_SECONDS = 2.0


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


class _CountingReader(io.BytesIO):
    """Una parte como archivo que avisa cuántos bytes va leyendo http.client al enviarla."""

    def __init__(self, data: bytes, on_read):
        super().__init__(data)
        self._on_read = on_read

    def read(self, size=-1):
        chunk = super().read(size)
        if chunk:
            self._on_read(len(chunk))
        return chunk


class _Progress:
    """Lo enviado entre todas las partes en curso. Solo avisa cifras mayores a la anterior."""

    def __init__(self, total: int, report, every: float = PROGRESS_EVERY_SECONDS, clock=time.monotonic):
        self.total = total
        self.report = report
        self.every = every
        self.clock = clock
        self.lock = threading.Lock()
        self.done = 0
        self.inflight: dict[int, int] = {}
        self.reported = 0
        self.last = clock()

    def start(self, number: int):
        with self.lock:
            self.inflight[number] = 0  # un reintento vuelve a contar la parte desde cero

    def add(self, number: int, amount: int):
        with self.lock:
            self.inflight[number] = self.inflight.get(number, 0) + amount
            self._maybe_report(False)

    def finish(self, number: int, size: int):
        with self.lock:
            self.inflight.pop(number, None)
            self.done += size
            self._maybe_report(True)

    def _maybe_report(self, force: bool):
        current = min(self.total, self.done + sum(self.inflight.values()))
        if current <= self.reported:
            return
        now = self.clock()
        if not force and now - self.last < self.every:
            return
        self.last = now
        self.reported = current
        self.report(current)  # dentro del candado: los avisos salen de a uno


class BackupUploader:
    def __init__(self, base_url: str, job: str, token: str, part_size: int, max_bytes: int,
                 send, log, session=None, sleep=time.sleep, parallel: int = DEFAULT_PARALLEL):
        self.base_url = base_url.rstrip("/")
        self.job = job
        self.token = token
        self.part_size = int(part_size)
        self.max_bytes = int(max_bytes)
        self.send = send
        self.log = log
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self.parallel = max(1, min(MAX_PARALLEL, int(parallel or 1)))
        self._stop = threading.Event()

    def _http(self):
        """Una sesión por hilo: cada parte en curso va por su propia conexión."""
        if self._session is not None:
            return self._session
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = requests.Session()
        return session

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
        response = self._http().post(self._url(action), headers=self._headers(kwargs.pop("headers", None)),
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
        count = max(1, -(-size // self.part_size))
        progress = _Progress(size, lambda sent: self.send({"t": "backup_progress", "job": self.job, "sent": sent}))

        def task(number: int) -> dict:
            offset = (number - 1) * self.part_size
            with open(path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read(self.part_size)
            if len(chunk) != min(self.part_size, size - offset):
                raise BackupUploadError("El backup cambió mientras se enviaba; vuelva a pedirlo")
            part = self._upload_part(number, chunk, progress)
            progress.finish(number, len(chunk))
            return part

        parts = []
        workers = min(self.parallel, count)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="backup-part") as pool:
            futures = [pool.submit(task, number) for number in range(1, count + 1)]
            try:
                for future in as_completed(futures):
                    parts.append(future.result())
            except BaseException:
                # Una parte que no salió detiene las demás: no tiene sentido seguir subiendo.
                self._stop.set()
                for future in futures:
                    future.cancel()
                raise
        if path.stat().st_size != size:
            raise BackupUploadError("El backup cambió mientras se enviaba; vuelva a pedirlo")
        parts.sort(key=lambda part: part["partNumber"])
        self._post("complete", json={"parts": parts})

    def _upload_part(self, number: int, chunk: bytes, progress: _Progress | None = None) -> dict:
        last_error = ""
        for attempt in range(1, PART_RETRIES + 1):
            if self._stop.is_set():
                raise BackupUploadError("Se detuvo porque otra parte no se pudo enviar")
            if progress:
                progress.start(number)
            body = _CountingReader(chunk, (lambda amount: progress.add(number, amount)) if progress else (lambda _a: None))
            try:
                # Como archivo y no como bytes: así http.client lo envía en bloques de 16 KiB y
                # cada bloque tiene sus 15 s. Con bytes se mandaba de un solo envío y la parte
                # entera debía salir en 15 s; con internet de subida lento fallaba con «The write
                # operation timed out» (Hospital II-E Bellavista, 2026-10-16).
                response = self._http().put(self._url(f"part/{number}"), data=body,
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
