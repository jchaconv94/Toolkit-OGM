"""Firma la actualización de código de esta versión, para publicarla junto al instalador.

    UPDATE_SIGNING_KEY=<clave en hexadecimal> python sign_code_update.py <carpeta de salida>

Escribe `ToolkitOGM-app-<versión>.zip`, `.json` (manifiesto) y `.json.sig` (firma Ed25519) a partir
de build/app y build/runtime.json, que deja la compilación. Sin la clave avisa y no escribe nada:
esa versión se publica solo con el instalador completo.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "toolskit"))

from update_signature import public_key, sign  # noqa: E402


def manifest_bytes(version: str, runtime: str, app_zip: Path) -> bytes:
    data = {
        "format": 1,
        "version": version,
        "runtime": runtime,
        "app": {"sha256": hashlib.sha256(app_zip.read_bytes()).hexdigest(), "size": app_zip.stat().st_size},
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main(out_dir: Path, build_dir: Path = REPO_ROOT / "build") -> int:
    key = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
    if not key:
        print("::warning::Falta el secreto UPDATE_SIGNING_KEY: esta versión se publica solo con el instalador completo.")
        return 0
    try:
        secret = bytes.fromhex(key)
    except ValueError:
        secret = b""
    if len(secret) != 32:
        print("::error::UPDATE_SIGNING_KEY no es una clave de 64 caracteres hexadecimales.")
        return 1
    runtime = json.loads((build_dir / "runtime.json").read_text(encoding="utf-8"))
    if public_key(secret).hex() != runtime["public_key"]:
        print("::error::UPDATE_SIGNING_KEY no corresponde a la clave pública del programa (update_public_key.txt).")
        return 1
    version = (build_dir / "app" / "VERSION").read_text(encoding="utf-8").strip()
    app_zip = build_dir / "app" / "app.zip"
    manifest = manifest_bytes(version, runtime["runtime"], app_zip)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"ToolkitOGM-app-{version}"   # la versión lleva puntos: nada de with_suffix
    shutil.copyfile(app_zip, out_dir / f"{base}.zip")
    (out_dir / f"{base}.json").write_bytes(manifest)
    (out_dir / f"{base}.json.sig").write_bytes(sign(secret, manifest))
    print(f"Actualización de código {version} firmada: {app_zip.stat().st_size / 1e6:.2f} MB, runtime {runtime['runtime']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
