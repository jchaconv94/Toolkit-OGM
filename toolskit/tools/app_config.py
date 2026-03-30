"""
app_config.py
=============
Persistencia de configuración de usuario entre sesiones.
Guarda/lee un JSON en %APPDATA%/ToolkitOGM/config.json
"""
import os
import json
import threading
from datetime import datetime

_CONFIG_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ToolkitOGM")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
_CONFIG_BACKUP_FILE = os.path.join(_CONFIG_DIR, "config.bak")
_CONFIG_LOG_FILE = os.path.join(_CONFIG_DIR, "config.log")
_CONFIG_LOCK = threading.RLock()

_DEFAULTS = {
    "medest_sismed_dir":       r"C:\SISMEDV2",
    "tmovim_sismed_dir":       r"C:\SISMEDV2",
    "tformdet_sismed_dir":     r"C:\SISMEDV2",
    "guias_sismed_dir":        r"C:\SISMEDV2",
    "stock_sismed_dir":        r"C:\SISMEDV2",
    "disponibilidad_sismed_dir": r"C:\SISMEDV2",
    "sync_sismed_dir":         r"C:\SISMEDV2",
    "sync_interval_minutes":   5,
    "sync_modo_consolidado":   False,
    "sync_apps_script_url":    "",
    "sync_auto_start":         False,
}


def _log_config_error(action: str, exc: Exception):
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {action}: {type(exc).__name__}: {exc}\n")
    except Exception:
        pass


def _load_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("El archivo de configuración no contiene un objeto JSON válido.")
    return data


def _write_json_atomic(path: str, data: dict):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _load() -> dict:
    try:
        with _CONFIG_LOCK:
            if not os.path.exists(_CONFIG_FILE):
                return dict(_DEFAULTS)

            data = _load_json_file(_CONFIG_FILE)
            return {**_DEFAULTS, **data}
    except Exception as exc:
        _log_config_error("Error cargando configuración principal", exc)

        try:
            with _CONFIG_LOCK:
                if not os.path.exists(_CONFIG_BACKUP_FILE):
                    return dict(_DEFAULTS)

                backup_data = _load_json_file(_CONFIG_BACKUP_FILE)
                _write_json_atomic(_CONFIG_FILE, backup_data)
                return {**_DEFAULTS, **backup_data}
        except Exception as backup_exc:
            _log_config_error("Error recuperando configuración desde respaldo", backup_exc)
            return dict(_DEFAULTS)


def _save(data: dict):
    try:
        with _CONFIG_LOCK:
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            _write_json_atomic(_CONFIG_FILE, data)
            _write_json_atomic(_CONFIG_BACKUP_FILE, data)
    except Exception as exc:
        _log_config_error("Error guardando configuración", exc)


def get(key: str):
    return _load().get(key, _DEFAULTS.get(key))


def set(key: str, value):
    data = _load()
    data[key] = value
    _save(data)


def get_config_log_path() -> str:
    return _CONFIG_LOG_FILE


def get_config_file_path() -> str:
    return _CONFIG_FILE


def get_config_backup_path() -> str:
    return _CONFIG_BACKUP_FILE
