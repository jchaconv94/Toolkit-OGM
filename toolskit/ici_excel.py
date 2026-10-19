"""Generar ICI: el libro de Excel con el diseño aprobado por el usuario el 2026-10-19.

Hojas: ICI (para imprimir horizontal y firmar), Vencimientos, Alertas de farmacia, Lotes sin
movimiento, Guías de ingreso y Correcciones de lote.

Decisiones del usuario que no hay que deshacer (docs/ICI_SISMED.md del ToolKit SISMED Web):
cifras sin separador de miles (con coma parecía decimal), precios completos, la misma letra en
todas las descripciones (un nombre largo pasa a otra línea), «–» en lugar de cero, encabezado
de columnas en cada página, firmas solo con nombre y DNI, fecha automática y sin lugar, y la
columna de ajuste de inventario que entra solo si algún lote la tiene.
"""

from __future__ import annotations

import collections
import datetime as dt
import unicodedata

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.page import PageMargins

from ici_data import CONSUMO, CONCEPTOS, MESES, IciReport, Movement, ipress_of

F = "Arial"
NAVY, NAVY2, GRID, SOFT, ZEBRA, INK, MUTED, WHITE = (
    "17324D", "24476B", "B8C2CC", "EEF2F6", "F7F9FB", "1F2933", "5F6B7A", "FFFFFF")
TINT = {"in": "E3EEF9", "cons": "E2F3EC", "dev": "FFF1DC", "venc": "FBE3E3", "fix": "EDE7F6"}
INKT = {"in": "1D4E89", "cons": "1E6B4F", "dev": "8A5300", "venc": "A11D1D", "fix": "5B3A9B"}
INT0 = '0;-0;"–"'
MONEY = '0.00;-0.00;"–"'
PRICE = "0.00####"
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", indent=1)
RIGHT = Alignment(horizontal="right", vertical="center", indent=1)
WRAP_LEFT = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
MID = Alignment(horizontal="center", vertical="center")


def side(color=GRID, style="thin"):
    return Side(style=style, color=color)


BOX = Border(left=side(), right=side(), top=side(), bottom=side())


def fill(color):
    return PatternFill("solid", fgColor=color)


def fnt(size=8, bold=False, color=INK, italic=False):
    return Font(name=F, size=size, bold=bold, color=color, italic=italic)


# (encabezado, ancho, grupo, campo, tinte)
COLS = [
    ("CÓDIGO", 5.6, "P", "CODIGO_MED", None), ("DESCRIPCIÓN", 46, "P", "DESC", None),
    ("UNIDAD", 6.2, "P", "MEDFF", None), ("LOTE", 12, "P", "MEDLOTE", None),
    ("REG. SANITARIO", 10.5, "P", "MEDREGSAN", None), ("VENCIMIENTO", 8.6, "P", "FEC_EXP", None),
    ("TIP. SUM.", 3.4, "P", "TIPSUM2", None), ("F. FINAN.", 3.9, "P", "FFINAN", None),
    ("PRECIO S/", 7.6, "P", "PRECIO", None),
    ("SALDO MES ANTERIOR", 6.6, "S", "SALDO", None),
    ("INGRESOS", 6.2, "E", "INGRE", "in"), ("REINGRESOS", 6.2, "E", "REINGRE", "in"),
    ("VENTA", 5.6, "C", "VENTA", "cons"), ("S.I.S.", 6.0, "C", "SIS", "cons"),
    ("INTERV. SANITARIA", 5.6, "C", "INTERSAN", "cons"), ("F. PÉRDIDA (ZOONOSIS)", 4.4, "C", "FAC_PERD", "cons"),
    ("DEFENSA NACIONAL", 4.4, "C", "DEFNAC", "cons"), ("EXONERACIÓN", 4.6, "C", "EXO", "cons"),
    ("SOAT", 4.4, "C", "SOAT", "cons"), ("CRÉDITO HOSP.", 4.6, "C", "CREDHOSP", "cons"),
    ("OTROS CONVENIOS", 4.6, "C", "OTR_CONV", "cons"),
    ("DEVOLUCIÓN", 6.2, "O", "DEVOL", "dev"), ("VENCIDOS", 5.0, "O", "VENCIDO", "venc"),
    ("MERMA", 4.4, "O", "MERMA", "dev"), ("OTRAS SALIDAS", 4.6, "O", "OTRAS", "dev"),
    ("REGULA.", 4.6, "O", "SAL_REGULA", "dev"), ("CONS. INSTITUC.", 4.6, "O", "SAL_CONINS", "dev"),
    ("TOTAL SALIDAS", 6.6, "T", "=TOTAL", None), ("STOCK FINAL", 7.0, "T", "=STOCK", None),
]
GROUPS = {"P": "PRODUCTO FARMACÉUTICO", "S": "SALDO", "E": "ENTRADAS", "C": "CONSUMOS",
          "O": "OTRAS SALIDAS", "T": "SALDO FINAL"}
# Ajuste de inventario que entra (concepto 21): en toda la región estuvo siempre en cero, así que
# la columna solo aparece si algún lote del mes lo tiene (si no, el stock no cuadraría a la vista).
ADJUST_COL = ("AJUSTE DE INVENTARIO (+)", 4.6, "E", "ING_REGULA", "in")
TEXT_FIELDS = ("CODIGO_MED", "DESC", "MEDFF", "MEDLOTE", "MEDREGSAN", "TIPSUM2", "FFINAN")


class Columns:
    def __init__(self, rows):
        cols = list(COLS)
        if any(row.get("ING_REGULA") for row in rows):
            cols.insert([c[3] for c in cols].index("REINGRE") + 1, ADJUST_COL)
        self.cols = cols
        self.ix = {c[3]: i + 1 for i, c in enumerate(cols)}
        self.n = len(cols)


def box(ws, r1, c1, r2, c2, value=None, font=None, fill_=None, align=None, border=True, fmt=None):
    if (r1, c1) != (r2, c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    cell = ws.cell(r1, c1)
    if value is not None:
        cell.value = value
    if font:
        cell.font = font
    if align:
        cell.alignment = align
    if fmt:
        cell.number_format = fmt
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            if fill_:
                ws.cell(r, c).fill = fill(fill_)
            if border:
                ws.cell(r, c).border = BOX
    return cell


def lines(value, per_line):
    """Líneas que ocupa un texto en su celda (misma letra en todas las filas)."""
    return max(1, -(-len(str(value)) // per_line))


def month_title(report: IciReport) -> str:
    return f"{MESES[int(report.annomes[4:6]) - 1]} {report.annomes[:4]}"


def consumo(row) -> float:
    return sum(row[f] for f in CONSUMO)


def _as_datetime(value):
    return dt.datetime.combine(value, dt.time()) if isinstance(value, dt.date) else None


def _footer(ws, label: str, report: IciReport):
    ws.oddFooter.left.text = f"{label} {month_title(report).title()} · {report.ficha['Establecimiento']}"
    ws.oddFooter.left.size = 7
    ws.oddFooter.right.text = "Página &P de &N"
    ws.oddFooter.right.size = 7


def _landscape(ws, margins=(0.3, 0.3, 0.4, 0.45)):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    left, right, top, bottom = margins
    ws.page_margins = PageMargins(left=left, right=right, top=top, bottom=bottom, footer=0.2)


def _title(ws, nc, title, report: IciReport, subtitle: str, size=14, split=4):
    box(ws, 1, 1, 1, nc - split, title, fnt(size, True, WHITE), NAVY, LEFT, border=False)
    box(ws, 1, nc - split + 1, 1, nc, month_title(report), fnt(size, True, WHITE), NAVY, RIGHT, border=False)
    ws.row_dimensions[1].height = 28
    box(ws, 2, 1, 2, nc, subtitle, fnt(8, False, "D6E2EE"), NAVY2, LEFT, border=False)


# ── Hoja ICI ───────────────────────────────────────────────────────────────────


def ici_sheet(wb, report: IciReport):
    rows = report.rows
    C = Columns(rows)
    IX, NCOL = C.ix, C.n
    ws = wb.active
    ws.title = "ICI"
    ws.sheet_view.showGridLines = False
    for i, c in enumerate(C.cols, 1):
        ws.column_dimensions[L(i)].width = c[1]

    box(ws, 1, 1, 1, NCOL - 8, "INFORME DE CONSUMO INTEGRADO  ·  ICI", fnt(15, True, WHITE), NAVY, LEFT, border=False)
    box(ws, 1, NCOL - 7, 1, NCOL, month_title(report), fnt(15, True, WHITE), NAVY, RIGHT, border=False)
    ws.row_dimensions[1].height = 30
    box(ws, 2, 1, 2, NCOL, "Declaración del movimiento de medicamentos, insumos y productos sanitarios  ·  "
        f"Periodo del {report.desde:%d/%m/%Y} al {report.hasta:%d/%m/%Y}",
        fnt(8, False, "D6E2EE"), NAVY2, LEFT, border=False)
    ws.row_dimensions[2].height = 16
    ws.row_dimensions[3].height = 6

    first = 16
    lastr = first + max(len(rows), 1) - 1
    R = lambda f: f"${L(IX[f])}${first}:${L(IX[f])}${lastr}"
    P = R("PRECIO")
    SP = lambda *fs: "+".join(f"SUMPRODUCT({P},{R(f)})" for f in fs if f in IX)

    # Bloque A: datos del establecimiento
    box(ws, 4, 1, 4, 9, "DATOS DEL ESTABLECIMIENTO", fnt(7.5, True, WHITE), NAVY, LEFT)
    for k, (label, value) in enumerate(list(report.ficha.items())[:5]):
        r = 5 + k
        box(ws, r, 1, r, 2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, r, 3, r, 9, value, fnt(8, True), None, LEFT)
    # Bloque B: resumen valorizado
    box(ws, 4, 11, 4, 22, "RESUMEN VALORIZADO DEL MES (S/)", fnt(7.5, True, WHITE), NAVY, LEFT)
    left = [("Saldo anterior", SP("SALDO")), ("Ingresos", SP("INGRE", "ING_REGULA")), ("Reingresos", SP("REINGRE")),
            ("Consumo total", SP(*CONSUMO)), ("Stock final", f"SUMPRODUCT({P},{R('=STOCK')})")]
    right = [("Venta", SP("VENTA")), ("S.I.S.", SP("SIS")), ("Interv. sanitaria", SP("INTERSAN")),
             ("Devoluciones", SP("DEVOL")), ("Vencidos", SP("VENCIDO"))]
    for k in range(5):
        r = 5 + k
        for (label, formula), (c1, c2, c3) in ((left[k], (11, 13, 16)), (right[k], (17, 19, 22))):
            strong = label in ("Stock final", "Consumo total")
            box(ws, r, c1, r, c2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
            box(ws, r, c2 + 1, r, c3, f"={formula}", fnt(8.5 if strong else 8, True, INKT["venc"] if label == "Vencidos" else INK),
                None, RIGHT, fmt=MONEY)
    # Bloque C: control del mes
    box(ws, 4, 24, 4, NCOL, "CONTROL DEL MES", fnt(7.5, True, WHITE), NAVY, LEFT)
    end = report.hasta
    pe = f"DATE({end.year},{end.month},{end.day})"
    control = [
        ("Lotes con stock", f"=COUNTIF({R('=STOCK')},\">0\")", INK),
        ("Por vencer en 6 meses", f"=COUNTIFS({R('FEC_EXP')},\">\"&{pe},{R('FEC_EXP')},\"<=\"&EDATE({pe},6),{R('=STOCK')},\">0\")", INKT["dev"]),
        ("Vencidos con stock", f"=COUNTIFS({R('FEC_EXP')},\"<=\"&{pe},{R('=STOCK')},\">0\")", INKT["venc"]),
        ("Productos sin precio", f"=COUNTIFS({P},0,{R('=STOCK')},\">0\")", INK),
        ("Guías de ingreso", len(report.guias), INK),
    ]
    for k, (label, value, color) in enumerate(control):
        r = 5 + k
        box(ws, r, 24, r, NCOL - 2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, r, NCOL - 1, r, NCOL, value, fnt(8.5, True, color), None, CENTER, fmt=INT0)
    ws.row_dimensions[10].height = 6

    # Encabezado de la tabla
    gr, hr, rr = 11, 12, 13
    start = 1
    for i in range(2, NCOL + 2):
        if i == NCOL + 1 or C.cols[i - 1][2] != C.cols[start - 1][2]:
            box(ws, gr, start, gr, i - 1, GROUPS[C.cols[start - 1][2]], fnt(7, True, WHITE), NAVY, CENTER)
            start = i
    for i, c in enumerate(C.cols, 1):
        box(ws, hr, i, hr, i, c[0], fnt(6.8, True, WHITE), NAVY2,
            Alignment(horizontal="center", vertical="center", wrap_text=True, text_rotation=90 if c[1] < 9 else 0))
    ws.row_dimensions[hr].height = 72
    box(ws, rr, 1, rr, IX["VENTA"] - 1, "N° DE RECETAS (CONSUMOS)  ·  N° DE LOTES (OTRAS SALIDAS)",
        fnt(7, True, INKT["cons"]), TINT["cons"], RIGHT)
    for f, value in zip(CONSUMO, report.recetas):
        box(ws, rr, IX[f], rr, IX[f], value, fnt(7.5, True, INKT["cons"]), TINT["cons"], CENTER, fmt=INT0)
    for f in ("DEVOL", "VENCIDO", "MERMA", "OTRAS", "SAL_REGULA", "SAL_CONINS"):
        box(ws, rr, IX[f], rr, IX[f], f"=COUNTIF({R(f)},\">0\")", fnt(7.5, True, INKT["dev"]), TINT["dev"], CENTER, fmt=INT0)
    box(ws, rr, IX["=TOTAL"], rr, NCOL, None, None, TINT["cons"])
    ws.row_dimensions[rr].height = 18
    for r in (14, 15):
        ws.row_dimensions[r].height = 3

    # Detalle
    total_formula = lambda r: f"=SUM({L(IX['VENTA'])}{r}:{L(IX['SAL_CONINS'])}{r})"
    stock_formula = lambda r: ("=" + "+".join(f"{L(IX[f])}{r}" for f in ("SALDO", "INGRE", "REINGRE", "ING_REGULA") if f in IX)
                               + f"-{L(IX['=TOTAL'])}{r}")
    for k, row in enumerate(rows):
        r = first + k
        fixed = "correccion" in row["flags"]
        for i, (_, _, _, fld, _) in enumerate(C.cols, 1):
            cell = ws.cell(r, i)
            if fld == "=TOTAL":
                cell.value = total_formula(r)
            elif fld == "=STOCK":
                cell.value = stock_formula(r)
            elif fld == "FEC_EXP":
                cell.value = _as_datetime(row["FEC_EXP"])
            else:
                cell.value = row[fld]
            cell.font = fnt(7.2, bold=fld == "=STOCK")
            cell.border = BOX
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True) if fld == "DESC" else MID
            if fld == "FEC_EXP":
                cell.number_format = "dd/mm/yyyy"
            elif fld == "PRECIO":
                cell.number_format = PRICE
            elif fld not in TEXT_FIELDS:
                cell.number_format = INT0
            if fixed and fld == "MEDLOTE":
                cell.fill = fill(TINT["fix"])
                cell.font = fnt(7.2, True, INKT["fix"])
            elif k % 2:
                cell.fill = fill(ZEBRA)
        ws.row_dimensions[r].height = 13 * lines(row["DESC"], 56)
    if rows:
        for tint in ("in", "cons", "dev", "venc"):
            for i in (i for i, c in enumerate(C.cols, 1) if c[4] == tint):
                col = L(i)
                ws.conditional_formatting.add(f"{col}{first}:{col}{lastr}", CellIsRule(
                    operator="greaterThan", formula=["0"], fill=fill(TINT[tint]), font=Font(name=F, color=INKT[tint], bold=True)))
        E, S = L(IX["FEC_EXP"]), L(IX["=STOCK"])
        ws.conditional_formatting.add(f"{E}{first}:{E}{lastr}", FormulaRule(
            formula=[f"AND({S}{first}>0,{E}{first}<={pe})"], fill=fill(TINT["venc"]), font=Font(name=F, color=INKT["venc"], bold=True)))
        ws.conditional_formatting.add(f"{E}{first}:{E}{lastr}", FormulaRule(
            formula=[f"AND({S}{first}>0,{E}{first}>{pe},{E}{first}<=EDATE({pe},6))"], fill=fill(TINT["dev"]),
            font=Font(name=F, color=INKT["dev"], bold=True)))
    else:
        box(ws, first, 1, first, NCOL, "Sin lotes en el mes.", fnt(7.5, False, MUTED, True), None, LEFT)

    tr = lastr + 1
    box(ws, tr, 1, tr, IX["PRECIO"], f"TOTAL  ·  {len(rows)} lotes", fnt(7.5, True, WHITE), NAVY, RIGHT)
    for i in range(IX["SALDO"], NCOL + 1):
        box(ws, tr, i, tr, i, f"=SUM({L(i)}{first}:{L(i)}{lastr})", fnt(7.2, True, WHITE), NAVY, CENTER, fmt=INT0)
    ws.row_dimensions[tr].height = 16

    notes = ["Colores:  ingresos y reingresos en azul · consumos en verde · devoluciones y otras salidas en ámbar · "
             "vencidos en rojo · vencimiento en rojo si el lote ya venció con stock y en ámbar si vence en los próximos 6 meses."]
    if report.corrections:
        notes.append("Lote en morado: corrección de lote del mes (salió y volvió a entrar en la misma farmacia); "
                     "el detalle está en la hoja «Correcciones de lote».")
    if report.consolidated:
        if report.internal_estimated:
            notes.append(f"Consolidado: se descontaron, estimadas por lote, las entregas entre farmacias del establecimiento "
                         f"(S/ {report.internal_value:.2f} de devolución y reingreso del mismo lote).")
        elif report.internal_value:
            notes.append(f"Consolidado: se descontaron las entregas entre farmacias del establecimiento (S/ {report.internal_value:.2f}).")
        if report.in_transit > 0.005:
            notes.append(f"Entregado a otra farmacia del establecimiento y todavía no recibido al cierre del mes: "
                         f"S/ {report.in_transit:.2f} (queda como salida).")
    r = tr + 1
    for note in notes:
        box(ws, r, 1, r, NCOL, note, fnt(6.5, False, MUTED, True), None, LEFT, border=False)
        r += 1
    _signature(ws, r + 1, [c[1] for c in C.cols])

    ws.freeze_panes = ws.cell(first, 3)
    ws.print_title_rows = f"{gr}:{hr}"
    _landscape(ws, (0.25, 0.25, 0.35, 0.45))
    ws.print_options.horizontalCentered = True
    _footer(ws, "ICI", report)
    return ws


def date_in_words(day: dt.date) -> str:
    """«18 de octubre de 2026»."""
    return f"{day.day} de {MESES[day.month - 1].lower()} de {day.year}"


def column_span(widths, start: float, end: float) -> tuple[int, int]:
    """Columnas (desde 1) que ocupan del `start` al `end` del ancho total (fracciones de 0 a 1)."""
    total = sum(widths)
    first = last = None
    acc = 0.0
    for i, w in enumerate(widths, 1):
        middle = (acc + w / 2) / total
        if first is None and middle >= start:
            first = i
        if middle <= end:
            last = i
        acc += w
    first = first or 1
    return first, max(first, last or first)


def signature_blocks(widths) -> tuple[tuple[int, int], tuple[int, int]]:
    """Columnas de las dos firmas: la izquierda cerca del 10–40 % del ancho y la derecha su espejo,
    para que queden a la misma distancia de los bordes aunque las columnas tengan anchos distintos."""
    left = column_span(widths, 0.10, 0.40)
    total = sum(widths)
    a = sum(widths[: left[0] - 1]) / total
    b = sum(widths[: left[1]]) / total
    return left, column_span(widths, 1 - b, 1 - a)


def _signature(ws, r, widths):
    """Declaración jurada, fecha y las dos firmas centradas en el ancho de la hoja."""
    ncol = len(widths)
    box(ws, r, 1, r, ncol, "DECLARACIÓN JURADA", fnt(8, True, WHITE), NAVY, LEFT)
    statement = ("Declaramos bajo juramento que la información consignada en el presente Informe de Consumo Integrado "
                 "corresponde al movimiento real de medicamentos, insumos y productos sanitarios de la farmacia durante "
                 "el periodo indicado, que se encuentra registrada en el SISMED y que el stock final declarado coincide "
                 "con las existencias físicas al cierre del mes.")
    box(ws, r + 1, 1, r + 2, ncol, statement, fnt(7.5), None,
        Alignment(horizontal="justify", vertical="center", wrap_text=True, indent=1))
    ws.row_dimensions[r + 1].height = ws.row_dimensions[r + 2].height = 15
    box(ws, r + 3, 1, r + 3, ncol, f"Fecha: {date_in_words(dt.date.today())}", fnt(7.5, True), None, LEFT, border=False)
    ws.row_dimensions[r + 3].height = 18
    for k in range(r + 4, r + 8):
        ws.row_dimensions[k].height = 14
    ws.row_dimensions[r + 8].height = 30
    for (c1, c2), title in zip(signature_blocks(widths), ("RESPONSABLE DE FARMACIA", "JEFE DEL ESTABLECIMIENTO")):
        for c in range(c1, c2 + 1):
            ws.cell(r + 8, c).border = Border(bottom=side(INK))
        box(ws, r + 9, c1, r + 9, c2, title, fnt(7.5, True), None, CENTER, border=False)
        for k, label in enumerate(("Nombre:", "DNI:")):
            box(ws, r + 10 + k, c1, r + 10 + k, c2, label, fnt(7, False, MUTED), None,
                Alignment(horizontal="left", vertical="bottom"), border=False)
            for c in range(c1, c2 + 1):
                ws.cell(r + 10 + k, c).border = Border(bottom=side(GRID))
            ws.row_dimensions[r + 10 + k].height = 18


# ── Vencimientos ───────────────────────────────────────────────────────────────


def expiry_groups(rows, end: dt.date):
    """Los cuatro grupos del reporte de vencimientos: (título, tinta, tinte, filas, campo de cantidad)."""
    months = lambda d: (d - end).days / 30.4375
    with_stock = [r for r in rows if r["STOCK_FIN"] > 0 and r["FEC_EXP"]]
    return [
        ("SALIERON POR VENCIMIENTO EN EL MES", INKT["venc"], TINT["venc"], [r for r in rows if r["VENCIDO"] > 0], "VENCIDO"),
        ("VENCIDOS QUE AÚN TIENEN STOCK", INKT["venc"], TINT["venc"], [r for r in with_stock if r["FEC_EXP"] <= end], "STOCK_FIN"),
        ("VENCEN EN LOS PRÓXIMOS 3 MESES", INKT["dev"], TINT["dev"], [r for r in with_stock if 0 < months(r["FEC_EXP"]) <= 3], "STOCK_FIN"),
        ("VENCEN ENTRE 3 Y 6 MESES", "7A5B00", "FFF8E1", [r for r in with_stock if 3 < months(r["FEC_EXP"]) <= 6], "STOCK_FIN"),
    ]


def expiry_sheet(wb, report: IciReport):
    ws = wb.create_sheet("Vencimientos")
    ws.sheet_view.showGridLines = False
    cols = [("CÓDIGO", 7), ("DESCRIPCIÓN", 40), ("UNIDAD", 8), ("LOTE", 13), ("VENCE", 10), ("MESES", 6.5),
            ("STOCK", 8.5), ("CONSUMO DEL MES", 9), ("PRECIO S/", 8.5), ("VALOR S/", 11)]
    for i, (_, w) in enumerate(cols, 1):
        ws.column_dimensions[L(i)].width = w
    nc = len(cols)
    end = report.hasta
    _title(ws, nc, "REPORTE DE VENCIMIENTOS", report,
           f"{report.title}  ·  Meses contados desde el cierre del mes ({end:%d/%m/%Y})")
    groups = expiry_groups(report.rows, end)

    r = 4
    box(ws, r, 1, r, 5, "RESUMEN", fnt(7.5, True, WHITE), NAVY, LEFT)
    box(ws, r, 6, r, 7, "LOTES", fnt(7.5, True, WHITE), NAVY, CENTER)
    box(ws, r, 8, r, 10, "VALOR S/", fnt(7.5, True, WHITE), NAVY, CENTER)
    for k, (title, ink, tint, items, qf) in enumerate(groups):
        rr = r + 1 + k
        box(ws, rr, 1, rr, 5, title.capitalize(), fnt(8, True, ink), tint, LEFT)
        box(ws, rr, 6, rr, 7, len(items), fnt(9, True, ink), tint, CENTER, fmt=INT0)
        box(ws, rr, 8, rr, 10, sum(t["PRECIO"] * t[qf] for t in items), fnt(9, True, ink), tint, RIGHT, fmt=MONEY)
        ws.row_dimensions[rr].height = 17
    r += 6
    for title, ink, tint, items, qf in groups:
        box(ws, r, 1, r, nc, f"{title}  ·  {len(items)} lotes", fnt(8, True, WHITE), NAVY, LEFT)
        r += 1
        for i, (h, _) in enumerate(cols, 1):
            box(ws, r, i, r, i, "SALIÓ" if (h == "STOCK" and qf == "VENCIDO") else h, fnt(7, True, NAVY), SOFT, CENTER)
        ws.row_dimensions[r].height = 22
        r += 1
        if not items:
            box(ws, r, 1, r, nc, "Sin lotes en este grupo.", fnt(7.5, False, MUTED, True), None, LEFT)
            r += 2
            continue
        start = r
        for t in sorted(items, key=lambda t: (t["FEC_EXP"] or end, -t["PRECIO"] * t[qf])):
            d = t["FEC_EXP"]
            values = [t["CODIGO_MED"], t["DESC"], t["MEDFF"], t["MEDLOTE"], _as_datetime(d),
                      round((d - end).days / 30.4375, 1) if d else None, t[qf], consumo(t), t["PRECIO"], f"=G{r}*I{r}"]
            for i, v in enumerate(values, 1):
                c = ws.cell(r, i, v)
                c.font = fnt(7.5, bold=i in (7, 10))
                c.border = BOX
                c.alignment = WRAP_LEFT if i == 2 else MID
                c.number_format = {5: "dd/mm/yyyy", 6: '0.0;-0.0;"–"', 7: INT0, 8: INT0, 9: PRICE, 10: "0.00"}.get(i, "General")
                if (r - start) % 2:
                    c.fill = fill(ZEBRA)
            ws.row_dimensions[r].height = 13 * lines(t["DESC"], 52)
            r += 1
        box(ws, r, 1, r, 9, "Total", fnt(7.5, True, ink), tint, RIGHT)
        box(ws, r, 10, r, 10, f"=SUM(J{start}:J{r - 1})", fnt(7.5, True, ink), tint, CENTER, fmt='"S/ "0.00')
        r += 2
    ws.print_title_rows = "1:2"
    _landscape(ws)
    _footer(ws, "Vencimientos", report)


# ── Alertas de farmacia y lotes sin movimiento ─────────────────────────────────


def alerts(rows):
    """(desabastecidos, 10 de mayor consumo en soles, consumo total en soles, lotes sin movimiento)."""
    products = collections.OrderedDict()
    for t in rows:
        p = products.setdefault(t["CODIGO_MED"], {"desc": t["DESC"], "ff": t["MEDFF"], "cons": 0.0, "val": 0.0,
                                                   "stock": 0.0, "saldo": 0.0, "ing": 0.0})
        p["cons"] += consumo(t)
        p["val"] += consumo(t) * t["PRECIO"]
        p["stock"] += t["STOCK_FIN"]
        p["saldo"] += t["SALDO"]
        p["ing"] += t["INGRE"] + t["REINGRE"] + t["ING_REGULA"]
    out = sorted(((k, v) for k, v in products.items() if v["cons"] > 0 and v["stock"] <= 0), key=lambda kv: -kv[1]["cons"])
    total = sum(v["val"] for v in products.values())
    top = sorted((kv for kv in products.items() if kv[1]["val"] > 0), key=lambda kv: -kv[1]["val"])[:10]
    still = sorted((t for t in rows if t["STOCK_FIN"] > 0 and not (t["INGRE"] + t["REINGRE"] + t["ING_REGULA"] + t["TOTAL"])),
                   key=lambda t: -t["STOCK_FIN"] * t["PRECIO"])
    return out, top, total, still


def alerts_sheet(wb, report: IciReport):
    ws = wb.create_sheet("Alertas de farmacia")
    ws.sheet_view.showGridLines = False
    widths = [8, 30, 18, 8, 13, 11, 11, 11, 11, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    nc = len(widths)
    _title(ws, nc, "ALERTAS DE FARMACIA", report, f"{report.title}  ·  Al cierre del {report.hasta:%d/%m/%Y}", split=3)
    out, top, total, still = alerts(report.rows)
    still_value = sum(t["STOCK_FIN"] * t["PRECIO"] for t in still)
    share = sum(v["val"] for _, v in top) / total * 100 if total else 0

    r = 4
    cards = [("PRODUCTOS DESABASTECIDOS", f"{len(out)}", "consumo en el mes y stock final cero", INKT["venc"], TINT["venc"]),
             ("10 DE MAYOR CONSUMO", f"{share:.1f} %", f"del consumo del mes (S/ {total:.2f})", INKT["cons"], TINT["cons"]),
             ("LOTES SIN MOVIMIENTO", f"{len(still)}", f"S/ {still_value:.2f} en stock sin entradas ni salidas", INKT["dev"], TINT["dev"])]
    for (title, value, hint, ink, tint), (c1, c2) in zip(cards, [(1, 2), (3, 6), (7, 10)]):
        box(ws, r, c1, r, c2, title, fnt(7.5, True, ink), tint, CENTER)
        box(ws, r + 1, c1, r + 1, c2, value, fnt(14, True, ink), tint, CENTER)
        box(ws, r + 2, c1, r + 2, c2, hint, fnt(7.5, False, ink), tint, CENTER)
    ws.row_dimensions[r + 1].height = 22
    r += 4

    def table(title, cols, data, note):
        nonlocal r
        box(ws, r, 1, r, nc, title, fnt(8, True, WHITE), NAVY, LEFT)
        r += 1
        box(ws, r, 1, r, nc, note, fnt(7, False, MUTED, True), None, LEFT, border=False)
        r += 1
        for h, c1, c2, _ in cols:
            box(ws, r, c1, r, c2, h, fnt(7, True, NAVY), SOFT, CENTER)
        ws.row_dimensions[r].height = 22
        r += 1
        if not data:
            box(ws, r, 1, r, nc, "Sin registros.", fnt(7.5, False, MUTED, True), None, LEFT)
            r += 2
            return
        desc_width = next(sum(widths[c - 1] for c in range(c1, c2 + 1)) for h, c1, c2, _ in cols if h == "DESCRIPCIÓN")
        for k, values in enumerate(data):
            for j, ((h, c1, c2, fmt), v) in enumerate(zip(cols, values)):
                box(ws, r, c1, r, c2, v, fnt(7.5, bold=j == len(cols) - 1), ZEBRA if k % 2 else None,
                    WRAP_LEFT if h == "DESCRIPCIÓN" else MID, fmt=fmt)
            ws.row_dimensions[r].height = 13 * lines(values[1], int(desc_width * 1.2))
            r += 1
        r += 1

    table(f"PRODUCTOS DESABASTECIDOS  ·  {len(out)}",
          [("CÓDIGO", 1, 1, None), ("DESCRIPCIÓN", 2, 5, None), ("UNIDAD", 6, 6, None), ("SALDO ANTERIOR", 7, 7, INT0),
           ("INGRESOS", 8, 8, INT0), ("CONSUMO DEL MES", 9, 9, INT0), ("STOCK FINAL", 10, 10, INT0)],
          [[k, v["desc"], v["ff"], v["saldo"], v["ing"], v["cons"], v["stock"]] for k, v in out],
          "Tuvieron consumo en el mes y terminaron con stock cero (sumando todos sus lotes). De mayor a menor consumo.")
    table("LOS 10 PRODUCTOS DE MAYOR CONSUMO EN SOLES",
          [("CÓDIGO", 1, 1, None), ("DESCRIPCIÓN", 2, 5, None), ("UNIDAD", 6, 6, None), ("CONSUMO DEL MES", 7, 7, INT0),
           ("VALOR S/", 8, 8, "0.00"), ("% DEL CONSUMO", 9, 9, "0.0%"), ("STOCK FINAL", 10, 10, INT0)],
          [[k, v["desc"], v["ff"], v["cons"], v["val"], (v["val"] / total) if total else 0, v["stock"]] for k, v in top],
          "Venta, SIS, intervención sanitaria y demás consumos, valorizados al precio de cada lote.")
    shown = still[:30]
    table(f"LOTES SIN MOVIMIENTO  ·  LOS {len(shown)} DE MAYOR VALOR  (de {len(still)} lotes, S/ {still_value:.2f})",
          [("CÓDIGO", 1, 1, None), ("DESCRIPCIÓN", 2, 3, None), ("UNIDAD", 4, 4, None), ("LOTE", 5, 5, None),
           ("VENCE", 6, 6, "dd/mm/yyyy"), ("STOCK", 7, 7, INT0), ("PRECIO S/", 8, 8, PRICE), ("VALOR S/", 9, 10, "0.00")],
          [[t["CODIGO_MED"], t["DESC"], t["MEDFF"], t["MEDLOTE"], _as_datetime(t["FEC_EXP"]), t["STOCK_FIN"], t["PRECIO"],
            t["STOCK_FIN"] * t["PRECIO"]] for t in shown],
          "Lotes con stock que no tuvieron ninguna entrada ni salida en el mes. De mayor a menor valor. "
          "La lista completa está en la hoja «Lotes sin movimiento».")
    ws.print_title_rows = "1:2"
    _landscape(ws)
    _footer(ws, "Alertas de farmacia", report)

    full = wb.create_sheet("Lotes sin movimiento")
    full.sheet_view.showGridLines = False
    header = ["CÓDIGO", "DESCRIPCIÓN", "UNIDAD", "LOTE", "VENCE", "STOCK", "PRECIO S/", "VALOR S/"]
    for i, (h, w) in enumerate(zip(header, [8, 52, 8, 14, 11, 9, 10, 12]), 1):
        full.column_dimensions[L(i)].width = w
    box(full, 1, 1, 1, len(header), f"LOTES SIN MOVIMIENTO  ·  {month_title(report)}  ·  {len(still)} lotes  ·  S/ {still_value:.2f}",
        fnt(11, True, WHITE), NAVY, LEFT, border=False)
    full.row_dimensions[1].height = 22
    for i, h in enumerate(header, 1):
        box(full, 2, i, 2, i, h, fnt(7.5, True, NAVY), SOFT, CENTER)
    for k, t in enumerate(still):
        rr = 3 + k
        values = [t["CODIGO_MED"], t["DESC"], t["MEDFF"], t["MEDLOTE"], _as_datetime(t["FEC_EXP"]), t["STOCK_FIN"], t["PRECIO"], f"=F{rr}*G{rr}"]
        for i, v in enumerate(values, 1):
            c = full.cell(rr, i, v)
            c.font, c.border = fnt(8, bold=i == 8), BOX
            c.alignment = WRAP_LEFT if i == 2 else MID
            c.number_format = {5: "dd/mm/yyyy", 6: INT0, 7: PRICE, 8: "0.00"}.get(i, "General")
            if k % 2:
                c.fill = fill(ZEBRA)
        full.row_dimensions[rr].height = 13 * lines(t["DESC"], 62)
    full.freeze_panes = "A3"
    full.auto_filter.ref = f"A2:H{2 + max(len(still), 1)}"
    full.print_title_rows = "1:2"
    _landscape(full)
    _footer(full, "Lotes sin movimiento", report)
    return {"desabastecidos": len(out), "sin_movimiento": len(still), "sin_movimiento_valor": still_value,
            "top10": share}


# ── Guías de ingreso y correcciones de lote ────────────────────────────────────


def _place_name(code: str, names: dict) -> str:
    name = names.get(code) or names.get(ipress_of(code)) or ""
    return f"{code} · {name}" if name else code or "—"


def _concept(code: str) -> str:
    """Solo el nombre del concepto («Distribución»), sin su número."""
    return CONCEPTOS.get(code, f"Concepto {code}" if code else "—")


# La referencia de la guía la escriben a mano en el almacén; normalmente dice de qué es.
REFERENCE_GROUPS = ("SISMED", "INTERVENCIÓN", "TRANSFERENCIAS")
OTHER_REFERENCES = "OTRAS REFERENCIAS"


def reference_group(reference: str) -> str:
    """«SISMED», «INTERVENCIÓN», «TRANSFERENCIAS» u «OTRAS REFERENCIAS», según lo que escribieron."""
    plain = unicodedata.normalize("NFKD", str(reference or "")).encode("ascii", "ignore").decode().upper()
    if "SISMED" in plain:
        return "SISMED"
    if "INTERV" in plain:
        return "INTERVENCIÓN"
    if "TRANSF" in plain:
        return "TRANSFERENCIAS"
    return OTHER_REFERENCES


def _guide_number(move: Movement) -> str:
    return move.doc_numero or move.numero


def _header_row(ws, r, header):
    for i, h in enumerate(header, 1):
        box(ws, r, i, r, i, h, fnt(7.5, True, NAVY), SOFT, CENTER)
    ws.row_dimensions[r].height = 22


def _data_rows(ws, r, data, formats):
    """Escribe las filas desde r y devuelve la fila siguiente."""
    for k, values in enumerate(data):
        rr = r + k
        for i, v in enumerate(values, 1):
            c = ws.cell(rr, i, v)
            c.font, c.border = fnt(8), BOX
            c.alignment = WRAP_LEFT if formats.get(i) == "text" else MID
            c.number_format = formats.get(i, "General") if formats.get(i) != "text" else "General"
            if k % 2:
                c.fill = fill(ZEBRA)
    return r + len(data)


def guides_sheet(wb, report: IciReport):
    ws = wb.create_sheet("Guías de ingreso")
    ws.sheet_view.showGridLines = False
    # En el consolidado también se dice a qué farmacia entró cada guía.
    columns = [("FECHA", 10, "dd/mm/yyyy"), ("N° DE GUÍA", 14, None), ("PROCEDENCIA", 38, "text"),
               ("CONCEPTO", 22, "text"), ("REFERENCIA", 26, "text")]
    if report.consolidated:
        columns.append(("FARMACIA", 9, None))
    columns += [("ÍTEMS", 7, INT0), ("VALOR S/", 12, MONEY)]
    header = [c[0] for c in columns]
    formats = {i: c[2] for i, c in enumerate(columns, 1) if c[2]}
    nc = len(columns)
    for i, c in enumerate(columns, 1):
        ws.column_dimensions[L(i)].width = c[1]
    total = sum(m.valor or 0 for m in report.guias)
    _title(ws, nc, "GUÍAS DE INGRESO", report,
           f"{report.title}  ·  {len(report.guias)} guías  ·  S/ {total:.2f}  ·  Del {report.desde:%d/%m/%Y} al {report.hasta:%d/%m/%Y}", split=2)

    groups = {name: [] for name in REFERENCE_GROUPS}
    for move in report.guias:
        groups.setdefault(reference_group(move.referencia), []).append(move)
    if not groups.get(OTHER_REFERENCES):
        groups.pop(OTHER_REFERENCES, None)

    # Resumen por referencia
    r = 4
    box(ws, r, 1, r, nc - 2, "RESUMEN POR REFERENCIA", fnt(7.5, True, WHITE), NAVY, LEFT)
    box(ws, r, nc - 1, r, nc - 1, "GUÍAS", fnt(7.5, True, WHITE), NAVY, CENTER)
    box(ws, r, nc, r, nc, "VALOR S/", fnt(7.5, True, WHITE), NAVY, CENTER)
    for name, moves in groups.items():
        r += 1
        box(ws, r, 1, r, nc - 2, name.capitalize(), fnt(8, True), SOFT, LEFT)
        box(ws, r, nc - 1, r, nc - 1, len(moves), fnt(8.5, True), None, CENTER, fmt=INT0)
        box(ws, r, nc, r, nc, sum(m.valor or 0 for m in moves), fnt(8.5, True), None, CENTER, fmt=MONEY)
    r += 1
    box(ws, r, 1, r, nc - 2, "Total", fnt(8, True, WHITE), NAVY, RIGHT)
    box(ws, r, nc - 1, r, nc - 1, len(report.guias), fnt(8.5, True, WHITE), NAVY, CENTER, fmt=INT0)
    box(ws, r, nc, r, nc, total, fnt(8.5, True, WHITE), NAVY, CENTER, fmt=MONEY)
    r += 2

    value_col = L(nc)
    for name, moves in groups.items():
        box(ws, r, 1, r, nc, f"{name}  ·  {len(moves)} guías", fnt(8, True, WHITE), NAVY, LEFT)
        r += 1
        if not moves:
            box(ws, r, 1, r, nc, "Sin guías con esta referencia.", fnt(7.5, False, MUTED, True), None, LEFT)
            r += 2
            continue
        _header_row(ws, r, header)
        r += 1
        start = r
        data = []
        for m in moves:
            row = [_as_datetime(m.fecha), _guide_number(m), _place_name(m.origen, report.names), _concept(m.concepto),
                   m.referencia or "—"]
            if report.consolidated:
                row.append(m.destino[-3:])
            data.append(row + [len(m.lines), m.valor])
        r = _data_rows(ws, r, data, formats)
        box(ws, r, 1, r, nc - 1, "Subtotal", fnt(7.5, True, NAVY), SOFT, RIGHT)
        box(ws, r, nc, r, nc, f"=SUM({value_col}{start}:{value_col}{r - 1})", fnt(7.5, True, NAVY), SOFT, CENTER, fmt=MONEY)
        r += 2
    ws.print_title_rows = "1:2"
    _landscape(ws)
    _footer(ws, "Guías de ingreso", report)


def corrections_sheet(wb, report: IciReport, products: dict):
    ws = wb.create_sheet("Correcciones de lote")
    ws.sheet_view.showGridLines = False
    columns = [("FECHA", 10, "dd/mm/yyyy"), ("N° DE GUÍA", 13, None), ("FARMACIA", 9, None), ("MOVIMIENTO", 11, None),
               ("CONCEPTO", 20, "text"), ("REFERENCIA", 22, "text"), ("CÓDIGO", 8, None), ("DESCRIPCIÓN", 38, "text"),
               ("LOTE", 14, None), ("VENCIMIENTO", 11, "dd/mm/yyyy"), ("CANTIDAD", 9, INT0)]
    nc = len(columns)
    for i, c in enumerate(columns, 1):
        ws.column_dimensions[L(i)].width = c[1]
    _title(ws, nc, "CORRECCIONES DE LOTE", report,
           f"{report.title}  ·  Guías con las que un producto salió y volvió a entrar en la misma farmacia (para cambiarle "
           "el lote o el código). En el ICI quedan en Devolución y Reingreso.", split=2)
    if not report.corrections:
        box(ws, 4, 1, 4, nc, "Sin correcciones de lote en el mes.", fnt(7.5, False, MUTED, True), None, LEFT)
    else:
        _header_row(ws, 4, [c[0] for c in columns])
        # El vencimiento sale del detalle de la guía; si no lo trae, del lote en el ICI.
        expiry = {(r["CODIGO_MED"], r["MEDLOTE"]): r["FEC_EXP"] for r in report.rows if r["FEC_EXP"]}
        data = []
        for m in sorted(report.corrections, key=lambda m: (m.fecha or dt.date.min, m.doc_numero, m.tipo != "S")):
            for line in m.lines:
                data.append([_as_datetime(m.fecha), _guide_number(m), m.origen[-3:], "Salida" if m.tipo == "S" else "Entrada",
                             _concept(m.concepto), m.referencia or "—", line.code, products.get(line.code, ""), line.lote,
                             _as_datetime(line.vence or expiry.get((line.code, line.lote))), line.qty])
        _data_rows(ws, 5, data, {i: c[2] for i, c in enumerate(columns, 1) if c[2]})
        ws.freeze_panes = "A5"
    ws.print_title_rows = "1:4"
    _landscape(ws)
    _footer(ws, "Correcciones de lote", report)


def build_workbook(report: IciReport) -> tuple[Workbook, dict]:
    """Arma el libro completo. Devuelve (libro, cifras para mostrar en la consola)."""
    wb = Workbook()
    ici_sheet(wb, report)
    expiry_sheet(wb, report)
    summary = alerts_sheet(wb, report)
    guides_sheet(wb, report)
    corrections_sheet(wb, report, {r["CODIGO_MED"]: r["DESC"] for r in report.rows})
    wb.active = 0
    return wb, summary


def _safe_name(value: str) -> str:
    cleaned = "".join("-" if ch in '<>:"/\\|?*' else ch for ch in str(value))
    return " ".join(cleaned.split()).strip(" .")[:90]


def write_reports(month, out_dir: str, consolidated: bool = True, per_pharmacy: bool = True, pdf: bool = True,
                  log=print, open_exporter=None) -> list[str]:
    """Escribe un libro por farmacia y el consolidado de cada establecimiento, cada uno en Excel y
    en PDF (todas las hojas, para imprimir). Devuelve las rutas de todos los archivos."""
    import os

    from ici_data import balance_errors, month_label

    label = month_label(month.annomes)
    paths = []
    exporter = None
    if pdf:
        if open_exporter is None:
            from ici_pdf import open_exporter
        exporter = open_exporter(log=log)
        if exporter is not None:
            log(f"📄 Los PDF se arman con {exporter.name}.")

    def save(report, file_name):
        bad = balance_errors(report.rows)
        if bad:
            log(f"⚠️ {bad} lotes de {report.title} no cuadran (saldo + entradas − salidas ≠ stock final).")
        wb, summary = build_workbook(report)
        path = os.path.join(out_dir, f"{_safe_name(file_name)}.xlsx")
        wb.save(path)
        paths.append(path)
        log(f"✅ {os.path.basename(path)}  ·  {len(report.rows)} lotes · {summary['desabastecidos']} desabastecidos · "
            f"{summary['sin_movimiento']} lotes sin movimiento")
        if exporter is not None:
            pdf_path = path[:-len(".xlsx")] + ".pdf"
            try:
                exporter.export(path, pdf_path)
                paths.append(pdf_path)
                log(f"📄 {os.path.basename(pdf_path)}")
            except Exception as exc:  # noqa: BLE001 - el Excel ya quedó; se avisa y se sigue
                log(f"⚠️ No se pudo pasar a PDF {os.path.basename(path)}: {exc}")

    try:
        _write_all(month, consolidated, per_pharmacy, save, log, label)
    finally:
        if exporter is not None:
            exporter.close()
    return paths


def _write_all(month, consolidated, per_pharmacy, save, log, label):
    from ici_data import consolidated_report, pharmacy_report

    for est in month.establishments:
        if consolidated and len(est.pharmacies) > 1:
            report = consolidated_report(month, est)
            if report.internal_value:
                kind = "estimado por lote" if report.internal_estimated else "según las guías"
                log(f"🔁 {est.name}: entregas entre farmacias descontadas, S/ {report.internal_value:.2f} ({kind}).")
            save(report, f"ICI CONSOLIDADO {label} - {est.code} - {est.name}")
        if per_pharmacy or len(est.pharmacies) == 1:
            for ph in est.pharmacies:
                save(pharmacy_report(month, est, ph), f"ICI {label} - {ph.code} - {ph.name}")
