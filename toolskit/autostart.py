"""Abrir el Toolkit al encender Windows.

Desde la 2.3.19 el arranque lo deja puesto el instalador: un acceso directo en la carpeta Inicio
de Windows que abre el Toolkit con ``--autorun``. El Toolkit ya no se registra solo en el arranque.
Antes, cada vez que se abría, volvía a crear la tarea programada ``ToolkitOGM_Autorun`` (o la clave
Run ``ToolkitOGM_Sync`` si la tarea fallaba), y Windows Defender lo ponía en cuarentena como
«Behavior:Win32/Persistence.A!ml»: borraba ToolkitOGM.exe y parecía que se había desinstalado solo.

La casilla «Abrir esta aplicación al encender Windows» solo guarda la preferencia. Si está apagada,
el Toolkit abierto por el acceso directo se cierra sin mostrar nada.

La primera vez, la preferencia sale de lo que dejó la versión anterior (la tarea o la clave Run). Desde
la 2.4.5 eso solo se lee y se deja como está: el Toolkit no toca el arranque de Windows de ninguna
forma, ni para borrar (la 2.4.4 lo borraba). Lo viejo que quede abre el Toolkit con ``--autorun`` una
vez más al encender, y esa apertura se cierra sola: ya hay uno abierto, o la casilla está apagada.
La tarea se lee con el Programador de tareas de Windows, sin abrir ``schtasks``. Es una sola para
toda la PC y quedaba a nombre del último usuario de Windows que abrió el Toolkit: si es de otro
usuario, no cuenta para este.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable

PREFERENCE_KEY = "auto_startup"
SHORTCUT_NAME = "ToolKit SISMED.lnk"
LEGACY_TASK_NAME = "ToolkitOGM_Autorun"
LEGACY_RUN_VALUE = "ToolkitOGM_Sync"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_DIR = os.path.join("Microsoft", "Windows", "Start Menu", "Programs", "StartUp")


def shortcut_paths(env=None) -> list[str]:
    """Dónde deja el instalador el acceso directo: para todos (Program Files) o para el usuario."""
    env = os.environ if env is None else env
    roots = [env.get("ProgramData") or env.get("PROGRAMDATA"), env.get("APPDATA")]
    return [os.path.join(root, _STARTUP_DIR, SHORTCUT_NAME) for root in roots if root]


def shortcut_installed(exists: Callable[[str], bool] = os.path.exists, env=None) -> bool:
    return any(exists(path) for path in shortcut_paths(env))


def startup_preference(get, set_, legacy, log=lambda message: None) -> bool:
    """La preferencia guardada; la primera vez la toma de lo que dejó la versión anterior, sin tocarlo."""
    saved = get(PREFERENCE_KEY)
    if isinstance(saved, bool):
        return saved
    enabled = legacy.enabled()
    set_(PREFERENCE_KEY, enabled)
    log(f"startup_migrated enabled={enabled}; legacy_left=True")
    return enabled


def _read_task_xml() -> str | None:
    """El XML de la tarea vieja, leído con el Programador de tareas de Windows (sin abrir schtasks).
    None si no existe o no se puede leer."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return None
    try:
        pythoncom.CoInitialize()
        initialized = True
    except Exception:
        initialized = False
    try:
        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        return str(service.GetFolder("\\").GetTask(LEGACY_TASK_NAME).Xml)
    except Exception:
        return None
    finally:
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _current_user_ids(env=None) -> set[str]:
    """Cómo puede figurar este usuario en una tarea: SID, «usuario» o «DOMINIO\\usuario»."""
    env = os.environ if env is None else env
    ids = set()
    user, domain = env.get("USERNAME", ""), env.get("USERDOMAIN", "")
    if user:
        ids.add(user.lower())
        if domain:
            ids.add(f"{domain}\\{user}".lower())
    try:
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        ids.add(win32security.ConvertSidToStringSid(sid).lower())
    except Exception:
        pass
    return ids


class LegacyStartup:
    """La tarea programada y la clave Run que creaban las versiones anteriores. Solo se leen."""

    def __init__(self, task_xml: Callable[[], str | None] = _read_task_xml, registry=None, user_ids=None):
        self.task_xml = task_xml
        self.registry = registry
        self.user_ids = user_ids
        self._task = None

    def _winreg(self):
        if self.registry is not None:
            return self.registry
        if not sys.platform.startswith("win"):
            return None
        import winreg

        return winreg

    def task_owner(self) -> str | None:
        """None si la tarea no existe; "" si existe y no dice de quién es."""
        if self._task is None:
            try:
                xml = self.task_xml()
            except Exception:
                xml = None
            if xml is None:
                self._task = (False, "")
            else:
                text = str(xml).replace("\x00", "")
                match = re.search(r"<UserId>\s*([^<]*?)\s*</UserId>", text)
                self._task = (True, match.group(1) if match else "")
        exists, owner = self._task
        return owner if exists else None

    def task_is_mine(self) -> bool:
        owner = self.task_owner()
        if owner is None:
            return False
        if not owner:
            return True
        ids = _current_user_ids() if self.user_ids is None else {i.lower() for i in self.user_ids}
        return owner.lower() in ids

    def run_value_exists(self) -> bool:
        reg = self._winreg()
        if reg is None:
            return False
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_READ) as key:
                reg.QueryValueEx(key, LEGACY_RUN_VALUE)
            return True
        except Exception:
            return False

    def enabled(self) -> bool:
        return self.task_is_mine() or self.run_value_exists()
