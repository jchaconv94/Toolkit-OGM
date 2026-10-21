"""Prueba de punta a punta de las actualizaciones de código, con el instalador de verdad.

Antes de correrla, el flujo compila el programa con una clave de prueba (UPDATE_PUBLIC_KEY) y deja
la clave privada en UPDATE_SIGNING_KEY. Esta prueba:

1. instala esa compilación en Archivos de programa y la abre como al encender Windows;
2. arma una actualización de código (un cambio en el código y otra versión), la firma, la sirve
   desde un servidor local y la descarga con el mismo código del Toolkit;
3. vuelve a abrir el Toolkit y comprueba que arranca con la versión nueva, sin instalar nada;
4. prueba lo que puede salir mal: zip alterado, firma de otra clave, otro runtime, código que no
   importa y código que se cae al arrancar (vuelve solo a la versión anterior);
5. compila de nuevo con otra versión para ver que el runtime no cambia y que el instalador completo
   sigue mandando sobre las actualizaciones de código.

Instala en Archivos de programa: solo corre en GitHub Actions (máquina desechable).
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolskit"))
sys.path.insert(0, str(ROOT / "packaging" / "windows"))

import update_signature  # noqa: E402
from code_update import CodeUpdater, find_code_update  # noqa: E402

INSTALL_DIR = Path(os.environ["ProgramFiles"]) / "ToolKit SISMED"
EXE = INSTALL_DIR / "ToolkitOGM.exe"
BUNDLE = INSTALL_DIR / "_internal"
UPDATES = Path(os.environ["LOCALAPPDATA"]) / "ToolkitOGM" / "app"
CONFIG = Path(os.environ["APPDATA"]) / "ToolkitOGM" / "config.json"
STARTUP_LOG = Path(os.environ["APPDATA"]) / "ToolkitOGM" / "startup.log"
SECRET = bytes.fromhex(os.environ["UPDATE_SIGNING_KEY"])
WORK = ROOT / "build" / "e2e-codigo"

results: list[tuple[bool, str]] = []


def check(condition, message: str):
    results.append((bool(condition), message))
    print(("OK    " if condition else "FALLO ") + message, flush=True)


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, stdin=subprocess.DEVNULL, **kwargs)


def wait_until(condition, timeout: float, step: float = 0.5) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(step)
    return bool(condition())


def kill_toolkit():
    for image in ("ToolkitOGM.exe", "flet.exe"):
        run(["taskkill", "/F", "/T", "/IM", image])
    time.sleep(2)


def installer(version: str) -> Path:
    return ROOT / "dist" / "installer" / f"ToolkitOGM-Setup-{version}.exe"


def install(version: str, log: str):
    result = run([installer(version), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/ALLUSERS",
                  f"/LOG={WORK / log}"], timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"El instalador terminó con código {result.returncode}")


def config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_config(**values):
    data = config()
    data.update(values)
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


def open_at_logon(wait_ready: bool = True) -> tuple[str, subprocess.Popen]:
    """Abre el Toolkit como al encender Windows y devuelve lo que anotó en el registro de arranque."""
    mark = log_mark()
    process = subprocess.Popen([str(EXE), "--autorun"])
    if wait_ready:
        wait_until(lambda: "boot_status=autorun" in log_since(mark) or process.poll() is not None, 90)
    else:
        try:
            process.wait(60)
        except subprocess.TimeoutExpired:
            pass
    time.sleep(2)
    return log_since(mark), process


def running_version(text: str) -> str | None:
    for line in text.splitlines():
        if "] version=" in line:
            return line.split("] version=", 1)[1].split(";", 1)[0]
    return None


def state() -> dict:
    try:
        return json.loads((UPDATES / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def runtime() -> dict:
    return json.loads((BUNDLE / "runtime.json").read_text(encoding="utf-8"))


def pyc(source: str, name: str) -> bytes:
    code = compile(source, name, "exec")
    return importlib._bootstrap_external._code_to_hash_pyc(code, importlib.util.source_hash(source.encode()), False)


def replaced(app_zip: bytes, name: str, data: bytes) -> bytes:
    """El mismo app.zip con un archivo cambiado."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(app_zip)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, data if item.filename == name else src.read(item.filename))
    return out.getvalue()


def place_update(version: str, app_zip: bytes, runtime_id: str | None = None, secret: bytes = SECRET):
    """Deja una actualización ya descargada, como la deja code_update (para los casos de falla)."""
    manifest = json.dumps({"format": 1, "version": version, "runtime": runtime_id or runtime()["runtime"],
                           "app": {"sha256": hashlib.sha256(app_zip).hexdigest(), "size": len(app_zip)}},
                          sort_keys=True, separators=(",", ":")).encode()
    folder = UPDATES / version
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    (folder / "app.zip").write_bytes(app_zip)
    (folder / "manifest.json").write_bytes(manifest)
    (folder / "manifest.sig").write_bytes(update_signature.sign(secret, manifest))


def serve(directory: Path) -> tuple[str, http.server.ThreadingHTTPServer]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def case(title: str):
    def wrap(fn):
        def runner(*args):
            print(f"\n== {title} ==", flush=True)
            try:
                return fn(*args)
            except Exception as exc:
                traceback.print_exc()
                check(False, f"{title}: se detuvo por {type(exc).__name__}: {exc}")
            finally:
                kill_toolkit()
        return runner
    return wrap


@case("Instalar el programa con el código aparte")
def install_base(version: str):
    install(version, "base.log")
    check((BUNDLE / "app" / "app.zip").exists(), "el código del Toolkit está en _internal/app/app.zip")
    check((BUNDLE / "app" / "VERSION").read_text().strip() == version, f"la versión instalada es {version}")
    check(bool(runtime().get("runtime")), f"runtime.json identifica el runtime ({runtime().get('runtime')})")
    check(runtime().get("public_key") == update_signature.public_key(SECRET).hex(),
          "el programa trae la clave pública de prueba")
    print(f"ToolkitOGM.exe: {EXE.stat().st_size / 1e6:.2f} MB; app.zip: {(BUNDLE / 'app' / 'app.zip').stat().st_size / 1e6:.2f} MB")
    set_config(auto_startup=True)
    text, _ = open_at_logon()
    check(running_version(text) == version, f"abre con la versión {version} (registro: {running_version(text)})")
    check("autorun-hidden-ready" in text, "arranca escondido en la bandeja, como al encender Windows")
    check(not (Path(os.environ["USERPROFILE"]) / ".flet" / "bin").exists(),
          "Flet usa su ventana incluida: no descargó nada a la carpeta del usuario")


@case("Descargar una actualización de código")
def download_update(version: str, app_zip: Path, signed_dir: Path):
    url, server = serve(signed_dir)
    try:
        names = [p.name for p in signed_dir.iterdir()]
        payload = [{"draft": False, "prerelease": False,
                    "assets": [{"name": n, "browser_download_url": f"{url}/{n}"} for n in names]}]
        info = find_code_update(payload, (BUNDLE / "app" / "VERSION").read_text().strip())
        check(info is not None and info.version == version, f"encuentra la actualización {version} en la versión publicada")
        updater = CodeUpdater(requests.Session(), validate_url=lambda _u: None, user_agent="e2e",
                              root=UPDATES, bundle=BUNDLE)
        check(updater.supported(), "el programa instalado acepta actualizaciones de código")
        sizes = []
        check(updater.install(info, progress=lambda done, total: sizes.append(total)) == version,
              "la descarga se verifica y queda lista")
        check(sizes and sizes[-1] == app_zip.stat().st_size and sizes[-1] < 2_000_000,
              f"bajó solo el código: {sizes[-1] / 1e6:.2f} MB (el instalador pesa "
              f"{installer((BUNDLE / 'app' / 'VERSION').read_text().strip()).stat().st_size / 1e6:.0f} MB)")
        check(not any(p.suffix.lower() in (".exe", ".dll") for p in (UPDATES / version).iterdir()),
              "la actualización no trae ningún programa: solo el zip, el manifiesto y la firma")
    finally:
        server.shutdown()


@case("Abrir el Toolkit con la actualización")
def open_updated(version: str):
    text, _ = open_at_logon()
    check(running_version(text) == version, f"abre con la versión {version} sin instalar nada (registro: {running_version(text)})")
    check(str(UPDATES / version) in text, "el código sale de la carpeta del usuario")
    check(wait_until(lambda: state().get("healthy") == version, 30), "la versión nueva queda marcada como sana")
    check(config().get("last_run_version") == version, "anota la versión para avisar que se actualizó")
    check((INSTALL_DIR / "_internal" / "app" / "VERSION").read_text().strip() != version,
          "Archivos de programa no se tocó")


@case("Actualización alterada")
def tampered(good: str, base: str):
    path = UPDATES / good / "app.zip"
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    try:
        text, _ = open_at_logon()
        check(running_version(text) == base, f"con el zip alterado abre la versión del instalador ({running_version(text)})")
    finally:
        path.write_bytes(original)
    text, _ = open_at_logon()
    check(running_version(text) == good, "con el zip bueno vuelve a abrir la actualización")


@case("Firma de otra clave y otro runtime")
def wrong_signature(good: str, app_zip: bytes):
    place_update("9.9.20", app_zip, secret=bytes(32))
    place_update("9.9.21", app_zip, runtime_id="otro-runtime")
    text, _ = open_at_logon()
    check(running_version(text) == good, f"ignora la firma ajena y el otro runtime ({running_version(text)})")
    for v in ("9.9.20", "9.9.21"):
        shutil.rmtree(UPDATES / v, ignore_errors=True)


@case("Código que no se puede importar")
def broken_import(good: str, base: str, app_zip: bytes):
    place_update("9.9.30", replaced(app_zip, "main.pyc", pyc("raise ImportError('roto a proposito')\n", "main.py")))
    text, _ = open_at_logon()
    check(running_version(text) == base, f"en el mismo arranque vuelve al código del instalador ({running_version(text)})")
    check("9.9.30" in state().get("bad", []), "la versión rota queda marcada como mala")
    text, _ = open_at_logon()
    check(running_version(text) == good, f"el siguiente arranque abre la última buena ({running_version(text)})")


@case("Código que se cae al arrancar")
def crash_on_start(good: str, app_zip: bytes):
    source = "import sys\ndef run():\n    raise SystemExit(3)\n"
    place_update("9.9.40", replaced(app_zip, "main.pyc", pyc(source, "main.py")))
    codes = []
    for _ in range(2):
        _, process = open_at_logon(wait_ready=False)
        codes.append(process.poll())
    check(codes == [3, 3], f"los dos primeros arranques se caen (códigos {codes})")
    text, _ = open_at_logon()
    check(running_version(text) == good, f"al tercero vuelve a la última buena ({running_version(text)})")
    check("9.9.40" in state().get("bad", []), "la versión que se cae queda marcada como mala")


@case("Código que lanza un error al arrancar")
def error_on_start(good: str, app_zip: bytes):
    source = "def run():\n    raise RuntimeError('falla a proposito')\n"
    place_update("9.9.50", replaced(app_zip, "main.pyc", pyc(source, "main.py")))
    mark = log_mark()
    subprocess.Popen([str(EXE), "--autorun"])
    check(wait_until(lambda: "boot_status=autorun" in log_since(mark), 90),
          "el Toolkit se vuelve a abrir solo, sin mostrar el error")
    check(running_version(log_since(mark)) == good, f"y abre la última buena ({running_version(log_since(mark))})")
    check("9.9.50" in state().get("bad", []), "la versión que falla queda marcada como mala")


@case("Instalador completo después de una actualización de código")
def full_installer_wins(version: str, base_runtime: str):
    install(version, "completo.log")
    check(runtime()["runtime"] == base_runtime,
          f"el runtime no cambió con un cambio de código ({runtime()['runtime']} = {base_runtime})")
    text, _ = open_at_logon()
    check(running_version(text) == version, f"abre la versión del instalador nuevo ({running_version(text)})")
    def stale():
        return [p.name for p in UPDATES.iterdir() if p.is_dir() and p.name[0].isdigit()
                and tuple(map(int, p.name.split("."))) < tuple(map(int, version.split(".")))]
    check(wait_until(lambda: not stale(), 60), f"borra las actualizaciones de código que quedaron viejas ({stale()})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("Esta prueba instala el Toolkit de verdad: solo corre en GitHub Actions.")
        return 2
    step = sys.argv[1]
    WORK.mkdir(parents=True, exist_ok=True)
    if step == "base":
        version = (ROOT / "VERSION").read_text().strip()
        install_base(version)
        (WORK / "base.json").write_text(json.dumps({"version": version, "runtime": runtime()["runtime"]}))
    elif step == "update":
        base = json.loads((WORK / "base.json").read_text())
        version = (ROOT / "VERSION").read_text().strip()
        signed = ROOT / "build" / "firmado"
        app_zip = signed / f"ToolkitOGM-app-{version}.zip"
        download_update(version, app_zip, signed)
        open_updated(version)
        tampered(version, base["version"])
        wrong_signature(version, app_zip.read_bytes())
        broken_import(version, base["version"], app_zip.read_bytes())
        crash_on_start(version, app_zip.read_bytes())
        error_on_start(version, app_zip.read_bytes())
    elif step == "full":
        base = json.loads((WORK / "base.json").read_text())
        full_installer_wins((ROOT / "VERSION").read_text().strip(), base["runtime"])

    failed = [m for ok, m in results if not ok and m]
    lines = [f"## Actualizaciones de código · paso «{step}»", "",
             f"{len(results) - len(failed)} de {len(results)} comprobaciones OK", ""]
    lines += [("✅ " if ok else "❌ ") + m for ok, m in results if m]
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
