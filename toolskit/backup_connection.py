"""Conexión inmediata con ToolkitSISMED Web (backups SISMED · etapa 1, piloto).

Las PC de los establecimientos no aceptan conexiones de afuera, así que para que la web
pueda pedirle algo al Toolkit al instante es el Toolkit el que abre una conexión con el
servicio «sismed-conexion» de Cloudflare y la mantiene abierta mientras Sync SISMED corre.

- Solo se conecta si el establecimiento tiene **clave de envío** configurada en esta PC y
  la web lo tiene habilitado (durante el piloto, solo los códigos de
  `backup_pilot_codes`). Las demás PC no intentan nada.
- El servicio vuelve a comprobar la clave y que esta sea la PC vinculada.
- Cada 50 s manda el texto «ping»; el servicio responde «pong» sin gastar nada. Si no
  llega respuesta en 2 minutos, se reconecta.
- Responde el «aviso de prueba» de la web y, cuando la web pide un backup, sube el más
  reciente del SISMED (`backup_upload.py`). Un backup a la vez.
"""

from __future__ import annotations

import json
import random
import ssl
import threading
import time
import urllib.request
from urllib.parse import unquote, urlparse

import requests

from app_version import get_current_version
from send_key_check import SUPABASE_URL, keys_by_code, supabase_public_key
from backup_upload import BackupUploader, service_http_base

try:
    import websocket  # paquete websocket-client
except Exception:  # pragma: no cover - si falta el paquete, la función queda apagada
    websocket = None

SERVICE_URL = "wss://sismed-conexion.jchaconvillacis.workers.dev/pc"
ENABLED_RECHECK_SECONDS = 30 * 60
PING_SECONDS = 50
PONG_TIMEOUT_SECONDS = 120
REJECTED_WAIT_SECONDS = 30 * 60
MAX_BACKOFF_SECONDS = 300


def ssl_context() -> ssl.SSLContext:
    """
    Certificados para la conexión inmediata. websocket-client solo usa los de Windows, y una PC
    sin las raíces al día (Windows las baja recién cuando las necesita) fallaba con
    CERTIFICATE_VERIFY_FAILED mientras el stock sí se enviaba, porque `requests` usa certifi.
    Aquí van los dos: certifi y, encima, los de Windows (por si un antivirus inspecciona HTTPS).
    """
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return context


def proxy_options(service_url: str = "") -> dict:
    """
    Proxy del sistema para la conexión inmediata. `requests` y el navegador lo toman solos de
    Windows, pero websocket-client no: en una red que sale por proxy el stock se enviaba y la
    PC nunca aparecía en Backups SISMED. Solo proxies HTTP; sin proxy, devuelve {}.
    """
    try:
        proxies = urllib.request.getproxies()
        raw = proxies.get("https") or proxies.get("http") or ""
        host = urlparse((service_url or SERVICE_URL).replace("wss://", "https://", 1)).hostname or ""
        if not raw or (host and urllib.request.proxy_bypass(host)):
            return {}
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return {}
        options = {"http_proxy_host": parsed.hostname, "http_proxy_port": parsed.port or 8080, "proxy_type": "http"}
        if parsed.username:
            options["http_proxy_auth"] = (unquote(parsed.username), unquote(parsed.password or ""))
        return options
    except Exception:
        return {}


def _short(error) -> str:
    """Motivo de un error en una línea corta para el registro."""
    text = " ".join(str(error or "").split()) or type(error).__name__
    return text[:160]


class BackupConnection:
    def __init__(self, log, get_keys, get_device_id, get_equipo, get_base_dir=lambda: ""):
        self.log = log
        self.get_base_dir = get_base_dir
        self._upload_lock = threading.Lock()
        self.get_keys = get_keys
        self.get_device_id = get_device_id
        self.get_equipo = get_equipo
        self._stop = threading.Event()
        # Despierta una espera larga antes de tiempo (ver `retry_after_link`).
        self._wake = threading.Event()
        # La última vuelta terminó sin conexión porque la web no la aceptó todavía.
        self._waiting_for_link = False
        self._thread: threading.Thread | None = None
        self._ws = None
        self._last_pong = 0.0
        self._enabled_checked_at = 0.0
        self._enabled_codes: list[str] = []
        # Último problema anotado en el registro: cada motivo se anota una vez, no en cada intento.
        self._last_problem: str | None = None
        self.connected = False

    # --- ciclo de vida -------------------------------------------------------------
    def start(self):
        if websocket is None:
            self._report("missing", "  ⚠ Backups SISMED: falta el componente de conexión inmediata (websocket-client); esta PC no aparecerá en Backups.")
            return
        if self._thread and self._thread.is_alive():
            if not self._stop.is_set():
                # Ya corre: que vuelva a mirar ahora las claves (pudieron cambiar).
                self._wake.set()
                return
            # Se pidió detener y todavía no terminó: se espera un momento para no quedarse sin
            # conexión (antes `start` volvía sin hacer nada y el hilo viejo terminaba solo).
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name="backup-connection", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    # --- lógica --------------------------------------------------------------------
    def _keys(self) -> dict[str, str]:
        try:
            return keys_by_code(self.get_keys())
        except Exception:
            return {}

    def enabled_codes(self, codes: list[str]) -> list[str]:
        """Códigos que la web tiene habilitados (clave de envío + piloto)."""
        public_key = supabase_public_key()
        if not public_key or not codes:
            return []
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/app_backup_pc_enabled",
            headers={"apikey": public_key, "Content-Type": "application/json"},
            json={"p_codes": codes},
            timeout=15,
        )
        if response.status_code == 404:
            return []  # la base todavía no tiene la función: la conexión queda apagada
        response.raise_for_status()
        data = response.json()
        return [str(c).upper() for c in data] if isinstance(data, list) else []

    def _report(self, kind: str, message: str):
        """Anota un problema de conexión en el registro solo si cambió desde la última vez."""
        if kind == self._last_problem:
            return
        self._last_problem = kind
        self.log(message)

    def _wait(self, seconds: float) -> bool:
        """Espera o termina antes si se pidió detener o despertar. Devuelve True si hay que salir."""
        self._wake.wait(max(1.0, seconds))
        self._wake.clear()
        return self._stop.is_set()

    def retry_after_link(self) -> bool:
        """
        Sync SISMED la llama tras un envío de stock aceptado. Una clave recién puesta se vincula
        a la PC en su primer envío; si la conexión ya había sido rechazada por eso, esperaba
        30 minutos para volver a intentar. Así lo intenta enseguida, una sola vez por rechazo.
        """
        if self.connected or not self._waiting_for_link:
            return False
        self._waiting_for_link = False
        self._wake.set()
        return True

    def _run(self):
        backoff = 5
        while not self._stop.is_set():
            keys = self._keys()
            if not keys:
                # Sin clave todavía: al poner la clave, el primer envío aceptado la despierta.
                self._waiting_for_link = True
                if self._wait(ENABLED_RECHECK_SECONDS):
                    return
                continue
            try:
                codes = self.enabled_codes(sorted(keys))
                self._enabled_codes = codes
                self._enabled_checked_at = time.monotonic()
            except Exception as exc:
                self._report("enabled-error", f"  ⚠ Backups SISMED: no se pudo consultar a la web si esta PC está habilitada ({_short(exc)}). Se reintentará en 5 minutos.")
                if self._wait(300):
                    return
                continue
            if not codes:
                self._report("not-enabled", "  ℹ Backups SISMED: la web todavía no habilita esta PC (clave sin vincular o sin clave de envío). Se volverá a consultar en 30 minutos.")
                self._waiting_for_link = True
                if self._wait(ENABLED_RECHECK_SECONDS):
                    return
                continue

            self._waiting_for_link = False
            outcome = self._connect({c: keys[c] for c in codes if c in keys})
            if self._stop.is_set():
                return
            if outcome == "rejected":
                self._report("rejected", "  ⚠ Conexión inmediata rechazada por la web (clave o PC no vinculada). Se reintentará más tarde.")
                backoff = 5
                self._waiting_for_link = True
                if self._wait(REJECTED_WAIT_SECONDS):
                    return
                continue
            if outcome == "ok":
                backoff = 5
            if self._wait(backoff + random.uniform(0, backoff / 2)):
                return
            backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)

    def _connect(self, keys: dict[str, str]) -> str:
        """Abre la conexión y la mantiene hasta que se corte. Devuelve ok / rejected / error."""
        headers = [
            f"X-Toolkit-Claves: {','.join(keys.values())}",
            f"X-Toolkit-Equipo-Id: {self.get_device_id()}",
            f"X-Toolkit-Equipo: {self.get_equipo()}",
            f"X-Toolkit-Version: {get_current_version()}",
        ]
        state = {"opened": False, "rejected": False, "error": ""}

        def on_open(ws):
            state["opened"] = True
            self.connected = True
            self._last_problem = None
            self._last_pong = time.monotonic()
            self.log(f"  🔌 Conexión inmediata activa con la web ({', '.join(keys)}).")
            threading.Thread(target=self._keepalive, args=(ws,), daemon=True).start()

        def on_message(ws, message):
            if isinstance(message, (bytes, bytearray)):
                message = bytes(message).decode("utf-8", "ignore")
            if message == "pong":
                self._last_pong = time.monotonic()
                return
            try:
                data = json.loads(message)
            except Exception:
                return
            if data.get("t") == "ping":
                self._last_pong = time.monotonic()
                ws.send(json.dumps({"t": "pong", "id": data.get("id"), "code": data.get("code"),
                                    "web": data.get("web"), "sentAt": data.get("sentAt")}))
                self.log(f"  📨 Aviso de prueba recibido desde la web ({data.get('code')}).")
            elif data.get("t") == "backup":
                self._start_backup(ws, data)

        def on_error(ws, error):
            status = getattr(error, "status_code", None)
            if status in (401, 403):
                state["rejected"] = True
            elif not state["error"]:
                state["error"] = _short(error)

        def on_close(ws, *_args):
            if self.connected:
                self.log("  🔌 Conexión inmediata cerrada; se reconectará sola.")
            self.connected = False

        app = websocket.WebSocketApp(SERVICE_URL, header=headers, on_open=on_open,
                                     on_message=on_message, on_error=on_error, on_close=on_close)
        self._ws = app
        proxy = proxy_options()
        if proxy:
            self._report(f"proxy:{proxy['http_proxy_host']}:{proxy['http_proxy_port']}",
                         f"  ℹ Backups SISMED: se conecta por el proxy del sistema ({proxy['http_proxy_host']}:{proxy['http_proxy_port']}).")
        try:
            app.run_forever(ping_interval=0, sslopt={"context": ssl_context()}, **proxy)
        except Exception as exc:
            state["error"] = state["error"] or _short(exc)
        finally:
            self._ws = None
            self.connected = False
        if state["rejected"]:
            return "rejected"
        if not state["opened"]:
            self._report("unreachable", (
                f"  ⚠ Backups SISMED: no se pudo conectar con el servicio de backups ({state['error'] or 'sin respuesta'}). "
                "Si sigue así, la red del establecimiento puede estar bloqueando sismed-conexion.jchaconvillacis.workers.dev. "
                "Se reintentará sola."
            ))
            return "error"
        return "ok"

    def _start_backup(self, ws, data: dict):
        job = str(data.get("job") or "")
        if not job or not data.get("token"):
            return

        def send(message: dict):
            ws.send(json.dumps(message))

        if not self._upload_lock.acquire(blocking=False):
            send({"t": "backup_error", "job": job, "reason": "Esta PC ya está enviando otro backup"})
            return

        def work():
            try:
                uploader = BackupUploader(
                    base_url=service_http_base(SERVICE_URL), job=job, token=str(data["token"]),
                    part_size=int(data.get("partSize") or 20 * 1024 * 1024),
                    max_bytes=int(data.get("maxBytes") or 600 * 1024 * 1024),
                    send=send, log=self.log,
                )
                uploader.run(self.get_base_dir(), str(data.get("code") or ""))
            finally:
                self._upload_lock.release()

        threading.Thread(target=work, name="backup-upload", daemon=True).start()

    def _keepalive(self, ws):
        while not self._stop.is_set() and self.connected:
            if self._stop.wait(PING_SECONDS):
                break
            if not self.connected:
                break
            if time.monotonic() - self._last_pong > PONG_TIMEOUT_SECONDS:
                try:
                    ws.close()  # sin respuesta: se reconecta
                except Exception:
                    pass
                break
            # Si la web lo sacó del piloto, se desconecta en la siguiente revisión.
            if time.monotonic() - self._enabled_checked_at > ENABLED_RECHECK_SECONDS:
                self._enabled_checked_at = time.monotonic()
                try:
                    if not self.enabled_codes(sorted(self._keys())):
                        ws.close()
                        break
                except Exception:
                    pass
            try:
                ws.send("ping")
            except Exception:
                break
