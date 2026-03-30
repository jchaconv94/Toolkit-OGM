# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]
TOOLKIT_DIR = REPO_ROOT / "toolskit"
ICON_FILE = SPEC_DIR / "ToolkitOGM.ico"
VERSION_FILE = SPEC_DIR / "ToolkitOGM.version.txt"

datas = [
    (str(TOOLKIT_DIR / "assets"), "assets"),
]
datas += collect_data_files("flet")

hiddenimports = [
    "fitz",
    "PyPDF2",
    "xlsxwriter",
    "pystray._win32",
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ToolkitOGM",
)