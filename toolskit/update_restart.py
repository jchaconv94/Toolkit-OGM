"""Reinicio silencioso para aplicar una actualización de código ya descargada.

Una actualización de código se aplica al abrir el Toolkit. Para no esperar al día siguiente, el
Toolkit se reinicia solo, sin mostrar nada, cuando se cumple todo esto:

- hay una actualización descargada y verificada (firma, runtime, huella), más nueva que la abierta;
- la ventana lleva escondida en la bandeja al menos IDLE_SECONDS (si está a la vista, alguien la usa);
- no hay nada trabajando (activity: herramientas, envío de Sync SISMED, subida de backups) y el
  actualizador no está buscando ni descargando;
- no se intentó ya dos veces con esa versión, ni hace menos de RETRY_SECONDS.

Se vuelve a revisar justo antes de reiniciar. El Toolkit nuevo espera a que el anterior termine
(`--wait-pid`) y arranca escondido, como al encender Windows.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

IDLE_SECONDS = 20 * 60
CHECK_SECONDS = 5 * 60
RETRY_SECONDS = 6 * 60 * 60
MAX_ATTEMPTS = 2
BUSY_UPDATER_STATES = {"checking", "downloading", "installing"}
RESTART_ARGS = ("--autorun", "--update-restart")


def _seconds(name: str, default: int) -> int:
    """Los tiempos se pueden acortar solo para las pruebas de punta a punta."""
    try:
        return max(1, int(os.environ.get(name, "")))
    except ValueError:
        return default


def idle_seconds() -> int:
    return _seconds("TOOLKIT_RESTART_IDLE_SECONDS", IDLE_SECONDS)


def check_seconds() -> int:
    return _seconds("TOOLKIT_RESTART_CHECK_SECONDS", CHECK_SECONDS)


def _key(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def pending_version(bundle, root, running_version: str) -> str | None:
    """La actualización de código que se abriría al reiniciar, si es más nueva que la abierta."""
    import app_loader

    if bundle is None:
        return None
    update = app_loader.choose(bundle, root)
    if update and _key(update.version) > _key(running_version):
        return update.version
    return None


@dataclass
class Situation:
    now: float                 # reloj de la PC (para los intentos guardados)
    pending: str | None        # versión lista para aplicar
    hidden_for: float | None   # segundos con la ventana escondida; None si está a la vista
    busy: list[str]            # lo que está trabajando
    updater_state: str
    attempts: dict             # {versión: [intentos, último intento (reloj de la PC)]}


def decide(s: Situation, idle: int | None = None) -> tuple[bool, str]:
    idle = idle_seconds() if idle is None else idle
    if not s.pending:
        return False, "no hay actualización lista"
    if s.hidden_for is None:
        return False, "la ventana está a la vista"
    if s.hidden_for < idle:
        return False, f"la ventana está escondida hace {int(s.hidden_for)} s (espera {idle} s)"
    if s.busy:
        return False, "trabajando: " + ", ".join(s.busy)
    if s.updater_state in BUSY_UPDATER_STATES:
        return False, f"el actualizador está ocupado ({s.updater_state})"
    count, last = (s.attempts.get(s.pending) or [0, 0])[:2]
    if count >= MAX_ATTEMPTS:
        return False, f"ya se intentó {count} veces con la versión {s.pending}"
    if count and 0 <= s.now - last < RETRY_SECONDS:
        return False, f"se intentó hace poco con la versión {s.pending}"
    return True, f"reiniciar para aplicar la versión {s.pending}"


def record_attempt(attempts: dict, version: str, now: float) -> dict:
    count = int((attempts.get(version) or [0])[0])
    # Solo se guardan las últimas versiones: no crece sin fin.
    kept = {v: a for v, a in attempts.items() if v != version}
    kept = dict(sorted(kept.items(), key=lambda kv: kv[1][1])[-4:])
    kept[version] = [count + 1, now]
    return kept


class RestartWatcher:
    """Revisa cada cierto tiempo si conviene reiniciar; si sí, llama a `restart(versión)`."""

    def __init__(self, situation: Callable[[], Situation], restart: Callable[[str], bool],
                 log: Callable[[str], None]):
        self.situation = situation
        self.restart = restart
        self.log = log
        self.stop_event = threading.Event()
        self.last_reason = ""

    def check_once(self) -> bool:
        ok, reason = decide(self.situation())
        if reason != self.last_reason and (ok or "no hay actualización" not in reason):
            self.log(f"Reinicio para actualizar: {reason}")
        self.last_reason = reason
        if not ok:
            return False
        # Otra vez, justo antes: pudo empezar un trabajo o abrirse la ventana.
        again = self.situation()
        ok, reason = decide(again)
        if not ok:
            self.log(f"Reinicio para actualizar: se suspendió ({reason})")
            return False
        return bool(self.restart(again.pending))

    def run(self):
        while not self.stop_event.wait(check_seconds()):
            try:
                if self.check_once():
                    return
            except Exception as exc:  # noqa: BLE001 - nunca tumba el Toolkit
                self.log(f"Reinicio para actualizar: no se pudo revisar ({type(exc).__name__}: {exc})")

    def start(self):
        threading.Thread(target=self.run, name="ToolkitUpdateRestart", daemon=True).start()

    def stop(self):
        self.stop_event.set()


def now() -> float:
    return time.time()
