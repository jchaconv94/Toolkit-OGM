"""La ventana del Toolkit congelada: cerrarla a la fuerza y anotar cuándo pasa.

El Toolkit son dos procesos: este (Python: Sync SISMED, backups, icono de la bandeja) y la
ventana, `flet.exe`, que este abre. Después de mucho tiempo abierta, la ventana a veces se
congela: no responde a clics ni a la X, aunque Sync SISMED sigue enviando. Al «Cerrar
completamente», el pedido de cierre no le llega y la ventana quedaba abierta y huérfana.

- `kill_flet_views` cierra solo los `flet.exe` hijos de este proceso. Nunca el instalador de
  una actualización, que también es hijo de este proceso.
- `WindowHeartbeat` pregunta a la ventana cada pocos minutos si responde y anota en el
  registro cuándo deja de responder y cuándo vuelve, para saber cada cuánto pasa.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable

FLET_VIEW_EXE = "flet.exe"
HEARTBEAT_INTERVAL_SECONDS = 5 * 60
HEARTBEAT_TIMEOUT_SECONDS = 20


def flet_view_pids(parent_pid: int, processes: Iterable[tuple[int, int, str]]) -> list[int]:
    """De (pid, pid del padre, nombre), los `flet.exe` hijos de `parent_pid`."""
    return sorted(
        pid for pid, ppid, name in processes
        if ppid == parent_pid and str(name or "").lower() == FLET_VIEW_EXE
    )


def _windows_processes() -> list[tuple[int, int, str]]:
    """Procesos de Windows (pid, pid del padre, nombre). Vacío en otros sistemas."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    processes = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def kill_flet_views(
    list_processes: Callable[[], Iterable[tuple[int, int, str]]] = _windows_processes,
    run: Callable[..., object] = subprocess.run,
) -> list[int]:
    """Cierra a la fuerza la ventana del Toolkit (aunque esté congelada). Devuelve los pid cerrados."""
    pids = flet_view_pids(os.getpid(), list_processes())
    for pid in pids:
        try:
            run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    return pids


class WindowHeartbeat:
    """Pregunta a la ventana si responde y anota en el registro solo los cambios."""

    def __init__(
        self,
        ping: Callable[[], object],
        log: Callable[[str], None],
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._ping = ping
        self._log = log
        self._interval = interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._frozen_since: float | None = None
        self._thread: threading.Thread | None = None

    @property
    def frozen(self) -> bool:
        return self._frozen_since is not None

    def check(self) -> bool:
        """Una revisión. Devuelve True si la ventana respondió."""
        try:
            self._ping()
        except Exception as exc:
            if self._frozen_since is None:
                self._frozen_since = self._clock()
                self._log(
                    "La ventana del Toolkit no responde "
                    f"({type(exc).__name__}). Sync SISMED sigue enviando. "
                    "Para cerrarla: icono de la bandeja → «Cerrar completamente»."
                )
            return False
        if self._frozen_since is not None:
            minutes = max(0, int((self._clock() - self._frozen_since) // 60))
            self._frozen_since = None
            self._log(f"La ventana del Toolkit volvió a responder (estuvo sin responder ~{minutes} min).")
        return True

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="window-heartbeat", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self._interval):
            self.check()
