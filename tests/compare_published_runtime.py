"""Qué cambió en el runtime entre dos versiones publicadas.

    python tests/compare_published_runtime.py 2.4.4 2.4.5

Instala cada versión sin ventanas (en Windows), toma la huella de cada archivo instalado y de cada
módulo que va dentro de ToolkitOGM.exe, la desinstala y compara. El código del Toolkit
(`_internal/app`) y `runtime.json` cambian siempre; lo demás es el runtime. Sirve para saber por
qué una versión salió con otro runtime y llegó a las PC con el instalador completo.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "comparar-runtime"
INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ToolKit SISMED"
RELEASES = "https://github.com/jchaconv94/ToolkitSISMED/releases/download"
ALWAYS_CHANGE = ("_internal/app/", "_internal/runtime.json", "unins")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def kill_toolkit():
    for image in ("ToolkitOGM.exe", "flet.exe", "ToolkitUpdater.exe"):
        subprocess.run(["taskkill", "/F", "/T", "/IM", image], capture_output=True)


def download(version: str) -> Path:
    name = f"ToolkitOGM-Setup-{version}.exe"
    setup = WORK / name
    with requests.get(f"{RELEASES}/desktop-v{version}/{name}", stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(setup, "wb") as out:
            for chunk in response.iter_content(1 << 20):
                out.write(chunk)
    return setup


def embedded(exe: Path) -> dict[str, str]:
    """Huella de cada módulo de Python que va dentro del exe (el PYZ) y de lo demás que lleva."""
    from PyInstaller.archive.readers import CArchiveReader

    found: dict[str, str] = {}
    archive = CArchiveReader(str(exe))
    for name, entry in archive.toc.items():
        if entry[-1] == "z":
            pyz = archive.open_embedded_archive(name)
            for module in pyz.toc:
                found[f"pyz:{module}"] = sha(pyz.extract(module, raw=True) or b"")
        else:
            # Las opciones del arranque no tienen contenido: extract devuelve None.
            found[f"pkg:{name}"] = sha(archive.extract(name) or b"")
    return found


def snapshot(version: str) -> tuple[dict[str, str], dict[str, str]]:
    kill_toolkit()
    setup = download(version)
    log = WORK / f"instalar-{version}.log"
    result = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/ALLUSERS", "/NOICONS",
                             f"/LOG={log}"], timeout=900)
    if result.returncode != 0:
        raise SystemExit(f"El instalador {version} terminó con código {result.returncode}")
    time.sleep(3)
    kill_toolkit()
    files: dict[str, str] = {}
    texts: dict[str, str] = {}
    for path in sorted(p for p in INSTALL_DIR.rglob("*") if p.is_file()):
        name = path.relative_to(INSTALL_DIR).as_posix()
        data = path.read_bytes()
        files[name] = sha(data)
        # Los textos chicos se guardan para mostrar qué líneas cambiaron.
        if len(data) < 2_000_000 and path.suffix.lower() not in (".exe", ".dll", ".pyd", ".zip"):
            try:
                texts[name] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    try:
        files.update(embedded(INSTALL_DIR / "ToolkitOGM.exe"))
    except Exception as exc:  # noqa: BLE001 - sin el detalle del exe igual sirve lo demás
        print(f"No se pudo leer lo que va dentro de ToolkitOGM.exe {version}: {type(exc).__name__}: {exc}")
    uninstall(version)
    return files, texts


def uninstall(version: str):
    uninstallers = sorted(INSTALL_DIR.glob("unins*.exe"))
    if uninstallers:
        subprocess.run([str(uninstallers[0]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=600)
    # El desinstalador se copia a otra carpeta y sigue solo: se espera a que termine de borrar.
    deadline = time.time() + 180
    while time.time() < deadline and (INSTALL_DIR / "ToolkitOGM.exe").exists():
        time.sleep(2)
    if (INSTALL_DIR / "ToolkitOGM.exe").exists():
        raise SystemExit(f"No se pudo desinstalar la {version}")


def report(before: str, after: str, a: dict[str, str], b: dict[str, str],
           texts_a: dict[str, str] | None = None, texts_b: dict[str, str] | None = None) -> list[str]:
    def runtime(name: str) -> bool:
        return not any(name.startswith(prefix) or f"/{prefix}" in name for prefix in ALWAYS_CHANGE)

    changed = sorted(k for k in b if k in a and a[k] != b[k] and runtime(k))
    added = sorted(k for k in b if k not in a and runtime(k))
    removed = sorted(k for k in a if k not in b and runtime(k))
    lines = [f"## Runtime de la {before} a la {after}", "",
             f"Archivos y módulos comparados: {len(b)}. Cambiaron {len(changed)}, nuevos {len(added)}, "
             f"quitados {len(removed)} (sin contar el código del Toolkit ni runtime.json).", ""]
    for k in changed:
        lines.append(f"- cambió `{k}`")
        if texts_a and texts_b and k in texts_a and k in texts_b:
            old, new = texts_a[k].splitlines(), texts_b[k].splitlines()
            diff = [line for line in difflib.unified_diff(old, new, lineterm="", n=0)
                    if line[:1] in "+-" and line[:3] not in ("+++", "---")]
            lines += [f"    {line}" for line in diff[:40]]
    lines += [f"- nuevo `{k}`" for k in added]
    lines += [f"- quitado `{k}`" for k in removed]
    return lines


def main() -> int:
    before, after = sys.argv[1:3]
    WORK.mkdir(parents=True, exist_ok=True)
    a, texts_a = snapshot(before)
    b, texts_b = snapshot(after)
    lines = report(before, after, a, b, texts_a, texts_b)
    text = "\n".join(lines)
    print(text, flush=True)
    (WORK / "comparacion.md").write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
