import requests
import json
import re
import time
import os
import sys
import threading
import tempfile
import traceback
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import activity
from app_version import get_current_version
from dbf_utils import DbfReadMetrics, iter_dbf_records, open_dbf, snapshot_dbf
from tools.app_config import set_many, update_runtime_status
from sync_device_id import get_device_id
from send_key_check import SendKeyChecker, supabase_public_key
from sismed_version import read_sismed_version
from backup_connection import BackupConnection
from stock_routes import (
    CLOUDFLARE_RELAY_URL,
    DIRECT_BLOCKED_SECONDS,
    ROUTE_CLOUDFLARE,
    ROUTE_DIRECT,
    ROUTE_LABELS,
    ROUTE_SUPABASE,
    SUPABASE_MIN_INTERVAL_SECONDS,
    SUPABASE_RELAY_URL,
    internal_addresses,
    redact_sensitive,
    relay_failure,
    relay_headers,
)

SYNC_DBF_ABORT_MIN_BAD_RECORDS = 15
SYNC_DBF_ABORT_BAD_RATIO = 0.05
SYNC_DNS_RETRY_ATTEMPTS = 6
SYNC_DNS_RETRY_SECONDS = 20


def _read_toolkit_version() -> str:
    return get_current_version()


@dataclass
class _SendAttempt:
    """Resultado de un intento por un camino (Google directo o un respaldo)."""
    route: str
    response: requests.Response | None = None
    error_kind: str = ""
    user_message: str = ""
    technical_detail: str = ""
    # Probar el siguiente camino: el envío no llegó a Google por este.
    fallback: bool = False
    # Vale la pena reintentar en 20 s (falla de red pasajera).
    retry: bool = False

class SismedSyncManager:
    def __init__(self, log_callback=None, on_stop_callback=None):
        self.is_running = False
        self.log_callback = log_callback
        self.on_stop_callback = on_stop_callback
        self.thread = None
        # Conexión inmediata con la web (backups SISMED). Sync SISMED 2.0 no la usa.
        self.backup_connection_supported = True
        self._backup_connection = None
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self.run_state = "idle"
        self.last_cycle_status = "never-run"
        self.last_cycle_message = ""
        self.last_cycle_error_kind = ""
        self.last_http_status = ""
        
        # Configuraciones por defecto
        self.apps_script_url = "https://script.google.com/macros/s/AKfycbyAtEQj5huUcEsXHLiMIe2-wzwFtlvYckIAabQQr2Z_g6Aa3o_93DaXaLgmfeYZm5pqCw/exec"
        self.base_dir = r"C:\SISMEDV2"
        self.modo_consolidado = False
        self.omitir_stock_cero = True
        # Clave de envío generada en ToolkitSISMED Web → «Claves de envío», una por
        # establecimiento (030S05-K7QM-4XPA-93RD). Con clave, solo la PC vinculada puede
        # enviar ese establecimiento. Vacía = se envía como siempre.
        self.clave_envio = ""
        self.intervalo_minutos = 5
        self.destination_name = "Google"
        self.destination_label = "Google Sheets"
        self._last_reported_almcods: list[str] = []
        self._last_reported_facility_codes: list[str] = []
        self._last_source_record_count = 0
        self._last_zero_stock_omitted = 0
        # Caminos de respaldo (stock_routes.py). Hasta cuándo se salta Google directo porque la
        # red lo bloquea, cuándo se envió por Supabase la última vez y por dónde salió el último envío.
        self._direct_blocked_until = 0.0
        self._supabase_last_sent = 0.0
        self._last_block_note = ""
        self.last_sync_route = ""

    def _set_run_state(self, state: str, detail: str = ""):
        with self._state_lock:
            self.run_state = state
            self.is_running = state in {"starting", "running", "stopping"}

        set_many({
            "runtime_sync_run_state": state,
            "runtime_sync_run_state_detail": detail,
            "runtime_sync_run_state_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _record_cycle_result(
        self,
        status: str,
        message: str,
        *,
        error_kind: str = "",
        http_status: int | str | None = None,
        records: int = 0,
        success: bool = False,
    ):
        message = redact_sensitive(message)
        self.last_cycle_status = status
        self.last_cycle_message = message
        self.last_cycle_error_kind = error_kind or ""
        self.last_http_status = "" if http_status in (None, "") else str(http_status)

        update_runtime_status("sync_cycle", status, message)

        updates = {
            "runtime_last_sync_cycle_records": max(0, int(records or 0)),
            "runtime_last_sync_error_kind": self.last_cycle_error_kind,
            "runtime_last_sync_http_status": self.last_http_status,
        }

        updates["runtime_last_sync_route"] = self.last_sync_route
        if success:
            updates["runtime_last_sync_success_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            updates["runtime_last_sync_success_records"] = max(0, int(records or 0))

        set_many(updates)

    def _host_timestamp(self) -> str:
        return time.strftime('%d/%m/%Y %H:%M:%S')

    @staticmethod
    def _normalize_code(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z]", "", value or "").upper()

    @classmethod
    def _facility_from_almcod(cls, almcod: str) -> str:
        code = cls._normalize_code(almcod)
        if len(code) >= 8 and code[5:6] == "F":
            return code[:5]
        if len(code) >= 6 and any(ch.isalpha() for ch in code[:6]):
            return code[:6]
        return code[:5] if len(code) >= 5 else code

    @classmethod
    def _consolidated_almcod(cls, facility_code: str) -> str:
        code = cls._normalize_code(facility_code)
        if len(code) == 6 and any(ch.isalpha() for ch in code):
            return f"{code}01"
        return f"{code}F01" if code else ""

    def _stamp_payload_host_time(self, payload_data: list[dict]):
        fecha_equipo = self._host_timestamp()
        for item in payload_data:
            item["fecha_equipo"] = fecha_equipo
            # Compatibilidad con el Apps Script anterior.
            item["actualizado"] = fecha_equipo

    def _integration_url(self) -> str:
        return (self.apps_script_url or "").strip()

    def _request_headers(self) -> dict:
        return {'Content-Type': 'application/json'}

    @staticmethod
    def _equipo_name() -> str:
        """Nombre de la PC, para que la web muestre qué equipo envió."""
        try:
            name = socket.gethostname() or os.environ.get("COMPUTERNAME", "")
        except Exception:
            name = os.environ.get("COMPUTERNAME", "")
        return re.sub(r"[^0-9A-Za-z._-]", "", str(name or ""))[:64]

    def _clave_envio_normalizada(self) -> str:
        claves = re.split(r"[\s,;]+", str(self.clave_envio or "").strip().upper())
        return ",".join(clave for clave in claves if clave)

    def _clave_envio_resumen(self) -> str:
        """Para el log: los códigos de la clave, nunca la clave completa."""
        codigos = [clave.split("-", 1)[0] for clave in self._clave_envio_normalizada().split(",") if clave]
        return ", ".join(codigos)

    def _request_params(self) -> dict:
        params = {}
        equipo = self._equipo_name()
        if equipo:
            params["equipo"] = equipo
        try:
            params["equipo_id"] = get_device_id()
        except Exception:
            pass
        clave = self._clave_envio_normalizada()
        if clave:
            params["clave"] = clave
        if self.omitir_stock_cero:
            params["omit_zero_stock"] = "1"
        if self._last_reported_almcods:
            params["reported_almcods"] = ",".join(self._last_reported_almcods)
        if self._last_reported_facility_codes:
            params["reported_facility_codes"] = ",".join(self._last_reported_facility_codes)
        return params

    def _request_body(self, payload_data: list[dict]) -> str:
        return json.dumps(payload_data)

    def _is_success_response(self, response: requests.Response) -> bool:
        return response.status_code == 200 and response.text.startswith("OK")

    def _success_message(self, response: requests.Response, record_count: int) -> str:
        return f"Stock detallado sincronizado ({response.text.strip()})."

    def _acknowledged_record_count(self, response: requests.Response) -> int | None:
        text = (response.text or "").strip()
        match = re.search(r"\bOK\s*:\s*(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    _BLOCK_REASONS = {
        "SIN_CLAVE": "esta PC no tiene configurada la clave de envío",
        "CLAVE_INCORRECTA": "la clave de envío no es la vigente",
        "OTRO_EQUIPO": "el establecimiento está vinculado a otra PC",
        "SIN_VERIFICAR": "no se pudo consultar la clave en la web y esta PC no es la última aprobada",
    }

    @staticmethod
    def _send_key_blocks(response: requests.Response) -> list[tuple[str, str]]:
        """Establecimientos que el script rechazó por la clave de envío.

        El script responde, además del «OK: n», ``BLOQUEADO: 030S05=OTRO_EQUIPO,06519=SIN_CLAVE``.
        """
        text = (getattr(response, "text", "") or "").strip()
        match = re.search(r"BLOQUEADO\s*:\s*([^\n|;]+)", text, flags=re.IGNORECASE)
        if not match:
            return []
        bloqueos = []
        for parte in match.group(1).split(","):
            codigo, _, motivo = parte.strip().partition("=")
            if codigo.strip():
                bloqueos.append((codigo.strip().upper(), motivo.strip().upper()))
        return bloqueos

    def _send_key_block_message(self, bloqueos: list[tuple[str, str]]) -> str:
        detalle = "; ".join(
            f"{codigo}: {self._BLOCK_REASONS.get(motivo, motivo.lower() or 'bloqueado')}"
            for codigo, motivo in bloqueos
        )
        return (
            f"Envío bloqueado por la clave de envío ({detalle}). No se envió ese stock y su pestaña no se modificó. "
            "Pida al informático SISMED que lo revise en ToolkitSISMED Web → «Claves de envío»."
        )

    def _validate_payload_before_send(self, payload_data: list[dict]) -> tuple[bool, str]:
        return True, ""

    def _apply_send_key_check(self, payload_data: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
        """Consulta la clave de envío en la web y quita lo que esta PC no puede enviar.

        Devuelve el envío que sí puede salir y los establecimientos bloqueados con su motivo.
        Los bloqueados tampoco se reportan para vaciar: su pestaña queda intacta.
        """
        rows_by_code: dict[str, int] = {}
        for item in payload_data:
            code = self._facility_from_almcod(str(item.get("almcod", "")))
            if code:
                rows_by_code[code] = rows_by_code.get(code, 0) + 1
        for almcod in self._last_reported_almcods:
            code = self._facility_from_almcod(almcod)
            if code:
                rows_by_code.setdefault(code, 0)
        if not rows_by_code:
            return payload_data, []

        result = SendKeyChecker(log=self.log).check(
            rows_by_code,
            self._clave_envio_normalizada(),
            get_device_id(),
            self._equipo_name(),
            sismed=read_sismed_version(self.base_dir),
        )
        blocked = sorted(code for code, (allowed, _motivo) in result.items() if not allowed)
        if not blocked:
            return payload_data, []

        blocked_set = set(blocked)
        payload_data = [
            item for item in payload_data
            if self._facility_from_almcod(str(item.get("almcod", ""))) not in blocked_set
        ]
        self._last_reported_almcods = [
            almcod for almcod in self._last_reported_almcods
            if self._facility_from_almcod(almcod) not in blocked_set
        ]
        self._last_reported_facility_codes = [
            code for code in self._last_reported_facility_codes if code not in blocked_set
        ]
        return payload_data, [(code, result[code][1]) for code in blocked]

    def _set_reported_scope(self, payload_data: list[dict]):
        almcods = sorted({
            self._normalize_code(str(item.get("almcod", "")))
            for item in payload_data
            if str(item.get("almcod", "")).strip()
        })
        self._last_reported_almcods = almcods
        self._last_reported_facility_codes = sorted({
            self._facility_from_almcod(almcod)
            for almcod in almcods
            if almcod
        })
        self._last_source_record_count = len(payload_data)
        self._last_zero_stock_omitted = 0

    @staticmethod
    def _is_zero_stock_item(item: dict) -> bool:
        try:
            return float(item.get("saldo") or 0) == 0.0
        except (TypeError, ValueError):
            return False

    def _filter_zero_stock_records(self, payload_data: list[dict], stage: str) -> list[dict]:
        if not self.omitir_stock_cero:
            return payload_data

        filtered = [item for item in payload_data if not self._is_zero_stock_item(item)]
        omitted = len(payload_data) - len(filtered)
        if omitted:
            self._last_zero_stock_omitted += omitted
            self.log(f"  ℹ Lotes con stock 0 omitidos ({stage}): {omitted}")
        return filtered

    def _can_send_empty_payload_for_clear(self) -> bool:
        return bool(self.omitir_stock_cero and self._last_reported_almcods)

    def _destination_user_message(self, error_kind: str) -> str:
        if error_kind == "dns-error":
            return f"No se pudo resolver el servidor de {self.destination_name}. Revisa DNS, proxy o conectividad."
        if error_kind == "tls-error":
            return f"Error TLS/SSL al enviar datos a {self.destination_name}. Revisa certificados del sistema, fecha/hora del equipo o inspeccion HTTPS."
        if error_kind == "proxy-error":
            return f"Error de proxy al enviar datos a {self.destination_name}. Revisa la configuracion de red del equipo."
        if error_kind == "timeout":
            return f"La conexion a {self.destination_name} excedio el tiempo de espera. Revisa conectividad o saturacion de red."
        if error_kind == "connection-error":
            return f"No se pudo establecer conexion con {self.destination_name}. Revisa red, firewall o acceso a Internet."
        return f"Error de red al enviar datos a {self.destination_name}."

    def _sync_target_host(self) -> str:
        parsed = urlparse(self._integration_url())
        return parsed.hostname or ""

    def _wait_between_quick_retries(self) -> bool:
        self.log(f"  Reintentando en {SYNC_DNS_RETRY_SECONDS} segundos sin esperar el intervalo normal...")
        return self._stop_event.wait(SYNC_DNS_RETRY_SECONDS)

    def _note_block(self, note: str):
        """Explica una vez por qué no se llega a Google, no en cada ciclo."""
        if note and note != self._last_block_note:
            self.log(note)
        self._last_block_note = note

    def _post_payload_with_retries(self, payload_data: list[dict]):
        """
        Envía por el primer camino que llegue a Google (directo, Cloudflare, Supabase) y
        reintenta todo cada 20 s mientras la falla sea de red. Devuelve
        (respuesta, tipo de error, mensaje, detalle técnico); el camino queda en `last_sync_route`.
        """
        body = self._request_body(payload_data)
        params = self._request_params()
        self.last_sync_route = ""
        result = _SendAttempt(route="")

        for attempt in range(1, SYNC_DNS_RETRY_ATTEMPTS + 1):
            result = self._post_by_routes(body, params)
            if result.response is not None:
                self.last_sync_route = result.route
                return result.response, "", "", ""
            if result.retry and attempt < SYNC_DNS_RETRY_ATTEMPTS:
                self.log(
                    f"  ⚠ {result.user_message} Intento {attempt}/{SYNC_DNS_RETRY_ATTEMPTS}. "
                    f"Detalle: {result.technical_detail}"
                )
                if self._wait_between_quick_retries():
                    return None, "stopped", "Sincronizacion detenida por el usuario.", ""
                continue
            break

        return None, result.error_kind or "request-error", result.user_message, result.technical_detail

    def _post_by_routes(self, body: str, params: dict) -> _SendAttempt:
        failures: list[_SendAttempt] = []
        direct_skipped = time.monotonic() < self._direct_blocked_until

        if not direct_skipped:
            direct = self._post_direct(body, params)
            if direct.response is not None or not direct.fallback:
                return direct
            failures.append(direct)

        # Google respondió por un respaldo, pero con un error de su lado (429, 5xx): puede ser
        # solo con ese servidor, así que se prueba el otro y, si tampoco, se usa esa respuesta.
        google_error: _SendAttempt | None = None
        for route in (ROUTE_CLOUDFLARE, ROUTE_SUPABASE):
            relay = self._post_relay(route, body, params)
            if relay.response is not None:
                if failures:
                    # Google directo falló y un respaldo sí llegó: unas horas se va directo al respaldo.
                    self._direct_blocked_until = time.monotonic() + DIRECT_BLOCKED_SECONDS
                if relay.response.status_code == 429 or relay.response.status_code >= 500:
                    google_error = google_error or relay
                    continue
                return relay
            failures.append(relay)
            if not relay.fallback:
                break
        if google_error is not None:
            return google_error

        dns_only = bool(failures) and failures[0].route == ROUTE_DIRECT and failures[0].error_kind == "network-block"
        if direct_skipped or dns_only:
            # Los respaldos fallaron y a Google directo no se le mandó nada: se prueba ahora, por si
            # la red ya lo permite, el respaldo rechaza a esta PC o la IP interna es un proxy que sí llega.
            self._direct_blocked_until = 0.0
            direct = self._post_direct(body, params, ignore_internal_dns=True)
            if direct.response is not None:
                return direct
            if dns_only:
                # La red ya lo desvía a propósito: reintentarlo en 20 s no cambia nada.
                direct.retry = False
                failures[0] = direct
            else:
                failures.insert(0, direct)

        return self._combine_failures(failures)

    def _combine_failures(self, failures: list[_SendAttempt]) -> _SendAttempt:
        if len(failures) == 1:
            return failures[0]
        last = failures[-1]
        detail = " | ".join(
            f"{ROUTE_LABELS.get(f.route, f.route)}: {f.user_message}"
            + (f" ({f.technical_detail})" if f.technical_detail else "")
            for f in failures
        )
        return _SendAttempt(
            route="",
            error_kind=last.error_kind or "request-error",
            user_message="No se pudo enviar el stock por ningún camino (Google directo ni respaldos).",
            technical_detail=detail,
            fallback=False,
            # Un respaldo que rechazó la clave la va a rechazar también en 20 s.
            retry=any(f.retry for f in failures) and not any(f.error_kind == "relay-rejected" for f in failures),
        )

    def _post_direct(self, body: str, params: dict, ignore_internal_dns: bool = False) -> _SendAttempt:
        host = self._sync_target_host()
        if not host:
            return _SendAttempt(
                route=ROUTE_DIRECT,
                error_kind="dns-error",
                user_message="La URL de integracion no contiene un servidor valido.",
            )

        resolved, internal, dns_detail = internal_addresses(host)
        if not resolved:
            # Sin DNS para Google: los respaldos son otros servidores y pueden resolver.
            return _SendAttempt(
                route=ROUTE_DIRECT,
                error_kind="dns-error",
                user_message=self._destination_user_message("dns-error"),
                technical_detail=dns_detail,
                fallback=True,
                retry=True,
            )
        if internal and not ignore_internal_dns:
            self._note_block(
                f"  ⚠ La red de este establecimiento desvía {host} a una dirección interna ({', '.join(internal)}): "
                "bloquea Google Apps Script. Se envía por el camino de respaldo."
            )
            return _SendAttempt(
                route=ROUTE_DIRECT,
                error_kind="network-block",
                user_message=f"La red desvía {host} a una dirección interna ({', '.join(internal)}).",
                fallback=True,
            )

        try:
            response = requests.post(
                self._integration_url(),
                data=body,
                headers=self._request_headers(),
                params=params or None,
                timeout=(10, 300)
            )
            self._last_block_note = ""
            return _SendAttempt(route=ROUTE_DIRECT, response=response)
        except requests.exceptions.RequestException as req_err:
            error_kind, user_message = self._classify_request_exception(req_err)
            # Solo si no se llegó a Google (sin conexión, DNS, TLS cortado, proxy) se prueba el
            # respaldo. Si Google tardó en responder (ReadTimeout) puede estar escribiendo la hoja.
            connection_failed = isinstance(req_err, requests.exceptions.ConnectionError)
            return _SendAttempt(
                route=ROUTE_DIRECT,
                error_kind=error_kind,
                user_message=user_message,
                technical_detail=f"{type(req_err).__name__}: {req_err}",
                fallback=connection_failed,
                retry=(
                    error_kind in {"dns-error", "connection-error"}
                    or isinstance(req_err, requests.exceptions.ConnectTimeout)
                ),
            )

    def _post_relay(self, route: str, body: str, params: dict) -> _SendAttempt:
        label = ROUTE_LABELS[route]
        if not params.get("clave"):
            # Los respaldos solo aceptan una PC con clave de envío: no se gasta la consulta.
            return _SendAttempt(
                route=route,
                error_kind="relay-rejected",
                user_message=(
                    "El camino de respaldo solo funciona con clave de envío. Configure la clave de este "
                    "establecimiento (ToolkitSISMED Web → «Claves de envío») en Sync SISMED."
                ),
            )
        public_key = ""
        if route == ROUTE_SUPABASE:
            public_key = supabase_public_key()
            if not public_key:
                return _SendAttempt(route=route, error_kind="relay-unavailable",
                                    user_message=f"El {label} no está disponible en esta versión.", fallback=True)
            wait = SUPABASE_MIN_INTERVAL_SECONDS - (time.monotonic() - self._supabase_last_sent)
            if self._supabase_last_sent and wait > 0:
                return _SendAttempt(
                    route=route,
                    error_kind="relay-throttled",
                    user_message=(
                        f"Por el {label} se envía como mucho cada {SUPABASE_MIN_INTERVAL_SECONDS // 60} minutos; "
                        f"el próximo, en {int(wait // 60) + 1} min."
                    ),
                    fallback=True,
                )
        url = CLOUDFLARE_RELAY_URL if route == ROUTE_CLOUDFLARE else SUPABASE_RELAY_URL

        try:
            response = requests.post(
                url,
                data=body,
                headers=relay_headers(self._integration_url(), params, public_key),
                timeout=(10, 300),
            )
        except requests.exceptions.RequestException as req_err:
            error_kind, _message = self._classify_request_exception(req_err)
            return _SendAttempt(
                route=route,
                error_kind=error_kind,
                user_message=f"No se pudo conectar con el {label}.",
                technical_detail=f"{type(req_err).__name__}: {req_err}",
                # Si el respaldo recibió el envío y Google tarda, el otro respaldo solo lo duplicaría.
                fallback=isinstance(req_err, requests.exceptions.ConnectionError),
                retry=isinstance(req_err, requests.exceptions.ConnectionError),
            )

        failure = relay_failure(response)
        if failure is None:
            if route == ROUTE_SUPABASE:
                self._supabase_last_sent = time.monotonic()
            return _SendAttempt(route=route, response=response)

        code, message, final = failure
        return _SendAttempt(
            route=route,
            error_kind="relay-rejected" if final else "relay-error",
            user_message=f"El {label} no pudo reenviar el stock: {message}",
            technical_detail=f"{code} (HTTP {response.status_code})",
            fallback=not final,
            retry=not final,
        )

    def _classify_request_exception(self, req_err: requests.exceptions.RequestException) -> tuple[str, str]:
        if isinstance(req_err, requests.exceptions.SSLError):
            return ("tls-error", self._destination_user_message("tls-error"))

        if isinstance(req_err, requests.exceptions.ProxyError):
            return ("proxy-error", self._destination_user_message("proxy-error"))

        if isinstance(req_err, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout)):
            return ("timeout", self._destination_user_message("timeout"))

        if isinstance(req_err, requests.exceptions.ConnectionError):
            detail = str(req_err).lower()
            dns_markers = (
                "nameresolutionerror",
                "temporary failure in name resolution",
                "failed to resolve",
                "getaddrinfo failed",
                "name or service not known",
                "no address associated",
                "nodename nor servname",
            )
            if any(marker in detail for marker in dns_markers):
                return (
                    "dns-error",
                    self._destination_user_message("dns-error"),
                )

            return (
                "connection-error",
                self._destination_user_message("connection-error"),
            )

        return (
            "request-error",
            f"Error de red al enviar datos a {self.destination_name}: {type(req_err).__name__}.",
        )

    def _persist_dbf_quality(self, metrics_list: list[DbfReadMetrics]):
        relevant_metrics = [
            metric for metric in metrics_list
            if metric.total_records or metric.field_fallbacks or metric.omitted_records
        ]

        if not relevant_metrics:
            set_many({
                "runtime_last_sync_dbf_source": "",
                "runtime_last_sync_dbf_problem_records": 0,
                "runtime_last_sync_dbf_problem_ratio": 0.0,
                "runtime_last_sync_dbf_corrupted_records": 0,
                "runtime_last_sync_dbf_omitted_records": 0,
                "runtime_last_sync_dbf_field_fallbacks": 0,
                "runtime_last_sync_dbf_summary": "",
            })
            return

        worst_metric = max(
            relevant_metrics,
            key=lambda metric: (
                metric.problem_records,
                metric.problem_ratio,
                metric.field_fallbacks,
                metric.total_records,
            ),
        )

        set_many({
            "runtime_last_sync_dbf_source": worst_metric.label,
            "runtime_last_sync_dbf_problem_records": worst_metric.problem_records,
            "runtime_last_sync_dbf_problem_ratio": round(worst_metric.problem_ratio, 6),
            "runtime_last_sync_dbf_corrupted_records": worst_metric.corrupted_records,
            "runtime_last_sync_dbf_omitted_records": worst_metric.omitted_records,
            "runtime_last_sync_dbf_field_fallbacks": worst_metric.field_fallbacks,
            "runtime_last_sync_dbf_summary": " | ".join(metric.summary() for metric in relevant_metrics),
        })

    def inspect_local_almcods(self, base_dir: str | None = None) -> dict:
        """Lee el stock local y resume los ALMCOD reales antes de enviar."""
        base_dir = (base_dir or self.base_dir or "").strip()
        if not base_dir:
            return {"ok": False, "error": "No se ha configurado el directorio SISMED."}

        datos_dir = os.path.join(base_dir, "DATOS")
        stock_path = os.path.join(datos_dir, "MSTKALMDE.DBF")
        almacen_path = os.path.join(datos_dir, "MALMACEN.DBF")

        if not os.path.isdir(datos_dir):
            return {"ok": False, "error": f"No existe la carpeta DATOS en: {base_dir}"}
        if not os.path.exists(stock_path):
            return {"ok": False, "error": f"No se encontro MSTKALMDE.DBF en: {stock_path}"}

        try:
            with tempfile.TemporaryDirectory(prefix="toolkit_almcod_") as snapshot_dir:
                stock_read_path = snapshot_dbf(stock_path, snapshot_dir)
                almacen_read_path = snapshot_dbf(almacen_path, snapshot_dir)

                almacen_metrics = DbfReadMetrics("MALMACEN.DBF")
                stock_metrics = DbfReadMetrics("MSTKALMDE.DBF")
                almacen_names = {}
                counts = {}
                omitted = 0

                if os.path.exists(almacen_read_path):
                    for rec in iter_dbf_records(open_dbf(almacen_read_path, metrics=almacen_metrics), almacen_metrics):
                        almcod = str(rec.get("ALMCOD", "")).strip()
                        if almcod:
                            almacen_names[almcod] = str(rec.get("ALMDES", "")).strip()

                for rec in iter_dbf_records(open_dbf(stock_read_path, metrics=stock_metrics), stock_metrics):
                    almcod = str(rec.get("ALMCOD", "")).strip()
                    if not almcod:
                        omitted += 1
                        continue
                    counts[almcod] = counts.get(almcod, 0) + 1

                rows = [
                    {
                        "almcod": almcod,
                        "desc_alm": almacen_names.get(almcod, ""),
                        "records": count,
                        "facility_code": self._facility_from_almcod(almcod),
                    }
                    for almcod, count in sorted(counts.items())
                ]
                facility_codes = sorted({row["facility_code"] for row in rows if row["facility_code"]})
                warnings = []
                if self.modo_consolidado and any(len(row["facility_code"]) == 6 for row in rows):
                    warnings.append(
                        "El modo consolidado esta activo y hay codigos IPRESS de 6 caracteres. "
                        "Para Sync 2.0 se recomienda modo detallado salvo que el servidor ya apruebe el ALMCOD consolidado."
                    )

                return {
                    "ok": True,
                    "rows": rows,
                    "almcods": [row["almcod"] for row in rows],
                    "facility_codes": facility_codes,
                    "total_records": sum(counts.values()),
                    "omitted": omitted,
                    "metrics": [almacen_metrics.summary(), stock_metrics.summary()],
                    "warnings": warnings,
                }
        except Exception as exc:
            return {"ok": False, "error": f"No se pudo leer ALMCOD local: {type(exc).__name__}: {exc}"}

    def _log_payload_almcods(self, payload_data: list[dict]):
        counts = {}
        names = {}
        for item in payload_data:
            almcod = str(item.get("almcod", "")).strip()
            if not almcod:
                continue
            counts[almcod] = counts.get(almcod, 0) + 1
            if item.get("desc_alm") and almcod not in names:
                names[almcod] = str(item.get("desc_alm", "")).strip()

        if not counts:
            self.log("  ALMCOD detectados en SISMED: ninguno.")
            return

        codes = sorted(counts)
        self.log(f"  ALMCOD detectados en SISMED: {', '.join(codes)}")
        for code in codes[:10]:
            desc = f" | {names[code]}" if names.get(code) else ""
            self.log(f"    - {code}: {counts[code]} registros{desc}")
        if len(codes) > 10:
            self.log(f"    ... {len(codes) - 10} ALMCOD adicionales.")

    def _log_dbf_metrics(self, metrics_list: list[DbfReadMetrics]):
        for metric in metrics_list:
            if metric.total_records or metric.field_fallbacks or metric.omitted_records:
                self.log(f"  ℹ Calidad DBF {metric.summary()}")

    def _should_abort_for_dbf_quality(self, metrics: DbfReadMetrics) -> bool:
        if metrics.total_records <= 0:
            return False
        if metrics.problem_records < SYNC_DBF_ABORT_MIN_BAD_RECORDS:
            return False
        return metrics.problem_ratio >= SYNC_DBF_ABORT_BAD_RATIO

    def _dbf_quality_abort_message(self, metrics: DbfReadMetrics) -> str:
        return (
            f"Se abortó la sincronización por calidad insuficiente en {metrics.label}: "
            f"{metrics.problem_records}/{metrics.total_records} registros problemáticos "
            f"({metrics.problem_ratio:.2%}). Umbral activo: al menos "
            f"{SYNC_DBF_ABORT_MIN_BAD_RECORDS} registros y {SYNC_DBF_ABORT_BAD_RATIO:.0%} del archivo."
        )

    def log(self, message):
        """Envía el mensaje a la interfaz si existe un callback, de lo contrario lo imprime."""
        # Nunca la clave de envío, el identificador de la PC ni la dirección del script.
        message = redact_sensitive(message)
        if self.log_callback:
            self.log_callback(message)
        else:
            try:
                print(message)
            except UnicodeEncodeError:
                encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
                safe_message = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
                print(safe_message)

    def start_sync(self):
        with self._state_lock:
            if self.run_state in {"starting", "running", "stopping"}:
                return False
            self._stop_event.clear()

        self._set_run_state("starting", "Inicializando hilo de sincronizacion")
        self.log("▶ Iniciando sincronizador SISMED SYNC...")
        self.log(f"  Modo Consolidado: {'ACTIVADO' if self.modo_consolidado else 'DESACTIVADO (Detallado)'}")
        self.log(f"  Intervalo: {self.intervalo_minutos} minutos")
        self.log(f"  Equipo: {self._equipo_name() or 'sin nombre'}")
        resumen_clave = self._clave_envio_resumen()
        self.log(f"  Clave de envío: {'configurada para ' + resumen_clave if resumen_clave else 'NO configurada'}")
        self.log("="*50)
        
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        self._start_backup_connection()
        return True

    def _start_backup_connection(self):
        if not self.backup_connection_supported:
            return
        try:
            if self._backup_connection is None:
                self._backup_connection = BackupConnection(
                    log=self.log,
                    get_keys=self._clave_envio_normalizada,
                    get_device_id=get_device_id,
                    get_equipo=self._equipo_name,
                    get_base_dir=lambda: self.base_dir,
                )
            self._backup_connection.start()
        except Exception as exc:
            self.log(f"  ⚠ No se pudo iniciar la conexión inmediata con la web: {exc}")

    def _retry_backup_connection(self):
        """Tras un envío aceptado (la PC ya quedó vinculada), reintenta la conexión inmediata."""
        connection = self._backup_connection
        if connection is None:
            return
        try:
            if connection.retry_after_link():
                self.log("  Conexión inmediata con la web: se reintenta ahora que la PC está vinculada.")
        except Exception:
            pass

    def _stop_backup_connection(self):
        if self._backup_connection is not None:
            try:
                self._backup_connection.stop()
            except Exception:
                pass

    def stop_sync(self):
        with self._state_lock:
            if self.run_state in {"idle", "stopping"}:
                return False
            self._stop_event.set()

        self._set_run_state("stopping", "Detencion solicitada por el usuario")
        self.log("⏹ Deteniendo sincronizador... (esto puede tardar unos segundos)")
        return True

    def _sync_loop(self):
        self._set_run_state("running", "Hilo de sincronizacion activo")
        try:
            while not self._stop_event.is_set():
                with activity.busy("Sync SISMED"):
                    self.perform_sync()

                if self._stop_event.is_set():
                    break

                wait_seconds = max(1, int(self.intervalo_minutos)) * 60
                self.log(f"  Esperando {self.intervalo_minutos} minutos para la siguiente actualización...")
                if self._stop_event.wait(wait_seconds):
                    break
        finally:
            self._stop_backup_connection()
            self._set_run_state("idle", "Hilo de sincronizacion detenido")
            self.log("❌ Sincronizador completamente detenido.")
            if self.on_stop_callback:
                self.on_stop_callback()

    def perform_sync(self):
        self.last_sync_route = ""
        hora = time.strftime('%H:%M:%S')
        self.log(f"[{hora}] Leyendo stock detallado de SISMED...")
        self._persist_dbf_quality([])

        PATH_MEDICAM   = os.path.join(self.base_dir, "DATOS", "MMEDICAM.DBF")
        PATH_STOCK_DET = os.path.join(self.base_dir, "DATOS", "MSTKALMDE.DBF")
        PATH_MALMACEN  = os.path.join(self.base_dir, "DATOS", "MALMACEN.DBF")
        PATH_MTIPSUM   = os.path.join(self.base_dir, "DATOS", "MTIPSUM.DBF")
        PATH_MFFINAN   = os.path.join(self.base_dir, "DATOS", "MFFINAN.DBF")

        try:
            # --- Validaciones de archivos ---
            archivos_requeridos = {"Stock Detallado": PATH_STOCK_DET, "Catálogo": PATH_MEDICAM}
            for nombre, ruta in archivos_requeridos.items():
                if not os.path.exists(ruta):
                    self.log(f"  ⚠ ADVERTENCIA: No se encontró '{nombre}' en: {ruta}")

            with tempfile.TemporaryDirectory(prefix="toolkit_sync_") as snapshot_dir:
                PATH_MEDICAM_READ = snapshot_dbf(PATH_MEDICAM, snapshot_dir)
                PATH_STOCK_DET_READ = snapshot_dbf(PATH_STOCK_DET, snapshot_dir)
                PATH_MALMACEN_READ = snapshot_dbf(PATH_MALMACEN, snapshot_dir)
                PATH_MTIPSUM_READ = snapshot_dbf(PATH_MTIPSUM, snapshot_dir)
                PATH_MFFINAN_READ = snapshot_dbf(PATH_MFFINAN, snapshot_dir)

                medicam_metrics = DbfReadMetrics("MMEDICAM.DBF")
                stock_metrics = DbfReadMetrics("MSTKALMDE.DBF")
                almacen_metrics = DbfReadMetrics("MALMACEN.DBF")
                tipsum_metrics = DbfReadMetrics("MTIPSUM.DBF")
                ffinan_metrics = DbfReadMetrics("MFFINAN.DBF")

                # 1. Cargar catálogo de MEDICAMENTOS
                cat_medicam = {}
                if os.path.exists(PATH_MEDICAM_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MEDICAM_READ, metrics=medicam_metrics), medicam_metrics):
                        cod = str(rec.get('MEDCOD', '')).strip().zfill(5)
                        if cod:
                            nombre  = str(rec.get('MEDNOM', '')).strip()
                            conc    = str(rec.get('MEDCNC', '')).strip()
                            forma   = str(rec.get('MEDFF', '')).strip()
                            partes  = [p for p in [nombre, conc, forma] if p]
                            cat_medicam[cod] = {
                                "xnom": ' - '.join(partes) + (' -' if partes else ''),
                                "codigo_sig": str(rec.get('CODIGO_SIG', '')).strip(),
                            }
                self.log(f"  ✓ Medicamentos cargados: {len(cat_medicam)}")

                # 2. Cargar ALMACENES
                cat_almacen = {}
                if os.path.exists(PATH_MALMACEN_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MALMACEN_READ, metrics=almacen_metrics), almacen_metrics):
                        alm_cod = str(rec.get('ALMCOD', '')).strip()
                        if alm_cod:
                            cat_almacen[alm_cod] = str(rec.get('ALMDES', '')).strip()

                def buscar_establecimiento(alm_cod):
                    if alm_cod in cat_almacen:
                        nombre = cat_almacen[alm_cod]
                        genericos = ['FAR SISMED', 'FAR DONACIONES', 'ALM SISMED', 'FARM SISMED']
                        if any(g in nombre.upper() for g in genericos):
                            for longitud in [8, 6, 5]:
                                if len(alm_cod) > longitud:
                                    prefijo = alm_cod[:longitud]
                                    if prefijo in cat_almacen:
                                        return cat_almacen[prefijo]
                        return nombre
                    for longitud in [10, 8, 6, 5]:
                        if len(alm_cod) >= longitud:
                            prefijo = alm_cod[:longitud]
                            if prefijo in cat_almacen:
                                return cat_almacen[prefijo]
                    for clave, desc in sorted(cat_almacen.items(), key=lambda x: len(x[0]), reverse=True):
                        if alm_cod.startswith(clave) and len(clave) >= 4:
                            return desc
                    return ''

                # 3. Y 4. Cargar TIPSUM y FFINAN
                cat_tipsum = {}
                if os.path.exists(PATH_MTIPSUM_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MTIPSUM_READ, metrics=tipsum_metrics), tipsum_metrics):
                        if str(rec.get('CODSUM', '')).strip():
                            cat_tipsum[str(rec.get('CODSUM', '')).strip()] = str(rec.get('NOMSUM', '')).strip()

                cat_ffinan = {}
                if os.path.exists(PATH_MFFINAN_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_MFFINAN_READ, metrics=ffinan_metrics), ffinan_metrics):
                        if str(rec.get('CODFF', '')).strip():
                            cat_ffinan[str(rec.get('CODFF', '')).strip()] = str(rec.get('DESFF', '')).strip()

                # 5. Leer STOCK DETALLADO
                payload_data = []
                registros_omitidos = 0
                
                def safe_float(val):
                    if val is None:
                        return 0.0
                    try:
                        clean_str = str(val).strip()
                        if not clean_str:
                            return 0.0
                        return float(clean_str)
                    except (ValueError, TypeError):
                        return 0.0


                if os.path.exists(PATH_STOCK_DET_READ):
                    for rec in iter_dbf_records(open_dbf(PATH_STOCK_DET_READ, metrics=stock_metrics), stock_metrics):
                        med_id_raw = str(rec.get('MEDCOD', '')).strip()
                        if not med_id_raw:
                            registros_omitidos += 1
                            stock_metrics.note_omission("missing-medcod")
                            continue

                        med_id = med_id_raw.zfill(5)
                        alm_cod = str(rec.get('ALMCOD', '')).strip()
                        alm_des = buscar_establecimiento(alm_cod)

                        med_info = cat_medicam.get(med_id, {})
                        
                        fecha_vto_raw = rec.get('MEDFECHVTO')
                        if fecha_vto_raw and hasattr(fecha_vto_raw, 'strftime'):
                            fecha_vto = fecha_vto_raw.strftime('%d/%m/%Y')
                        elif fecha_vto_raw:
                            fecha_vto = str(fecha_vto_raw)
                        else:
                            fecha_vto = ""

                        payload_data.append({
                            "almcod":      alm_cod,
                            "desc_alm":    alm_des,
                            "medcod":      med_id,
                            "codigo_sig":  med_info.get("codigo_sig", ""),
                            "xnom":        med_info.get("xnom", "Sin Nombre"),
                            "lote":        str(rec.get('MEDLOTE', '')).strip(),
                            "fecha":       fecha_vto,
                            "medregsan":   str(rec.get('MEDREGSAN', '')).strip(),
                            "tipsum":      str(rec.get('TIPSUM', '')).strip(),
                            "tipsum_des":  cat_tipsum.get(str(rec.get('TIPSUM', '')).strip(), ""),
                            "ffinan":      str(rec.get('FFINAN', '')).strip(),
                            "ffinan_des":  cat_ffinan.get(str(rec.get('FFINAN', '')).strip(), ""),
                            "saldo":       safe_float(rec.get('STKSALDODE')),
                            "precio_det":  safe_float(rec.get('STKPRED')),
                            "preciocab":   safe_float(rec.get('STKPREO')),
                            "fecha_equipo": "",
                            "actualizado": "",
                        })
                else:
                    message = f"No se encontró archivo de stock en: {PATH_STOCK_DET}"
                    self.log(f"  ❌ ERROR: {message}")
                    self._record_cycle_result(
                        "missing-stock-dbf",
                        message,
                        error_kind="missing-stock-dbf",
                    )
                    return

                self.log(f"  ✓ Registros leídos de MSTKALMDE: {len(payload_data)}")
                self._log_payload_almcods(payload_data)
                if registros_omitidos:
                    self.log(f"  ℹ Registros omitidos por claves incompletas: {registros_omitidos}")
                self._set_reported_scope(payload_data)
                payload_data = self._filter_zero_stock_records(payload_data, "lectura DBF")

                dbf_metrics = [
                    medicam_metrics,
                    almacen_metrics,
                    tipsum_metrics,
                    ffinan_metrics,
                    stock_metrics,
                ]
                self._log_dbf_metrics(dbf_metrics)
                self._persist_dbf_quality(dbf_metrics)

                for critical_metrics in (medicam_metrics, stock_metrics):
                    if self._should_abort_for_dbf_quality(critical_metrics):
                        message = self._dbf_quality_abort_message(critical_metrics)
                        self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                        self._record_cycle_result(
                            "dbf-quality-abort",
                            message,
                            error_kind="dbf-quality-abort",
                            records=len(payload_data),
                        )
                        return

                # 6. Consolidación (Si está activado)
                if self.modo_consolidado:
                    self.log(
                        "  ⚠ Modo CONSOLIDADO activo: se sumarán farmacias/sub-almacenes "
                        "y el total de filas enviadas puede ser menor al stock detallado."
                    )
                    self.log(f"  Σ Consolidando stock de sub-almacenes...")
                    consolidado = {}
                    for item in payload_data:
                        alm_base = self._facility_from_almcod(item["almcod"])
                        group_key = (alm_base, item["medcod"], item["lote"], item["fecha"], item["ffinan"], item["tipsum"])
                        
                        if group_key not in consolidado:
                            consolidado[group_key] = item.copy()
                            nombre_base = buscar_establecimiento(alm_base)
                            consolidado[group_key]["almcod"] = self._consolidated_almcod(alm_base)
                            consolidado[group_key]["desc_alm"] = f"{nombre_base} (CONSOLIDADO)"
                        else:
                            consolidado[group_key]["saldo"] += item["saldo"]
                            consolidado[group_key]["precio_det"] = max(consolidado[group_key]["precio_det"], item["precio_det"])
                            consolidado[group_key]["preciocab"] = max(consolidado[group_key]["preciocab"], item["preciocab"])

                    payload_data = list(consolidado.values())
                    self.log(f"  ✓ Stock consolidado: {len(payload_data)} lotes únicos.")
                    payload_data = self._filter_zero_stock_records(payload_data, "consolidación")
                else:
                    self.log(f"  ℹ Modo DETALLADO activo (farmacias por separado).")

                # 7. Enviar a Google Apps Script (Envío Unificado)
                if not payload_data:
                    if self._can_send_empty_payload_for_clear():
                        self.log(
                            "  ℹ No hay lotes con stock distinto de cero; se enviará señal de limpieza "
                            "para los ALMCOD reportados."
                        )
                    else:
                        message = "No hay stock para enviar. El archivo DBF analizado está vacío o sin precios."
                        self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                        self._record_cycle_result(
                            "no-data",
                            message,
                            records=0,
                        )
                        return
                    
                payload_ok, payload_message = self._validate_payload_before_send(payload_data)
                if not payload_ok:
                    message = payload_message or "La validacion local del stock impidio el envio."
                    self.log(f"[{time.strftime('%H:%M:%S')}] â›” {message}")
                    self._record_cycle_result(
                        "payload-validation",
                        message,
                        error_kind="payload-validation",
                        records=len(payload_data),
                    )
                    return

                payload_data, bloqueos_clave = self._apply_send_key_check(payload_data)
                if bloqueos_clave:
                    message = self._send_key_block_message(bloqueos_clave)
                    self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
                    if not payload_data and not self._last_reported_almcods:
                        self._record_cycle_result(
                            "send-key-blocked",
                            message,
                            error_kind="send-key-blocked",
                            records=0,
                        )
                        return

                self._stamp_payload_host_time(payload_data)
                self.log(f"[{time.strftime('%H:%M:%S')}] Subiendo a la nube ({self.destination_label})...")
                
                response, error_kind, user_message, technical_detail = self._post_payload_with_retries(payload_data)
                if error_kind == "stopped":
                    return

                if response is None:
                    self.log(f"  ⚠️ {user_message}")
                    if technical_detail:
                        self.log(f"  Detalle técnico: {technical_detail}")
                    self._record_cycle_result(
                        error_kind or "request-error",
                        f"{user_message} | {technical_detail}".strip(" |"),
                        error_kind=error_kind or "request-error",
                        records=len(payload_data),
                    )
                    return

                bloqueos = self._send_key_blocks(response)
                if bloqueos:
                    message = self._send_key_block_message(bloqueos)
                    self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
                    self._record_cycle_result(
                        "send-key-blocked",
                        message,
                        error_kind="send-key-blocked",
                        http_status=response.status_code,
                        records=len(payload_data),
                    )
                    return

                if self._is_success_response(response):
                    acknowledged_count = self._acknowledged_record_count(response)
                    if acknowledged_count is not None and acknowledged_count != len(payload_data):
                        message = (
                            f"Envío parcial detectado: {self.destination_name} confirmó "
                            f"{acknowledged_count} registros, pero Toolkit envió {len(payload_data)}. "
                            "No se marcará como éxito hasta que ambos conteos coincidan."
                        )
                        self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                        self.log(f"  Respuesta del servidor: {(response.text or '').strip()[:300]}")
                        self._record_cycle_result(
                            "partial-upload",
                            message,
                            error_kind="partial-upload",
                            http_status=response.status_code,
                            records=len(payload_data),
                        )
                        return

                    success_message = self._success_message(response, len(payload_data))
                    if self.last_sync_route and self.last_sync_route != ROUTE_DIRECT:
                        success_message += f" Enviado por el {ROUTE_LABELS[self.last_sync_route]}."
                    self.log(f"[{time.strftime('%H:%M:%S')}] ✓ ¡Éxito! {success_message}")
                    self._retry_backup_connection()
                    self._record_cycle_result(
                        "success",
                        (
                            f"{success_message} Registros={len(payload_data)}; "
                            f"stock_cero_omitidos={self._last_zero_stock_omitted}; "
                            f"omitidos={registros_omitidos}; problemas_dbf={stock_metrics.problem_records}"
                        ),
                        http_status=response.status_code,
                        records=len(payload_data),
                        success=True,
                    )
                else:
                    response_preview = response.text[:300].strip()
                    failure_message = f"HTTP {response.status_code} al sincronizar con {self.destination_name}."
                    self.log(f"  ✗ Fallo en la conexión a {self.destination_name}: HTTP {response.status_code}")
                    if response_preview:
                        self.log(f"  Respuesta del servidor: {response_preview}")
                    self._record_cycle_result(
                        "http-error",
                        f"{failure_message} {response_preview}".strip(),
                        error_kind="http-error",
                        http_status=response.status_code,
                        records=len(payload_data),
                    )

        except (PermissionError, OSError) as os_err:
            if getattr(os_err, 'winerror', 0) in [32, 33] or isinstance(os_err, PermissionError):
                message = "El archivo está bloqueado por SISMED u otro proceso. Reintentando próximo ciclo."
                self.log(f"[{time.strftime('%H:%M:%S')}] ⚠ {message}")
                self._record_cycle_result(
                    "dbf-locked",
                    message,
                    error_kind="dbf-locked",
                )
            else:
                message = f"Error de I/O en disco: {str(os_err)}"
                self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
                self._record_cycle_result(
                    "io-error",
                    message,
                    error_kind="io-error",
                )
        except Exception as e:
            message = f"Error crítico durante la sincronización: {str(e)}"
            self.log(f"[{time.strftime('%H:%M:%S')}] ✗ {message}")
            self.log(traceback.format_exc())
            self._record_cycle_result(
                "unexpected-error",
                message,
                error_kind=type(e).__name__,
            )
