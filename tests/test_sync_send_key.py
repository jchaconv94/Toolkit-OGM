import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import sismed_sync  # noqa: E402
import sync_device_id  # noqa: E402
import sismed_version  # noqa: E402
from sismed_sync import SismedSyncManager  # noqa: E402


class SendKeyParamsTests(unittest.TestCase):
    def setUp(self):
        sync_device_id.reset_cache()

    def _manager(self, clave=""):
        manager = SismedSyncManager()
        manager.clave_envio = clave
        manager.omitir_stock_cero = False
        return manager

    def test_sends_key_equipment_name_and_device_id(self):
        manager = self._manager("030s05-k7qm-4xpa-93rd")
        with patch.object(sismed_sync.socket, "gethostname", return_value="PC-ALMACEN 01"), \
                patch.object(sismed_sync, "get_device_id", return_value="win-abc"):
            params = manager._request_params()
        self.assertEqual(params, {"equipo": "PC-ALMACEN01", "equipo_id": "win-abc", "clave": "030S05-K7QM-4XPA-93RD"})

    def test_without_key_sends_no_clave(self):
        manager = self._manager("")
        with patch.object(sismed_sync.socket, "gethostname", return_value="PC1"), \
                patch.object(sismed_sync, "get_device_id", return_value="win-abc"):
            params = manager._request_params()
        self.assertNotIn("clave", params)
        self.assertEqual(params["equipo_id"], "win-abc")

    def test_several_keys_are_normalized(self):
        manager = self._manager(" 06519-AAAA-BBBB-CCCC ;\n030S05-DDDD-EEEE-FFFF , ")
        self.assertEqual(manager._clave_envio_normalizada(), "06519-AAAA-BBBB-CCCC,030S05-DDDD-EEEE-FFFF")

    def test_log_summary_never_shows_the_secret_part(self):
        manager = self._manager("06519-K7QM-4XPA-93RD")
        resumen = manager._clave_envio_resumen()
        self.assertEqual(resumen, "06519")
        self.assertNotIn("K7QM", resumen)


class SendKeyBlockTests(unittest.TestCase):
    def _response(self, text):
        return SimpleNamespace(text=text, status_code=200)

    def test_reads_blocked_codes_and_reasons(self):
        bloqueos = SismedSyncManager._send_key_blocks(self._response("OK: 0 | BLOQUEADO: 030S05=OTRO_EQUIPO,06519=SIN_CLAVE"))
        self.assertEqual(bloqueos, [("030S05", "OTRO_EQUIPO"), ("06519", "SIN_CLAVE")])

    def test_plain_ok_is_not_blocked(self):
        self.assertEqual(SismedSyncManager._send_key_blocks(self._response("OK: 489")), [])

    def test_message_explains_what_to_do(self):
        message = SismedSyncManager()._send_key_block_message([("030S05", "OTRO_EQUIPO")])
        self.assertIn("030S05: el establecimiento está vinculado a otra PC", message)
        self.assertIn("Claves de envío", message)

    def test_unverified_reason_is_explained(self):
        message = SismedSyncManager()._send_key_block_message([("030S05", "SIN_VERIFICAR")])
        self.assertIn("no se pudo consultar la clave", message)


class DeviceIdTests(unittest.TestCase):
    def setUp(self):
        sync_device_id.reset_cache()

    def tearDown(self):
        sync_device_id.reset_cache()

    def test_same_machine_guid_gives_same_id_and_hides_it(self):
        with patch.object(sync_device_id, "_windows_machine_guid", return_value="1234-GUID"):
            first = sync_device_id.get_device_id()
            sync_device_id.reset_cache()
            second = sync_device_id.get_device_id()
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("win-"))
        self.assertNotIn("1234", first)
        self.assertEqual(len(first), 36)

    def test_other_machine_gets_other_id(self):
        with patch.object(sync_device_id, "_windows_machine_guid", return_value="PC-A"):
            a = sync_device_id.get_device_id()
        sync_device_id.reset_cache()
        with patch.object(sync_device_id, "_windows_machine_guid", return_value="PC-B"):
            b = sync_device_id.get_device_id()
        self.assertNotEqual(a, b)

    def test_without_windows_uses_a_saved_random_id(self):
        store = {}
        with patch.object(sync_device_id, "_windows_machine_guid", return_value=""), \
                patch.object(sync_device_id, "cfg_get", side_effect=store.get), \
                patch.object(sync_device_id, "cfg_set", side_effect=store.__setitem__):
            first = sync_device_id.get_device_id()
            sync_device_id.reset_cache()
            second = sync_device_id.get_device_id()
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("cfg-"))
        self.assertIn("sync_device_fallback_id", store)


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = str(data)

    def json(self):
        return self._data


class SendKeyCheckerTests(unittest.TestCase):
    def setUp(self):
        import send_key_check
        self.mod = send_key_check
        self.store = {}
        self.patches = [
            patch.object(send_key_check, "supabase_public_key", return_value="sb_publishable_x"),
            patch.object(send_key_check, "cfg_get", side_effect=self.store.get),
            patch.object(send_key_check, "cfg_set", side_effect=self.store.__setitem__),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _check(self, respuesta, clave="030S05-K7QM-4XPA-93RD"):
        with patch.object(self.mod.requests, "post", side_effect=respuesta) as post:
            result = self.mod.SendKeyChecker().check({"030S05": 14}, clave, "win-A", "PC-ALMACEN")
        return result, post

    def test_without_public_key_nothing_is_checked(self):
        with patch.object(self.mod, "supabase_public_key", return_value=""), \
                patch.object(self.mod.requests, "post") as post:
            result = self.mod.SendKeyChecker().check({"030S05": 14}, "", "win-A", "PC")
        self.assertEqual(result, {"030S05": (True, "")})
        post.assert_not_called()

    def test_sends_code_key_and_device_with_only_the_apikey_header(self):
        result, post = self._check([_Resp(200, {"permitido": True, "protegido": True, "motivo": "ACEPTADO"})])
        self.assertEqual(result, {"030S05": (True, "ACEPTADO")})
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"apikey": "sb_publishable_x", "Content-Type": "application/json"})
        self.assertEqual(kwargs["json"]["p_key"], "030S05-K7QM-4XPA-93RD")
        self.assertEqual(kwargs["json"]["p_device_id"], "win-A")
        self.assertEqual(kwargs["json"]["p_rows"], 14)

    def test_sends_the_toolkit_version(self):
        with patch.object(self.mod, "get_current_version", return_value="2.2.0"):
            _, post = self._check([_Resp(200, {"permitido": True, "protegido": False})])
        self.assertEqual(post.call_args.kwargs["json"]["p_version"], "2.2.0")

    def test_falls_back_when_the_database_lacks_the_version_function(self):
        with patch.object(self.mod, "get_current_version", return_value="2.2.0"):
            result, post = self._check([_Resp(404, {"code": "PGRST202"}), _Resp(200, {"permitido": False, "protegido": True, "motivo": "SIN_CLAVE"})])
        self.assertEqual(result, {"030S05": (False, "SIN_CLAVE")})
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("p_version", post.call_args_list[1].kwargs["json"])

    def test_sends_the_sismed_version(self):
        with patch.object(self.mod, "get_current_version", return_value="2.2.1"), \
                patch.object(self.mod.requests, "post", return_value=_Resp(200, {"permitido": True, "protegido": False})) as post:
            self.mod.SendKeyChecker().check({"030S05": 14}, "", "win-A", "PC", sismed="V2.5.3 vf 12/01/2026")
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["p_version"], body["p_sismed"]), ("2.2.1", "V2.5.3 vf 12/01/2026"))

    def test_without_the_sismed_function_retries_once_and_remembers(self):
        respuestas = [_Resp(404, {}), _Resp(200, {"permitido": True, "protegido": False}),
                      _Resp(200, {"permitido": True, "protegido": False})]
        with patch.object(self.mod, "get_current_version", return_value="2.2.1"), \
                patch.object(self.mod.requests, "post", side_effect=respuestas) as post:
            self.mod.SendKeyChecker().check({"030S05": 14, "06519": 2}, "", "win-A", "PC", sismed="V2.5.3")
        enviados = [c.kwargs["json"] for c in post.call_args_list]
        self.assertEqual(len(enviados), 3)
        self.assertIn("p_sismed", enviados[0])
        self.assertNotIn("p_sismed", enviados[1])
        self.assertEqual(enviados[1]["p_version"], "2.2.1")
        # El segundo establecimiento ya no repite el intento.
        self.assertNotIn("p_sismed", enviados[2])

    def test_without_both_functions_falls_back_to_the_simple_query(self):
        respuestas = [_Resp(404, {}), _Resp(404, {}), _Resp(200, {"permitido": False, "protegido": True, "motivo": "SIN_CLAVE"})]
        with patch.object(self.mod, "get_current_version", return_value="2.2.1"), \
                patch.object(self.mod.requests, "post", side_effect=respuestas) as post:
            result = self.mod.SendKeyChecker().check({"030S05": 14}, "", "win-A", "PC", sismed="V2.5.3")
        self.assertEqual(result, {"030S05": (False, "SIN_CLAVE")})
        self.assertEqual(set(post.call_args_list[2].kwargs["json"]), {"p_code", "p_key", "p_device_id", "p_device_name", "p_rows"})

    def test_blocked_by_the_web(self):
        result, _ = self._check([_Resp(200, {"permitido": False, "protegido": True, "motivo": "OTRO_EQUIPO"})])
        self.assertEqual(result, {"030S05": (False, "OTRO_EQUIPO")})

    def test_web_down_only_the_last_approved_pc_and_key_pass(self):
        self._check([_Resp(200, {"permitido": True, "protegido": True, "motivo": "ACEPTADO"})])
        result, _ = self._check(ConnectionError("sin red"))
        self.assertEqual(result, {"030S05": (True, "ACEPTADO_SIN_VERIFICAR")})
        result, _ = self._check(ConnectionError("sin red"), clave="030S05-OTRA-CLAV-EXXX")
        self.assertEqual(result, {"030S05": (False, "SIN_VERIFICAR")})

    def test_web_down_after_a_block_stays_blocked(self):
        self._check([_Resp(200, {"permitido": False, "protegido": True, "motivo": "SIN_CLAVE"})])
        result, _ = self._check(ConnectionError("sin red"), clave="")
        self.assertEqual(result, {"030S05": (False, "SIN_VERIFICAR")})

    def test_web_down_without_history_sends_as_always(self):
        result, _ = self._check(ConnectionError("sin red"))
        self.assertEqual(result, {"030S05": (True, "")})

    def test_unprotected_forgets_the_cache(self):
        self._check([_Resp(200, {"permitido": True, "protegido": True, "motivo": "ACEPTADO"})])
        self._check([_Resp(200, {"permitido": True, "protegido": False})])
        result, _ = self._check(ConnectionError("sin red"), clave="")
        self.assertEqual(result, {"030S05": (True, "")})


def _write_dbf(path, fields, records):
    """DBF mínimo (dBase III) solo con campos de texto."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(size for _name, size in fields)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<BBBBIHH20x", 0x03, 126, 9, 30, len(records), header_len, record_len))
        for name, size in fields:
            fh.write(struct.pack("<11sc4xB15x", name.encode("ascii"), b"C", size))
        fh.write(b"\r")
        for record in records:
            fh.write(b" ")
            for (name, size), value in zip(fields, record):
                fh.write(value.encode("cp1252").ljust(size)[:size])
        fh.write(b"\x1a")


class SismedVersionTests(unittest.TestCase):
    FIELDS = [("CFGCODMOD", 3), ("CFGCODIGO", 2), ("CFGDESCRIP", 40), ("CFGVALACT", 99)]

    def _base(self, records):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "DATOS"))
        _write_dbf(os.path.join(tmp.name, "DATOS", "MCONFIG.DBF"), self.FIELDS, records)
        return tmp.name

    def test_reads_only_the_sis_ab_row(self):
        base = self._base([
            ("HTP", "A5", "http_password ACTUALIZA-STOCK", "secreto"),
            ("SIS", "BD", "SERVICIO RENIEC EN LINEA S/N", "S"),
            ("SIS", "AB", "FECHA ULTIMA VERSION SISMED", "V2.5.3 vf 12/01/2026"),
        ])
        self.assertEqual(sismed_version.read_sismed_version(base), "V2.5.3 vf 12/01/2026")

    def test_missing_table_or_row_gives_empty(self):
        self.assertEqual(sismed_version.read_sismed_version(tempfile.gettempdir() + "/no-existe"), "")
        base = self._base([("SIS", "BD", "SERVICIO RENIEC", "S")])
        self.assertEqual(sismed_version.read_sismed_version(base), "")

    def test_sync_sends_it_with_the_key_check(self):
        base = self._base([("SIS", "AB", "FECHA ULTIMA VERSION SISMED", "V2.5.3 vf 12/01/2026")])
        manager = SismedSyncManager()
        manager.base_dir = base
        manager._last_reported_almcods = []
        with patch.object(sismed_sync.SendKeyChecker, "check", return_value={"030S05": (True, "")}) as check, \
                patch.object(sismed_sync, "get_device_id", return_value="win-A"):
            manager._apply_send_key_check([{"almcod": "030S0501"}])
        self.assertEqual(check.call_args.kwargs["sismed"], "V2.5.3 vf 12/01/2026")


class ApplySendKeyCheckTests(unittest.TestCase):
    def _manager(self):
        manager = SismedSyncManager()
        manager._last_reported_almcods = ["030S0501", "06519F0101"]
        manager._last_reported_facility_codes = ["030S05", "06519"]
        return manager

    def test_blocked_facility_is_removed_from_payload_and_clear_list(self):
        manager = self._manager()
        payload = [{"almcod": "030S0501"}] * 14 + [{"almcod": "06519F0101"}] * 2
        verdict = {"030S05": (False, "SIN_CLAVE"), "06519": (True, "")}
        with patch.object(sismed_sync.SendKeyChecker, "check", return_value=verdict) as check, \
                patch.object(sismed_sync, "get_device_id", return_value="win-B"):
            restante, bloqueos = manager._apply_send_key_check(payload)
        self.assertEqual(check.call_args.args[0], {"030S05": 14, "06519": 2})
        self.assertEqual(len(restante), 2)
        self.assertEqual(bloqueos, [("030S05", "SIN_CLAVE")])
        self.assertEqual(manager._last_reported_almcods, ["06519F0101"])
        self.assertEqual(manager._last_reported_facility_codes, ["06519"])

    def test_nothing_blocked_keeps_everything(self):
        manager = self._manager()
        payload = [{"almcod": "030S0501"}]
        with patch.object(sismed_sync.SendKeyChecker, "check", return_value={"030S05": (True, ""), "06519": (True, "")}), \
                patch.object(sismed_sync, "get_device_id", return_value="win-A"):
            restante, bloqueos = manager._apply_send_key_check(payload)
        self.assertEqual((restante, bloqueos), (payload, []))



if __name__ == "__main__":
    unittest.main()
