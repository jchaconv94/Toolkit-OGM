"""Compila el arranque (bootloader) de PyInstaller desde su código y lo pone en el PyInstaller instalado.

ToolkitOGM.exe es el arranque de PyInstaller con el programa pegado detrás. El arranque que trae el
paquete de PyInstaller es el mismo archivo en miles de programas, también en programas maliciosos, y
los antivirus lo usan de pista: Defender puso en cuarentena la 2.4.6 como «Trojan:Win32/Bearfoos.A!ml»
(falso positivo, 2026-10-24). Sin certificado de firma, compilarlo uno mismo es la medida más citada
(OnionShare, Mapillary): es el mismo código, pero otro archivo.

Pasos: baja de PyPI el código de la misma versión de PyInstaller que está instalada (con la huella
SHA-256 que publica PyPI), compila los cuatro arranques de Windows de 64 bits con MSVC (`waf configure
all`) y los copia sobre los del paquete. Falla si algo no sale: nunca se publica con el arranque de
serie sin que se note. Deja lo que hizo en build/bootloader/bootloader.json.

El runtime (ToolkitOGM.spec) no cuenta la huella de estos archivos, que cambia en cada compilación,
sino este archivo y build_windows.ps1: el cambio al arranque propio llega una vez con el instalador
completo y después las PC siguen recibiendo solo el código.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build" / "bootloader"
PLATFORM_DIR = "Windows-64bit-intel"
# Consola y ventana, normal y de depuración: los cuatro que PyInstaller puede pegar al programa.
BOOTLOADERS = ("run.exe", "runw.exe", "run_d.exe", "runw_d.exe")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pick_sdist(release: dict, version: str) -> dict:
    """El archivo de código (sdist) de esa versión en la respuesta de PyPI: nombre, dirección y huella."""
    for entry in release.get("urls", []):
        if entry.get("packagetype") == "sdist" and entry.get("filename", "").endswith(".tar.gz"):
            digest = (entry.get("digests") or {}).get("sha256", "")
            if not digest:
                raise SystemExit(f"PyPI no publica la huella SHA-256 del código de PyInstaller {version}.")
            return {"filename": entry["filename"], "url": entry["url"], "sha256": digest.lower()}
    raise SystemExit(f"PyPI no tiene el código (sdist) de PyInstaller {version}.")


def verified(data: bytes, expected: str, name: str) -> bytes:
    actual = sha256(data)
    if actual != expected.lower():
        raise SystemExit(f"La huella de {name} no coincide con la de PyPI ({actual} en vez de {expected}).")
    return data


def download_source(version: str) -> Path:
    with urllib.request.urlopen(f"https://pypi.org/pypi/pyinstaller/{version}/json", timeout=60) as response:
        sdist = pick_sdist(json.load(response), version)
    archive = WORK / sdist["filename"]
    if not archive.is_file() or sha256(archive.read_bytes()) != sdist["sha256"]:
        with urllib.request.urlopen(sdist["url"], timeout=300) as response:
            archive.write_bytes(verified(response.read(), sdist["sha256"], sdist["filename"]))
    source = WORK / "src"
    shutil.rmtree(source, ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(source, filter="data")
    folders = [path for path in source.iterdir() if path.is_dir()]
    if len(folders) != 1 or not (folders[0] / "bootloader" / "waf").is_file():
        raise SystemExit(f"El código de PyInstaller {version} no trae la carpeta bootloader con waf.")
    return folders[0]


def compile_bootloaders(source: Path) -> Path:
    out = source / "PyInstaller" / "bootloader" / PLATFORM_DIR
    # Se borran los que vienen en el código: lo que quede después lo compiló waf.
    for name in BOOTLOADERS:
        (out / name).unlink(missing_ok=True)
    result = subprocess.run([sys.executable, "waf", "configure", "all", "--target-arch=64bit"],
                            cwd=source / "bootloader")
    if result.returncode != 0:
        raise SystemExit("No se pudo compilar el arranque de PyInstaller (¿falta Visual Studio con C++?).")
    missing = [name for name in BOOTLOADERS if not (out / name).is_file()]
    if missing:
        raise SystemExit(f"La compilación no dejó {', '.join(missing)} en {out}.")
    return out


def install(built: Path, target: Path) -> list[dict]:
    """Copia los arranques compilados sobre los del PyInstaller instalado y dice qué cambió."""
    report = []
    for name in BOOTLOADERS:
        new = (built / name).read_bytes()
        old_path = target / name
        old = old_path.read_bytes() if old_path.is_file() else b""
        if new == old:
            raise SystemExit(f"{name} compilado es idéntico al instalado: no se compiló o ya estaba puesto.")
        old_path.write_bytes(new)
        report.append({"file": name, "stock_sha256": sha256(old) if old else None, "built_sha256": sha256(new)})
    return report


def main() -> int:
    if os.name != "nt":
        print("El arranque de Windows se compila en Windows (con MSVC).")
        return 2
    import PyInstaller

    version = PyInstaller.__version__
    target = Path(PyInstaller.__file__).resolve().parent / "bootloader" / PLATFORM_DIR
    WORK.mkdir(parents=True, exist_ok=True)
    marker = WORK / "bootloader.json"
    if marker.is_file():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        rows = previous.get("files") or []
        # Ya puesto en este mismo entorno (otra compilación local): no se vuelve a compilar.
        if previous.get("pyinstaller") == version and len(rows) == len(BOOTLOADERS) and all(
                (target / row["file"]).is_file() and sha256((target / row["file"]).read_bytes()) == row["built_sha256"]
                for row in rows):
            print(f"El arranque propio de PyInstaller {version} ya está puesto.")
            return 0
    print(f"Compilando el arranque de PyInstaller {version} desde su código...", flush=True)
    files = install(compile_bootloaders(download_source(version)), target)
    marker.write_text(json.dumps({"pyinstaller": version, "files": files}, indent=1), encoding="utf-8")
    for row in files:
        print(f"  {row['file']}: {row['stock_sha256']} -> {row['built_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
