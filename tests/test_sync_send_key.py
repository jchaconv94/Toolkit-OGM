import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import sismed_sync  # noqa: E402
from sismed_sync import SismedSyncManager  # noqa: E402


class SendKeyParamsTests(unittest.TestCase):
    def _manager(self, clave=""):
        manager = SismedSyncManager()
        manager.clave_envio = clave
        manager.omitir_stock_cero = False
        return manager

    def test_sends_equipment_name_and_key(self):
        manager = self._manager("06519-3f9a2c7d41b8e605")
        with patch.object(sismed_sync.socket, "gethostname", return_value="PC-FARMACIA 01"):
            params = manager._request_params()
        self.assertEqual(params["equipo"], "PC-FARMACIA01")
        self.assertEqual(params["clave"], "06519-3f9a2c7d41b8e605")

    def test_without_key_sends_only_equipment_name(self):
        manager = self._manager("")
        with patch.object(sismed_sync.socket, "gethostname", return_value="PC1"):
            params = manager._request_params()
        self.assertEqual(params, {"equipo": "PC1"})

    def test_several_keys_are_normalized(self):
        manager = self._manager(" 06519-aaaa ;\n030S05-bbbb , ")
        self.assertEqual(manager._clave_envio_normalizada(), "06519-aaaa,030S05-bbbb")

    def test_log_summary_never_shows_the_secret_part(self):
        manager = self._manager("06519-3f9a2c7d41b8e605")
        resumen = manager._clave_envio_resumen()
        self.assertEqual(resumen, "06519")
        self.assertNotIn("3f9a", resumen)

    def test_supabase_sync_does_not_send_the_key(self):
        from sismed_sync_supabase import SismedSyncSupabaseManager

        manager = SismedSyncSupabaseManager()
        manager.clave_envio = "06519-3f9a2c7d41b8e605"
        params = manager._request_params()
        self.assertNotIn("clave", params)
        self.assertNotIn("equipo", params)


if __name__ == "__main__":
    unittest.main()
