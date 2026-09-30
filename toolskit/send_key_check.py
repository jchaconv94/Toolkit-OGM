"""Verificación de la clave de envío antes de subir el stock a Google Sheets.

Antes de enviar, el Toolkit pregunta a ToolkitSISMED Web (función ``app_send_key_check`` en
Supabase) si esta PC puede enviar cada establecimiento:

- sin clave registrada en la web → se envía como siempre;
- con clave → solo la PC vinculada envía. Otra PC (sin clave, con otra clave o con la misma
  copiada) no envía ese establecimiento, su pestaña no se toca y la web muestra el aviso.

Así no hace falta tocar el script de Google de ninguna UNGET: la regla llega a todas las
PC con la actualización automática del Toolkit.

Si la web no responde, pasa solo lo que la web aprobó la última vez a esta misma PC y con
esta misma clave; lo que nunca tuvo clave se envía como siempre.

La clave pública de Supabase la agrega el flujo de publicación desde el secreto
``SUPABASE_ANON_KEY`` (archivo ``send_key_config.py``, que no se sube al repositorio). Sin
ella no se verifica nada y el envío sigue igual que antes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

import requests

from tools.app_config import get as cfg_get, set as cfg_set

SUPABASE_URL = "https://ujknopysvgqqvkmgrfhp.supabase.co"
CHECK_TIMEOUT_SECONDS = 15
_CACHE_KEY = "sync_send_key_last_check"


def supabase_public_key() -> str:
    try:
        from send_key_config import SUPABASE_ANON_KEY  # generado al publicar
    except Exception:
        SUPABASE_ANON_KEY = ""
    return str(SUPABASE_ANON_KEY or os.environ.get("TOOLKIT_SUPABASE_ANON_KEY", "")).strip()


def normalize_key(value: str) -> str:
    return re.sub(r"\s", "", str(value or "")).upper()


def keys_by_code(value: str) -> dict[str, str]:
    """La clave de cada código es la que empieza con «código-». Puede venir más de una."""
    mapping = {}
    for key in re.split(r"[\s,;]+", str(value or "")):
        key = normalize_key(key)
        code = key.split("-", 1)[0]
        if code:
            mapping[code] = key
    return mapping


def key_hash(value: str) -> str:
    return hashlib.sha256(normalize_key(value).encode("utf-8")).hexdigest()


class SendKeyChecker:
    def __init__(self, log=None):
        self.log = log or (lambda _msg: None)

    def _load_cache(self) -> dict:
        try:
            data = cfg_get(_CACHE_KEY)
            if isinstance(data, str):
                data = json.loads(data)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self, cache: dict):
        try:
            cfg_set(_CACHE_KEY, cache)
        except Exception:
            pass

    def _ask(self, public_key: str, code: str, key: str, device_id: str, device_name: str, rows: int):
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/app_send_key_check",
            headers={"apikey": public_key, "Content-Type": "application/json"},
            json={
                "p_code": code,
                "p_key": key,
                "p_device_id": device_id,
                "p_device_name": device_name,
                "p_rows": rows,
            },
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {(response.text or '')[:200]}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("respuesta inesperada")
        return data

    def check(self, rows_by_code: dict[str, int], keys: str, device_id: str, device_name: str) -> dict[str, tuple[bool, str]]:
        """Devuelve {código: (permitido, motivo)} para cada establecimiento del envío."""
        result = {code: (True, "") for code in rows_by_code}
        public_key = supabase_public_key()
        if not public_key or not rows_by_code:
            return result

        claves = keys_by_code(keys)
        cache = self._load_cache()
        changed = False

        for code, rows in rows_by_code.items():
            key = claves.get(code, "")
            try:
                data = self._ask(public_key, code, key, device_id, device_name, rows)
            except Exception as exc:
                previous = cache.get(code)
                if not previous:
                    self.log(f"  ⚠ No se pudo consultar la clave de envío de {code} ({exc}). Se envía como siempre.")
                    continue
                allowed = bool(previous.get("aprobado")) and bool(key) and previous.get("clave") == key_hash(key)
                result[code] = (allowed, "ACEPTADO_SIN_VERIFICAR" if allowed else "SIN_VERIFICAR")
                self.log(f"  ⚠ No se pudo consultar la clave de envío de {code} ({exc}).")
                continue

            if not data.get("protegido"):
                if cache.pop(code, None) is not None:
                    changed = True
                continue

            allowed = bool(data.get("permitido"))
            result[code] = (allowed, str(data.get("motivo") or ""))
            entry = {"aprobado": allowed, "clave": key_hash(key) if allowed else ""}
            if cache.get(code) != entry:
                cache[code] = entry
                changed = True

        if changed:
            self._save_cache(cache)
        return result
