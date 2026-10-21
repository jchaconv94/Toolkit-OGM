# -*- mode: python ; coding: utf-8 -*-

import hashlib
import json
import os
import platform
import sys
from pathlib import Path

import flet_desktop
import PyInstaller
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]
TOOLKIT_DIR = REPO_ROOT / "toolskit"
ICON_FILE = SPEC_DIR / "ToolkitOGM.ico"
VERSION_FILE = SPEC_DIR / "ToolkitOGM.version.txt"
FLET_DESKTOP_DIR = Path(flet_desktop.__file__).resolve().parent
FLET_DESKTOP_TREE = Tree(str(FLET_DESKTOP_DIR / "app"), prefix="flet_desktop/app")
APP_BUILD_DIR = REPO_ROOT / "build" / "app"

# El código del Toolkit va aparte del exe, en _internal/app/app.zip (lo arma build_app.py): una
# actualización de código solo cambia ese zip y el exe se queda igual. Ver toolskit/app_loader.py.
sys.path.insert(0, str(SPEC_DIR))
from build_app import RUNTIME_MODULES, app_modules  # noqa: E402

APP_MODULES = app_modules(TOOLKIT_DIR)

datas = [
    (str(TOOLKIT_DIR / "assets"), "assets"),
    (str(APP_BUILD_DIR / "app.zip"), "app"),
    (str(APP_BUILD_DIR / "VERSION"), "app"),
]
datas += collect_data_files("flet")

hiddenimports = [
    "fitz",
    "PyPDF2",
    "xlsxwriter",
    "pystray._win32",
    # Clave pública de Supabase para las claves de envío (la genera el flujo de publicación).
    "send_key_config",
    # Conexión inmediata con la web (backups SISMED).
    "websocket",
    # Generar ICI: el PDF lo dibuja el Toolkit (ici_render con PyMuPDF); Excel o WPS por COM, de respaldo.
    "ici_render",
    "ici_values",
    "win32com.client",
    "pythoncom",
]
hiddenimports += collect_submodules("pdf2docx")
# Todo el código del Toolkit se analiza para que entren las librerías que usa, aunque luego vaya en app.zip.
hiddenimports += [name for name, _ in APP_MODULES]

excludes = [
    "IPython",
    "ipykernel",
    "jupyter_client",
    "jupyter_core",
    "debugpy",
    "matplotlib",
    "scipy",
    "seaborn",
    "sklearn",
    "xgboost",
    "tkinter",
    "_tkinter",
    "tornado",
]


a = Analysis(
    [str(TOOLKIT_DIR / "launcher.py")],
    pathex=[str(TOOLKIT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Fuera del exe: el código del Toolkit (va en app.zip). Dentro: el arranque y las librerías.
_own = {str(path.resolve()).lower() for _, path in APP_MODULES}
a.pure = [entry for entry in a.pure if str(Path(entry[1]).resolve()).lower() not in _own]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content(src) -> str:
    path = Path(str(src or ""))
    return _sha256(path) if path.is_file() else "-"


def _runtime_id(public_key: str) -> str:
    """Identidad del runtime: si cambia, una actualización de código no sirve y hace falta el instalador.

    Sale del contenido de cada archivo que se instala fuera del código del Toolkit (Python, librerías,
    sus DLL y datos, Flet), de la versión de PyInstaller (su arranque va en el exe) y de los archivos
    de la compilación y el instalador. No de lo instalado en el equipo de compilación: pip y lo que no
    viaja con el programa no cuentan (antes sí, y casi cada versión salía con otro runtime). Para que
    no cambie solo, Python, PyInstaller y todas las librerías están fijados (build-constraints.txt)."""
    parts = [f"python={platform.python_version()}", f"pyinstaller={PyInstaller.__version__}", f"key={public_key}"]
    shipped = [("pure", a.pure), ("bin", a.binaries),
               ("data", [e for e in a.datas if Path(e[0]).parts[0] != "app"]), ("flet", FLET_DESKTOP_TREE)]
    for kind, toc in shipped:
        parts += sorted(f"{kind}:{entry[0]}={_content(entry[1])}" for entry in toc)
    for path in [*(TOOLKIT_DIR / f"{name}.py" for name in RUNTIME_MODULES), Path(SPEC),
                 SPEC_DIR / "ToolkitOGM.iss", SPEC_DIR / "ToolkitUpdater.cs", SPEC_DIR / "build_windows.ps1",
                 SPEC_DIR / "build-constraints.txt"]:
        parts.append(f"file:{path.name}={_sha256(path)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


# Clave pública de las actualizaciones de código: la de producción, o la de prueba que pase el flujo.
_public_key = (os.environ.get("UPDATE_PUBLIC_KEY") or (SPEC_DIR / "update_public_key.txt").read_text()).strip().lower()
_runtime_file = APP_BUILD_DIR.parent / "runtime.json"
_runtime_file.write_text(json.dumps({"runtime": _runtime_id(_public_key), "public_key": _public_key}, indent=1),
                         encoding="utf-8")
a.datas += [("runtime.json", str(_runtime_file), "DATA")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ToolkitOGM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE) if ICON_FILE.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    FLET_DESKTOP_TREE,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ToolkitOGM",
)
