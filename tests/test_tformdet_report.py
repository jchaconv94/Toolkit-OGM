import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

TOOLKIT_DIR = Path(__file__).resolve().parents[1] / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from tformdet_report import ADDITIONAL_TFORMDET_COLUMNS, PRODUCT_CLASSIFICATION_COLUMNS, TformdetManager


class TformdetReportTests(unittest.TestCase):
    def test_additional_movement_columns_are_exported_after_total(self):
        extra_values = {
            name: index * 10
            for index, name in enumerate(ADDITIONAL_TFORMDET_COLUMNS, start=1)
        }
        tformdet_record = {
            "ANNOMES": "202601",
            "CODIGO_PRE": "030S05",
            "CODIGO_MED": "00123",
            "TOTAL": 75,
            **extra_values,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "DATOS"
            data_dir.mkdir()
            for name in ("TFORMDET.DBF", "MALMACEN.DBF", "MPRODUCTO.DBF"):
                (data_dir / name).touch()

            output_path = Path(temp_dir) / "report.xlsx"

            def fake_open_dbf(path):
                filename = Path(path).name.upper()
                if filename == "MALMACEN.DBF":
                    return [{"ALMCOD": "030S05", "ALMDES": "ESTABLECIMIENTO"}]
                if filename == "MPRODUCTO.DBF":
                    return [{"MEDCOD": "00123", "MEDNOM": "PRODUCTO"}]
                return [tformdet_record]

            with (
                patch("tformdet_report.snapshot_dbf", side_effect=lambda path, _directory: path),
                patch("tformdet_report.open_dbf", side_effect=fake_open_dbf),
            ):
                success = TformdetManager(temp_dir, log_callback=lambda _message: None).generate_report(
                    "202601",
                    "202601",
                    str(output_path),
                )

            self.assertTrue(success)
            exported = pd.read_excel(output_path)
            columns = list(exported.columns)
            start = columns.index("TOTAL") + 1
            self.assertEqual(
                columns[start:start + len(ADDITIONAL_TFORMDET_COLUMNS)],
                list(ADDITIONAL_TFORMDET_COLUMNS),
            )
            self.assertEqual(exported.loc[0, "TOTAL"], 75)
            for name, expected in extra_values.items():
                self.assertEqual(exported.loc[0, name], expected)


    def test_product_classification_is_exported_at_the_end(self):
        records = [
            {"ANNOMES": "202601", "CODIGO_PRE": "06503", "CODIGO_MED": "00143", "STOCK_FIN": 10},
            {"ANNOMES": "202602", "CODIGO_PRE": "06503", "CODIGO_MED": "00999", "STOCK_FIN": 5},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "DATOS"
            data_dir.mkdir()
            for name in ("TFORMDET.DBF", "MALMACEN.DBF", "MPRODUCTO.DBF", "MMEDICAM.DBF"):
                (data_dir / name).touch()
            output_path = Path(temp_dir) / "report.xlsx"

            def fake_open_dbf(path):
                filename = Path(path).name.upper()
                if filename == "MALMACEN.DBF":
                    return [{"ALMCOD": "06503", "ALMDES": "P.S. BUENOS AIRES"}]
                if filename == "MPRODUCTO.DBF":
                    return [
                        {"MEDCOD": "00143", "MEDNOM": "ACICLOVIR", "MEDEST": "S"},
                        {"MEDCOD": "00999", "MEDNOM": "OTRO", "MEDTIP": "I", "MEDPET": "_", "MEDEST": "_", "MEDFF": "UNIDAD"},
                    ]
                if filename == "MMEDICAM.DBF":
                    # MMEDICAM manda; lo que no trae se toma de MPRODUCTO.
                    return [{"MEDCOD": "00143", "MEDTIP": "M", "MEDPET": "P", "MEDEST": "", "MEDFF": "TABLET"}]
                return records

            with (
                patch("tformdet_report.snapshot_dbf", side_effect=lambda path, _directory: path),
                patch("tformdet_report.open_dbf", side_effect=fake_open_dbf),
            ):
                success = TformdetManager(temp_dir, log_callback=lambda _message: None).generate_report(
                    "202601", "202602", str(output_path),
                )

            self.assertTrue(success)
            exported = pd.read_excel(output_path, dtype=str)
            self.assertEqual(list(exported.columns[-len(PRODUCT_CLASSIFICATION_COLUMNS):]), list(PRODUCT_CLASSIFICATION_COLUMNS))
            self.assertEqual(exported.columns[0], "ANNOMES")
            first = exported.iloc[0]
            self.assertEqual((first["MEDFF"], first["MEDTIP"], first["MEDPET"], first["MEDEST"]), ("TABLET", "M", "P", "S"))
            second = exported.iloc[1]
            self.assertEqual((second["MEDTIP"], second["MEDPET"], second["MEDEST"]), ("I", "_", "_"))


if __name__ == "__main__":
    unittest.main()
