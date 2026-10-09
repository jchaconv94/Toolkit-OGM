import socket
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import requests

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import sismed_sync  # noqa: E402
import stock_routes  # noqa: E402
from sismed_sync import SismedSyncManager  # noqa: E402
from stock_routes import (  # noqa: E402
    CLOUDFLARE_RELAY_URL,
    ROUTE_CLOUDFLARE,
    ROUTE_DIRECT,
    ROUTE_SUPABASE,
    SUPABASE_RELAY_URL,
    internal_addresses,
    redact_sensitive,
    relay_failure,
)

# Dirección de mentira: nunca la de una UNGET real.
SCRIPT_URL = "https://script.google.com/macros/s/AKfycbPRUEBA_relay-0123456789/exec"
CLAVE = "06506-K7QM-4XPA-93RD"


def http_response(status=200, text="OK:2 registros", headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = text.encode("utf-8")
    response.encoding = "utf-8"
    response.headers.update(headers or {})
    return response


def relay_ok(text="OK:2 registros"):
    return http_response(200, text, {"X-Relay": "ok", "Content-Type": "text/plain; charset=utf-8"})


def relay_error(code, final, status=403):
    body = '{"error": "%s", "message": "mensaje %s", "final": %s}' % (code, code, "true" if final else "false")
    return http_response(status, body, {"X-Relay-Error": code, "Content-Type": "application/json"})


def refused():
    # La IP interna del desvío responde al ping pero cierra el 443.
    return requests.exceptions.ConnectionError("[WinError 10061] No connection could be made: 10.254.30.102:443")


def tls_reset():
    return requests.exceptions.ConnectionError(
        f"('Connection aborted.', ConnectionResetError(10054)) url: {SCRIPT_URL}?equipo_id=win-abc&clave={CLAVE}"
    )


class FakePost:
    """requests.post simulado: cada URL (google, cloudflare, supabase) responde lo que se le dé."""

    def __init__(self, **by_route):
        self.by_route = {route: list(values) if isinstance(values, list) else [values] for route, values in by_route.items()}
        self.calls = []

    @staticmethod
    def route_of(url):
        if url == CLOUDFLARE_RELAY_URL:
            return ROUTE_CLOUDFLARE
        if url == SUPABASE_RELAY_URL:
            return ROUTE_SUPABASE
        return ROUTE_DIRECT

    def __call__(self, url, **kwargs):
        route = self.route_of(url)
        self.calls.append((route, url, kwargs))
        queue = self.by_route.get(route)
        if not queue:
            raise AssertionError(f"no se esperaba un envío por {route}")
        value = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def routes(self):
        return [route for route, _url, _kwargs in self.calls]


class RedactTests(unittest.TestCase):
    def test_hides_key_device_and_script_in_urls(self):
        text = (
            "ConnectTimeout: HTTPSConnectionPool(host='script.google.com', port=443): Max retries exceeded with url: "
            f"/macros/s/AKfycbPRUEBA_relay-0123456789/exec?equipo=PC1&equipo_id=win-abc123&clave={CLAVE}&omit_zero_stock=1"
        )
        clean = redact_sensitive(text)
        self.assertNotIn("AKfycbPRUEBA", clean)
        self.assertNotIn("win-abc123", clean)
        self.assertNotIn("K7QM", clean)
        self.assertIn("/macros/s/***/exec", clean)
        self.assertIn("equipo_id=***", clean)
        self.assertIn("clave=***", clean)
        self.assertIn("equipo=PC1", clean)
        self.assertIn("omit_zero_stock=1", clean)

    def test_hides_keys_anywhere_but_keeps_the_code(self):
        clean = redact_sensitive(f"claves {CLAVE}, 030S05-AAAA-BBBB-CCCC")
        self.assertEqual(clean, "claves 06506-****, 030S05-****")

    def test_workspace_script_and_google_echo(self):
        clean = redact_sensitive(
            "https://script.google.com/a/macros/diresa.gob.pe/s/AKfycbPRUEBA_relay-0123456789/exec "
            "https://script.googleusercontent.com/macros/echo?user_content_key=SECRETO&lib=x"
        )
        self.assertNotIn("AKfycbPRUEBA", clean)
        self.assertNotIn("SECRETO", clean)

    def test_plain_messages_are_untouched(self):
        message = "✓ ¡Éxito! Stock detallado sincronizado (OK:489 registros en hojas: 06506(489))."
        self.assertEqual(redact_sensitive(message), message)
        self.assertEqual(redact_sensitive(None), "")

    def test_log_and_cycle_status_never_show_secrets(self):
        lines = []
        manager = SismedSyncManager(log_callback=lines.append)
        manager.log(f"Detalle: {SCRIPT_URL}?clave={CLAVE}&equipo_id=win-abc")
        self.assertNotIn("K7QM", lines[0])
        self.assertNotIn("AKfycbPRUEBA", lines[0])
        with patch.object(sismed_sync, "update_runtime_status") as status, patch.object(sismed_sync, "set_many"):
            manager._record_cycle_result("timeout", f"Error {SCRIPT_URL}?clave={CLAVE}")
        self.assertNotIn("K7QM", status.call_args[0][2])
        self.assertNotIn("K7QM", manager.last_cycle_message)


class InternalAddressTests(unittest.TestCase):
    @staticmethod
    def _info(address):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def test_detects_dns_sent_to_an_internal_address(self):
        with patch.object(stock_routes.socket, "getaddrinfo", return_value=self._info("10.254.30.102")):
            self.assertEqual(internal_addresses("script.google.com"), (True, ["10.254.30.102"], ""))

    def test_google_addresses_are_not_internal(self):
        with patch.object(stock_routes.socket, "getaddrinfo", return_value=self._info("142.251.133.110")):
            self.assertEqual(internal_addresses("script.google.com"), (True, [], ""))

    def test_dns_failure(self):
        with patch.object(stock_routes.socket, "getaddrinfo", side_effect=socket.gaierror(11001, "getaddrinfo failed")):
            resolved, internal, detail = internal_addresses("script.google.com")
        self.assertFalse(resolved)
        self.assertIn("getaddrinfo failed", detail)


class RelayFailureTests(unittest.TestCase):
    def test_google_answer_through_the_relay(self):
        self.assertIsNone(relay_failure(relay_ok()))
        self.assertIsNone(relay_failure(http_response(500, "Error", {"X-Relay": "ok"})))

    def test_relay_error(self):
        self.assertEqual(relay_failure(relay_error("CLAVE_NO_VALIDA", True)), ("CLAVE_NO_VALIDA", "mensaje CLAVE_NO_VALIDA", True))
        self.assertEqual(relay_failure(relay_error("GOOGLE_NO_RESPONDE", False, 502))[2], False)

    def test_unknown_answers_are_not_trusted(self):
        # Un portal cautivo, o el servicio sin la ruta /stock todavía.
        self.assertEqual(relay_failure(http_response(200, "<html>Portal</html>"))[0], "RESPUESTA_DESCONOCIDA")
        self.assertEqual(relay_failure(http_response(404, '{"error": "No encontrado"}'))[:2], ("No encontrado", "No encontrado"))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.manager = SismedSyncManager(log_callback=self.lines.append)
        self.manager.apps_script_url = SCRIPT_URL
        self.manager.clave_envio = CLAVE
        self.manager.omitir_stock_cero = False
        patches = [
            patch.object(sismed_sync, "get_device_id", return_value="win-abc"),
            patch.object(sismed_sync.socket, "gethostname", return_value="PC-FARMACIA"),
            patch.object(sismed_sync, "supabase_public_key", return_value="anon-key"),
            patch.object(sismed_sync, "SYNC_DNS_RETRY_ATTEMPTS", 2),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.waits = patch.object(self.manager, "_wait_between_quick_retries", return_value=False).start()
        self.addCleanup(patch.stopall)
        self.dns(internal=[])

    def dns(self, internal=None, fails=False):
        if fails:
            value = (False, [], "No se pudo resolver script.google.com: getaddrinfo failed")
        else:
            value = (True, internal or [], "")
        patcher = patch.object(sismed_sync, "internal_addresses", return_value=value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, fake):
        with patch.object(sismed_sync.requests, "post", fake):
            return self.manager._post_payload_with_retries([{"almcod": "06506F01", "saldo": 3}])

    def test_direct_when_google_answers(self):
        fake = FakePost(google=http_response())
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(response.text, "OK:2 registros")
        self.assertEqual(kind, "")
        self.assertEqual(fake.routes(), [ROUTE_DIRECT])
        self.assertEqual(self.manager.last_sync_route, ROUTE_DIRECT)

    def test_hijacked_dns_goes_to_cloudflare_without_touching_google(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=relay_ok())
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(kind, "")
        self.assertEqual(response.text, "OK:2 registros")
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE])
        self.assertEqual(self.manager.last_sync_route, ROUTE_CLOUDFLARE)

        _route, url, kwargs = fake.calls[0]
        headers = kwargs["headers"]
        self.assertEqual(headers["X-Toolkit-Destino"], SCRIPT_URL)
        params = parse_qs(headers["X-Toolkit-Params"])
        self.assertEqual(params["clave"], [CLAVE])
        self.assertEqual(params["equipo_id"], ["win-abc"])
        self.assertNotIn("apikey", headers)
        self.assertNotIn("params", kwargs)  # la clave no va en la dirección
        self.assertEqual(kwargs["data"], '[{"almcod": "06506F01", "saldo": 3}]')
        self.assertTrue(any("10.254.30.102" in line for line in self.lines))

    def test_block_is_explained_once_not_every_cycle(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=relay_ok())
        self.send(fake)
        self.send(fake)
        self.assertEqual(sum("dirección interna" in line for line in self.lines), 1)

    def test_tls_cut_by_firewall_goes_to_cloudflare_and_remembers(self):
        fake = FakePost(google=tls_reset(), cloudflare=relay_ok())
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(kind, "")
        self.assertEqual(fake.routes(), [ROUTE_DIRECT, ROUTE_CLOUDFLARE])
        self.assertGreater(self.manager._direct_blocked_until, time.monotonic())

        # El siguiente envío va directo al respaldo: no pierde tiempo en Google.
        fake.calls.clear()
        self.send(fake)
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE])

    def test_google_is_tried_again_after_the_block_expires(self):
        self.manager._direct_blocked_until = time.monotonic() - 1
        fake = FakePost(google=http_response())
        self.send(fake)
        self.assertEqual(fake.routes(), [ROUTE_DIRECT])

    def test_if_relays_fail_while_skipping_google_it_tries_google(self):
        self.manager._direct_blocked_until = time.monotonic() + 3600
        fake = FakePost(cloudflare=relay_error("CLAVE_NO_VALIDA", True), google=http_response())
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(kind, "")
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_DIRECT])
        self.assertEqual(self.manager.last_sync_route, ROUTE_DIRECT)
        self.assertEqual(self.manager._direct_blocked_until, 0.0)

    def test_slow_google_is_not_resent_by_a_relay(self):
        # Google recibió el envío y tarda: puede estar escribiendo la hoja.
        fake = FakePost(google=requests.exceptions.ReadTimeout("Read timed out"))
        response, kind, _msg, _detail = self.send(fake)
        self.assertIsNone(response)
        self.assertEqual(kind, "timeout")
        self.assertEqual(fake.routes(), [ROUTE_DIRECT])
        self.waits.assert_not_called()

    def test_google_http_error_is_final(self):
        fake = FakePost(google=http_response(500, "Error"))
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(fake.routes(), [ROUTE_DIRECT])

    def test_cloudflare_down_goes_to_supabase_with_public_key(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=requests.exceptions.ConnectionError("bloqueado"), supabase=relay_ok())
        response, kind, _msg, _detail = self.send(fake)
        self.assertEqual(kind, "")
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_SUPABASE])
        self.assertEqual(self.manager.last_sync_route, ROUTE_SUPABASE)
        self.assertEqual(fake.calls[1][2]["headers"]["apikey"], "anon-key")

    def test_supabase_is_used_at_most_every_30_minutes(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=requests.exceptions.ConnectionError("bloqueado"), supabase=relay_ok(), google=refused())
        self.send(fake)
        fake.calls.clear()
        response, _kind, message, detail = self.send(fake)
        self.assertIsNone(response)
        self.assertNotIn(ROUTE_SUPABASE, fake.routes())
        self.assertIn("30 minutos", detail)

        self.manager._supabase_last_sent = time.monotonic() - 31 * 60
        fake.calls.clear()
        response, _kind, _message, _detail = self.send(fake)
        self.assertIsNotNone(response)

    def test_without_public_key_supabase_is_skipped(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=requests.exceptions.ConnectionError("bloqueado"), google=refused())
        with patch.object(sismed_sync, "supabase_public_key", return_value=""):
            response, _kind, _message, _detail = self.send(fake)
        self.assertIsNone(response)
        self.assertNotIn(ROUTE_SUPABASE, fake.routes())

    def test_rejected_key_stops_without_trying_supabase_or_retrying(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=relay_error("CLAVE_NO_VALIDA", True), supabase=relay_ok(), google=refused())
        response, kind, message, detail = self.send(fake)
        self.assertIsNone(response)
        self.assertEqual(kind, "relay-rejected")
        # Supabase no (daría lo mismo); Google, como último intento.
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_DIRECT])
        self.assertIn("ningún camino", message)
        self.assertIn("10061", detail)
        self.assertIn("CLAVE_NO_VALIDA", detail)
        self.waits.assert_not_called()

    def test_relay_temporary_error_tries_supabase(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=relay_error("GOOGLE_NO_RESPONDE", False, 502), supabase=relay_ok())
        response, _kind, _message, _detail = self.send(fake)
        self.assertIsNotNone(response)
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_SUPABASE])

    def test_old_service_without_stock_route_is_not_trusted(self):
        self.dns(internal=["10.254.30.102"])
        fake = FakePost(cloudflare=http_response(404, '{"error": "No encontrado"}'), supabase=relay_ok())
        response, _kind, _message, _detail = self.send(fake)
        self.assertEqual(self.manager.last_sync_route, ROUTE_SUPABASE)

    def test_no_internet_retries_every_route(self):
        self.dns(fails=True)
        down = requests.exceptions.ConnectionError("sin red")
        fake = FakePost(cloudflare=down, supabase=down)
        response, kind, message, detail = self.send(fake)
        self.assertIsNone(response)
        self.assertEqual(self.waits.call_count, 1)  # 2 intentos
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_SUPABASE] * 2)
        self.assertEqual(self.manager._direct_blocked_until, 0.0)

    def test_without_key_relays_are_not_asked(self):
        self.dns(internal=["10.254.30.102"])
        self.manager.clave_envio = ""
        fake = FakePost(google=refused())
        response, kind, _message, detail = self.send(fake)
        self.assertIsNone(response)
        self.assertEqual(kind, "relay-rejected")
        self.assertEqual(fake.routes(), [ROUTE_DIRECT])
        self.assertIn("clave de envío", detail)
        self.waits.assert_not_called()

    def test_internal_dns_that_works_is_used_when_relays_fail(self):
        # Red con un proxy interno que sí lleva a Google y sin salida a los respaldos.
        self.dns(internal=["10.0.0.5"])
        down = requests.exceptions.ConnectionError("bloqueado")
        fake = FakePost(cloudflare=down, supabase=down, google=http_response())
        response, kind, _message, _detail = self.send(fake)
        self.assertEqual(kind, "")
        self.assertEqual(fake.routes(), [ROUTE_CLOUDFLARE, ROUTE_SUPABASE, ROUTE_DIRECT])
        self.assertEqual(self.manager.last_sync_route, ROUTE_DIRECT)

    def test_google_error_through_cloudflare_tries_supabase(self):
        self.dns(internal=["10.254.30.102"])
        google_busy = http_response(503, "Service Unavailable", {"X-Relay": "ok"})
        fake = FakePost(cloudflare=google_busy, supabase=relay_ok())
        response, _kind, _message, _detail = self.send(fake)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.last_sync_route, ROUTE_SUPABASE)

    def test_google_error_on_both_relays_returns_googles_answer(self):
        self.dns(internal=["10.254.30.102"])
        google_busy = http_response(503, "Service Unavailable", {"X-Relay": "ok"})
        fake = FakePost(cloudflare=google_busy, supabase=http_response(500, "Error", {"X-Relay": "ok"}))
        response, kind, _message, _detail = self.send(fake)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(kind, "")
        self.assertEqual(self.manager.last_sync_route, ROUTE_CLOUDFLARE)

    def test_failure_logs_never_show_secrets(self):
        self.dns(internal=[])
        fake = FakePost(google=tls_reset(), cloudflare=tls_reset(), supabase=tls_reset())
        self.send(fake)
        joined = "\n".join(self.lines)
        self.assertNotIn("K7QM", joined)
        self.assertNotIn("AKfycbPRUEBA", joined)
        self.assertNotIn("win-abc&", joined)


if __name__ == "__main__":
    unittest.main()
