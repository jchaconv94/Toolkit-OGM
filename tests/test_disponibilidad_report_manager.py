import sys
import unittest
from pathlib import Path


TOOLKIT_DIR = Path(__file__).resolve().parents[1] / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from disponibilidad_report_manager import DisponibilidadReportManager


class DisponibilidadReportManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = DisponibilidadReportManager("C:\\SISMED")

    def test_codigo_de_ipress_abarca_sus_farmacias(self):
        lista = {"06502"}
        for codigo in ("06502", "06502F01", "06502F06", "06502f12"):
            self.assertTrue(DisponibilidadReportManager._en_lista(codigo, lista), codigo)
        self.assertFalse(DisponibilidadReportManager._en_lista("06503F01", lista))
        self.assertFalse(DisponibilidadReportManager._en_lista("065021", lista))

    def test_farmacia_con_codigo_completo_quita_solo_esa(self):
        lista = {"06502F02"}
        self.assertTrue(DisponibilidadReportManager._en_lista("06502F02", lista))
        self.assertFalse(DisponibilidadReportManager._en_lista("06502F01", lista))
        self.assertFalse(DisponibilidadReportManager._en_lista("06502", lista))

    def test_reingreso_is_not_counted_as_consumption(self):
        record = {
            "VENTA": 1,
            "SIS": 2,
            "INTERSAN": 3,
            "REINGRE": 50,
            "SOAT": 4,
            "CREDHOSP": 5,
            "OTR_CONV": 6,
        }

        self.assertEqual(self.manager._calculate_consumption(record), 21)

    def test_exonerado_is_counted_as_consumption(self):
        record = {"VENTA": 1, "EXO": 7, "REINGRE": 50}

        self.assertEqual(self.manager._calculate_consumption(record), 8)

    def test_reported_august_case_totals_32_without_reingreso(self):
        records = [
            {"INTERSAN": 27},
            {"INTERSAN": 1},
            {"REINGRE": 50, "INTERSAN": 4},
        ]

        total = sum(self.manager._calculate_consumption(record) for record in records)

        self.assertEqual(total, 32)


if __name__ == "__main__":
    unittest.main()
