"""Qué está haciendo el Toolkit en este momento, para no reiniciarlo en medio de un trabajo.

Las herramientas, Sync SISMED y los backups marcan aquí mientras trabajan. El reinicio para
aplicar una actualización de código (update_restart) solo ocurre si no hay nada marcado: así no se
corta un envío de stock, la subida de un backup ni una herramienta que escribe en el SISMED.
"""

from __future__ import annotations

import collections
import os
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_active: collections.Counter = collections.Counter()


@contextmanager
def busy(name: str):
    with _lock:
        _active[name] += 1
    try:
        yield
    finally:
        with _lock:
            _active[name] -= 1
            if _active[name] <= 0:
                del _active[name]


def active() -> list[str]:
    """Lo que está trabajando ahora (vacío si nada)."""
    with _lock:
        names = sorted(_active)
    # Solo para las pruebas de punta a punta: mientras exista ese archivo, cuenta como un trabajo.
    test_file = os.environ.get("TOOLKIT_TEST_ACTIVITY_FILE", "")
    if test_file and os.path.exists(test_file):
        names.append("prueba")
    return names


def background(name: str, target, *args, **kwargs) -> threading.Thread:
    """Corre `target` en un hilo aparte, marcado como trabajo mientras dure."""
    def run():
        with busy(name):
            target(*args, **kwargs)

    thread = threading.Thread(target=run, name=f"trabajo: {name}", daemon=True)
    thread.start()
    return thread
