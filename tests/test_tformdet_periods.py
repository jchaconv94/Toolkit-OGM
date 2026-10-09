import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from tformdet_periods import clamp_months, last_months  # noqa: E402

HOY = date(2026, 10, 9)


class LastMonthsTests(unittest.TestCase):
    def test_last_12_months_without_current(self):
        r = last_months(12, False, HOY)
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202510", "202609"))
        self.assertEqual(r.description(), "De Octubre 2025 a Septiembre 2026 · 12 meses")

    def test_last_12_months_with_current(self):
        r = last_months(12, True, HOY)
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202511", "202610"))
        self.assertTrue(r.includes_current)

    def test_last_24_months(self):
        r = last_months(24, False, HOY)
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202410", "202609"))

    def test_one_month_is_the_previous_or_the_current(self):
        self.assertEqual(last_months(1, False, HOY).periodo_ini, "202609")
        r = last_months(1, True, HOY)
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202610", "202610"))
        self.assertEqual(r.description(), "Octubre 2026 · 1 mes")

    def test_crosses_year_in_january(self):
        r = last_months(3, False, date(2027, 1, 15))
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202610", "202612"))
        r = last_months(1, False, date(2027, 1, 1))
        self.assertEqual(r.periodo_fin, "202612")

    def test_december_with_current(self):
        r = last_months(12, True, date(2026, 12, 31))
        self.assertEqual((r.periodo_ini, r.periodo_fin), ("202601", "202612"))

    def test_clamp(self):
        self.assertEqual(clamp_months("24"), 24)
        self.assertEqual(clamp_months(" 6 "), 6)
        self.assertEqual(clamp_months("0"), 1)
        self.assertEqual(clamp_months("-5"), 1)
        self.assertEqual(clamp_months("500"), 120)
        self.assertEqual(clamp_months("doce"), 1)
        self.assertEqual(clamp_months(None), 1)
        self.assertEqual(last_months("abc", False, HOY).months, 1)


if __name__ == "__main__":
    unittest.main()
