"""Qué código del Toolkit se abre: el que trae el instalador o una actualización de código ya descargada.

El programa instalado (ToolkitOGM.exe, Python y las librerías: el «runtime») casi no cambia. El
código del Toolkit va aparte, en `_internal/app/app.zip`, y las actualizaciones de código solo
traen ese archivo (menos de 1 MB). El Toolkit las descarga en la carpeta del usuario
(`%LOCALAPPDATA%\\ToolkitOGM\\app\\<versión>`), sin tocar Archivos de programa ni pedir permiso a
Windows, y se aplican la próxima vez que se abre:

- solo si el manifiesto está firmado con la clave del Toolkit (`update_signature`) y el zip tiene
  la huella que dice el manifiesto;
- solo si es para este mismo runtime: si el runtime cambió, hace falta el instalador completo;
- si la versión nueva no termina de arrancar dos veces seguidas (o falla al importar), se marca
  como mala y se vuelve a la anterior.

Este módulo va dentro del exe (no en el zip): tiene que funcionar aunque el código descargado esté
roto. No escribe programas ni toca el arranque de Windows: solo elige un zip.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_FAILED_STARTS = 2
_VERSION = re.compile(r"^\d+(\.\d+){1,3}$")


@dataclass
class CodeUpdate:
    version: str
    folder: Path

    @property
    def zip_path(self) -> Path:
        return self.folder / "app.zip"


def version_key(value: str) -> tuple:
    return tuple(int(part) for part in value.split("."))


def bundle_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def updates_root(env=None) -> Path:
    env = os.environ if env is None else env
    base = env.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "ToolkitOGM" / "app"


def read_runtime(bundle: Path) -> dict:
    """`_internal/runtime.json`: identidad del runtime y clave pública de las actualizaciones."""
    try:
        return json.loads((bundle / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def bundled_version(bundle: Path) -> str:
    try:
        value = (bundle / "app" / "VERSION").read_text(encoding="utf-8").strip()
        return value if _VERSION.match(value) else "0.0.0"
    except OSError:
        return "0.0.0"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(manifest: bytes, signature: bytes, runtime: dict) -> dict | None:
    """El manifiesto, si está bien firmado y es para este runtime; si no, None."""
    from update_signature import verify

    try:
        public = bytes.fromhex(str(runtime.get("public_key") or ""))
    except ValueError:
        return None
    if not runtime.get("runtime") or not verify(public, manifest, signature):
        return None
    try:
        data = json.loads(manifest.decode("utf-8"))
    except ValueError:
        return None
    if data.get("format") != 1 or data.get("runtime") != runtime.get("runtime"):
        return None
    if not _VERSION.match(str(data.get("version") or "")):
        return None
    app = data.get("app") or {}
    if not re.fullmatch(r"[0-9a-f]{64}", str(app.get("sha256") or "")) or not isinstance(app.get("size"), int):
        return None
    return data


def verify_folder(folder: Path, runtime: dict) -> dict | None:
    """Comprueba una actualización descargada: firma, runtime, versión de la carpeta y huella del zip."""
    try:
        manifest = (folder / "manifest.json").read_bytes()
        signature = (folder / "manifest.sig").read_bytes()
    except OSError:
        return None
    data = check_manifest(manifest, signature, runtime)
    if not data or data["version"] != folder.name:
        return None
    zip_path = folder / "app.zip"
    try:
        if zip_path.stat().st_size != data["app"]["size"] or file_sha256(zip_path) != data["app"]["sha256"]:
            return None
    except OSError:
        return None
    return data


class State:
    """`state.json`: arranques en curso sin terminar y versiones marcadas como malas."""

    def __init__(self, root: Path):
        self.path = root / "state.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("trying", {})
        self.data.setdefault("bad", [])

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(temp, self.path)
        except OSError:
            pass

    def failed_starts(self, version: str) -> int:
        return int(self.data["trying"].get(version, 0))

    def mark_bad(self, version: str):
        if version not in self.data["bad"]:
            self.data["bad"].append(version)
        self.data["trying"].pop(version, None)


def choose(bundle: Path, root: Path, state: State | None = None) -> CodeUpdate | None:
    """La actualización de código más nueva que se puede usar, o None para el código del instalador."""
    runtime = read_runtime(bundle)
    base = bundled_version(bundle)
    state = state or State(root)
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and _VERSION.match(p.name)]
    except OSError:
        return None
    changed = False
    for folder in sorted(folders, key=lambda p: version_key(p.name), reverse=True):
        version = folder.name
        if version_key(version) <= version_key(base) or version in state.data["bad"]:
            continue
        if state.failed_starts(version) >= MAX_FAILED_STARTS:
            state.mark_bad(version)
            changed = True
            continue
        if verify_folder(folder, runtime):
            if changed:
                state.save()
            return CodeUpdate(version, folder)
    if changed:
        state.save()
    return None


def _forget_modules(prefix: str):
    for name, module in list(sys.modules.items()):
        if str(getattr(module, "__file__", "") or "").startswith(prefix):
            del sys.modules[name]


def prepare() -> CodeUpdate | None:
    """Pone en sys.path el código que se va a abrir. Fuera del programa instalado no hace nada."""
    bundle = bundle_dir()
    if bundle is None:
        return None
    # Un Toolkit abierto por el actualizador hereda el entorno del anterior: la versión la decide este arranque.
    os.environ.pop("TOOLKIT_VERSION_OVERRIDE", None)
    root = updates_root()
    state = State(root)
    update = None
    try:
        update = choose(bundle, root, state)
    except Exception:  # noqa: BLE001 - ante cualquier duda, el código del instalador
        update = None
    path = update.zip_path if update else bundle / "app" / "app.zip"
    sys.path.insert(0, str(path))
    if update:
        os.environ["TOOLKIT_VERSION_OVERRIDE"] = update.version
        state.data["trying"][update.version] = state.failed_starts(update.version) + 1
        state.save()
    return update


def import_main(update: CodeUpdate | None):
    """Importa `main`; si el código descargado ni siquiera se puede importar, vuelve al del instalador."""
    try:
        import main
        return main
    except Exception:
        if update is None:
            raise
        state = State(updates_root())
        state.mark_bad(update.version)
        state.save()
        _forget_modules(str(update.zip_path))
        sys.path.remove(str(update.zip_path))
        os.environ.pop("TOOLKIT_VERSION_OVERRIDE", None)
        sys.path.insert(0, str(bundle_dir() / "app" / "app.zip"))
        import main
        return main


def run_main(main, update: CodeUpdate | None):
    """Abre el Toolkit. Si el código descargado se cae al arrancar, se marca como malo y el Toolkit se
    vuelve a abrir solo con el anterior, sin mostrar el error a la persona."""
    try:
        main.run()
    except Exception:
        if update is None:
            raise
        state = State(updates_root())
        state.mark_bad(update.version)
        state.save()
        import subprocess

        subprocess.Popen([sys.executable, *sys.argv[1:]], close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def mark_healthy():
    """El código que se abrió arrancó bien: se olvidan sus intentos fallidos."""
    version = os.environ.get("TOOLKIT_VERSION_OVERRIDE", "").strip()
    if not version or bundle_dir() is None:
        return
    state = State(updates_root())
    if state.data["trying"].pop(version, None) is not None:
        state.data["healthy"] = version
        state.save()
