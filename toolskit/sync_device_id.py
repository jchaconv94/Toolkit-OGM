"""Identificador del equipo para las claves de envío de ToolkitSISMED Web.

Con una clave de envío, solo la PC vinculada puede enviar el stock de su establecimiento.
Para eso cada envío dice qué equipo es. El identificador tiene que:

- ser el mismo en cada envío de esta PC, aunque se actualice o reinstale el Toolkit;
- ser distinto en otra PC, **aunque le copien la carpeta o la configuración del Toolkit**.
  Ese es justamente el caso que se quiere bloquear: una copia vieja del SISMED en otra PC.

Por eso sale del ``MachineGuid`` de Windows, que se crea al instalar Windows y no viaja con
los archivos. Se envía resumido con SHA-256: el valor original no sale de la PC.

Si Windows no lo entrega (otro sistema, permisos), se usa un identificador aleatorio
guardado en la configuración. Es menos fuerte —viaja si copian la configuración—, pero
el envío no se detiene.
"""

from __future__ import annotations

import hashlib
import sys
import uuid

from tools.app_config import get as cfg_get, set as cfg_set

_PREFIX = "toolkit-sismed-envio:"
_FALLBACK_KEY = "sync_device_fallback_id"
_cached: str | None = None


def _windows_machine_guid() -> str:
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value or "").strip()
    except Exception:
        return ""


def _fallback_id() -> str:
    value = str(cfg_get(_FALLBACK_KEY) or "").strip()
    if not value:
        value = uuid.uuid4().hex
        try:
            cfg_set(_FALLBACK_KEY, value)
        except Exception:
            pass
    return value


def get_device_id() -> str:
    """Identificador estable de esta PC (32 caracteres hexadecimales)."""
    global _cached
    if _cached:
        return _cached
    source = _windows_machine_guid()
    origin = "win"
    if not source:
        source = _fallback_id()
        origin = "cfg"
    _cached = f"{origin}-" + hashlib.sha256((_PREFIX + source).encode("utf-8")).hexdigest()[:32]
    return _cached


def reset_cache() -> None:
    """Solo para pruebas."""
    global _cached
    _cached = None
