# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import flet_desktop
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]
TOOLKIT_DIR = REPO_ROOT / "toolskit"
ICON_FILE = SPEC_DIR / "ToolkitOGM.ico"
VERSION_FILE = SPEC_DIR / "ToolkitOGM.version.txt"
FLET_DESKTOP_DIR = Path(flet_desktop.__file__).resolve().parent
FLET_DESKTOP_TREE = Tree(str(FLET_DESKTOP_DIR / "app"), prefix="flet_desktop/app")

datas = [
    (str(TOOLKIT_DIR / "assets"), "assets"),
    (str(REPO_ROOT / "VERSION"), "."),
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
    [str(TOOLKIT_DIR / "main.py")],
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="ToolkitOGM",
)
