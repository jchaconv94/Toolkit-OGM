import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from edit_sismed_manager import EditSismedManager  # noqa: E402
from tmovim_search import (  # noqa: E402
    BY_GUIDE, BY_MOVEMENT, ListMatcher, guide_key, guide_number, simple_match, split_values, summarize,
)

FIELDS = [
    ("MOVCODITIP", 1), ("MOVNUMERO", 10), ("MOVNUMEDCO", 20), ("MOVFECHREG", 10),
    ("MOVSITUA", 1), ("MOVINDPRC", 1), ("BLOQUEO", 1), ("USRBLOQ", 10),
]
# (tipo, N° movimiento, N° guía, situación)
REGISTROS = [
    ("I", "0000101", "001-0012345", "0"),   # guía anulada...
    ("I", "0000102", "001-0012345", "1"),   # ...y registrada de nuevo
    ("I", "0000103", "0004567", "1"),
    ("S", "0000104", "002-0000890", "1"),
    ("I", "0000105", "", "1"),
    ("I", "0000106", "001 - 0077777", "1"),
]


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
            for (_name, size), value in zip(fields, record):
                fh.write(value.encode("cp1252").ljust(size)[:size])
        fh.write(b"\x1a")


class GuideKeyTests(unittest.TestCase):
    def test_series_zeros_and_spaces_give_the_same_key(self):
        for value in ("001-0012345", "001 - 12345", "1-12345", " 001-0012345 "):
            self.assertEqual(guide_key(value), "1-12345")
        self.assertEqual(guide_key("0004567"), "4567")
        self.assertEqual(guide_key(""), "")

    def test_number_without_series(self):
        self.assertEqual(guide_number("001-0012345"), "12345")
        self.assertEqual(guide_number("0004567"), "4567")
        self.assertEqual(guide_number("GR-000"), "0")
        self.assertEqual(guide_number("SIN NUMERO"), "")


class SplitTests(unittest.TestCase):
    def test_guides_go_one_per_line(self):
        texto = "001 - 0077777\r\n0004567\n\n0004567\n12345;890\t555"
        self.assertEqual(split_values(texto, BY_GUIDE), ["001 - 0077777", "0004567", "12345", "890", "555"])

    def test_movements_split_by_space_as_before(self):
        self.assertEqual(split_values("101 102,103\n101", BY_MOVEMENT), ["101", "102", "103"])


class SimpleMatchTests(unittest.TestCase):
    def test_guide_contains_with_or_without_zeros(self):
        self.assertTrue(simple_match("12345", "001-0012345", BY_GUIDE))
        self.assertTrue(simple_match("001-0012345", "001-0012345", BY_GUIDE))
        self.assertTrue(simple_match("001-12345", "001-0012345", BY_GUIDE))
        self.assertTrue(simple_match("0077777", "001 - 0077777", BY_GUIDE))
        self.assertTrue(simple_match("001-0077777", "001 - 0077777", BY_GUIDE))
        self.assertFalse(simple_match("99999", "001-0012345", BY_GUIDE))
        self.assertFalse(simple_match("   ", "001-0012345", BY_GUIDE))

    def test_movement_keeps_the_old_contains(self):
        self.assertTrue(simple_match("101", "0000101", BY_MOVEMENT))
        self.assertFalse(simple_match("12345", "0000101", BY_MOVEMENT))


class ListMatcherTests(unittest.TestCase):
    def test_excel_without_zeros_and_number_without_series(self):
        matcher = ListMatcher(["4567", "12345"], BY_GUIDE)
        self.assertEqual(matcher.match("0004567"), ["4567"])
        self.assertEqual(matcher.match("001-0012345"), ["12345"])
        self.assertEqual(matcher.match("002-0000890"), [])

    def test_series_written_only_matches_that_series(self):
        matcher = ListMatcher(["001-0000890"], BY_GUIDE)
        self.assertEqual(matcher.match("002-0000890"), [])
        self.assertEqual(matcher.match("001-890"), ["001-0000890"])

    def test_same_guide_pasted_twice_counts_once(self):
        matcher = ListMatcher(["0012345", "12345", "  "], BY_GUIDE)
        self.assertEqual(matcher.values, ["0012345"])

    def test_movements_are_exact(self):
        matcher = ListMatcher(["0000101"], BY_MOVEMENT)
        self.assertEqual(matcher.match("0000101"), ["0000101"])
        self.assertEqual(matcher.match("101"), [])


class SummarizeTests(unittest.TestCase):
    def test_repeated_guide_is_not_marked(self):
        preselect, not_found, repeated = summarize(
            ["12345", "4567", "999"], [["12345"], ["12345"], ["4567"]], BY_GUIDE,
        )
        self.assertEqual(preselect, {2})
        self.assertEqual(not_found, ["999"])
        self.assertEqual(repeated, ["12345"])

    def test_movements_mark_everything_found_as_before(self):
        preselect, not_found, repeated = summarize(["1", "2"], [["1"], ["1"]], BY_MOVEMENT)
        self.assertEqual((preselect, not_found, repeated), ({0, 1}, ["2"], []))


class ManagerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "DATOS"))
        rows = [(tipo, mov, guia, "01/10/2026", situa, "A", "", "") for tipo, mov, guia, situa in REGISTROS]
        _write_dbf(os.path.join(tmp.name, "DATOS", "TMOVIM.DBF"), FIELDS, rows)
        self.mgr = EditSismedManager(tmp.name)

    def test_simple_by_guide(self):
        found = self.mgr.search_guias("12345", BY_GUIDE)
        self.assertEqual([g["movnumero"] for g in found], ["0000101", "0000102"])
        self.assertEqual([g["id_fisico"] for g in found], [0, 1])

    def test_simple_by_movement_unchanged(self):
        found = self.mgr.search_guias("0000103")
        self.assertEqual([g["movnumedco"] for g in found], ["0004567"])

    def test_bulk_by_guide(self):
        matcher = ListMatcher(split_values("12345\n4567\n002-890\n555", BY_GUIDE), BY_GUIDE)
        found = self.mgr.search_guias_by_list(matcher)
        self.assertEqual([g["movnumero"] for g in found], ["0000101", "0000102", "0000103", "0000104"])
        preselect, not_found, repeated = summarize(matcher.values, [g["coincide"] for g in found], BY_GUIDE)
        self.assertEqual(preselect, {2, 3})
        self.assertEqual(not_found, ["555"])
        self.assertEqual(repeated, ["12345"])

    def test_writing_after_search_uses_the_found_record(self):
        found = self.mgr.search_guias("0004567", BY_GUIDE)
        total, _ = self.mgr.update_movsitua_bulk([found[0]["id_fisico"]], "0")
        self.assertEqual(total, 1)
        again = EditSismedManager(os.path.dirname(os.path.dirname(self.mgr.tmovim_path))).search_guias("4567", BY_GUIDE)
        self.assertEqual([(g["movnumero"], g["movsitua"]) for g in again], [("0000103", "0")])

    def test_missing_file_is_reported(self):
        mgr = EditSismedManager(tempfile.gettempdir() + "/no-existe-sismed")
        with self.assertRaises(FileNotFoundError):
            mgr.search_guias_by_list(["1"], BY_GUIDE)



def _mark_deleted(path, fields, position):
    """Marca un registro como borrado, como DELETE de FoxPro (sin PACK)."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(size for _name, size in fields)
    with open(path, "r+b") as fh:
        fh.seek(header_len + position * record_len)
        fh.write(b"*")


class DeletedRecordTests(unittest.TestCase):
    """Un registro borrado antes de la guía no debe hacer que se modifique otra guía."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        os.makedirs(os.path.join(self.base, "DATOS"))
        self.path = os.path.join(self.base, "DATOS", "TMOVIM.DBF")
        rows = [
            ("I", "0000001", "G-1", "01/10/2026", "1", "A", "S", "USR"),
            ("I", "0000002", "G-2", "01/10/2026", "1", "A", "S", "USR"),
            ("I", "0000003", "G-3", "01/10/2026", "1", "A", "S", "USR"),
        ]
        _write_dbf(self.path, FIELDS, rows)
        _mark_deleted(self.path, FIELDS, 0)

    def _state(self):
        return {
            g["movnumero"]: (g["movsitua"], g["movindprc"], g["bloqueo"])
            for g in EditSismedManager(self.base).search_guias("G-", BY_GUIDE)
        }

    def test_actions_touch_only_the_selected_guide(self):
        mgr = EditSismedManager(self.base)
        found = mgr.search_guias("G-3", BY_GUIDE)
        self.assertEqual(found[0]["id_fisico"], 2)
        self.assertEqual(mgr.update_movsitua_bulk(found, "0")[0], 1)
        self.assertEqual(mgr.toggle_movindprc_bulk(found)[0], 1)
        self.assertEqual(mgr.clear_bloqueo_bulk(found)[0], 1)
        self.assertEqual(self._state(), {"0000002": ("1", "A", "S"), "0000003": ("0", "M", "")})

    def test_changed_file_is_not_written(self):
        mgr = EditSismedManager(self.base)
        found = mgr.search_guias("G-3", BY_GUIDE)
        stale = dict(found[0], id_fisico=1)   # el archivo se reordenó después de buscar
        total, msg = mgr.update_movsitua_bulk([stale], "0")
        self.assertEqual(total, 0)
        self.assertIn("Vuelva a buscar", msg)
        total, msg = mgr.update_movsitua_bulk([dict(found[0], id_fisico=0)], "0")
        self.assertEqual(total, 0)
        self.assertIn("ya no está", msg)
        self.assertEqual(self._state()["0000002"], ("1", "A", "S"))

    def test_medest_uses_the_physical_record(self):
        fields = [("MEDCOD", 7), ("MEDNOM", 20), ("MEDEST", 1)]
        path = os.path.join(self.base, "DATOS", "MPRODUCTO.DBF")
        _write_dbf(path, fields, [("0000001", "UNO", "E"), ("0000002", "DOS", "E"), ("0000003", "TRES", "E")])
        _mark_deleted(path, fields, 0)
        mgr = EditSismedManager(self.base)
        found = mgr.search_medicines("TRES")
        self.assertEqual(found[0]["id_fisico"], 2)
        self.assertEqual(mgr.update_medest_bulk([found[0]["id_fisico"]], "S")[0], 1)
        estados = {m["medcod"]: m["medest"] for m in EditSismedManager(self.base).search_medicines("0")}
        self.assertEqual(estados, {"0000002": "E", "0000003": "S"})


if __name__ == "__main__":
    unittest.main()
