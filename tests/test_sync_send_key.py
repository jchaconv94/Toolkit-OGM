import sys
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

    def test_supabase_sync_does_not_send_key_or_device(self):
        from sismed_sync_supabase import SismedSyncSupabaseManager

        manager = SismedSyncSupabaseManager()
        manager.clave_envio = "06519-K7QM-4XPA-93RD"
        with patch.object(sismed_sync, "get_device_id", return_value="win-abc"):
            params = manager._request_params()
        for key in ("clave", "equipo", "equipo_id"):
            self.assertNotIn(key, params)


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


if __name__ == "__main__":
    unittest.main()
