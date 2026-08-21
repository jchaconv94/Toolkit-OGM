import os
import re
import sys
from pathlib import Path


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?$")


def normalize_version(value: str) -> str:
    version = str(value or "").strip()
    if version.lower().startswith("v"):
        version = version[1:]
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Version no valida: {value!r}")
    return version


def version_tuple(value: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in normalize_version(value).split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _version_candidates() -> list[Path]:
    candidates: list[Path] = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir) / "VERSION")

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "VERSION")

    module_path = Path(__file__).resolve()
    candidates.extend([
        module_path.parent / "VERSION",
        module_path.parent.parent / "VERSION",
    ])
    return candidates


def get_current_version() -> str:
    override = os.environ.get("TOOLKIT_VERSION_OVERRIDE", "").strip()
    if override:
        try:
            return normalize_version(override)
        except ValueError:
            pass

    for candidate in _version_candidates():
        try:
            if candidate.is_file():
                return normalize_version(candidate.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError, ValueError):
            continue

    return "0.0.0"
