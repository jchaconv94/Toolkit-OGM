"""Arma el código del Toolkit aparte del exe: build/app/app.zip (módulos compilados) y build/app/VERSION.

ToolkitOGM.exe solo lleva el arranque (launcher, app_loader, update_signature) y las librerías;
el resto del código va en `_internal/app/app.zip`. Así una actualización de código solo cambia
ese zip. El zip sale igual byte a byte si el código no cambió: fechas fijas, orden fijo y .pyc
sin fecha de origen (hash sin comprobar), compilado con PYTHONHASHSEED=0.

    python build_app.py
"""

from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TOOLKIT_DIR = REPO_ROOT / "toolskit"
OUT_DIR = REPO_ROOT / "build" / "app"
# Van dentro del exe: tienen que funcionar aunque el código descargado esté roto.
RUNTIME_MODULES = ("launcher", "app_loader", "update_signature")


def app_modules(toolkit_dir: Path = TOOLKIT_DIR) -> list[tuple[str, Path]]:
    """(nombre del módulo, archivo) de todo el código del Toolkit que va en app.zip."""
    found = []
    for path in sorted(toolkit_dir.rglob("*.py")):
        rel = path.relative_to(toolkit_dir)
        if "__pycache__" in rel.parts or rel.name.startswith("test_"):
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        name = ".".join(parts)
        if not name or name in RUNTIME_MODULES:
            continue
        found.append((name, path))
    return found


def counts_for_runtime(dest: str) -> bool:
    """Si un archivo de datos instalado cuenta para la identidad del runtime (ToolkitOGM.spec).

    No cuentan el código del Toolkit (va en app/) ni el RECORD de cada librería: pip lo escribe al
    instalarla con la huella de los lanzadores .exe que arma en ese momento (f2py.exe de numpy), y
    esos llevan la hora de instalación. Con el RECORD, cada compilación en un entorno nuevo salía
    con otro runtime y ninguna versión llegaba como actualización chica (2.4.5)."""
    parts = PureWindowsPath(dest).parts
    if not parts or parts[0] == "app":
        return False
    return not (len(parts) >= 2 and parts[-2].endswith(".dist-info") and parts[-1] == "RECORD")


def build_zip(out_zip: Path, toolkit_dir: Path = TOOLKIT_DIR):
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, path in app_modules(toolkit_dir):
            rel = path.relative_to(toolkit_dir).as_posix()
            compiled = Path(tmp) / (rel.replace("/", "_") + "c")
            py_compile.compile(str(path), cfile=str(compiled), dfile=rel, doraise=True, optimize=0,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            info = zipfile.ZipInfo(rel[:-3] + ".pyc", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, compiled.read_bytes())


def main():
    if os.environ.get("PYTHONHASHSEED") != "0":
        # Sin semilla fija, los conjuntos de constantes salen en otro orden en cada compilación.
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        sys.exit(subprocess.call([sys.executable, __file__, *sys.argv[1:]], env=env))
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    build_zip(OUT_DIR / "app.zip")
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    (OUT_DIR / "VERSION").write_text(version + "\n", encoding="utf-8")
    print(f"app.zip: {len(app_modules())} módulos, {(OUT_DIR / 'app.zip').stat().st_size / 1e6:.2f} MB; versión {version}")


if __name__ == "__main__":
    main()
