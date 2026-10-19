import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl

TOOLKIT_DIR = Path(__file__).resolve().parents[1] / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import ici_data
import ici_pdf
from ici_excel import COLS, Page, build_workbook, row_height, column_span, signature_blocks, date_in_words, reference_group, write_reports

MONTH = "202608"


def tformdet(farmacia, code, lote, precio=1.0, **values):
    """Fila de TFORMDET que cuadra: TOTAL y STOCK_FIN salen de las demás cifras."""
    rec = {"ANNOMES": MONTH, "CODIGO_PRE": farmacia, "CODIGO_MED": code, "MEDLOTE": lote,
           "MEDREGSAN": "RS1", "FEC_EXP": date(2027, 12, 31), "TIPSUM2": "CI", "FFINAN": "DYT",
           "PRECIO": precio, **values}
    salidas = [*ici_data.CONSUMO, "DEVOL", "VENCIDO", "MERMA", "SAL_REGULA", "SAL_CONINS", *ici_data.OTHER_OUT]
    rec["TOTAL"] = sum(rec.get(n, 0) for n in salidas)
    rec["STOCK_FIN"] = sum(rec.get(n, 0) for n in ("SALDO", "INGRE", "REINGRE", "ING_REGULA")) - rec["TOTAL"]
    return rec


def head(tipo, numero, concepto, origen, destino, dia=10, doc=("04", "001-1"), situa="1", refe=""):
    return {"MOVCODITIP": tipo, "MOVNUMERO": numero, "CCTCODIGO": concepto, "ALMORGVIR": origen,
            "ALMDSTVIR": destino, "MOVTIPODCO": doc[0], "MOVNUMEDCO": doc[1], "MOVSITUA": situa,
            "MOVFECHREG": date(2026, 8, dia), "MOVREFE": refe}


def detail(tipo, numero, code, lote, qty, total=None, vence=date(2027, 12, 31), regsan="RS1", tipsum="CI", ffinan="DYT"):
    return {"MOVCODITIP": tipo, "MOVNUMERO": numero, "MEDCOD": code, "MEDLOTE": lote, "MOVCANTID": qty,
            "MOVTOTAL": qty if total is None else total, "MEDFECHVTO": vence, "MEDREGSAN": regsan,
            "TIPSUM": tipsum, "FFINAN": ffinan}


def month(tformdet_rows, heads=None, details=None, tformato=None, links=None, ventas=None):
    tables = {
        "TFORMDET": tformdet_rows,
        "TFORMATO": tformato or [],
        "MALMACEN": [{"ALMCOD": "06502", "ALMDES": "HOSPITAL"}, {"ALMCOD": "06502F01", "ALMDES": "FARMACIA"},
                     {"ALMCOD": "06502F02", "ALMDES": "EMERGENCIA"}, {"ALMCOD": "030A00", "ALMDES": "ALMACEN UNGET"}],
        "MPRODUCTO": [{"MEDCOD": "001", "MEDNOM": "PARACETAMOL", "MEDPRES": "500 mg", "MEDFF": "TABLET"},
                      {"MEDCOD": "002", "MEDNOM": "AMOXICILINA", "MEDPRES": "500 mg", "MEDFF": "TABLET"}],
    }
    if heads is not None:
        tables["TMOVIM"] = heads
        tables["TMOVIMDET"] = details or []
        tables["TMOVIMTRF"] = [{"MOVNUMESAL": s, "MOVNUMEING": e} for s, e in (links or [])]
    if ventas is not None:
        tables["TVENTA"] = ventas
    return ici_data.load_month(lambda name: tables.get(name), MONTH, log=lambda _m: None)


class IciDataTests(unittest.TestCase):
    def test_otras_salidas_keep_the_sismed_total(self):
        rec = tformdet("06502F01", "001", "L1", SALDO=100, VENTA=10, OTRAS_SAL=5, DISTRI=2, SAL_REGULA=3)
        row = ici_data.normalize_row(rec, {})
        self.assertEqual(row["OTRAS"], 7)
        self.assertEqual(ici_data.balance_errors([row]), 0)
        # Si el ajuste ya viene dentro de OTRAS_SAL (no aparte en el total), no se cuenta dos veces.
        inside = {**rec, "TOTAL": rec["TOTAL"] - 3, "STOCK_FIN": rec["STOCK_FIN"] + 3}
        row = ici_data.normalize_row(inside, {})
        self.assertEqual(row["OTRAS"], 4)
        self.assertEqual(ici_data.balance_errors([row]), 0)

    def test_groups_pharmacies_by_establishment_with_recetas(self):
        m = month(
            [tformdet("06502F01", "001", "L1", SALDO=10, SIS=2), tformdet("06502F02", "001", "L1", SALDO=5, VENTA=1),
             tformdet("06502F01", "999", "X", ANNOMES="202607", SALDO=1)],
            tformato=[{"ANNOMES": MONTH, "CODIGO_PRE": "06502F01", "TIPSUM": "C", "REC_SIS": 7, "REC_OTRCON": 2},
                      {"ANNOMES": MONTH, "CODIGO_PRE": "06502F01", "TIPSUM": "D", "REC_SIS": 1},
                      {"ANNOMES": MONTH, "CODIGO_PRE": "06502F02", "TIPSUM": "C", "REC_VTAS": 4}],
        )
        self.assertEqual(len(m.establishments), 1)
        est = m.establishments[0]
        self.assertEqual((est.code, est.name), ("06502", "HOSPITAL"))
        self.assertEqual([p.code for p in est.pharmacies], ["06502F01", "06502F02"])
        f01 = est.pharmacies[0]
        self.assertEqual(f01.recetas[ici_data.CONSUMO.index("SIS")], 8)
        self.assertEqual(f01.recetas[ici_data.CONSUMO.index("OTR_CONV")], 2)
        self.assertEqual(f01.rows[0]["DESC"], "PARACETAMOL 500 mg")
        self.assertEqual(f01.rows[0]["MEDFF"], "TABLET")
        report = ici_data.consolidated_report(m, est)
        self.assertEqual(report.recetas[ici_data.CONSUMO.index("VENTA")], 4)
        self.assertEqual(report.ficha["Farmacias"], "F01 y F02 (consolidado)")

    def test_concept_35_goes_to_vencidos(self):
        m = month(
            [tformdet("06502F01", "001", "L1", SALDO=50, DEVOL=30)],
            heads=[head("S", "1", "35", "06502F0101", "030A0001"), head("S", "2", "07", "06502F0101", "030A0001")],
            details=[detail("S", "1", "001", "L1", 12), detail("S", "2", "001", "L1", 18)],
        )
        row = m.establishments[0].pharmacies[0].rows[0]
        self.assertEqual((row["DEVOL"], row["VENCIDO"]), (18, 12))
        self.assertEqual(ici_data.balance_errors([row]), 0)

    def test_concept_35_already_in_vencidos_is_not_moved_twice(self):
        m = month(
            [tformdet("06502F01", "001", "L1", SALDO=50, DEVOL=5, VENCIDO=12)],
            heads=[head("S", "1", "35", "06502F0101", "030A0001")],
            details=[detail("S", "1", "001", "L1", 12)],
        )
        row = m.establishments[0].pharmacies[0].rows[0]
        self.assertEqual((row["DEVOL"], row["VENCIDO"]), (5, 12))

    def test_cancelled_and_other_month_movements_are_ignored(self):
        m = month(
            [tformdet("06502F01", "001", "L1", SALDO=50, DEVOL=30)],
            heads=[head("S", "1", "35", "06502F0101", "030A0001", situa="0"),
                   {**head("S", "2", "35", "06502F0101", "030A0001"), "MOVFECHREG": date(2026, 9, 1)}],
            details=[detail("S", "1", "001", "L1", 10), detail("S", "2", "001", "L1", 10)],
        )
        self.assertEqual(m.establishments[0].pharmacies[0].rows[0]["VENCIDO"], 0)

    def test_consolidated_nets_deliveries_between_pharmacies(self):
        rows = [
            tformdet("06502F01", "001", "L1", SALDO=100, INGRE=50, DEVOL=40, SIS=10),
            tformdet("06502F02", "001", "L1", REINGRE=30, VENTA=20),
        ]
        heads = [
            head("E", "9", "04", "030A0001", "06502F0101", dia=2, doc=("03", "G-100")),
            head("S", "10", "07", "06502F0101", "06502F0201", dia=5),
            head("E", "11", "07", "06502F0101", "06502F0201", dia=5),
            head("S", "12", "07", "06502F0101", "06502F0201", dia=31),   # llega en septiembre
        ]
        details = [detail("E", "9", "001", "L1", 50), detail("S", "10", "001", "L1", 30),
                   detail("E", "11", "001", "L1", 30), detail("S", "12", "001", "L1", 10)]
        m = month(rows, heads, details)
        est = m.establishments[0]
        report = ici_data.consolidated_report(m, est)
        self.assertEqual(len(report.rows), 1)
        row = report.rows[0]
        self.assertEqual((row["DEVOL"], row["REINGRE"]), (10, 0))
        self.assertEqual(row["STOCK_FIN"], 100 + 50 - 40 - 10 + 30 - 20)
        self.assertEqual(ici_data.balance_errors(report.rows), 0)
        self.assertAlmostEqual(report.internal_value, 30)
        self.assertAlmostEqual(report.in_transit, 10)
        self.assertEqual([g.doc_numero for g in report.guias], ["G-100"])
        # En la farmacia que recibe, la entrega de la F01 sí es una guía de ingreso.
        f02 = ici_data.pharmacy_report(m, est, est.pharmacies[1])
        self.assertEqual([g.numero for g in f02.guias], ["11"])
        self.assertEqual(f02.rows[0]["REINGRE"], 30)

    def test_without_tmovim_the_internal_delivery_is_estimated(self):
        m = month([tformdet("06502F01", "001", "L1", SALDO=100, DEVOL=40),
                   tformdet("06502F02", "001", "L1", REINGRE=40, VENTA=5)])
        report = ici_data.consolidated_report(m, m.establishments[0])
        self.assertTrue(report.internal_estimated)
        self.assertEqual((report.rows[0]["DEVOL"], report.rows[0]["REINGRE"]), (0, 0))
        self.assertEqual(ici_data.balance_errors(report.rows), 0)
        self.assertTrue(m.warnings)

    def test_lot_correction_stays_and_is_marked(self):
        rows = [tformdet("06502F01", "001", "L1", SALDO=20, DEVOL=20),
                tformdet("06502F01", "001", "L2", REINGRE=20)]
        heads = [head("S", "1", "07", "06502F0101", "06502F0101"), head("E", "2", "07", "06502F0101", "06502F0101")]
        details = [detail("S", "1", "001", "L1", 20), detail("E", "2", "001", "L2", 20)]
        m = month(rows, heads, details)
        est = m.establishments[0]
        for report in (ici_data.pharmacy_report(m, est, est.pharmacies[0]), ici_data.consolidated_report(m, est)):
            by_lot = {r["MEDLOTE"]: r for r in report.rows}
            self.assertEqual(by_lot["L1"]["DEVOL"], 20)
            self.assertEqual(by_lot["L2"]["REINGRE"], 20)
            self.assertIn("correccion", by_lot["L1"]["flags"])
            self.assertIn("correccion", by_lot["L2"]["flags"])
            # Una sola corrección: la salida y su reingreso juntos, con lo que cambió.
            self.assertEqual(len(report.corrections), 1)
            change = report.corrections[0].changes[0]
            self.assertEqual(change.fields, ["Lote"])
            self.assertEqual((change.before.lote, change.after.lote), ("L1", "L2"))
            self.assertEqual(report.guias, [])

    def test_correction_detected_by_what_changed(self):
        rows = [tformdet("06502F01", "001", "L1", SALDO=30, DEVOL=10, REINGRE=10),
                tformdet("06502F01", "002", "L5", SALDO=8, DEVOL=8),
                tformdet("06502F01", "009", "L5", REINGRE=8)]
        heads = [head("S", "10", "07", "06502F0101", "030A0001", doc=("04", "001-0000700")),
                 head("E", "11", "07", "030A0001", "06502F0101", doc=("04", "001-0000901")),
                 head("S", "12", "07", "06502F0101", "030A0001", doc=("04", "001-0000702")),
                 head("E", "13", "07", "030A0001", "06502F0101", doc=("04", "1-702"))]
        details = [detail("S", "10", "001", "L1", 10, vence=date(2026, 9, 30)),
                   detail("E", "11", "001", "L1", 10, vence=date(2027, 9, 30)),
                   detail("S", "12", "002", "L5", 8), detail("E", "13", "009", "L5", 8)]
        # La primera se enlaza por TMOVIMTRF; la segunda, por el mismo número de guía.
        m = month(rows, heads, details, links=[("10", "11")])
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        self.assertEqual([[ch.fields for ch in c.changes] for c in report.corrections], [[["Vencimiento"]], [["Código"]]])
        self.assertEqual(report.corrections[0].changes[0].after.describe(["Vencimiento"]), "Vencimiento 30/09/2027")
        self.assertEqual(report.guias, [])

    def test_recovered_products_are_not_corrections(self):
        # Producto recuperado: salió, sobró y volvió como reingreso, igual que salió.
        rows = [tformdet("06502F01", "001", "L1", SALDO=30, SAL_CONINS=10, REINGRE=4)]
        heads = [head("S", "20", "33", "06502F0101", "", dia=3),
                 head("E", "21", "07", "06502F0101", "06502F0101", dia=9, doc=("04", "260322"), refe="PRODUCTO RECUPERADO")]
        details = [detail("S", "20", "001", "L1", 10), detail("E", "21", "001", "L1", 4)]
        m = month(rows, heads, details)
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        self.assertEqual(report.corrections, [])
        self.assertEqual([g.doc_numero for g in report.guias], ["260322"])
        self.assertEqual(ici_data.entry_kind(report.guias[0]), "otro")
        cells = [c.value for row in build_workbook(report)[0]["Guías de ingreso"].iter_rows() for c in row if c.value]
        self.assertIn("GUÍA N° 260322  ·  09/08/2026", cells)
        self.assertIn("PARACETAMOL 500 mg", cells)

    def test_correction_sent_but_not_back_is_pending(self):
        rows = [tformdet("06502F01", "001", "L1", SALDO=30, DEVOL=10)]
        m = month(rows, [head("S", "30", "07", "06502F0101", "030A0001", refe="CORRECCION DE LOTE")],
                  [detail("S", "30", "001", "L1", 10)])
        est = m.establishments[0]
        corrections = ici_data.pharmacy_report(m, est, est.pharmacies[0]).corrections
        self.assertEqual(len(corrections), 1)
        self.assertIsNone(corrections[0].entrada)

    def test_daily_recetas_by_type(self):
        rows = [tformdet("06502F01", "001", "L1", SALDO=30, SIS=3, VENTA=1)]
        heads = [head("S", "40", "13", "06502F0101", "", dia=4), head("S", "41", "13", "06502F0101", "", dia=4),
                 head("S", "42", "10", "06502F0101", "", dia=5)]
        details = [detail("S", "40", "001", "L1", 2, 2.5), detail("S", "41", "001", "L1", 1, 1.25),
                   detail("S", "42", "001", "L1", 1, 1.25)]
        m = month(rows, heads, details)
        est = m.establishments[0]
        daily = {d.day: (counts, value) for d, counts, value, _ in ici_data.pharmacy_report(m, est, est.pharmacies[0]).recetas_diarias}
        self.assertEqual(len(daily), 31)
        self.assertEqual(daily[4][0][ici_data.CONSUMO.index("SIS")], 2)
        self.assertAlmostEqual(daily[4][1], 3.75)
        self.assertEqual(daily[5][0][ici_data.CONSUMO.index("VENTA")], 1)

    def test_consumption_values_come_from_the_sismed(self):
        # La venta valorizada es la del SISMED (TFORMATO.VTAS), no cantidad × precio del lote.
        m = month([tformdet("06502F01", "001", "L1", precio=2.0, SALDO=10, VENTA=3, SIS=2)],
                  tformato=[{"ANNOMES": MONTH, "CODIGO_PRE": "06502F01", "TIPSUM": "S", "REC_VTAS": 3,
                             "VTAS": 5.85, "SIS": 4.0}])
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        self.assertEqual(report.valores[ici_data.CONSUMO.index("VENTA")], 5.85)
        ws = build_workbook(report)[0]["ICI"]
        labels = {ws.cell(r, c).value: ws.cell(r, c + 3).value for r in range(5, 10) for c in (11, 17)}
        self.assertEqual(labels["Venta"], 5.85)
        self.assertTrue(str(labels["Consumo total"]).startswith("=9.85+SUMPRODUCT"))
        self.assertTrue(str(labels["Saldo anterior"]).startswith("=SUMPRODUCT"))

    def test_other_agreements_are_valued_by_lot(self):
        # Otros convenios no los graba el SISMED (TFORMATO.CON en 0): el consumo total no los pierde.
        m = month([tformdet("06502F01", "001", "L1", precio=2.0, SALDO=10, VENTA=3, OTR_CONV=2)],
                  tformato=[{"ANNOMES": MONTH, "CODIGO_PRE": "06502F01", "TIPSUM": "S", "VTAS": 5.85, "CON": 0}])
        est = m.establishments[0]
        ws = build_workbook(ici_data.pharmacy_report(m, est, est.pharmacies[0]))[0]["ICI"]
        labels = {ws.cell(r, c).value: ws.cell(r, c + 3).value for r in range(5, 10) for c in (11, 17)}
        self.assertEqual(labels["Venta"], 5.85)
        total = str(labels["Consumo total"])
        self.assertTrue(total.startswith("=5.85+SUMPRODUCT"), total)
        self.assertEqual(total.count("SUMPRODUCT"), 2)  # factor de pérdida y otros convenios

    def test_single_pharmacy_establishment_finds_its_movements(self):
        # Puesto con una sola farmacia: el ICI va con el código del establecimiento (06513) y el SISMED
        # escribe el almacén como el de su farmacia principal (06513F0101) o como 0651301.
        heads = [head("E", "1", "04", "030S0501", "06513F0101", doc=("03", "260322"), refe="SISMED"),
                 head("S", "2", "13", "06513F0101", "", dia=4),
                 head("S", "3", "13", "0651301", "", dia=5),
                 head("S", "4", "13", "06513F0102", "", dia=5)]          # donaciones: no entra
        details = [detail("E", "1", "001", "L1", 20), detail("S", "2", "001", "L1", 1),
                   detail("S", "3", "001", "L1", 1), detail("S", "4", "001", "L1", 1)]
        m = month([tformdet("06513", "001", "L1", SALDO=10, INGRE=20, SIS=2)], heads, details)
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        self.assertEqual([g.numero for g in report.guias], ["1"])
        self.assertEqual(report.guias[0].origen, "030S05")
        sis = sum(counts[ici_data.CONSUMO.index("SIS")] for _, counts, _, _ in report.recetas_diarias)
        self.assertEqual(sis, 2)
        self.assertEqual(m.warnings, [])

    def test_daily_recetas_come_from_tventa(self):
        # Como las cuenta el ICI: cada venta vigente de la farmacia es una receta, con su forma de pago.
        ventas = [{"ALMCOD": "06513", "ALMCODSUB": "0651301", "VTASIT": "1", "VTATIP": "M", "VTATIPODOC": "26",
                   "VTAFORMPAG": "03", "VTAFECHREG": date(2026, 8, 4), "VTATOTAL": 2.5},
                  {"ALMCOD": "06513", "ALMCODSUB": "0651301", "VTASIT": "1", "VTATIP": "M", "VTATIPODOC": "08",
                   "VTAFORMPAG": "01", "VTAFECHREG": date(2026, 8, 4), "VTATOTAL": 1.25},
                  {"ALMCOD": "06513", "ALMCODSUB": "0651301", "VTASIT": "0", "VTATIP": "M", "VTATIPODOC": "26",
                   "VTAFORMPAG": "03", "VTAFECHREG": date(2026, 8, 4), "VTATOTAL": 9.0},       # anulada
                  {"ALMCOD": "06513", "ALMCODSUB": "0651301", "VTASIT": "1", "VTATIP": "M", "VTATIPODOC": "26",
                   "VTAFORMPAG": "03", "VTAFECHREG": date(2026, 7, 31), "VTATOTAL": 9.0}]     # otro mes
        m = month([tformdet("06513", "001", "L1", SALDO=10, SIS=2)], ventas=ventas)
        est = m.establishments[0]
        daily = {d.day: (counts, value) for d, counts, value, _ in ici_data.pharmacy_report(m, est, est.pharmacies[0]).recetas_diarias}
        self.assertEqual(daily[4][0][ici_data.CONSUMO.index("SIS")], 1)
        self.assertEqual(daily[4][0][ici_data.CONSUMO.index("VENTA")], 1)
        self.assertAlmostEqual(daily[4][1], 3.75)
        self.assertEqual(sum(sum(c) for c, _ in daily.values()), 2)

    def test_warns_when_no_movement_is_found(self):
        m = month([tformdet("06513", "001", "L1", SALDO=10, INGRE=20)],
                  [head("E", "1", "04", "030S0501", "99999XX01")], [detail("E", "1", "001", "L1", 20)])
        self.assertEqual(len(m.warnings), 1)
        self.assertIn("06513", m.warnings[0])
        self.assertIn("99999XX01", m.warnings[0])

    def test_month_without_tformdet_is_empty(self):
        m = month([tformdet("06502F01", "001", "L1", ANNOMES="202607", SALDO=1)])
        self.assertEqual(m.establishments, [])


class IciExcelTests(unittest.TestCase):
    def _report(self, **extra):
        rows = [tformdet("06502F01", "001", "L1", SALDO=100, SIS=10, DEVOL=5, **extra),
                tformdet("06502F01", "002", "L9", SALDO=8, FEC_EXP=date(2026, 7, 1))]
        m = month(rows, heads=[head("E", "1", "04", "030A0001", "06502F0101", doc=("03", "G-1"), refe="Intervención sanitaria"),
                               head("E", "2", "04", "030A0001", "06502F0101", doc=("03", "G-2"), refe="SISMED SET")],
                  details=[detail("E", "1", "001", "L1", 0, 0), detail("E", "2", "001", "L1", 0, 12.5)])
        est = m.establishments[0]
        return ici_data.pharmacy_report(m, est, est.pharmacies[0])

    def test_workbook_has_the_approved_sheets(self):
        wb, summary = build_workbook(self._report())
        # Orden del usuario; alertas y lotes sin movimiento al final y solo en el Excel.
        self.assertEqual(wb.sheetnames, ["ICI", "Guías de ingreso", "Correcciones de lote", "Vencimientos",
                                         "Recetas diarias", "Alertas de farmacia", "Lotes sin movimiento"])
        printable = build_workbook(self._report(), printable="toolkit")[0]
        self.assertEqual(printable.sheetnames, ["ICI", "Guías de ingreso", "Correcciones de lote", "Vencimientos",
                                                "Recetas diarias"])
        cells = [c.value for row in printable["ICI"].iter_rows() for c in row if isinstance(c.value, str)]
        self.assertIn("RESPONSABLE DE FARMACIA", cells)
        self.assertFalse(any(v in ("Nombre:", "DNI:") for v in cells))
        ws = wb["ICI"]
        headers = [ws.cell(12, c).value for c in range(1, ws.max_column + 1)]
        self.assertNotIn("AJUSTE DE INVENTARIO (+)", headers)
        self.assertEqual(ws.page_setup.orientation, "landscape")
        self.assertEqual(ws.print_title_rows, "$11:$12")
        self.assertEqual(summary["sin_movimiento"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ici.xlsx"
            wb.save(path)
            guides = openpyxl.load_workbook(path)["Guías de ingreso"]
            cells = [c.value for row in guides.iter_rows() for c in row if c.value is not None]
        # Una sección por referencia, en el orden SISMED, intervención, transferencias.
        self.assertLess(cells.index("DESDE EL ALMACÉN · SISMED  ·  1 guías"), cells.index("DESDE EL ALMACÉN · ESTRATEGIA  ·  1 guías"))
        self.assertLess(cells.index("DESDE EL ALMACÉN · ESTRATEGIA  ·  1 guías"), cells.index("DESDE EL ALMACÉN · TRANSFERENCIAS  ·  0 guías"))
        self.assertIn("Distribución", cells)
        self.assertNotIn("04 Distribución", cells)
        self.assertIn("Intervención sanitaria", cells)

    def test_excel_has_the_column_letters_with_filter(self):
        wb, _ = build_workbook(self._report())
        ws = wb["ICI"]
        # Sin fila vacía: recetas en la 13, letras con el filtro en la 14 y datos desde la 15.
        self.assertEqual([ws.cell(14, c).value for c in (1, 2, 3)], ["A", "B", "C"])
        self.assertTrue(ws.auto_filter.ref.startswith("A14:"))
        self.assertEqual(ws.cell(15, 2).value, "AMOXICILINA 500 mg")
        self.assertTrue(str(ws.cell(17, ws.max_column).value).startswith("=SUBTOTAL(9,"))

    def test_print_version_repeats_the_header_on_every_page(self):
        rows = [tformdet("06502F01", f"{k:03d}", f"L{k}", SALDO=10 + k, SIS=1) for k in range(150)]
        m = month(rows)
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        wb, _ = build_workbook(report, printable=True)
        ws = wb["ICI"]
        breaks = [b.id for b in ws.row_breaks.brk]
        self.assertGreaterEqual(len(breaks), 2)
        # Cada página nueva empieza con el encabezado de la tabla (o con la declaración jurada).
        for brk in breaks:
            self.assertIn(ws.cell(brk + 1, 1).value, ("PRODUCTO FARMACÉUTICO", "DECLARACIÓN JURADA"))
            if ws.cell(brk + 1, 1).value == "PRODUCTO FARMACÉUTICO":
                self.assertEqual(ws.cell(brk + 2, 2).value, "DESCRIPCIÓN")
        self.assertFalse(ws.print_title_rows)
        self.assertIsNone(ws.auto_filter.ref)
        # El ICI es más ancho que la página: se ajusta a una página de ancho (lo calcula el programa que
        # arma el PDF, así llena el ancho en Excel y en LibreOffice) y de alto libre (cortes propios).
        self.assertTrue(ws.sheet_properties.pageSetUpPr.fitToPage)
        self.assertEqual((ws.page_setup.fitToWidth, ws.page_setup.fitToHeight), (1, 0))
        # Una hoja angosta se agranda con escala fija.
        small = build_workbook(report, printable=True)[0]["Vencimientos"]
        self.assertFalse(small.sheet_properties.pageSetUpPr.fitToPage)
        self.assertGreater(small.page_setup.scale, 100)

    def test_prices_never_show_hashes(self):
        wb, _ = build_workbook(self._report())
        ws = wb["ICI"]
        price_col = [ws.cell(13 - 1, c).value for c in range(1, ws.max_column + 1)].index("PRECIO S/") + 1
        self.assertTrue(ws.cell(15, price_col).alignment.shrink_to_fit)

    def test_signatures_never_alone_on_the_last_page(self):
        for count in range(30, 140, 7):
            rows = [tformdet("06502F01", f"{k:03d}", f"L{k}", SALDO=10 + k, SIS=1) for k in range(count)]
            m = month(rows)
            est = m.establishments[0]
            ws = build_workbook(ici_data.pharmacy_report(m, est, est.pharmacies[0]), printable=True)[0]["ICI"]
            breaks = [b.id for b in ws.row_breaks.brk]
            if breaks:
                # La última página empieza con el encabezado de la tabla y filas, no con la declaración.
                self.assertEqual(ws.cell(breaks[-1] + 1, 1).value, "PRODUCTO FARMACÉUTICO", count)

    def test_long_names_get_a_taller_row(self):
        long_name = "ACIDO FOLICO + FERROSO SULFATO (EQUIV. DE HIERRO ELEMENTAL) 400 UG + 60 MG FE TABLETA RECUBIERTA"
        self.assertGreaterEqual(row_height(long_name, 46, 7.2), 24)
        self.assertEqual(row_height("PARACETAMOL 500 mg", 46, 7.2), 13.8)

    def test_correction_reference_goes_to_corrections_not_to_guides(self):
        rows = [tformdet("06502F01", "001", "L1", SALDO=10, REINGRE=5)]
        m = month(rows, heads=[head("E", "1", "05", "030A0001", "06502F0101", doc=("04", "G-9"), refe="Corrección de lote")],
                  details=[detail("E", "1", "001", "L1", 5, 5)])
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        self.assertEqual(report.guias, [])
        self.assertEqual([c.entrada.doc_numero for c in report.corrections], ["G-9"])
        self.assertIn("correccion", report.rows[0]["flags"])
        # Cada corrección sale completa: cabecera con su referencia y debajo sus productos.
        wb, _ = build_workbook(report)
        cells = [str(c.value) for row in wb["Correcciones de lote"].iter_rows() for c in row if c.value is not None]
        self.assertIn("REINGRESO POR CORRECCIÓN  ·  GUÍA G-9", cells)
        self.assertTrue(any("ref. Corrección de lote" in v for v in cells))
        self.assertIn("PARACETAMOL 500 mg", cells)

    def test_reference_groups_and_date_in_words(self):
        self.assertEqual(reference_group("sismed"), "SISMED")
        self.assertEqual(reference_group("Estrategia sanitaria TBC"), "ESTRATEGIA")
        self.assertEqual(reference_group("INTERVENCION SANITARIA"), "ESTRATEGIA")
        self.assertEqual(reference_group("Transf. Hosp. Tarapoto"), "TRANSFERENCIAS")
        self.assertEqual(reference_group(""), "OTRAS REFERENCIAS")
        self.assertEqual(date_in_words(date(2026, 10, 18)), "18 de octubre de 2026")

    def test_signatures_are_centered_on_the_width(self):
        widths = [10] * 20
        self.assertEqual(column_span(widths, 0.10, 0.40), (3, 8))
        self.assertEqual(signature_blocks(widths), ((3, 8), (13, 18)))
        # En el ICI la descripción es ancha: la firma de la derecha es el espejo de la izquierda.
        widths = [c[1] for c in COLS]
        (l1, l2), (r1, r2) = signature_blocks(widths)
        total = sum(widths)
        left_margin = sum(widths[: l1 - 1]) / total
        right_margin = sum(widths[r2:]) / total
        self.assertLess(abs(left_margin - right_margin), 0.02)

    def test_adjustment_column_only_when_used(self):
        wb, _ = build_workbook(self._report(ING_REGULA=4))
        ws = wb["ICI"]
        headers = [ws.cell(12, c).value for c in range(1, ws.max_column + 1)]
        self.assertEqual(headers[headers.index("REINGRESOS") + 1], "AJUSTE DE INVENTARIO (+)")


class IciFilesTests(unittest.TestCase):
    def test_one_book_per_pharmacy_and_the_consolidated(self):
        m = month([tformdet("06502F01", "001", "L1", SALDO=10, SIS=2), tformdet("06502F02", "001", "L1", SALDO=5)])
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(m, tmp, pdf=False, log=lambda _m: None)
            names = sorted(Path(p).name for p in paths)
            self.assertEqual(names, ["ICI AGOSTO 2026 - 06502F01 - FARMACIA.xlsx", "ICI AGOSTO 2026 - 06502F02 - EMERGENCIA.xlsx",
                                     "ICI CONSOLIDADO AGOSTO 2026 - 06502 - HOSPITAL.xlsx"])
            only = write_reports(m, tmp, per_pharmacy=False, pdf=False, log=lambda _m: None)
            self.assertEqual([Path(p).name for p in only], ["ICI CONSOLIDADO AGOSTO 2026 - 06502 - HOSPITAL.xlsx"])

    def test_each_book_also_goes_to_pdf(self):
        m = month([tformdet("06502F01", "001", "L1", SALDO=10, SIS=2), tformdet("06502F02", "001", "L1", SALDO=5)])

        class FakeExporter:
            name = "Prueba"
            closed = False
            exported = []

            def export(self, xlsx, pdf):
                if "EMERGENCIA" in xlsx:
                    raise RuntimeError("falló")
                self.exported.append(Path(pdf).name)
                Path(pdf).write_bytes(b"%PDF")

            def close(self):
                FakeExporter.closed = True

        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(m, tmp, log=logs.append, open_exporter=lambda log: FakeExporter())
            names = sorted(Path(p).name for p in paths)
        self.assertIn("ICI CONSOLIDADO AGOSTO 2026 - 06502 - HOSPITAL.pdf", names)
        self.assertIn("ICI AGOSTO 2026 - 06502F01 - FARMACIA.pdf", names)
        # Si un PDF falla, el Excel queda y se sigue con los demás.
        self.assertIn("ICI AGOSTO 2026 - 06502F02 - EMERGENCIA.xlsx", names)
        self.assertNotIn("ICI AGOSTO 2026 - 06502F02 - EMERGENCIA.pdf", names)
        self.assertTrue(any("No se pudo pasar a PDF" in line for line in logs))
        self.assertTrue(FakeExporter.closed)

    def test_the_toolkit_draws_the_pdf_filling_every_page(self):
        import fitz
        import ici_render

        long_name = "ACIDO FOLICO + FERROSO SULFATO (Equiv. de Hierro elemental) 400 ug + 60 mg Fe"
        rows = [tformdet("06502F01", f"{k:03d}", f"L{k}", SALDO=10 + k, SIS=k % 3,
                         **({"DESCRIPCION MED": long_name} if k % 9 == 0 else {})) for k in range(260)]
        m = month(rows)
        est = m.establishments[0]
        report = ici_data.pharmacy_report(m, est, est.pharmacies[0])
        wb, _ = build_workbook(report, printable="toolkit")
        bottom = ici_render.A4_LANDSCAPE[1] - wb["ICI"].page_margins.bottom * 72
        sheet = ici_render._Sheet(wb["ICI"])
        pages = sheet.layout()
        self.assertGreater(len(pages), 3)
        for k, rows_on_page in enumerate(pages[:-2]):
            r, y, h = rows_on_page[-1]
            next_row = pages[k + 1][0][0]
            # La página llega hasta abajo: la fila que sigue ya no entraba.
            self.assertGreater(y + h + sheet.height(next_row) * sheet.scale, bottom - 60, k)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = str(Path(tmp) / "ici.pdf")
            total = ici_render.render_workbook(wb, pdf)
            doc = fitz.open(pdf)
            self.assertEqual(len(doc), total)
            for page in doc:
                for x0, y0, x1, y1, *_ in page.get_text("words"):
                    # Nada se sale de la página: cada hoja entra a lo ancho.
                    self.assertLessEqual(x1, ici_render.A4_LANDSCAPE[0] - 10)
                    self.assertLessEqual(y1, ici_render.A4_LANDSCAPE[1])
            text = doc[0].get_text()
            self.assertIn("INFORME DE CONSUMO INTEGRADO", text)
            self.assertIn(f"Página 1 de {total}", text)
            last_ici = next(i for i in range(len(doc)) if "DECLARACIÓN JURADA" in doc[i].get_text())
            self.assertIn("TOTAL", doc[last_ici].get_text())
            self.assertIn("ACIDO FOLICO", "".join(doc[i].get_text() for i in range(last_ici + 1)))
            doc.close()

    def test_formulas_and_formats_as_excel_shows_them(self):
        import ici_render
        import ici_values
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws["A1"], ws["A2"], ws["A3"] = 2, 3, "texto"
        ws["B1"], ws["B2"], ws["B3"] = 1.5, 2, 4
        ws["C1"] = date(2026, 9, 15)
        ws["D1"] = "=SUMPRODUCT(A1:A3,B1:B3)"
        ws["D2"] = "=SUM(A1:A3)+B2*2"
        ws["D3"] = '=COUNTIF(A1:A3,">2")'
        ws["D4"] = '=COUNTIFS(C1:C1,">"&DATE(2026,8,31),C1:C1,"<="&EDATE(DATE(2026,8,31),6))'
        ev = ici_values.Evaluator(ws)
        self.assertEqual(ev.value(1, 4), 9.0)
        self.assertEqual(ev.value(2, 4), 9.0)
        self.assertEqual(ev.value(3, 4), 1.0)
        self.assertEqual(ev.value(4, 4), 1.0)
        f = ici_render.format_value
        self.assertEqual(f(0, '0;-0;"–"'), "–")
        self.assertEqual(f(2.5, '0;-0;"–"'), "3")
        self.assertEqual(f(0.14875, "0.00####"), "0.14875")
        self.assertEqual(f(5, "0.00####"), "5.00")
        self.assertEqual(f(290.92, '"S/ "0.00'), "S/ 290.92")
        self.assertEqual(f(0.177, '0.0%;-0.0%;"–"'), "17.7%")
        self.assertEqual(f(date(2026, 8, 31), "dd/mm/yyyy"), "31/08/2026")

    def test_without_a_spreadsheet_program_only_the_excel_is_made(self):
        logs = []
        exporter = ici_pdf.open_exporter(log=logs.append, com_programs=(), libreoffice=lambda: None, toolkit=False)
        self.assertIsNone(exporter)
        self.assertIn("No se pudo generar el PDF", logs[0])

    @unittest.skipUnless(ici_pdf.find_libreoffice(), "sin LibreOffice")
    def test_libreoffice_prints_every_sheet(self):
        m = month([tformdet("06502F01", "001", "L1", SALDO=10, SIS=2)])
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(m, tmp, log=lambda _m: None, open_exporter=lambda log: ici_pdf.open_exporter(
                log=log, com_programs=(), toolkit=False))
            pdf = next(p for p in paths if p.endswith(".pdf"))
            data = Path(pdf).read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        # Una página por hoja como mínimo: ICI, Guías, Correcciones, Vencimientos y Recetas diarias.
        self.assertGreaterEqual(len(re.findall(rb"/Type\s*/Page(?!s)", data)), 5)

    def test_a_single_pharmacy_has_no_consolidated(self):
        m = month([tformdet("06502F01", "001", "L1", SALDO=10)])
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(m, tmp, per_pharmacy=False, pdf=False, log=lambda _m: None)
            self.assertEqual([Path(p).name for p in paths], ["ICI AGOSTO 2026 - 06502F01 - FARMACIA.xlsx"])


if __name__ == "__main__":
    unittest.main()
