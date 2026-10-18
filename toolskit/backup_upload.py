"""Subida del backup del SISMED a ToolkitSISMED Web (Backups SISMED · etapa 2).

El SISMED genera solo su backup (`<instalación>\\backup\\BKDA<AAAAMMDD><HHMM>.zip`, con su
contraseña) al primer ingreso del día y a las 13:00. Cuando la web lo pide, el Toolkit:

1. toma el zip más reciente de esa carpeta **sin abrirlo ni modificarlo**;
2. calcula su huella SHA-256 y su tamaño y se los informa a la web;
3. lo sube por partes (el tamaño y cuántas a la vez los dicta el servicio) a
   `sismed-conexion`, que las guarda en R2; una parte que falla se reintenta sola, sin
   repetir las demás;
4. avisa que terminó. La web lo descarga y comprueba la huella.

Desde la 2.3.10 (2026-10-18) cada backup nuevo también sube solo, y en la nube queda solo el
más reciente de cada establecimiento. Si la web pide uno y la nube ya tiene ese mismo, el
servicio responde `reused` al iniciar y no se sube nada: la web baja el de la nube.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import zipfile
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


# Un zip inválido cuyo tamaño ya no cambia en este tiempo está dañado (no es que se esté escribiendo).
BROKEN_AFTER_SECONDS = 15 * 60
# Un backup copiado de otro lado conserva la fecha de su contenido: si se creó en la carpeta más
# de un día después, no es uno recién hecho por el SISMED (en Windows `st_ctime` es la creación).
COPIED_GAP_SECONDS = 24 * 3600


def default_watch_state() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "ToolkitOGM" / "backups_conocidos.json"


def _zip_ok(path: Path) -> bool:
    """El zip está completo: tiene su índice al final y los datos coinciden (no lo descomprime a disco)."""
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
        return False
    except Exception:
        return False


class BackupWatcher:
    """Cuál es el backup más reciente de la carpeta, sin creerle al reloj de la PC (2.3.10, 2026-10-18).

    El SISMED nombra el backup con la fecha de la PC (`BKDA20261025…`) y a fin de mes la adelantan
    para cerrar y luego la regresan: ni el nombre ni la fecha del archivo dicen cuál es el último.
    El más reciente es **el último que apareció en la carpeta**: se recuerda en qué orden se vio
    cada archivo, también entre reinicios (`backups_conocidos.json` del equipo).

    Un archivo se da por terminado cuando el zip está completo (su índice va al final, así que uno
    a medio escribir no pasa la prueba). Mientras el más reciente no esté terminado no se ofrece
    ninguno: se espera a ese. Uno dañado que ya no crece se salta, y vuelve a contar el anterior.
    """

    def __init__(self, state_path: str | os.PathLike | None = None, clock=time.monotonic, created=None):
        self.state_path = Path(state_path) if state_path else default_watch_state()
        self.clock = clock
        # Fecha de creación del archivo (Windows); en otros sistemas no se conoce.
        self.created = created or (lambda st: st.st_ctime if os.name == "nt" else None)
        self._lock = threading.Lock()
        self._sizes: dict[str, tuple[int, float]] = {}
        self._checked: dict[tuple[str, int, float], bool] = {}
        self._state = self._load()

    # --- estado guardado ---------------------------------------------------------
    def _load(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            return None
        files = {str(k): int(v) for k, v in data["files"].items() if isinstance(v, int)}
        return {"folder": str(data.get("folder") or ""), "seq": int(data.get("seq") or 0),
                "files": files, "done": [str(n) for n in data.get("done") or [] if str(n) in files]}

    def _save(self):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            pass  # sin poder guardar, igual funciona mientras el Toolkit siga abierto

    # --- revisión de la carpeta ----------------------------------------------------
    def _scan(self, base_dir: str) -> dict[str, tuple[Path, os.stat_result]]:
        folder = Path(str(base_dir or "").strip()) / "backup"
        present: dict[str, tuple[Path, os.stat_result]] = {}
        if folder.is_dir():
            for entry in folder.iterdir():
                try:
                    if entry.is_file() and BACKUP_NAME.match(entry.name):
                        stat = entry.stat()
                        if stat.st_size > 0:
                            present[entry.name] = (entry, stat)
                except OSError:
                    continue
        key = str(folder).lower()
        by_date = lambda names: sorted(names, key=lambda n: (present[n][1].st_mtime, n))
        changed = False
        if self._state is None or self._state["folder"] != key:
            # Primera vez en esta carpeta: lo que ya estaba se ordena por fecha del archivo (una
            # sola vez) y se da por visto todo menos el último, que se ofrece.
            order = by_date(present)
            self._state = {"folder": key, "seq": len(order), "files": {n: i + 1 for i, n in enumerate(order)},
                           "done": order[:-1]}
            changed = True
        else:
            for name in by_date([n for n in present if n not in self._state["files"]]):
                self._state["seq"] += 1
                self._state["files"][name] = self._state["seq"]
                changed = True
        for name in [n for n in self._state["files"] if n not in present]:
            del self._state["files"][name]
            changed = True
        self._state["done"] = [n for n in self._state["done"] if n in self._state["files"]]
        now = self.clock()
        for name, (_entry, stat) in present.items():
            previous = self._sizes.get(name)
            if previous is None or previous[0] != stat.st_size:
                self._sizes[name] = (stat.st_size, now)
        self._sizes = {n: v for n, v in self._sizes.items() if n in present}
        if changed:
            self._save()
        return present

    def _copied(self, stat: os.stat_result) -> bool:
        created = self.created(stat)
        return created is not None and created - stat.st_mtime > COPIED_GAP_SECONDS

    def _finished(self, name: str, entry: Path, stat: os.stat_result) -> bool | None:
        """True terminado, False dañado (se salta), None todavía escribiéndose."""
        key = (name, stat.st_size, stat.st_mtime)
        if key not in self._checked:
            ok = _zip_ok(entry)
            try:
                same = entry.stat().st_size == stat.st_size
            except OSError:
                same = False
            if not same:
                return None
            self._checked = {k: v for k, v in self._checked.items() if k[0] in self._sizes}
            self._checked[key] = ok
        if self._checked[key]:
            return True
        _size, since = self._sizes.get(name, (stat.st_size, self.clock()))
        return False if self.clock() - since >= BROKEN_AFTER_SECONDS else None

    def _newest(self, base_dir: str) -> Path | None:
        present = self._scan(base_dir)
        order = sorted(present, key=lambda n: self._state["files"].get(n, 0), reverse=True)
        for name in order:
            entry, stat = present[name]
            if self._copied(stat):
                continue
            finished = self._finished(name, entry, stat)
            if finished is None:
                return None  # el más reciente todavía se escribe: se espera a ese
            if finished:
                return entry
        return None

    # --- lo que usa la conexión -----------------------------------------------------
    def latest(self, base_dir: str) -> Path | None:
        """El backup más reciente ya terminado (para un pedido de la web)."""
        with self._lock:
            return self._newest(base_dir)

    def candidate(self, base_dir: str) -> Path | None:
        """El más reciente, si todavía no está en la nube (para subirlo solo)."""
        with self._lock:
            path = self._newest(base_dir)
            return None if path is None or path.name in self._state["done"] else path

    def mark_done(self, name: str):
        """Ese backup ya está en la nube: no se vuelve a ofrecer."""
        with self._lock:
            if self._state and name in self._state["files"] and name not in self._state["done"]:
                self._state["done"].append(name)
                self._save()


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

    def __init__(self, data: bytes, on_read, stop: threading.Event | None = None, stop_reason=lambda: ""):
        super().__init__(data)
        self._on_read = on_read
        self._stop = stop
        self._stop_reason = stop_reason

    def read(self, size=-1):
        # Al cancelar, la parte en curso se corta en el siguiente bloque (16 KiB), no al final.
        if self._stop is not None and self._stop.is_set():
            raise BackupUploadError(self._stop_reason() or "Se detuvo la subida")
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
        self._stop_reason = "Se detuvo porque otra parte no se pudo enviar"
        # El backup que se envía (o que la nube ya tenía), para no volver a ofrecerlo como copia.
        self.path: Path | None = None

    def cancel(self, reason: str = "Se detuvo la subida"):
        """Corta la subida (la copia del día cede ante un pedido de la web)."""
        self._stop_reason = reason
        self._stop.set()

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

    def run(self, base_dir: str, code: str, path: Path | None = None) -> bool:
        try:
            path = path if path is not None else find_latest_backup(base_dir)
            if path is None:
                raise BackupUploadError("No hay backups del SISMED en la carpeta «backup» de esta PC")
            size = path.stat().st_size
            if size > self.max_bytes:
                raise BackupUploadError(f"El backup pesa {size // (1024 * 1024)} MB, más de lo permitido")
            sha = sha256_file(path)
            modified = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")
            self._meta = {"name": path.name, "size": size, "sha256": sha, "modified": modified}
            self.send({"t": "backup_meta", "job": self.job, **self._meta})
            self.path = path
            self.log(f"  📦 Enviando backup {path.name} ({size / 1048576:.1f} MB) de {code} a la web...")
            if not self._upload(path, size):
                self.log(f"  ✓ La nube ya tenía el backup {path.name}: no se volvió a subir.")
                return True
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

    def _upload(self, path: Path, size: int) -> bool:
        """Sube el backup. False si no hizo falta: la nube ya lo tenía (2.3.10)."""
        if self._start().get("reused"):
            return False
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
                if not self._stop.is_set():
                    self._stop.set()
                for future in futures:
                    future.cancel()
                raise
        if path.stat().st_size != size:
            raise BackupUploadError("El backup cambió mientras se enviaba; vuelva a pedirlo")
        parts.sort(key=lambda part: part["partNumber"])
        self._post("complete", json={"parts": parts})
        return True

    def _start(self):
        """Abre la subida. Los datos del backup van también aquí (2.3.9).

        Antes solo iban por la conexión abierta (backup_meta), y en una red congestionada (por
        ejemplo, mientras subía la copia del día) este pedido llegaba primero y el servicio
        respondía «Falta informar el backup». Un servicio anterior que no los lee aquí lo
        sigue diciendo: se reintenta unos segundos, hasta que llega el backup_meta.

        Desde el 2026-10-18 el servicio responde `reused` si la nube ya tiene ese mismo backup
        (por ejemplo, alguien pidió «uno nuevo» y el SISMED no generó otro): no se sube nada.
        """
        for attempt in range(1, 5):
            try:
                return self._post("start", json=getattr(self, "_meta", None)) or {}
            except BackupUploadError as exc:
                if "Falta informar" not in str(exc) or attempt == 4:
                    raise
                self.sleep(attempt)

    def _upload_part(self, number: int, chunk: bytes, progress: _Progress | None = None) -> dict:
        last_error = ""
        for attempt in range(1, PART_RETRIES + 1):
            if self._stop.is_set():
                raise BackupUploadError(self._stop_reason)
            if progress:
                progress.start(number)
            body = _CountingReader(chunk, (lambda amount: progress.add(number, amount)) if progress else (lambda _a: None),
                                   self._stop, lambda: self._stop_reason)
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
