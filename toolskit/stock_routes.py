"""Caminos de envío del stock y limpieza de datos sensibles en el registro.

Algunas redes de establecimientos (PRONATEL) bloquean `script.google.com`: desvían su DNS a
una IP interna (10.254.30.102 en CONSUELO y PUERTORICO) y cortan la conexión por nombre. Para
esas PC hay dos caminos de respaldo que reenvían el mismo envío al mismo Apps Script, de
servidor a servidor (código en ToolkitSISMED, `supabase/functions/stock-relay/index.ts`):

- A: el servicio de Cloudflare `sismed-conexion` (el mismo de Backups SISMED), ruta /stock.
- B: la función `stock-relay` de Supabase.

Google Sheets sigue siendo la fuente del stock: los respaldos no guardan nada. Solo aceptan
una PC con clave de envío vigente para ella.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlencode

from backup_connection import SERVICE_URL
from backup_upload import service_http_base
from send_key_check import SUPABASE_URL

ROUTE_DIRECT = "google"
ROUTE_CLOUDFLARE = "cloudflare"
ROUTE_SUPABASE = "supabase"

ROUTE_LABELS = {
    ROUTE_DIRECT: "Google directo",
    ROUTE_CLOUDFLARE: "respaldo Cloudflare",
    ROUTE_SUPABASE: "respaldo Supabase",
}

CLOUDFLARE_RELAY_URL = f"{service_http_base(SERVICE_URL)}/stock"
SUPABASE_RELAY_URL = f"{SUPABASE_URL}/functions/v1/stock-relay"

# Tras confirmar que la red bloquea Google y que un respaldo funcionó, se va directo al
# respaldo durante este tiempo (sin perder 10 s por intento en Google) y luego se vuelve a probar.
DIRECT_BLOCKED_SECONDS = 6 * 60 * 60
# Supabase cobra el tráfico de salida por encima de lo gratuito: por ese camino se envía
# como mucho una vez cada 30 minutos, aunque el intervalo de Sync SISMED sea menor.
SUPABASE_MIN_INTERVAL_SECONDS = 30 * 60


# --- Limpieza del registro -------------------------------------------------------------------

_SECRET_PARAM = re.compile(r"([?&](?:clave|equipo_id|user_content_key)=)[^&\s'\"<>)]+", re.IGNORECASE)
_SCRIPT_ID = re.compile(r"(/macros/(?:[^\s/]+/)*s/)[A-Za-z0-9_-]{10,}", re.IGNORECASE)
# 030S05-K7QM-4XPA-93RD → 030S05-****: deja ver de qué establecimiento es, nunca la clave.
_SEND_KEY = re.compile(r"\b([0-9A-Z]{5,6})-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}\b", re.IGNORECASE)


def redact_sensitive(text) -> str:
    """Quita del texto la clave de envío, el identificador de la PC y la dirección del script."""
    value = str(text if text is not None else "")
    value = _SECRET_PARAM.sub(r"\1***", value)
    value = _SCRIPT_ID.sub(r"\1***", value)
    value = _SEND_KEY.sub(r"\1-****", value)
    return value


# --- DNS desviado ----------------------------------------------------------------------------

def internal_addresses(host: str) -> tuple[bool, list[str], str]:
    """
    Resuelve `host` y dice si alguna respuesta es una dirección interna (10.x, 192.168.x...).

    Devuelve (resolvió, direcciones internas, detalle del error). Google nunca responde con una
    dirección interna: si aparece una, la red desvía el nombre a propósito.
    """
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, [], f"No se pudo resolver {host}: {exc}"
    internal = []
    for info in infos:
        address = str(info[4][0])
        try:
            if not ipaddress.ip_address(address.split("%", 1)[0]).is_global:
                internal.append(address)
        except ValueError:
            continue
    return True, sorted(set(internal)), ""


# --- Petición a un respaldo ------------------------------------------------------------------

def relay_headers(destination: str, params: dict, public_key: str = "") -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Toolkit-Destino": destination,
        "X-Toolkit-Params": urlencode(params or {}),
    }
    if public_key:
        headers["apikey"] = public_key
    return headers


def relay_failure(response) -> tuple[str, str, bool] | None:
    """
    None si la respuesta viene de Google (cabecera `X-Relay: ok`) y hay que leerla como siempre.
    Si no, (código, mensaje, final): `final` = el otro respaldo daría lo mismo.

    Una respuesta sin ninguna de las dos marcas (un portal cautivo, un proxy) no se cree.
    """
    headers = getattr(response, "headers", None) or {}
    if str(headers.get("X-Relay", "")).lower() == "ok":
        return None
    code = str(headers.get("X-Relay-Error", "") or "")
    message = ""
    final = False
    try:
        data = response.json()
        if isinstance(data, dict):
            code = code or str(data.get("error") or "")
            message = str(data.get("message") or "")
            final = bool(data.get("final"))
    except Exception:
        pass
    if not code:
        status = getattr(response, "status_code", "")
        return "RESPUESTA_DESCONOCIDA", f"respuesta inesperada (HTTP {status})", False
    return code, message or code, final
