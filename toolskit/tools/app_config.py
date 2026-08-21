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
_STARTUP_LOG_FILE = os.path.join(_CONFIG_DIR, "startup.log")
_SYNC_LOG_FILE = os.path.join(_CONFIG_DIR, "sync.log")
_UPDATE_LOG_FILE = os.path.join(_CONFIG_DIR, "update.log")
_CONFIG_LOCK = threading.RLock()

_DEFAULTS = {
    "medest_sismed_dir":       r"C:\SISMEDV2",
    "tmovim_sismed_dir":       r"C:\SISMEDV2",
    "tformdet_sismed_dir":     r"C:\SISMEDV2",
    "tformdet_append_source_file": "",
    "tformdet_append_sismed_dir": r"C:\SISMEDV2",
    "guias_sismed_dir":        r"C:\SISMEDV2",
    "stock_sismed_dir":        r"C:\SISMEDV2",
    "disponibilidad_sismed_dir": r"C:\SISMEDV2",
    "disponibilidad_filter_mode": "excluir",
    "disponibilidad_filter_codes": "",
    "disponibilidad_filter_remember": False,
    "sync_sismed_dir":         r"C:\SISMEDV2",
    "sync_interval_minutes":   5,
    "sync_modo_consolidado":   False,
    "sync_omit_zero_stock":     True,
    "sync_apps_script_url":    "",
    "sync_auto_start":         False,
    "sync2_sismed_dir":        r"C:\SISMEDV2",
    "sync2_interval_minutes":  5,
    "sync2_modo_consolidado":  False,
    "sync2_omit_zero_stock":    True,
    "sync2_endpoint_url":      "",
    "sync2_installation_token": "",
    "sync2_expected_facility_code": "",
    "sync2_auto_start":        False,
    "sync_access_password_hash": "",
    "update_auto_check":         True,
    "update_auto_download":      True,
    "update_last_check_at":      "",
    "update_pending_version":    "",
    "runtime_last_boot_status": "never-started",
    "runtime_last_boot_detail": "",
    "runtime_last_boot_at":     "",
    "runtime_last_sync_autostart_status": "not-attempted",
    "runtime_last_sync_autostart_message": "",
    "runtime_last_sync_autostart_at":      "",
    "runtime_sync_run_state":              "idle",
    "runtime_sync_run_state_detail":       "",
    "runtime_sync_run_state_at":           "",
    "runtime_last_sync_cycle_status":      "never-run",
    "runtime_last_sync_cycle_message":     "",
    "runtime_last_sync_cycle_at":          "",
    "runtime_last_sync_cycle_records":     0,
    "runtime_last_sync_error_kind":        "",
    "runtime_last_sync_http_status":       "",
    "runtime_last_sync_success_at":        "",
    "runtime_last_sync_success_records":   0,
    "runtime_last_sync_dbf_source":        "",
    "runtime_last_sync_dbf_problem_records": 0,
    "runtime_last_sync_dbf_problem_ratio":   0.0,
    "runtime_last_sync_dbf_corrupted_records": 0,
    "runtime_last_sync_dbf_omitted_records":   0,
    "runtime_last_sync_dbf_field_fallbacks":   0,
    "runtime_last_sync_dbf_summary":          "",
}

_RUNTIME_STATUS_MAP = {
    "boot": (
        "runtime_last_boot_status",
        "runtime_last_boot_detail",
        "runtime_last_boot_at",
    ),
    "sync_autostart": (
        "runtime_last_sync_autostart_status",
        "runtime_last_sync_autostart_message",
        "runtime_last_sync_autostart_at",
    ),
    "sync_cycle": (
        "runtime_last_sync_cycle_status",
        "runtime_last_sync_cycle_message",
        "runtime_last_sync_cycle_at",
    ),
}

_RUNTIME_LOG_PATHS = {
    "startup": _STARTUP_LOG_FILE,
    "sync": _SYNC_LOG_FILE,
    "update": _UPDATE_LOG_FILE,
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_config_error(action: str, exc: Exception):
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{_timestamp()}] {action}: {type(exc).__name__}: {exc}\n")
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


def set_many(values: dict):
    data = _load()
    data.update(values)
    _save(data)


def update_runtime_status(scope: str, status: str, detail: str | None = None):
    if scope not in _RUNTIME_STATUS_MAP:
        raise ValueError(f"Ambito de estado operativo no soportado: {scope}")

    status_key, detail_key, timestamp_key = _RUNTIME_STATUS_MAP[scope]
    set_many({
        status_key: status,
        detail_key: detail or "",
        timestamp_key: _timestamp(),
    })


def append_runtime_log(channel: str, message: str):
    log_path = _RUNTIME_LOG_PATHS.get(channel, _CONFIG_LOG_FILE)
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{_timestamp()}] {message}\n")
    except Exception as exc:
        _log_config_error(f"Error escribiendo log operativo '{channel}'", exc)


def get_config_log_path() -> str:
    return _CONFIG_LOG_FILE


def get_config_file_path() -> str:
    return _CONFIG_FILE


def get_config_backup_path() -> str:
    return _CONFIG_BACKUP_FILE


def get_startup_log_path() -> str:
    return _STARTUP_LOG_FILE


def get_sync_log_path() -> str:
    return _SYNC_LOG_FILE


def get_update_log_path() -> str:
    return _UPDATE_LOG_FILE
