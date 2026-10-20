"""Abrir el Toolkit al encender Windows.

Desde la 2.3.19 el arranque lo deja puesto el instalador: un acceso directo en la carpeta Inicio
de Windows que abre el Toolkit con ``--autorun``. El Toolkit ya no se registra solo en el arranque.
Antes, cada vez que se abría, volvía a crear la tarea programada ``ToolkitOGM_Autorun`` (o la clave
Run ``ToolkitOGM_Sync`` si la tarea fallaba), y Windows Defender lo ponía en cuarentena como
«Behavior:Win32/Persistence.A!ml»: borraba ToolkitOGM.exe y parecía que se había desinstalado solo.

La casilla «Abrir esta aplicación al encender Windows» solo guarda la preferencia. Si está apagada,
el Toolkit abierto por el acceso directo se cierra sin mostrar nada.

La primera vez, la preferencia sale de lo que dejó la versión anterior (la tarea o la clave Run), y
eso se borra: borrarlo no es registrarse en el arranque. La tarea es una sola para toda la PC y
quedaba a nombre del último usuario de Windows que abrió el Toolkit: si es de otro usuario, no cuenta
para este ni se borra (se la deja a su dueño, o al desinstalador).
"""

from __future__ import annotations

import os
import re
import subprocess
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
    """La preferencia guardada; la primera vez la toma de la versión anterior y borra su arranque."""
    saved = get(PREFERENCE_KEY)
    if isinstance(saved, bool):
        return saved
    enabled = legacy.enabled()
    set_(PREFERENCE_KEY, enabled)
    for message in legacy.remove():
        log(message)
    log(f"startup_migrated enabled={enabled}")
    return enabled


def _hidden_run(arguments: list[str]):
    startupinfo = None
    if os.name == "nt" and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        startupinfo=startupinfo,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


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
    """La tarea programada y la clave Run que creaban las versiones anteriores."""

    def __init__(self, run: Callable[[list[str]], object] = _hidden_run, registry=None, user_ids=None):
        self.run = run
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
                result = self.run(["schtasks", "/Query", "/TN", LEGACY_TASK_NAME, "/XML"])
                if result.returncode != 0:
                    self._task = (False, "")
                else:
                    # schtasks puede escribir el XML en UTF-16: se quitan los nulos antes de buscar.
                    xml = str(result.stdout or "").replace("\x00", "")
                    match = re.search(r"<UserId>\s*([^<]*?)\s*</UserId>", xml)
                    self._task = (True, match.group(1) if match else "")
            except Exception:
                self._task = (False, "")
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

    def remove(self) -> list[str]:
        messages = []
        owner = self.task_owner()
        if owner is not None and not self.task_is_mine():
            messages.append(f"startup_legacy_task_kept owner={owner}")
        elif owner is not None:
            try:
                result = self.run(["schtasks", "/Delete", "/TN", LEGACY_TASK_NAME, "/F"])
                ok = result.returncode == 0
                detail = (result.stdout or result.stderr or "").strip()
            except Exception as exc:
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            messages.append(f"startup_legacy_task_removed={ok}; {detail}".rstrip("; "))
            self._task = None
        reg = self._winreg()
        if reg is not None and self.run_value_exists():
            try:
                with reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                    reg.DeleteValue(key, LEGACY_RUN_VALUE)
                messages.append("startup_legacy_run_removed=True")
            except Exception as exc:
                messages.append(f"startup_legacy_run_removed=False; {type(exc).__name__}: {exc}")
        return messages
