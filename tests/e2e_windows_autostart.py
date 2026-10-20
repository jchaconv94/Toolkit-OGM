"""Prueba de punta a punta del arranque con Windows, con el instalador de verdad.

Instala la versión publicada anterior, simula su casilla de arranque como la dejaba (tarea
programada o clave Run), actualiza con el instalador recién compilado y abre el Toolkit como lo
abre Windows al encender (``--autorun``). Revisa cada caso que puede pasar en una laptop:

- con el arranque encendido en la versión anterior (tarea o clave Run) sigue encendido y lo viejo se borra;
- con la casilla apagada, el Toolkit se cierra sin abrir nada;
- si ya está abierto, la segunda apertura se cierra sola;
- la tarea de otro usuario de Windows no se toca;
- desinstalar quita el acceso de Inicio y la tarea vieja;
- instalado solo para el usuario, el acceso va a su carpeta Inicio.

Instala y desinstala en Archivos de programa y crea un usuario de Windows de prueba: solo corre en
GitHub Actions (máquina desechable). Uso: ``python tests/e2e_windows_autostart.py``.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import winreg
from pathlib import Path

import win32com.client

ROOT = Path(__file__).resolve().parents[1]
OLD_VERSION = "2.3.18"
OLD_URL = (f"https://github.com/jchaconv94/ToolkitSISMED/releases/download/desktop-v{OLD_VERSION}/"
           f"ToolkitOGM-Setup-{OLD_VERSION}.exe")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
NEW_INSTALLER = ROOT / "dist" / "installer" / f"ToolkitOGM-Setup-{VERSION}.exe"

INSTALL_DIR = Path(os.environ["ProgramFiles"]) / "ToolKit SISMED"
EXE = INSTALL_DIR / "ToolkitOGM.exe"
USER_INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "ToolKit SISMED"
COMMON_LINK = Path(os.environ["ProgramData"]) / "Microsoft/Windows/Start Menu/Programs/StartUp/ToolKit SISMED.lnk"
USER_LINK = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/ToolKit SISMED.lnk"
CONFIG = Path(os.environ["APPDATA"]) / "ToolkitOGM" / "config.json"
STARTUP_LOG = Path(os.environ["APPDATA"]) / "ToolkitOGM" / "startup.log"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
TASK = "ToolkitOGM_Autorun"
RUN_VALUE = "ToolkitOGM_Sync"
TEMP = Path(tempfile.mkdtemp(prefix="toolkit-arranque-"))

results: list[tuple[bool, str]] = []


def check(condition: bool, message: str):
    results.append((bool(condition), message))
    print(("OK    " if condition else "FALLO ") + message, flush=True)


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          **kwargs)


def install(installer: Path, *extra: str, log: str):
    result = run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={TEMP / log}", *extra],
                 timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"El instalador terminó con código {result.returncode}")


def uninstall(directory: Path):
    run([directory / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
    # El desinstalador de Inno se copia a una carpeta temporal y sigue trabajando desde allí.
    wait_until(lambda: not (directory / "ToolkitOGM.exe").exists(), 180)
    time.sleep(5)


def wait_until(condition, timeout: float, step: float = 0.5) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(step)
    return bool(condition())


def running(image: str) -> bool:
    return image.lower() in run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"]).stdout.lower()


def kill_toolkit():
    for image in ("ToolkitOGM.exe", "flet.exe"):
        run(["taskkill", "/F", "/T", "/IM", image])
    wait_until(lambda: not running("ToolkitOGM.exe"), 30)


def config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_preference(value):
    data = config()
    if value is None:
        data.pop("auto_startup", None)
    else:
        data["auto_startup"] = value
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_mark() -> int:
    return STARTUP_LOG.stat().st_size if STARTUP_LOG.exists() else 0


def log_since(mark: int) -> str:
    if not STARTUP_LOG.exists():
        return ""
    with open(STARTUP_LOG, "rb") as f:
        f.seek(mark)
        return f.read().decode("utf-8", "replace")


def task_exists() -> bool:
    return run(["schtasks", "/Query", "/TN", TASK]).returncode == 0


def create_old_task(*extra: str, interactive: bool = True):
    """Exactamente lo que hacía la versión anterior al marcar la casilla."""
    command = f'"{EXE}" --autorun'
    result = run(["schtasks", "/Create", "/TN", TASK, "/TR", command, "/SC", "ONLOGON", "/RL", "LIMITED",
                  *(["/IT"] if interactive else []), "/DELAY", "0002:00", "/F", *extra])
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo crear la tarea vieja: {result.stdout} {result.stderr}")


def task_owner() -> str:
    xml = run(["schtasks", "/Query", "/TN", TASK, "/XML"]).stdout.replace("\x00", "")
    return xml.split("<UserId>")[-1].split("</UserId>")[0] if "<UserId>" in xml else "(sin UserId)"


def delete_task():
    run(["schtasks", "/Delete", "/TN", TASK, "/F"])


def run_value() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except FileNotFoundError:
        return None


def set_run_value(value: str | None):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, value)


def shortcut(path: Path):
    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    return link.TargetPath, link.Arguments, link.WorkingDirectory


def same_path(a, b) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def autorun(exe: Path = EXE) -> subprocess.Popen:
    return subprocess.Popen([str(exe), "--autorun"])


def case(title: str):
    def wrap(fn):
        def runner():
            print(f"\n== {title} ==", flush=True)
            try:
                fn()
            except Exception as exc:
                traceback.print_exc()
                check(False, f"{title}: se detuvo por {type(exc).__name__}: {exc}")
            finally:
                kill_toolkit()
        return runner
    return wrap


@case("Instalar la versión anterior con el arranque encendido y actualizar")
def update_from_previous():
    installer = TEMP / f"ToolkitOGM-Setup-{OLD_VERSION}.exe"
    urllib.request.urlretrieve(OLD_URL, installer)
    install(installer, "/ALLUSERS", log="anterior.log")
    check(EXE.exists(), f"la {OLD_VERSION} quedó instalada en {INSTALL_DIR}")
    check(not COMMON_LINK.exists(), f"la {OLD_VERSION} no tenía acceso en la carpeta Inicio")
    create_old_task()
    check(task_exists(), "la tarea de arranque de la versión anterior existe")
    print("Tarea vieja, dueño:", task_owner())

    # Los mismos parámetros que usa el actualizador del Toolkit.
    install(NEW_INSTALLER, "/SP-", "/NORESTARTAPPLICATIONS", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS",
            "/AUTOUPDATE", "/SAFEUPDATE", "/ALLUSERS", f"/DIR={INSTALL_DIR}", log="actualizacion.log")
    check(EXE.exists(), "la actualización dejó ToolkitOGM.exe")
    check(COMMON_LINK.exists(), f"la actualización puso el acceso en la carpeta Inicio ({COMMON_LINK})")
    if COMMON_LINK.exists():
        target, arguments, workdir = shortcut(COMMON_LINK)
        check(same_path(target, EXE), f"el acceso abre {EXE} (abre {target})")
        check(arguments == "--autorun", f"el acceso abre con --autorun (tiene {arguments!r})")
        check(same_path(workdir, INSTALL_DIR), f"el acceso arranca en la carpeta del Toolkit ({workdir})")


@case("Primer encendido de Windows después de actualizar (tenía la tarea)")
def first_logon_with_task():
    check(task_exists(), "antes de abrir, la tarea vieja sigue (el instalador no la toca)")
    mark = log_mark()
    first = autorun()
    check(wait_until(lambda: config().get("auto_startup") is not None, 60),
          "el Toolkit guardó la preferencia al abrirse")
    check(config().get("auto_startup") is True, "la preferencia quedó encendida, como estaba")
    check(wait_until(lambda: not task_exists(), 30), "la tarea vieja se borró")
    time.sleep(20)
    check(first.poll() is None, "el Toolkit sigue abierto en la bandeja después de 20 s")
    text = log_since(mark)
    check("startup_migrated enabled=True" in text, "el registro de arranque anota la migración")
    print(text[-1500:])

    second = autorun()
    try:
        code = second.wait(60)
    except subprocess.TimeoutExpired:
        code = None
    check(code == 0, f"una segunda apertura al encender se cierra sola (código {code})")
    check(first.poll() is None, "el primero sigue abierto")


@case("Casilla apagada")
def preference_off():
    set_preference(False)
    started = time.time()
    process = autorun()
    try:
        code = process.wait(60)
    except subprocess.TimeoutExpired:
        code = None
    check(code == 0, f"el Toolkit se cerró solo sin abrir nada (código {code}, {time.time() - started:.1f} s)")
    check(not running("flet.exe"), "no quedó ninguna ventana del Toolkit abierta")
    check(config().get("auto_startup") is False, "la preferencia sigue apagada")


@case("Versión anterior que había dejado la clave Run (la tarea había fallado)")
def legacy_run_value():
    set_preference(None)
    delete_task()
    set_run_value(f'"{EXE}" --autorun')
    autorun()
    check(wait_until(lambda: config().get("auto_startup") is not None, 60), "el Toolkit guardó la preferencia")
    check(config().get("auto_startup") is True, "la preferencia quedó encendida")
    check(wait_until(lambda: run_value() is None, 30), "la clave Run vieja se borró")


@case("Sin nada de la versión anterior")
def nothing_before():
    set_preference(None)
    delete_task()
    set_run_value(None)
    process = autorun()
    try:
        code = process.wait(60)
    except subprocess.TimeoutExpired:
        code = None
    check(code == 0, f"el Toolkit se cerró solo (código {code})")
    check(config().get("auto_startup") is False, "la preferencia quedó apagada, como estaba")


@case("Tarea vieja de otro usuario de Windows en la misma PC")
def task_of_another_user():
    user = "toolkitprueba"
    password = "Tk9!" + secrets.token_hex(4)  # net user pide confirmar si pasa de 14 caracteres
    created = run(["net", "user", user, password, "/add"])
    print("net user:", created.returncode, created.stdout.strip(), created.stderr.strip())
    try:
        set_preference(None)
        set_run_value(None)
        try:
            create_old_task("/RU", user, "/RP", password)
        except RuntimeError as exc:
            print(exc, "- se intenta sin /IT")
            create_old_task("/RU", user, "/RP", password, interactive=False)
        print("Tarea de otro usuario, dueño:", task_owner())
        mark = log_mark()
        process = autorun()
        try:
            code = process.wait(60)
        except subprocess.TimeoutExpired:
            code = None
        check(code == 0, f"el Toolkit se cerró solo: la tarea no es de este usuario (código {code})")
        check(config().get("auto_startup") is False, "la preferencia de este usuario quedó apagada")
        check(task_exists(), "la tarea del otro usuario no se borró")
        check("startup_legacy_task_kept" in log_since(mark), "el registro anota que la tarea se dejó a su dueño")
    finally:
        delete_task()
        run(["net", "user", user, "/delete"])


@case("Desinstalar")
def uninstall_everything():
    create_old_task()
    uninstall(INSTALL_DIR)
    check(not EXE.exists(), "se quitó ToolkitOGM.exe")
    check(not COMMON_LINK.exists(), "se quitó el acceso de la carpeta Inicio")
    check(not task_exists(), "se quitó la tarea vieja")


@case("Instalado solo para el usuario")
def per_user_install():
    install(NEW_INSTALLER, "/CURRENTUSER", log="usuario.log")
    exe = USER_INSTALL_DIR / "ToolkitOGM.exe"
    check(exe.exists(), f"quedó instalado en {USER_INSTALL_DIR}")
    check(USER_LINK.exists(), f"el acceso quedó en la carpeta Inicio del usuario ({USER_LINK})")
    check(not COMMON_LINK.exists(), "no se puso acceso para todos los usuarios")
    if USER_LINK.exists():
        target, arguments, _ = shortcut(USER_LINK)
        check(same_path(target, exe) and arguments == "--autorun", f"el acceso abre {exe} con --autorun")
    uninstall(USER_INSTALL_DIR)
    check(not USER_LINK.exists(), "al desinstalar se quitó el acceso del usuario")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows usa cp1252: tildes y ✅
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("Esta prueba instala y desinstala el Toolkit de verdad: solo corre en GitHub Actions.")
        return 2
    if not NEW_INSTALLER.exists():
        print(f"Falta el instalador nuevo: {NEW_INSTALLER}")
        return 2
    for step in (update_from_previous, first_logon_with_task, preference_off, legacy_run_value,
                 nothing_before, task_of_another_user, uninstall_everything, per_user_install):
        step()

    failed = [message for ok, message in results if not ok]
    lines = ["## Arranque con Windows", "", f"{len(results) - len(failed)} de {len(results)} comprobaciones OK", ""]
    lines += [("✅ " if ok else "❌ ") + message for ok, message in results]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
