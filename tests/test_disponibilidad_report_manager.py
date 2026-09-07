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
