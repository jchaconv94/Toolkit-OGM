"""
app_config.py
=============
Persistencia de configuración de usuario entre sesiones.
Guarda/lee un JSON en %APPDATA%/ToolkitOGM/config.json
"""
import os
import json

_CONFIG_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ToolkitOGM")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

_DEFAULTS = {
    "medest_sismed_dir":       r"C:\SISMEDV2",
    "tmovim_sismed_dir":       r"C:\SISMEDV2",
    "tformdet_sismed_dir":     r"C:\SISMEDV2",
    "guias_sismed_dir":        r"C:\SISMEDV2",
    "stock_sismed_dir":        r"C:\SISMEDV2",
    "disponibilidad_sismed_dir": r"C:\SISMEDV2",
    "sync_sismed_dir":         r"C:\SISMEDV2",
}


def _load() -> dict:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except Exception:
        return dict(_DEFAULTS)


def _save(data: dict):
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get(key: str):
    return _load().get(key, _DEFAULTS.get(key))


def set(key: str, value):
    data = _load()
    data[key] = value
    _save(data)
