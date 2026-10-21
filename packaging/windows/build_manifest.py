"""Huella de cada archivo de dist/ToolkitOGM, para saber qué cambia de una versión a otra.

    python build_manifest.py <carpeta> <salida.json>
    python build_manifest.py --compare <antes.json> <despues.json>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def manifest(root: Path) -> dict:
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[path.relative_to(root).as_posix()] = {"sha256": digest, "size": path.stat().st_size}
    return {"files": files}


def mb(size: int) -> str:
    return f"{size / 1e6:.2f} MB"


def compare(before: dict, after: dict) -> str:
    a, b = before["files"], after["files"]
    changed = [k for k in b if k in a and a[k]["sha256"] != b[k]["sha256"]]
    added = [k for k in b if k not in a]
    removed = [k for k in a if k not in b]
    total = sum(f["size"] for f in b.values())
    moved = sum(b[k]["size"] for k in changed + added)
    lines = [f"Archivos: {len(b)} · total {mb(total)}",
             f"Cambiaron {len(changed)}, nuevos {len(added)}, quitados {len(removed)} · a descargar {mb(moved)}"]
    for k in sorted(changed + added, key=lambda k: -b[k]["size"])[:40]:
        lines.append(f"  {'nuevo ' if k in added else ''}{k}  {mb(b[k]['size'])}")
    for k in removed[:20]:
        lines.append(f"  quitado {k}")
    return "\n".join(lines)


def breakdown(data: dict) -> str:
    groups: dict[str, int] = {}
    for name, info in data["files"].items():
        parts = name.split("/")
        key = "/".join(parts[:2]) if parts[0] == "_internal" and len(parts) > 2 else name if len(parts) <= 2 else parts[0]
        groups[key] = groups.get(key, 0) + info["size"]
    top = sorted(groups.items(), key=lambda kv: -kv[1])[:25]
    return "\n".join(f"  {mb(size):>10}  {name}" for name, size in top)


if __name__ == "__main__":
    if sys.argv[1] == "--compare":
        before, after = (json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[2:4])
        print(compare(before, after))
    else:
        data = manifest(Path(sys.argv[1]))
        Path(sys.argv[2]).write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(breakdown(data))
