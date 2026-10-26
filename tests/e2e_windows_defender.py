"""Prueba de punta a punta con Microsoft Defender encendido (solo en GitHub Actions, Windows).

Las máquinas de GitHub traen Defender apagado y con todo el disco excluido. Aquí se enciende como
en una laptop (protección en tiempo real, vigilancia de comportamiento, protección en la nube,
descargas) y se comprueba que de verdad detecta con el archivo de prueba EICAR. Luego:

- `enable`: enciende Defender y lo comprueba;
- `published <versión>`: baja el instalador publicado en la Release (marcado como descargado de
  internet), lo hace analizar, lo instala, analiza lo instalado y deja el Toolkit abierto unos
  minutos, como al encender la PC y abierto a mano;
- `report`: lista lo que Defender detectó desde que se encendió (sin el EICAR) y falla si hubo algo
  (`report --informe` solo informa).

Entre `published` y `report` el flujo corre las pruebas de actualización de código (instalar,
actualizar, reinicio silencioso) con Defender encendido.

Actualizar desde una versión vieja (la 2.3.18 y anteriores creaban en cada arranque la tarea
`ToolkitOGM_Autorun` o, si no podían, la clave Run `ToolkitOGM_Sync`, y Defender las ponía en
cuarentena como «Behavior:Win32/Persistence.A!ml»):

- `legacy <versión vieja>`: con Defender todavía apagado, instala esa versión y deja su tarea y su
  clave Run, como en una PC que la usaba;
- `upgrade <versión>`: con Defender encendido, instala la versión publicada encima y la abre. Desde
  la 2.4.5 deja la tarea y la clave viejas como están (la 2.4.4 las borraba). No debe detectar nada;
- `oldrun`: control: con Defender encendido, abre la versión vieja, que vuelve a crear su tarea.
  Si Defender la detecta, estas máquinas reproducen lo que pasa en las PC.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "e2e-defender"
STATE = WORK / "defender.json"
INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ToolKit SISMED"
EXE = INSTALL_DIR / "ToolkitOGM.exe"
APPDATA = Path(os.environ.get("APPDATA", ""))
CONFIG = APPDATA / "ToolkitOGM" / "config.json"
STARTUP_LOG = APPDATA / "ToolkitOGM" / "startup.log"
RELEASES = "https://github.com/jchaconv94/ToolkitSISMED/releases/download"
EICAR_NAME = "prueba-eicar.com"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_TASK = "ToolkitOGM_Autorun"
LEGACY_RUN = "ToolkitOGM_Sync"
DETECTION_EVENTS = (1006, 1007, 1008, 1015, 1116, 1117, 1118, 1119, 1121, 1122, 1125, 1126)
CHANGE_EVENTS = (5001, 5004, 5007, 5010, 5012)

results: list[tuple[bool, str]] = []


def check(condition, message: str) -> bool:
    results.append((bool(condition), message))
    print(("OK    " if condition else "FALLA ") + message, flush=True)
    return bool(condition)


def ps(command: str, timeout: int = 900) -> subprocess.CompletedProcess:
    """Windows PowerShell 5.1: trae el módulo de Defender siempre."""
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", command], capture_output=True, text=True, timeout=timeout)


def ps_json(command: str):
    result = ps(f"$ErrorActionPreference = 'Stop'; @({command}) | ConvertTo-Json -Depth 4 -Compress")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    text = result.stdout.strip()
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def status() -> dict:
    rows = ps_json("Get-MpComputerStatus | Select-Object AMServiceEnabled, AntivirusEnabled, "
                   "RealTimeProtectionEnabled, BehaviorMonitorEnabled, IoavProtectionEnabled, "
                   "OnAccessProtectionEnabled, AMRunningMode, AMProductVersion, AntivirusSignatureVersion, "
                   "AntivirusSignatureLastUpdated")
    return rows[0] if rows else {}


def preferences() -> dict:
    rows = ps_json("Get-MpPreference | Select-Object DisableRealtimeMonitoring, DisableBehaviorMonitoring, "
                   "DisableIOAVProtection, DisableBlockAtFirstSeen, MAPSReporting, SubmitSamplesConsent, "
                   "PUAProtection, ExclusionPath, ExclusionProcess, ExclusionExtension")
    return rows[0] if rows else {}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detections(since: str) -> list[dict]:
    """Lo que Defender detectó desde `since` (UTC), con el nombre de la amenaza."""
    rows = ps_json(
        "$names = @{}; Get-MpThreat -ErrorAction SilentlyContinue | ForEach-Object { $names[[string]$_.ThreatID] = $_.ThreatName }; "
        "Get-MpThreatDetection -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ "
        "time = $_.InitialDetectionTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
        "threat = $names[[string]$_.ThreatID]; id = [string]$_.ThreatID; process = [string]$_.ProcessName; "
        "resources = (@($_.Resources) -join ' | '); action = [string]$_.ActionSuccess } }")
    return [r for r in rows if str(r.get("time") or "") >= since]


def events(since: str, ids) -> list[dict]:
    start = since.replace("Z", "")
    id_list = ",".join(str(i) for i in ids)
    return ps_json(
        "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Windows Defender/Operational'; "
        f"Id={id_list}; StartTime=([datetime]::SpecifyKind([datetime]'{start}', 'Utc')).ToLocalTime()}} "
        "-ErrorAction SilentlyContinue | ForEach-Object { $m = ([string]$_.Message -replace '\\s+', ' '); "
        "[pscustomobject]@{ id = $_.Id; time = $_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
        "message = $m.Substring(0, [Math]::Min(500, $m.Length)) } }")


def is_eicar(row: dict) -> bool:
    text = " ".join(str(v) for v in row.values()).lower()
    return "eicar" in text


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**values):
    data = load_state()
    data.update(values)
    STATE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def new_detections(label: str) -> bool:
    """Falla si Defender detectó algo (además del EICAR) desde que se encendió."""
    since = load_state().get("since", "")
    found = [d for d in detections(since) if not is_eicar(d)]
    for d in found:
        print(f"      {d['time']} {d.get('threat')} · {d.get('process')} · {d.get('resources')}")
    return check(not found, f"Defender no detectó nada {label}"
                 + ("" if not found else f": {', '.join(sorted({str(d.get('threat')) for d in found}))}"))


def fully_on(s: dict) -> bool:
    return all(s.get(k) for k in ("AntivirusEnabled", "RealTimeProtectionEnabled", "BehaviorMonitorEnabled",
                                  "IoavProtectionEnabled"))


def wait_until_on(timeout: int = 300) -> dict:
    """Al actualizar sus firmas, Defender puede instalar una versión nueva y reiniciarse: se espera."""
    deadline = time.time() + timeout
    s: dict = {}
    while time.time() < deadline:
        ps("Start-Service -Name WinDefend -ErrorAction SilentlyContinue")
        try:
            s = status()
        except Exception as exc:  # noqa: BLE001 - mientras se reinicia no responde
            print(f"      Defender todavía no responde: {exc}", flush=True)
            s = {}
        if fully_on(s):
            return s
        time.sleep(10)
    return s


def still_on(label: str) -> bool:
    s = status()
    return check(s.get("RealTimeProtectionEnabled") and s.get("BehaviorMonitorEnabled"),
                 f"Defender sigue encendido {label}")


# --- encender Defender ------------------------------------------------------------------
def enable():
    WORK.mkdir(parents=True, exist_ok=True)
    print("Antes:", json.dumps(status()), json.dumps(preferences()), sep="\n", flush=True)
    script = r"""
$ErrorActionPreference = 'Continue'
Remove-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender' -Recurse -Force -ErrorAction SilentlyContinue
Start-Service -Name WinDefend -ErrorAction SilentlyContinue
$p = Get-MpPreference
if ($p.ExclusionPath) { Remove-MpPreference -ExclusionPath $p.ExclusionPath }
if ($p.ExclusionProcess) { Remove-MpPreference -ExclusionProcess $p.ExclusionProcess }
if ($p.ExclusionExtension) { Remove-MpPreference -ExclusionExtension $p.ExclusionExtension }
Set-MpPreference -DisableRealtimeMonitoring $false
Set-MpPreference -DisableBehaviorMonitoring $false
Set-MpPreference -DisableIOAVProtection $false
Set-MpPreference -DisableScriptScanning $false
Set-MpPreference -DisableArchiveScanning $false
Set-MpPreference -DisableBlockAtFirstSeen $false
Set-MpPreference -MAPSReporting 2
Set-MpPreference -SubmitSamplesConsent 1
Set-MpPreference -PUAProtection 1
# Sin análisis completos programados ni de recuperación: en estas máquinas saturan el disco y la
# máquina se pierde a media prueba. La protección en tiempo real y la de comportamiento siguen.
Set-MpPreference -DisableCatchupFullScan $true
Set-MpPreference -DisableCatchupQuickScan $true
Set-MpPreference -ScanScheduleDay 8
Set-MpPreference -RemediationScheduleDay 8
Update-MpSignature -ErrorAction SilentlyContinue
"""
    result = ps(script)
    print(result.stdout.strip(), result.stderr.strip(), sep="\n", flush=True)
    s = wait_until_on()
    p = preferences()
    print("Después:", json.dumps(s), json.dumps(p), sep="\n", flush=True)
    check(s.get("AntivirusEnabled"), "el antivirus de Defender está encendido")
    check(s.get("RealTimeProtectionEnabled"), "la protección en tiempo real está encendida")
    check(s.get("BehaviorMonitorEnabled"), "la vigilancia de comportamiento está encendida")
    check(s.get("IoavProtectionEnabled"), "el análisis de lo descargado está encendido")
    check(int(p.get("MAPSReporting") or 0) > 0, "la protección en la nube está encendida")
    check(not p.get("ExclusionPath") and not p.get("ExclusionProcess"), "no queda ninguna carpeta ni programa excluido")
    print(f"Defender {s.get('AMProductVersion')} · firmas {s.get('AntivirusSignatureVersion')} · modo {s.get('AMRunningMode')}")

    since = now_utc()
    save_state(since=since)
    # El archivo de prueba estándar de los antivirus: si Defender está de verdad activo, lo bloquea.
    eicar = WORK / EICAR_NAME
    text = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-" + "ANTIVIRUS-TEST-FILE!$H+H*"
    try:
        eicar.write_text(text, encoding="ascii")
    except OSError as exc:
        print(f"      no dejó escribir el EICAR: {exc}")

    def caught() -> bool:
        try:
            gone = not eicar.exists() or eicar.read_text(encoding="ascii") != text
        except OSError:
            gone = True
        return gone or any(is_eicar(d) for d in detections(since))

    deadline = time.time() + 90
    while time.time() < deadline and not caught():
        time.sleep(3)
    check(caught(), "Defender bloquea el archivo de prueba EICAR: está activo de verdad")


# --- el instalador publicado ---------------------------------------------------------------
def config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_size() -> int:
    return STARTUP_LOG.stat().st_size if STARTUP_LOG.exists() else 0


def log_since(mark: int) -> str:
    if not STARTUP_LOG.exists():
        return ""
    with open(STARTUP_LOG, "rb") as f:
        f.seek(mark)
        return f.read().decode("utf-8", "replace")


def toolkit_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ToolkitOGM.exe", "/NH"], capture_output=True, text=True).stdout
    return "ToolkitOGM.exe" in out


def kill_toolkit():
    for image in ("ToolkitOGM.exe", "flet.exe", "ToolkitUpdater.exe"):
        subprocess.run(["taskkill", "/F", "/T", "/IM", image], capture_output=True)
    time.sleep(2)


def scan(path: Path, label: str):
    result = ps(f"Start-MpScan -ScanType CustomScan -ScanPath '{path}'", timeout=1800)
    check(result.returncode == 0, f"Defender analizó {label}" + ("" if result.returncode == 0 else f" ({result.stderr.strip()[:200]})"))
    new_detections(f"al analizar {label}")


def keep_open(process: subprocess.Popen, seconds: int, label: str):
    alive = True
    end = time.time() + seconds
    while time.time() < end:
        if not EXE.exists() or not toolkit_running():
            alive = False
            break
        time.sleep(10)
    check(alive and EXE.exists(), f"el Toolkit sigue abierto y en su lugar tras {seconds} s {label}")


def download(version: str, defender_on: bool = True) -> Path:
    name = f"ToolkitOGM-Setup-{version}.exe"
    setup = WORK / name
    with requests.get(f"{RELEASES}/desktop-v{version}/{name}", stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(setup, "wb") as out:
            for chunk in r.iter_content(1 << 20):
                out.write(chunk)
    sums = requests.get(f"{RELEASES}/desktop-v{version}/{name}.sha256", timeout=60)
    if sums.ok:
        declared = sums.text.split()[0].lower()
        check(hashlib.sha256(setup.read_bytes()).hexdigest() == declared,
              f"bajó el instalador publicado {version} con su huella correcta")
    # Como si lo hubieran bajado con el navegador: Windows lo marca como venido de internet.
    with open(f"{setup}:Zone.Identifier", "w", encoding="ascii") as ads:
        ads.write(f"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl={RELEASES}/desktop-v{version}/{name}\r\n")
    if defender_on:
        time.sleep(5)
        check(setup.exists(), f"el instalador {version} sigue ahí después de descargarlo (no lo puso en cuarentena)")
        new_detections(f"al descargar el instalador {version}")
        scan(setup, f"el instalador {version}")
    return setup


def install(setup: Path, version: str, *extra: str, log: str = "instalacion.log", defender_on: bool = True):
    result = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/ALLUSERS",
                             f"/LOG={WORK / log}", *extra], timeout=900)
    check(result.returncode == 0 and EXE.exists(), f"el instalador {version} terminó bien y dejó ToolkitOGM.exe")
    if defender_on:
        new_detections(f"al instalar la {version}")
        scan(INSTALL_DIR, "la carpeta instalada")


def published(version: str):
    WORK.mkdir(parents=True, exist_ok=True)
    install(download(version), version)

    # Como al encender la PC: escondido en la bandeja.
    data = config()
    data["auto_startup"] = True
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    kill_toolkit()
    mark = log_size()
    process = subprocess.Popen([str(EXE), "--autorun"])
    deadline = time.time() + 120
    while time.time() < deadline and "boot_status=autorun" not in log_since(mark) and process.poll() is None:
        time.sleep(2)
    text = log_since(mark)
    check(f"version={version}" in text, f"abrió la versión {version} al encender")
    keep_open(process, 180, "al encender")
    # Y abierto a mano (muestra la ventana).
    subprocess.Popen([str(EXE)])
    time.sleep(30)
    keep_open(process, 60, "con la ventana abierta")
    new_detections("con el Toolkit abierto")
    still_on("durante la prueba")
    kill_toolkit()


# --- actualizar desde una versión vieja -------------------------------------------------------
def task_exists() -> bool:
    return subprocess.run(["schtasks", "/Query", "/TN", LEGACY_TASK], capture_output=True).returncode == 0


def run_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, LEGACY_RUN)[0]
    except OSError:
        return None


def legacy(old_version: str):
    """Defender todavía apagado: la PC queda como la dejaba la versión vieja."""
    import winreg

    WORK.mkdir(parents=True, exist_ok=True)
    install(download(old_version, defender_on=False), old_version, log="anterior.log", defender_on=False)
    command = f'"{EXE}" --autorun'
    # Lo mismo que hacía la versión vieja: la tarea al iniciar sesión y, si fallaba, la clave Run.
    subprocess.run(["schtasks", "/Create", "/TN", LEGACY_TASK, "/TR", command, "/SC", "ONLOGON", "/RL", "LIMITED",
                    "/IT", "/DELAY", "0002:00", "/F"], capture_output=True)
    # En una cuenta nueva la clave Run puede no existir todavía.
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, LEGACY_RUN, 0, winreg.REG_SZ, command)
    check(task_exists(), f"quedó la tarea de arranque de la {old_version}")
    check(run_value() == command, f"quedó la clave Run de la {old_version}")
    save_state(old_version=old_version)


def open_at_logon(label: str, seconds: int = 180) -> str:
    kill_toolkit()
    mark = log_size()
    process = subprocess.Popen([str(EXE), "--autorun"])
    deadline = time.time() + 120
    while time.time() < deadline and "boot_status=autorun" not in log_since(mark) and process.poll() is None:
        time.sleep(2)
    keep_open(process, seconds, label)
    return log_since(mark)


def upgrade(version: str):
    """Defender encendido: la versión publicada se instala encima de la vieja y se abre al encender."""
    WORK.mkdir(parents=True, exist_ok=True)
    check(task_exists() and run_value(), "antes de actualizar siguen la tarea y la clave Run viejas")
    # Los mismos parámetros que usa el actualizador del Toolkit.
    install(download(version), version, "/SP-", "/NORESTARTAPPLICATIONS", "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS", f"/DIR={INSTALL_DIR}", log="actualizacion.log")
    # Sin tocar config.json: la primera vez la preferencia sale de la tarea y la clave viejas.
    text = open_at_logon(f"al encender por primera vez con la {version}")
    print(text, flush=True)
    check(f"version={version}" in text, f"abrió la versión {version}")
    check("startup_migrated enabled=True" in text, "tomó el arranque de la versión vieja y lo dejó encendido")
    if tuple(int(x) for x in version.split(".")) >= (2, 4, 5):
        check(task_exists(), "dejó la tarea vieja como estaba: no toca el arranque de Windows")
        check(run_value() is not None, "dejó la clave Run vieja como estaba")
    else:
        check(not task_exists(), "borró la tarea vieja")
        check(run_value() is None, "borró la clave Run vieja")
    new_detections(f"al abrir la {version} por primera vez sobre la versión vieja")
    subprocess.Popen([str(EXE)])
    time.sleep(30)
    new_detections("con la ventana abierta")
    # Segundo encendido: ya no hay nada que borrar.
    open_at_logon("al encender por segunda vez", 120)
    new_detections("en el segundo encendido")
    still_on("durante la prueba")
    kill_toolkit()


def oldrun():
    """Control: la versión vieja con Defender encendido. Solo informa."""
    old = load_state().get("old_version", "?")
    # Que no busque ni baje la versión nueva: se actualizaría sola en medio del control y su auxiliar
    # de actualización quedaría abierto.
    data = config()
    data.update({"update_auto_check": False, "update_auto_download": False})
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    mark = log_size()
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen([str(EXE), "--autorun"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
    end = time.time() + 240
    while time.time() < end and EXE.exists():
        time.sleep(10)
    since = load_state().get("since", "")
    found = [d for d in detections(since) if not is_eicar(d)]
    print(log_since(mark), flush=True)
    for d in found:
        print(f"      {d['time']} {d.get('threat')} · {d.get('process')} · {d.get('resources')}", flush=True)
    names = ", ".join(sorted({str(d.get("threat")) for d in found})) or "nada"
    print(f"CONTROL: con la {old}, Defender detectó: {names}; ToolkitOGM.exe "
          f"{'sigue' if EXE.exists() else 'ya no está (cuarentena)'}", flush=True)
    results.append((True, f"control con la {old}: Defender detectó {names}"))
    try:
        process.kill()
    except OSError:
        pass
    kill_toolkit()


# --- informe ----------------------------------------------------------------------------
def report(informative: bool = False):
    since = load_state().get("since", "")
    if not since:
        check(False, "Defender no se llegó a encender")
        return
    found = [d for d in detections(since) if not is_eicar(d)]
    seen = [e for e in events(since, DETECTION_EVENTS) if not is_eicar(e)]
    changes = events(since, CHANGE_EVENTS)
    print(f"Detecciones desde {since}: {len(found)}")
    for d in found:
        print(f"  {d['time']} {d.get('threat')} · {d.get('process')} · {d.get('resources')} · {d.get('action')}")
    print(f"Eventos de detección en el registro de Defender: {len(seen)}")
    for e in seen:
        print(f"  {e['time']} [{e['id']}] {e['message']}")
    print(f"Cambios de configuración de Defender: {len(changes)}")
    for e in changes:
        print(f"  {e['time']} [{e['id']}] {e['message'][:200]}")
    if informative:
        results.append((True, f"detecciones: {len(found)}; eventos de detección: {len(seen)} (solo informa)"))
    else:
        check(not found, "ninguna detección de Defender en toda la prueba (sin contar el EICAR)")
        check(not seen, "ningún evento de detección en el registro de Defender (sin contar el EICAR)")
    check(not any(e["id"] == 5001 for e in changes), "la protección en tiempo real no se apagó en ningún momento")
    still_on("al final")
    (WORK / "informe.json").write_text(json.dumps({"detections": found, "events": seen, "changes": changes},
                                                  indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        print("Esta prueba cambia la configuración de Defender: solo corre en GitHub Actions (Windows).")
        return 2
    step = sys.argv[1]
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        if step == "enable":
            enable()
        elif step == "published":
            published(sys.argv[2])
        elif step == "legacy":
            legacy(sys.argv[2])
        elif step == "upgrade":
            upgrade(sys.argv[2])
        elif step == "oldrun":
            oldrun()
        elif step == "report":
            report(informative="--informe" in sys.argv)
        else:
            raise SystemExit(f"Paso desconocido: {step}")
    except Exception as exc:  # noqa: BLE001 - que quede en el informe
        check(False, f"la prueba se interrumpió: {type(exc).__name__}: {exc}")

    failed = [m for ok, m in results if not ok]
    lines = [f"## Defender · paso «{step}»", "", f"{len(results) - len(failed)} de {len(results)} comprobaciones OK", ""]
    lines += [("✅ " if ok else "❌ ") + m for ok, m in results]
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    print("\n" + "\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
