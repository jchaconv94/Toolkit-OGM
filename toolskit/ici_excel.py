"""Generar ICI: el libro de Excel con el diseño aprobado por el usuario el 2026-10-19.

Hojas, en este orden: ICI (para imprimir horizontal y firmar), Guías de ingreso, Vencimientos,
Alertas de farmacia, Lotes sin movimiento y Correcciones de lote.

Se arman dos versiones del mismo libro: la de Excel (para revisarla en la PC: filtro en el ICI,
paneles fijos) y la de imprimir, que se pasa a PDF. En la de imprimir cada hoja ya viene cortada
en páginas y cada tabla repite su encabezado al empezar una página nueva (`Page`): el PDF que
armaba el Excel de la PC no repetía los «títulos de impresión» (2026-10-19).

Decisiones del usuario que no hay que deshacer (docs/ICI_SISMED.md del ToolKit SISMED Web):
cifras sin separador de miles (con coma parecía decimal), precios completos, la misma letra en
todas las descripciones (un nombre largo pasa a otra línea), «–» en lugar de cero, encabezado
de columnas en cada página, firmas solo con la línea y el cargo, fecha automática y sin lugar, y la
columna de ajuste de inventario que entra solo si algún lote la tiene.
"""

from __future__ import annotations

import collections
import datetime as dt
import difflib
import re

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.pagebreak import Break

from ici_data import CONSUMO, CONCEPTOS, MESES, IciReport, Movement, VALORES_FIELDS, ipress_of, plain_text

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
# Cifras: si no caben en la columna se achican en vez de salir como «####».
NUM = Alignment(horizontal="center", vertical="center", shrink_to_fit=True)


def side(color=GRID, style="thin"):
    return Side(style=style, color=color)


BOX = Border(left=side(), right=side(), top=side(), bottom=side())


def fill(color):
    return PatternFill("solid", fgColor=color)


def fnt(size=8, bold=False, color=INK, italic=False):
    return Font(name=F, size=size, bold=bold, color=color, italic=italic)


# (encabezado, ancho, grupo, campo, tinte)
# Anchos para que en el Excel cada dato se lea entero (código, unidad, lote, registro sanitario,
# vencimiento y precio sin cortarse ni achicarse; pedido del usuario del 2026-10-19). El PDF ajusta
# la hoja al ancho de la página.
COLS = [
    ("CÓDIGO", 6.6, "P", "CODIGO_MED", None), ("DESCRIPCIÓN", 46, "P", "DESC", None),
    ("UNIDAD", 7.4, "P", "MEDFF", None), ("LOTE", 12.5, "P", "MEDLOTE", None),
    ("REG. SANITARIO", 12, "P", "MEDREGSAN", None), ("VENCIMIENTO", 8.8, "P", "FEC_EXP", None),
    ("TIP. SUM.", 3.8, "P", "TIPSUM2", None), ("F. FINAN.", 4.4, "P", "FFINAN", None),
    ("PRECIO S/", 8.8, "P", "PRECIO", None),
    ("SALDO MES ANTERIOR", 6.8, "S", "SALDO", None),
    ("INGRESOS", 6.4, "E", "INGRE", "in"), ("REINGRESOS", 6.4, "E", "REINGRE", "in"),
    ("VENTA", 5.8, "C", "VENTA", "cons"), ("S.I.S.", 6.2, "C", "SIS", "cons"),
    ("INTERV. SANITARIA", 5.8, "C", "INTERSAN", "cons"), ("F. PÉRDIDA (ZOONOSIS)", 5.0, "C", "FAC_PERD", "cons"),
    ("DEFENSA NACIONAL", 5.0, "C", "DEFNAC", "cons"), ("EXONERACIÓN", 5.0, "C", "EXO", "cons"),
    ("SOAT", 5.0, "C", "SOAT", "cons"), ("CRÉDITO HOSP.", 5.0, "C", "CREDHOSP", "cons"),
    ("OTROS CONVENIOS", 5.0, "C", "OTR_CONV", "cons"),
    ("DEVOLUCIÓN", 6.4, "O", "DEVOL", "dev"), ("VENCIDOS", 5.4, "O", "VENCIDO", "venc"),
    ("MERMA", 5.0, "O", "MERMA", "dev"), ("OTRAS SALIDAS", 5.0, "O", "OTRAS", "dev"),
    ("REGULA.", 5.0, "O", "SAL_REGULA", "dev"), ("CONS. INSTITUC.", 5.0, "O", "SAL_CONINS", "dev"),
    ("TOTAL SALIDAS", 6.8, "T", "=TOTAL", None), ("STOCK FINAL", 7.2, "T", "=STOCK", None),
]
GROUPS = {"P": "PRODUCTO FARMACÉUTICO", "S": "SALDO", "E": "ENTRADAS", "C": "CONSUMOS",
          "O": "OTRAS SALIDAS", "T": "SALDO FINAL"}
# Ajuste de inventario que entra (concepto 21): en toda la región estuvo siempre en cero, así que
# la columna solo aparece si algún lote del mes lo tiene (si no, el stock no cuadraría a la vista).
ADJUST_COL = ("AJUSTE DE INVENTARIO (+)", 5.0, "E", "ING_REGULA", "in")
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
    """Líneas que ocupa un texto en su celda, cortando por palabras como lo hace Excel."""
    count, used = 1, 0
    for word in str(value or "").split():
        extra = len(word) + (1 if used else 0)
        if used and used + extra > per_line:
            count += 1
            used = len(word)
        else:
            used += extra
        while used > per_line:
            count += 1
            used -= per_line
    return count


def row_height(text, width, size=7.5):
    """Alto de fila para que un texto largo se vea completo en su columna.

    Calculado para nombres en mayúsculas (los del SISMED): en Arial entran unos 8,4 / tamaño de
    letra caracteres por unidad de ancho de columna, con un poco de margen. Mejor que sobre un poco
    a que el nombre quede cortado (pasó con 1,2 caracteres por unidad a 7,2 puntos)."""
    per_line = max(6, int((width - 1.5) * 8.4 / size))
    return max(13.0, lines(text, per_line) * size * 1.5 + 3)


A4_LANDSCAPE = (842.0, 595.0)  # puntos


class Page:
    """Lo que entra en cada página impresa (A4 horizontal, a todo el ancho de la hoja).

    Una hoja más ancha que la página se imprime «ajustada a una página de ancho»: el programa que
    arma el PDF calcula la escala justa y la tabla llena el ancho (con una escala calculada aquí,
    en el Excel del usuario sobraba espacio a los costados, porque Excel dibuja las columnas unos
    5 píxeles más angostas que LibreOffice). Una hoja angosta se agranda con una escala fija. En la
    versión de imprimir, `keep` corta la página antes de una fila que ya no entra y repite el
    encabezado de su tabla.

    Lo que entra por página depende de quién dibuja el PDF: `printable` es «toolkit» (lo dibuja
    ici_render con estas mismas medidas, así cada página llega exacta hasta abajo), «libreoffice» o
    «excel» (también WPS), que dibujan las columnas a su manera; True usa las medidas del Toolkit."""

    COLUMN_PADDING = {"toolkit": 0, "excel": 5, "libreoffice": 5}   # píxeles que se suman a 7 × ancho

    def __init__(self, ws, widths, printable, margins=(0.3, 0.3, 0.4, 0.45), max_scale=150):
        self.ws, self.printable, self.margins = ws, bool(printable), margins
        engine = printable if isinstance(printable, str) else "toolkit"
        self.exact = engine == "toolkit"
        # Una columna de ancho w mide 7 × w píxeles (ici_render dibuja así); Excel y LibreOffice la
        # imprimen unos 5 píxeles más ancha (medido en el PDF de Excel del usuario, 2026-10-19).
        width_pt = sum(w * 7 + self.COLUMN_PADDING.get(engine, 0) for w in widths) * 0.75
        usable_width = A4_LANDSCAPE[0] - (margins[0] + margins[1]) * 72
        fit = usable_width / width_pt
        self.fit_width = fit < 1
        if self.exact:
            # ici_render usa la escala exacta al ajustar al ancho; la fija, en enteros como Excel.
            self.scale = fit * 100 if self.fit_width else max(10, min(max_scale, int(fit * 100)))
        else:
            self.scale = int(fit * 100) if self.fit_width else max(10, min(max_scale, int(fit * 94)))
        usable_height = (A4_LANDSCAPE[1] - (margins[2] + margins[3]) * 72) * (0.999 if self.exact else 0.97)
        self.capacity = usable_height * 100 / max(self.scale, 1)
        self.used = 0.0
        self.counted = 0

    def _height(self, r):
        height = self.ws.row_dimensions[r].height
        return 15.0 if height is None else height

    def _count_until(self, r):
        for k in range(self.counted + 1, r):
            self.used += self._height(k)
        self.counted = max(self.counted, r - 1)

    def keep(self, r, height, header=None) -> int:
        """Antes de escribir en la fila r algo de `height` puntos que no debe partirse. Si no entra en
        lo que queda de la página (solo en la versión de imprimir), corta la página y escribe el
        encabezado con `header(r)`, que devuelve la fila siguiente. Devuelve dónde seguir."""
        if not self.printable:
            return r
        self._count_until(r)
        if self.used > 0 and self.used + height > self.capacity:
            self.ws.row_breaks.append(Break(id=r - 1))
            self.used = 0.0
            if header is not None:
                r = header(r)
                self._count_until(r)
        return r

    def force(self, r, header=None) -> int:
        """Corta la página antes de la fila r (si no es ya el comienzo de una) y repite el encabezado."""
        if not self.printable:
            return r
        self._count_until(r)
        if self.used > 0:
            self.ws.row_breaks.append(Break(id=r - 1))
            self.used = 0.0
            if header is not None:
                r = header(r)
                self._count_until(r)
        return r

    def tail_break(self, r, heights, header_height, tail_height, keep_rows=4):
        """Dónde cortar para que el pie (totales, notas, declaración y firmas) no quede solo en la última
        página: si no entra después de la última fila, se lleva consigo las últimas filas de la tabla.
        Devuelve el índice de la fila antes de la cual cortar, o None si no hace falta."""
        if not self.printable or not heights:
            return None
        self._count_until(r)
        used = self.used
        for h in heights:
            if used > 0 and used + h > self.capacity:
                used = header_height
            used += h
        if used + tail_height <= self.capacity:
            return None
        k, total = 0, header_height + tail_height
        for h in reversed(heights):
            if k >= keep_rows or total + h > self.capacity:
                break
            total += h
            k += 1
        return len(heights) - k if k else None

    def setup(self, label, report, titles=None):
        ws = self.ws
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        if self.fit_width:
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        else:
            ws.sheet_properties.pageSetUpPr.fitToPage = False
            ws.page_setup.scale = int(self.scale)
        left, right, top, bottom = self.margins
        ws.page_margins = PageMargins(left=left, right=right, top=top, bottom=bottom, footer=0.2)
        ws.print_options.horizontalCentered = True
        if titles and not self.printable:
            ws.print_title_rows = titles  # en la de imprimir el encabezado ya va repetido
        _footer(ws, label, report)


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


def _title(ws, nc, title, report: IciReport, subtitle: str, size=14, split=4):
    # El mes va en las últimas columnas: tantas como hagan falta para que entre entero («AGOSTO 2026»
    # salía como «GOSTO 2026» en las Guías de ingreso, que terminan en dos columnas angostas).
    room = lambda k: sum(ws.column_dimensions[L(c)].width or 8.43 for c in range(nc - k + 1, nc + 1))
    need = len(month_title(report)) * size * 0.65 / 5.25 + 3     # una unidad de ancho mide 5,25 puntos
    while split < nc - 1 and room(split) < need:
        split += 1
    box(ws, 1, 1, 1, nc - split, title, fnt(size, True, WHITE), NAVY, LEFT, border=False)
    box(ws, 1, nc - split + 1, 1, nc, month_title(report), fnt(size, True, WHITE), NAVY, RIGHT, border=False)
    ws.row_dimensions[1].height = 28
    box(ws, 2, 1, 2, nc, subtitle, fnt(8, False, "D6E2EE"), NAVY2, LEFT, border=False)


# ── Hoja ICI ───────────────────────────────────────────────────────────────────


def ici_sheet(wb, report: IciReport, printable=False):
    rows = report.rows
    C = Columns(rows)
    IX, NCOL = C.ix, C.n
    widths = [c[1] for c in C.cols]
    ws = wb.active
    ws.title = "ICI"
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable, margins=(0.25, 0.25, 0.35, 0.45))

    box(ws, 1, 1, 1, NCOL - 8, "INFORME DE CONSUMO INTEGRADO  ·  ICI", fnt(15, True, WHITE), NAVY, LEFT, border=False)
    box(ws, 1, NCOL - 7, 1, NCOL, month_title(report), fnt(15, True, WHITE), NAVY, RIGHT, border=False)
    ws.row_dimensions[1].height = 30
    box(ws, 2, 1, 2, NCOL, "Declaración del movimiento de medicamentos, insumos y productos sanitarios  ·  "
        f"Periodo del {report.desde:%d/%m/%Y} al {report.hasta:%d/%m/%Y}",
        fnt(8, False, "D6E2EE"), NAVY2, LEFT, border=False)
    ws.row_dimensions[2].height = 16
    ws.row_dimensions[3].height = 6

    def header(r):
        """Fila de grupos y fila de encabezados de columna (se repite en cada página impresa)."""
        start = 1
        for i in range(2, NCOL + 2):
            if i == NCOL + 1 or C.cols[i - 1][2] != C.cols[start - 1][2]:
                box(ws, r, start, r, i - 1, GROUPS[C.cols[start - 1][2]], fnt(7, True, WHITE), NAVY, CENTER)
                start = i
        for i, c in enumerate(C.cols, 1):
            box(ws, r + 1, i, r + 1, i, c[0], fnt(6.8, True, WHITE), NAVY2,
                Alignment(horizontal="center", vertical="center", wrap_text=True, text_rotation=90 if c[1] < 9 else 0))
        ws.row_dimensions[r].height = 15
        ws.row_dimensions[r + 1].height = 72
        return r + 2

    # Sin filas vacías entre los encabezados y los datos (pedido del usuario). En el Excel, la fila
    # 14 lleva las letras de columna con el filtro y los datos empiezan en la 15; en la versión de
    # imprimir no hay letras y los datos empiezan en la 14. Allí llevan dentro los encabezados
    # repetidos, así que la última fila se conoce al terminar de escribirlos.
    gr, rr, letters = 11, 13, 14
    first = letters if printable else letters + 1
    header(gr)
    if not printable:
        # Letras de columna con el filtro de Excel, para filtrar rápido (pedido del usuario).
        for i in range(1, NCOL + 1):
            box(ws, letters, i, letters, i, L(i), fnt(6.5, True, MUTED), SOFT, MID)
        ws.row_dimensions[letters].height = 14

    total_formula = lambda r: f"=SUM({L(IX['VENTA'])}{r}:{L(IX['SAL_CONINS'])}{r})"
    stock_formula = lambda r: ("=" + "+".join(f"{L(IX[f])}{r}" for f in ("SALDO", "INGRE", "REINGRE", "ING_REGULA") if f in IX)
                               + f"-{L(IX['=TOTAL'])}{r}")
    notes = ["Colores:  ingresos y reingresos en azul · consumos en verde · devoluciones y otras salidas en ámbar · "
             "vencidos en rojo · vencimiento en rojo si el lote ya venció con stock y en ámbar si vence en los próximos 6 meses."]
    if report.valores:
        notes.append("Venta, S.I.S., intervención sanitaria y el consumo total en soles: los que calculó el SISMED (cada venta "
                     "a su precio del día), más otros convenios y factor de pérdida, que el SISMED no guarda; esos y los "
                     "demás montos, cantidad × precio de cada lote.")
    if report.consolidated:
        if report.internal_estimated:
            notes.append(f"Consolidado: se descontaron, estimadas por lote, las entregas entre farmacias del establecimiento "
                         f"(S/ {report.internal_value:.2f} de devolución y reingreso del mismo lote).")
        elif report.internal_value:
            notes.append(f"Consolidado: se descontaron las entregas entre farmacias del establecimiento (S/ {report.internal_value:.2f}).")
        if report.in_transit > 0.005:
            notes.append(f"Entregado a otra farmacia del establecimiento y todavía no recibido al cierre del mes: "
                         f"S/ {report.in_transit:.2f} (queda como salida).")

    heights = [row_height(row["DESC"], C.cols[IX["DESC"] - 1][1], 7.2) for row in rows]
    # La declaración jurada y las firmas van con las últimas filas, nunca solas en una página.
    tail = 16 + NOTE_HEIGHT * len(notes) + 4 + SIGNATURE_HEIGHT
    cut = page.tail_break(first, heights, 15 + 72, tail)
    r = first
    for k, (row, height) in enumerate(zip(rows, heights)):
        r = page.force(r, header) if k == cut else page.keep(r, height, header)
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
            cell.alignment = (Alignment(horizontal="left", vertical="center", wrap_text=True) if fld == "DESC"
                              else MID if fld in TEXT_FIELDS else NUM)
            if fld == "FEC_EXP":
                cell.number_format = "dd/mm/yyyy"
            elif fld == "PRECIO":
                cell.number_format = PRICE
            elif fld not in TEXT_FIELDS:
                cell.number_format = INT0
            if k % 2:
                cell.fill = fill(ZEBRA)
        ws.row_dimensions[r].height = height
        r += 1
    if not rows:
        box(ws, r, 1, r, NCOL, "Sin lotes en el mes.", fnt(7.5, False, MUTED, True), None, LEFT)
        r += 1
    lastr = r - 1

    R = lambda f: f"${L(IX[f])}${first}:${L(IX[f])}${lastr}"
    P = R("PRECIO")
    # SUMPRODUCT toma como cero el texto de los encabezados repetidos de la versión de imprimir.
    SP = lambda *fs: "+".join(f"SUMPRODUCT({P},{R(f)})" for f in fs if f in IX)

    # Bloque A: datos del establecimiento
    box(ws, 4, 1, 4, 9, "DATOS DEL ESTABLECIMIENTO", fnt(7.5, True, WHITE), NAVY, LEFT)
    for k, (label, value) in enumerate(list(report.ficha.items())[:5]):
        box(ws, 5 + k, 1, 5 + k, 2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, 5 + k, 3, 5 + k, 9, value, fnt(8, True), None, LEFT)
    # Bloque B: resumen valorizado
    box(ws, 4, 11, 4, 22, "RESUMEN VALORIZADO DEL MES (S/)", fnt(7.5, True, WHITE), NAVY, LEFT)
    # Los consumos en soles son los del SISMED (TFORMATO), que valoriza cada venta a su precio del día:
    # así coinciden con su pantalla. Sin TFORMATO, cantidad × precio de cada lote.
    # Otros convenios y factor de pérdida no los graba el SISMED: esos, cantidad × precio del lote.
    def consumed(*fields):
        if not report.valores:
            return "=" + SP(*fields)
        fixed = round(sum(report.valores[CONSUMO.index(f)] for f in fields if f in VALORES_FIELDS), 2)
        rest = SP(*(f for f in fields if f not in VALORES_FIELDS))
        return f"={fixed}+{rest}" if rest else fixed

    left = [("Saldo anterior", "=" + SP("SALDO")), ("Ingresos", "=" + SP("INGRE", "ING_REGULA")),
            ("Reingresos", "=" + SP("REINGRE")), ("Consumo total", consumed(*CONSUMO)),
            ("Stock final", f"=SUMPRODUCT({P},{R('=STOCK')})")]
    right = [("Venta", consumed("VENTA")), ("S.I.S.", consumed("SIS")), ("Interv. sanitaria", consumed("INTERSAN")),
             ("Devoluciones", "=" + SP("DEVOL")), ("Vencidos", "=" + SP("VENCIDO"))]
    for k in range(5):
        for (label, value), (c1, c2, c3) in ((left[k], (11, 13, 16)), (right[k], (17, 19, 22))):
            strong = label in ("Stock final", "Consumo total")
            box(ws, 5 + k, c1, 5 + k, c2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
            box(ws, 5 + k, c2 + 1, 5 + k, c3, value,
                fnt(8.5 if strong else 8, True, INKT["venc"] if label == "Vencidos" else INK), None, RIGHT, fmt=MONEY)
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
        box(ws, 5 + k, 24, 5 + k, NCOL - 2, label, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, 5 + k, NCOL - 1, 5 + k, NCOL, value, fnt(8.5, True, color), None, CENTER, fmt=INT0)
    ws.row_dimensions[10].height = 6

    # Recetas bajo sus columnas y, bajo las otras salidas, cuántos lotes las tuvieron
    box(ws, rr, 1, rr, IX["VENTA"] - 1, "N° DE RECETAS (CONSUMOS)  ·  N° DE LOTES (OTRAS SALIDAS)",
        fnt(7, True, INKT["cons"]), TINT["cons"], RIGHT)
    for f, value in zip(CONSUMO, report.recetas):
        box(ws, rr, IX[f], rr, IX[f], value, fnt(7.5, True, INKT["cons"]), TINT["cons"], NUM, fmt=INT0)
    for f in ("DEVOL", "VENCIDO", "MERMA", "OTRAS", "SAL_REGULA", "SAL_CONINS"):
        box(ws, rr, IX[f], rr, IX[f], f"=COUNTIF({R(f)},\">0\")", fnt(7.5, True, INKT["dev"]), TINT["dev"], NUM, fmt=INT0)
    box(ws, rr, IX["=TOTAL"], rr, NCOL, None, None, TINT["cons"])
    ws.row_dimensions[rr].height = 18

    if rows:
        for tint in ("in", "cons", "dev", "venc"):
            for i in (i for i, c in enumerate(C.cols, 1) if c[4] == tint):
                col = L(i)
                ws.conditional_formatting.add(f"{col}{first}:{col}{lastr}", FormulaRule(
                    formula=[f"AND(ISNUMBER({col}{first}),{col}{first}>0)"], fill=fill(TINT[tint]),
                    font=Font(name=F, color=INKT[tint], bold=True)))
        E, S = L(IX["FEC_EXP"]), L(IX["=STOCK"])
        expired = f"AND(ISNUMBER({E}{first}),{S}{first}>0,{E}{first}<={pe})"
        soon = f"AND(ISNUMBER({E}{first}),{S}{first}>0,{E}{first}>{pe},{E}{first}<=EDATE({pe},6))"
        ws.conditional_formatting.add(f"{E}{first}:{E}{lastr}", FormulaRule(
            formula=[expired], fill=fill(TINT["venc"]), font=Font(name=F, color=INKT["venc"], bold=True)))
        ws.conditional_formatting.add(f"{E}{first}:{E}{lastr}", FormulaRule(
            formula=[soon], fill=fill(TINT["dev"]), font=Font(name=F, color=INKT["dev"], bold=True)))

    tr = page.keep(lastr + 1, 16, header)
    box(ws, tr, 1, tr, IX["PRECIO"], f"TOTAL  ·  {len(rows)} lotes", fnt(7.5, True, WHITE), NAVY, RIGHT)
    for i in range(IX["SALDO"], NCOL + 1):
        # SUBTOTAL: en el Excel, al filtrar, el total es de lo que se ve.
        total = f"=SUM({L(i)}{first}:{L(i)}{lastr})" if printable else f"=SUBTOTAL(9,{L(i)}{first}:{L(i)}{lastr})"
        box(ws, tr, i, tr, i, total, fnt(7.2, True, WHITE), NAVY, NUM, fmt=INT0)
    ws.row_dimensions[tr].height = 16

    r = tr + 1
    for note in notes:
        box(ws, r, 1, r, NCOL, note, fnt(6.5, False, MUTED, True), None, LEFT, border=False)
        ws.row_dimensions[r].height = NOTE_HEIGHT
        r += 1
    ws.row_dimensions[r].height = 4
    # La declaración jurada y las firmas no se parten entre dos páginas.
    r = page.keep(r + 1, SIGNATURE_HEIGHT)
    _signature(ws, r, widths, page)

    if not printable:
        ws.freeze_panes = ws.cell(first, 3)
        ws.auto_filter.ref = f"A{letters}:{L(NCOL)}{lastr}"
    page.setup("ICI", report, titles=f"{gr}:{gr + 1}")
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


# Espacio para firmar sobre la línea (pedido del usuario: con 28 puntos quedaba pegada a la tabla).
SIGN_SPACE = 64
# Compactas, para que entren más seguido en la página de las últimas filas.
SIGNATURE_HEIGHT = 15 + 2 * 12 + 14 + 6 + SIGN_SPACE + 12   # solo la línea y el cargo (sin nombre ni DNI)
NOTE_HEIGHT = 12


def _signature(ws, r, widths, page=None):
    """Declaración jurada, fecha y las dos firmas centradas en el ancho de la hoja, en poco alto para
    que entren en la misma página que el final de la tabla. En el PDF, las firmas van al pie de la página,
    justo encima del pie (pedido del usuario, 2026-10-20): el espacio antes de ellas llena lo que sobra."""
    ncol = len(widths)
    box(ws, r, 1, r, ncol, "DECLARACIÓN JURADA", fnt(8, True, WHITE), NAVY, LEFT)
    ws.row_dimensions[r].height = 15
    statement = ("Declaramos bajo juramento que la información consignada en el presente Informe de Consumo Integrado "
                 "corresponde al movimiento real de medicamentos, insumos y productos sanitarios de la farmacia durante "
                 "el periodo indicado, que se encuentra registrada en el SISMED y que el stock final declarado coincide "
                 "con las existencias físicas al cierre del mes.")
    box(ws, r + 1, 1, r + 2, ncol, statement, fnt(7.5), None,
        Alignment(horizontal="justify", vertical="center", wrap_text=True, indent=1))
    ws.row_dimensions[r + 1].height = ws.row_dimensions[r + 2].height = 12
    box(ws, r + 3, 1, r + 3, ncol, f"Fecha: {date_in_words(dt.date.today())}", fnt(7.5, True), None, LEFT, border=False)
    ws.row_dimensions[r + 3].height = 14
    spacer = 6
    if page is not None and page.printable:
        page._count_until(r + 4)                          # lo usado hasta la fecha, en esta página
        spacer = max(spacer, page.capacity - page.used - SIGN_SPACE - 12 - 1)
    ws.row_dimensions[r + 4].height = spacer
    ws.row_dimensions[r + 5].height = SIGN_SPACE          # espacio para firmar, sobre la línea
    for (c1, c2), title in zip(signature_blocks(widths), ("RESPONSABLE DE FARMACIA", "JEFE DEL ESTABLECIMIENTO")):
        for c in range(c1, c2 + 1):
            ws.cell(r + 5, c).border = Border(bottom=side(INK))
        box(ws, r + 6, c1, r + 6, c2, title, fnt(7.5, True), None, CENTER, border=False)
        ws.row_dimensions[r + 6].height = 12


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


def _section(ws, page, r, nc, title, header_row, first_height):
    """Título de una tabla y su fila de encabezados, sin dejarlos solos al pie de una página.
    Devuelve (fila siguiente, función que repite título y encabezados en una página nueva)."""
    def repeat(rr, suffix="  ·  continuación"):
        box(ws, rr, 1, rr, nc, title + suffix, fnt(8, True, WHITE), NAVY, LEFT)
        ws.row_dimensions[rr].height = 15
        header_row(rr + 1)
        return rr + 2

    r = page.keep(r, 15 + 22 + first_height)
    return repeat(r, ""), repeat


def _cells_header(ws, r, header):
    for i, h in enumerate(header, 1):
        box(ws, r, i, r, i, h, fnt(7, True, NAVY), SOFT, CENTER)
    ws.row_dimensions[r].height = 22


def expiry_sheet(wb, report: IciReport, printable=False):
    ws = wb.create_sheet("Vencimientos")
    ws.sheet_view.showGridLines = False
    cols = [("CÓDIGO", 7), ("DESCRIPCIÓN", 40), ("UNIDAD", 8), ("LOTE", 13), ("VENCE", 10), ("MESES", 6.5),
            ("STOCK", 8.5), ("CONSUMO DEL MES", 9), ("PRECIO S/", 8.5), ("VALOR S/", 11)]
    widths = [w for _, w in cols]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    nc = len(cols)
    page = Page(ws, widths, printable)
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
        header = ["SALIÓ" if (h == "STOCK" and qf == "VENCIDO") else h for h, _ in cols]
        ordered = sorted(items, key=lambda t: (t["FEC_EXP"] or end, -t["PRECIO"] * t[qf]))
        first_height = row_height(ordered[0]["DESC"], 40) if ordered else 15
        r, repeat = _section(ws, page, r, nc, f"{title}  ·  {len(items)} lotes",
                             lambda rr: _cells_header(ws, rr, header), first_height)
        if not items:
            box(ws, r, 1, r, nc, "Sin lotes en este grupo.", fnt(7.5, False, MUTED, True), None, LEFT)
            r += 2
            continue
        start = r
        for k, t in enumerate(ordered):
            height = row_height(t["DESC"], 40)
            r = page.keep(r, height, repeat)
            d = t["FEC_EXP"]
            values = [t["CODIGO_MED"], t["DESC"], t["MEDFF"], t["MEDLOTE"], _as_datetime(d),
                      round((d - end).days / 30.4375, 1) if d else None, t[qf], consumo(t), t["PRECIO"], f"=G{r}*I{r}"]
            for i, v in enumerate(values, 1):
                c = ws.cell(r, i, v)
                c.font = fnt(7.5, bold=i in (7, 10))
                c.border = BOX
                c.alignment = WRAP_LEFT if i == 2 else (NUM if i >= 5 else MID)
                c.number_format = {5: "dd/mm/yyyy", 6: '0.0;-0.0;"–"', 7: INT0, 8: INT0, 9: PRICE, 10: "0.00"}.get(i, "General")
                if k % 2:
                    c.fill = fill(ZEBRA)
            ws.row_dimensions[r].height = height
            r += 1
        r = page.keep(r, 15, repeat)
        box(ws, r, 1, r, 9, "Total", fnt(7.5, True, ink), tint, RIGHT)
        box(ws, r, 10, r, 10, f"=SUM(J{start}:J{r - 1})", fnt(7.5, True, ink), tint, CENTER, fmt='"S/ "0.00')
        r += 2
    page.setup("Vencimientos", report, titles="1:2")


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


def alerts_sheet(wb, report: IciReport, printable=False):
    ws = wb.create_sheet("Alertas de farmacia")
    ws.sheet_view.showGridLines = False
    widths = [8, 30, 18, 8, 13, 11, 11, 11, 11, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    nc = len(widths)
    page = Page(ws, widths, printable)
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
        desc_width = next(sum(widths[c - 1] for c in range(c1, c2 + 1)) for h, c1, c2, _ in cols if h == "DESCRIPCIÓN")
        heights = [row_height(values[1], desc_width) for values in data]

        def header_row(rr):
            for h, c1, c2, _ in cols:
                box(ws, rr, c1, rr, c2, h, fnt(7, True, NAVY), SOFT, CENTER)
            ws.row_dimensions[rr].height = 22

        r = page.keep(r, 15 + 15 + 22 + (heights[0] if heights else 15))
        box(ws, r, 1, r, nc, title, fnt(8, True, WHITE), NAVY, LEFT)
        box(ws, r + 1, 1, r + 1, nc, note, fnt(7, False, MUTED, True), None, LEFT, border=False)
        header_row(r + 2)
        r += 3

        def repeat(rr):
            box(ws, rr, 1, rr, nc, f"{title}  ·  continuación", fnt(8, True, WHITE), NAVY, LEFT)
            ws.row_dimensions[rr].height = 15
            header_row(rr + 1)
            return rr + 2

        if not data:
            box(ws, r, 1, r, nc, "Sin registros.", fnt(7.5, False, MUTED, True), None, LEFT)
            r += 2
            return
        for k, (values, height) in enumerate(zip(data, heights)):
            r = page.keep(r, height, repeat)
            for j, ((h, c1, c2, fmt), v) in enumerate(zip(cols, values)):
                box(ws, r, c1, r, c2, v, fnt(7.5, bold=j == len(cols) - 1), ZEBRA if k % 2 else None,
                    WRAP_LEFT if h == "DESCRIPCIÓN" else (NUM if fmt else MID), fmt=fmt)
            ws.row_dimensions[r].height = height
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
    page.setup("Alertas de farmacia", report, titles="1:2")
    return {"desabastecidos": len(out), "sin_movimiento": len(still), "sin_movimiento_valor": still_value,
            "top10": share}, still, still_value


def still_sheet(wb, report: IciReport, still, still_value, printable=False):
    ws = wb.create_sheet("Lotes sin movimiento")
    ws.sheet_view.showGridLines = False
    header = ["CÓDIGO", "DESCRIPCIÓN", "UNIDAD", "LOTE", "VENCE", "STOCK", "PRECIO S/", "VALOR S/"]
    widths = [8, 52, 8, 14, 11, 9, 10, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable)
    box(ws, 1, 1, 1, len(header), f"LOTES SIN MOVIMIENTO  ·  {month_title(report)}  ·  {len(still)} lotes  ·  S/ {still_value:.2f}",
        fnt(11, True, WHITE), NAVY, LEFT, border=False)
    ws.row_dimensions[1].height = 22

    def header_row(rr):
        _cells_header(ws, rr, header)
        return rr + 1

    r = header_row(2)
    for k, t in enumerate(still):
        height = row_height(t["DESC"], 52, 8)
        r = page.keep(r, height, header_row)
        values = [t["CODIGO_MED"], t["DESC"], t["MEDFF"], t["MEDLOTE"], _as_datetime(t["FEC_EXP"]), t["STOCK_FIN"], t["PRECIO"], f"=F{r}*G{r}"]
        for i, v in enumerate(values, 1):
            c = ws.cell(r, i, v)
            c.font, c.border = fnt(8, bold=i == 8), BOX
            c.alignment = WRAP_LEFT if i == 2 else (NUM if i >= 5 else MID)
            c.number_format = {5: "dd/mm/yyyy", 6: INT0, 7: PRICE, 8: "0.00"}.get(i, "General")
            if k % 2:
                c.fill = fill(ZEBRA)
        ws.row_dimensions[r].height = height
        r += 1
    if not printable:
        ws.freeze_panes = "A3"
        ws.auto_filter.ref = f"A2:H{max(r - 1, 3)}"
    page.setup("Lotes sin movimiento", report, titles="1:2")


# ── Guías de ingreso e ingresos internos ───────────────────────────────────────


def _place_name(code: str, names: dict) -> str:
    name = names.get(code) or names.get(ipress_of(code)) or ""
    return f"{code} · {name}" if name else code or "—"


def _concept(code: str, concepts: dict | None = None) -> str:
    """Solo el nombre del concepto («Distribución»), sin su número; el del SISMED si no está en la lista."""
    if code in CONCEPTOS:
        return CONCEPTOS[code]
    name = (concepts or {}).get(code)
    return name.capitalize() if name else (f"Concepto {code}" if code else "—")


# La referencia de la guía la escriben a mano en el almacén; normalmente dice de qué es.
REFERENCE_GROUPS = ("SISMED", "ESTRATEGIA", "TRANSFERENCIAS")
OTHER_REFERENCES = "OTRAS REFERENCIAS"


def reference_group(reference: str) -> str:
    """«SISMED», «ESTRATEGIA», «TRANSFERENCIAS» u «OTRAS REFERENCIAS», según lo que escribieron.

    En la UNGET del usuario los productos estratégicos llevan la referencia «ESTRATEGIA»; también
    se reconoce mal escrita («ESTRAGIA : REGULARIZACION», «ESTRATEJIA») y «INTERVENCIÓN», por si
    otra UNGET la escribe así. Si dice estrategia y SISMED, va a estrategia."""
    plain = plain_text(reference)
    words = re.findall(r"[A-Z]+", plain)
    looks = lambda word, target: difflib.SequenceMatcher(None, word, target).ratio() >= 0.75
    if any(w.startswith(("ESTRA", "INTERV")) or looks(w, "ESTRATEGIA") for w in words):
        return "ESTRATEGIA"
    if "SISMED" in plain or any(looks(w, "SISMED") for w in words):
        return "SISMED"
    if any(w.startswith("TRANSF") or looks(w, "TRANSFERENCIA") for w in words):
        return "TRANSFERENCIAS"
    return OTHER_REFERENCES


def _guide_number(move: Movement) -> str:
    return move.doc_numero or move.numero


def _data_row(ws, r, values, formats, zebra):
    for i, v in enumerate(values, 1):
        c = ws.cell(r, i, v)
        c.font, c.border = fnt(8), BOX
        c.alignment = WRAP_LEFT if formats.get(i) == "text" else (NUM if formats.get(i) else MID)
        c.number_format = formats.get(i, "General") if formats.get(i) != "text" else "General"
        if zebra:
            c.fill = fill(ZEBRA)


def _text_height(values, columns):
    """Alto de la fila según el texto más largo de sus columnas de texto."""
    return max([row_height(v, c[1], 8) for v, c in zip(values, columns) if c[2] == "text" and v] or [15.0])


def _field_height(v1, v2) -> float:
    return max(15.0, row_height(v1, 30, 8), row_height(v2, 40, 8))


def _block_height(fields) -> float:
    """Alto de la banda y los datos de una guía, para no separarlos de su primer producto."""
    return 16 + sum(_field_height(v1, v2) for _, v1, _, v2 in fields)


def _block_header(ws, r, nc, title, fields):
    """Banda con el título de la guía y, debajo, sus datos en pares etiqueta / valor (dos por fila).
    `fields` son tuplas (etiqueta, valor, etiqueta, valor); las columnas: 1 · 2-3 · 4 · 5 en adelante."""
    box(ws, r, 1, r, nc, title, fnt(8.5, True, WHITE), NAVY, LEFT)
    ws.row_dimensions[r].height = 16
    for k, (l1, v1, l2, v2) in enumerate(fields, 1):
        box(ws, r + k, 1, r + k, 1, l1, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, r + k, 2, r + k, 3, v1, fnt(8, True), None, WRAP_LEFT)
        box(ws, r + k, 4, r + k, 4, l2, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, r + k, 5, r + k, nc, v2, fnt(8, True), None, WRAP_LEFT)
        ws.row_dimensions[r + k].height = _field_height(v1, v2)
    return r + 1 + len(fields)


def _span_row(ws, r, spans, values, zebra, bold_last=False, tints=None):
    """Una fila de una tabla cuyas columnas ocupan varias columnas de la hoja: spans = (encabezado, desde,
    hasta, formato); formato «text» alinea a la izquierda."""
    for j, ((_, c1, c2, fmt), v) in enumerate(zip(spans, values)):
        tint = (tints or {}).get(j)
        cell = box(ws, r, c1, r, c2, v, fnt(8, bold=(bold_last and j == len(spans) - 1) or bool(tint),
                                            color=INKT["fix"] if tint else INK),
                   tint or (ZEBRA if zebra else None), WRAP_LEFT if fmt == "text" else (NUM if fmt else MID))
        if fmt and fmt != "text":
            cell.number_format = fmt


def _span_header(ws, r, spans):
    for h, c1, c2, _ in spans:
        box(ws, r, c1, r, c2, h, fnt(7, True, NAVY), SOFT, CENTER)
    ws.row_dimensions[r].height = 22
    return r + 1


def _span_height(spans, values, widths):
    heights = [row_height(v, sum(widths[c1 - 1:c2]), 8) for (_, c1, c2, fmt), v in zip(spans, values)
               if fmt == "text" and v]
    return max(heights or [15.0])


def _move_line(m: Movement, report: IciReport) -> str:
    """«GD 0000632 · 13/08/2026 · Devolución por sobrestock · ref. CORRECCION DE LOTE»."""
    parts = [f"Guía {_guide_number(m)}"]
    if m.fecha:
        parts.append(f"{m.fecha:%d/%m/%Y}")
    parts.append(_concept(m.concepto, report.concepts))
    if m.referencia:
        parts.append(f"ref. {m.referencia}")
    return "  ·  ".join(parts)


def guides_sheet(wb, report: IciReport, products: dict, printable=False):
    """Ingresos del mes en tres partes: desde el almacén (por referencia), desde otras farmacias del
    establecimiento y otros ingresos (productos recuperados y demás), estos con todo su detalle."""
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
    widths = [c[1] for c in columns]
    nc = len(columns)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable)
    total = sum(m.valor or 0 for m in report.guias)
    _title(ws, nc, "GUÍAS DE INGRESO", report,
           f"{report.title}  ·  {len(report.guias)} guías  ·  S/ {total:.2f}  ·  Del {report.desde:%d/%m/%Y} al {report.hasta:%d/%m/%Y}", split=2)

    groups = {name: [] for name in REFERENCE_GROUPS}
    for move in report.guias:      # solo lo que llegó del almacén por distribución
        groups.setdefault(reference_group(move.referencia), []).append(move)
    if not groups.get(OTHER_REFERENCES):
        groups.pop(OTHER_REFERENCES, None)

    # Resumen
    summary = [(f"Desde el almacén · {name.capitalize()}", moves) for name, moves in groups.items()]
    r = 4
    box(ws, r, 1, r, nc - 2, "RESUMEN DE INGRESOS", fnt(7.5, True, WHITE), NAVY, LEFT)
    box(ws, r, nc - 1, r, nc - 1, "GUÍAS", fnt(7.5, True, WHITE), NAVY, CENTER)
    box(ws, r, nc, r, nc, "VALOR S/", fnt(7.5, True, WHITE), NAVY, CENTER)
    for label, moves in summary:
        r += 1
        box(ws, r, 1, r, nc - 2, label, fnt(8, True), SOFT, LEFT)
        box(ws, r, nc - 1, r, nc - 1, len(moves), fnt(8.5, True), None, CENTER, fmt=INT0)
        box(ws, r, nc, r, nc, sum(m.valor or 0 for m in moves), fnt(8.5, True), None, CENTER, fmt=MONEY)
    r += 1
    box(ws, r, 1, r, nc - 2, "Total", fnt(8, True, WHITE), NAVY, RIGHT)
    box(ws, r, nc - 1, r, nc - 1, len(report.guias), fnt(8.5, True, WHITE), NAVY, CENTER, fmt=INT0)
    box(ws, r, nc, r, nc, total, fnt(8.5, True, WHITE), NAVY, CENTER, fmt=MONEY)
    r += 2

    value_col = L(nc)

    def guide_table(r, title, moves, empty):
        data = []
        for m in moves:
            row = [_as_datetime(m.fecha), _guide_number(m), _place_name(m.origen, report.names),
                   _concept(m.concepto, report.concepts), m.referencia or "—"]
            if report.consolidated:
                row.append(m.destino[-3:])
            data.append(row + [len(m.lines), m.valor])
        heights = [_text_height(values, columns) for values in data]
        r, repeat = _section(ws, page, r, nc, f"{title}  ·  {len(moves)} guías", lambda rr: _cells_header(ws, rr, header),
                             heights[0] if heights else 15)
        if not moves:
            box(ws, r, 1, r, nc, empty, fnt(7.5, False, MUTED, True), None, LEFT)
            return r + 2
        start = r
        for k, (values, height) in enumerate(zip(data, heights)):
            r = page.keep(r, height, repeat)
            _data_row(ws, r, values, formats, k % 2)
            ws.row_dimensions[r].height = height
            r += 1
        r = page.keep(r, 15, repeat)
        box(ws, r, 1, r, nc - 1, "Subtotal", fnt(7.5, True, NAVY), SOFT, RIGHT)
        box(ws, r, nc, r, nc, f"=SUM({value_col}{start}:{value_col}{r - 1})", fnt(7.5, True, NAVY), SOFT, CENTER, fmt=MONEY)
        return r + 2

    for name, moves in groups.items():
        r = guide_table(r, f"DESDE EL ALMACÉN · {name}", moves, "Sin guías con esta referencia.")

    page.setup("Guías de ingreso", report, titles="1:2")


GAP = 6   # alto de la fila vacía entre los datos de una guía y la tabla de sus productos


def internal_sheet(wb, report: IciReport, products: dict, printable=False):
    """Ingresos internos (antes «Correcciones de lote»; regla del usuario, 2026-10-19): todo lo que entró
    a la columna REINGRESO —la devolución por sobrestock y demás que ingresó el responsable de farmacia
    para hacer algún cambio— y lo que entregó otra farmacia del establecimiento."""
    _guide_detail_sheet(
        wb, report, products, printable, "Ingresos internos", report.internos,
        "Reingresos (devolución por sobrestock y demás) que ingresó la farmacia y lo que entregó otra farmacia del "
        "establecimiento. La referencia dice qué se cambió.", "Sin ingresos internos en el mes.")


def returns_sheet(wb, report: IciReport, products: dict, printable=False):
    """Salidas por devolución (pedido del usuario, 2026-10-19): lo que cae en la columna DEVOLUCIÓN del ICI
    —devolución por sobrestock, por RS cancelado y demás—; las de vencido (concepto 35) van a Vencidos y
    no entran."""
    _guide_detail_sheet(
        wb, report, products, printable, "Salidas por devolución", report.devoluciones,
        "Lo que salió por devolución (columna DEVOLUCIÓN del ICI): devolución por sobrestock, por RS cancelado y demás. "
        "La referencia dice por qué.", "Sin salidas por devolución en el mes.")


def _guide_detail_sheet(wb, report: IciReport, products: dict, printable, name: str, moves, subtitle: str, empty: str):
    """Guía por guía: origen y destino, concepto y referencia (ahí escriben el motivo o el cambio, va
    resaltada) y el detalle de sus productos."""
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    columns = [("CÓDIGO", 10), ("DESCRIPCIÓN", 52), ("LOTE", 14), ("VENCIMIENTO", 12), ("REG. SANITARIO", 13),
               ("CANTIDAD", 10), ("VALOR S/", 12)]
    widths = [w for _, w in columns]
    nc = len(columns)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable)
    total = sum(m.valor or 0 for m in moves)
    _title(ws, nc, name.upper(), report, f"{report.title}  ·  {len(moves)} guías  ·  S/ {total:.2f}  ·  {subtitle}", split=2)
    if not moves:
        box(ws, 4, 1, 4, nc, empty, fnt(7.5, False, MUTED, True), None, LEFT)
        page.setup(name, report, titles="1:2")
        return
    spans = [(h, i, i, fmt) for i, (h, fmt) in enumerate(
        [("CÓDIGO", None), ("DESCRIPCIÓN", "text"), ("LOTE", None), ("VENCIMIENTO", "dd/mm/yyyy"),
         ("REG. SANITARIO", None), ("CANTIDAD", INT0), ("VALOR S/", MONEY)], 1)]
    value_col = L(nc)
    r = 4
    for m in moves:
        title = f"GUÍA N° {_guide_number(m)}" + (f"  ·  {m.fecha:%d/%m/%Y}" if m.fecha else "")
        fields = [("Origen", _place_name(m.origen, report.names) if m.origen else "—",
                   "Destino", _place_name(m.destino, report.names) if m.destino else "—"),
                  ("Concepto", _concept(m.concepto, report.concepts), "Referencia", m.referencia or "—")]
        items = [[line.code, products.get(line.code, ("", ""))[0], line.lote, _as_datetime(line.vence), line.regsan,
                  line.qty, line.total] for line in m.lines]
        heights = [_span_height(spans, values, widths) for values in items]

        def repeat(rr, title=title):
            box(ws, rr, 1, rr, nc, f"{title}  ·  continuación", fnt(8, True, WHITE), NAVY, LEFT)
            ws.row_dimensions[rr].height = 15
            return _span_header(ws, rr + 1, spans)

        r = page.keep(r, _block_height(fields) + GAP + 22 + (heights[0] if heights else 15))
        r = _block_header(ws, r, nc, title, fields)
        ws.cell(r - 1, 5).font = fnt(8.5, True, INKT["fix"])      # la referencia, que es lo que se revisa
        ws.row_dimensions[r].height = GAP                          # separa los datos de la guía de sus productos
        r = _span_header(ws, r + 1, spans)
        start = r
        for k, (values, height) in enumerate(zip(items, heights)):
            r = page.keep(r, height, repeat)
            _span_row(ws, r, spans, values, k % 2, bold_last=True)
            ws.row_dimensions[r].height = height
            r += 1
        r = page.keep(r, 15, repeat)
        box(ws, r, 1, r, nc - 1, "Total de la guía", fnt(7.5, True, NAVY), SOFT, RIGHT)
        box(ws, r, nc, r, nc, f"=SUM({value_col}{start}:{value_col}{r - 1})", fnt(7.5, True, NAVY), SOFT, CENTER, fmt=MONEY)
        r += 2
    page.setup(name, report, titles="1:2")


RECETA_COLUMNS = (("VENTA", "VENTA"), ("SIS", "S.I.S."), ("INTERSAN", "INTERV. SANITARIA"), ("EXO", "EXONERACIÓN"),
                  ("SOAT", "SOAT"), ("CREDHOSP", "CRÉDITO HOSP."), ("OTR_CONV", "OTROS CONVENIOS"))
RECETA_LABELS = {"VENTA": "Venta", "S.I.S.": "S.I.S.", "INTERV. SANITARIA": "Intervención sanitaria",
                 "EXONERACIÓN": "Exoneración", "SOAT": "SOAT", "CRÉDITO HOSP.": "Crédito hospitalario",
                 "OTROS CONVENIOS": "Otros convenios"}
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def recetas_sheet(wb, report: IciReport, printable=False):
    """Recetas (dispensaciones) por día y tipo de atención, con su valor, contadas como el SISMED: una
    venta o ticket es una receta. Al pie, el total que guardó el ICI (TFORMATO) para comparar. A la
    derecha, el resumen del mes: cuántas, cuánto valen, días con atención y promedio, el día con más
    recetas, cada tipo de atención con su parte y cada día de la semana con su promedio (pedido del
    usuario del 2026-10-19: la hoja era «muy simple»)."""
    ws = wb.create_sheet("Recetas diarias")
    ws.sheet_view.showGridLines = False
    header = ["FECHA", "DÍA", *[h for _, h in RECETA_COLUMNS], "TOTAL", "VALOR S/"]
    nt = len(header)                       # columnas de la tabla por día
    side = nt + 2                          # primera columna del resumen (con una angosta de separación)
    widths = [10.5, 10, *[10] * len(RECETA_COLUMNS), 8.5, 11, 2, 22, 9.5, 9.5, 11]
    nc = len(widths)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable, max_scale=95)
    _title(ws, nc, "RECETAS DIARIAS", report,
           f"{report.title}  ·  Recetas atendidas por día y tipo de atención (cada venta o ticket del SISMED es una receta)",
           split=3)
    ws.row_dimensions[3].height = 6
    if not report.recetas_diarias:
        box(ws, 4, 1, 4, nc, "Sin datos: el SISMED no tiene las ventas ni los movimientos del mes (TVENTA, TMOVIM).",
            fnt(7.5, False, MUTED, True), None, LEFT)
        page.setup("Recetas diarias", report, titles="1:2")
        return

    def header_row(rr):
        for i, h in enumerate(header, 1):
            box(ws, rr, i, rr, i, h, fnt(7, True, NAVY), SOFT, CENTER)
        ws.row_dimensions[rr].height = 22
        return rr + 1

    first = header_row(4)
    r = first
    idx = [CONSUMO.index(key) for key, _ in RECETA_COLUMNS]
    days = report.recetas_diarias
    for k, (day, counts, value, _) in enumerate(days):
        r = page.keep(r, 12.4, header_row)
        values = [_as_datetime(day), DIAS[day.weekday()], *[counts[i] for i in idx],
                  f"=SUM(C{r}:{L(2 + len(idx))}{r})", value]
        for i, v in enumerate(values, 1):
            cell = ws.cell(r, i, v)
            cell.font = fnt(8, bold=i in (nt - 1, nt), color=MUTED if day.weekday() >= 5 and i <= 2 else INK)
            cell.border = BOX
            cell.alignment = MID if i <= 2 else NUM
            cell.number_format = {1: "dd/mm/yyyy", nt: MONEY}.get(i, INT0)
            if day.weekday() >= 5:
                cell.fill = fill(SOFT)
            elif k % 2:
                cell.fill = fill(ZEBRA)
        ws.row_dimensions[r].height = 12.4
        r += 1
    last = r - 1
    r = page.keep(r, 48, header_row)
    box(ws, r, 1, r, 2, "Total del mes", fnt(8, True, WHITE), NAVY, RIGHT)
    for i in range(3, nt + 1):
        box(ws, r, i, r, i, f"=SUM({L(i)}{first}:{L(i)}{last})", fnt(8, True, WHITE), NAVY, CENTER,
            fmt=MONEY if i == nt else INT0)
    by_type = [sum(c[i] for _, c, _, _ in days) for i in idx]
    value_by_type = [sum(v[i] for _, _, _, v in days) for i in idx]
    total = sum(by_type)
    total_value = sum(value for _, _, value, _ in days)
    box(ws, r + 1, 1, r + 1, 2, "% del total", fnt(7.5, True, MUTED), SOFT, RIGHT)
    for j, n in enumerate(by_type):
        box(ws, r + 1, 3 + j, r + 1, 3 + j, n / total if total else 0, fnt(7.5, True, INKT["cons"]), SOFT, CENTER,
            fmt='0.0%;-0.0%;"–"')
    box(ws, r + 1, 3 + len(idx), r + 1, nt, None, None, SOFT)
    official = [report.recetas[i] for i in idx]
    box(ws, r + 2, 1, r + 2, 2, "Según el ICI (TFORMATO)", fnt(7.5, True, MUTED), SOFT, RIGHT)
    for j, v in enumerate(official):
        box(ws, r + 2, 3 + j, r + 2, 3 + j, v, fnt(8, True), SOFT, CENTER, fmt=INT0)
    box(ws, r + 2, 3 + len(official), r + 2, 3 + len(official), sum(official), fnt(8, True), SOFT, CENTER, fmt=INT0)
    box(ws, r + 2, nt, r + 2, nt, None, None, SOFT)
    for k in (1, 2):
        ws.row_dimensions[r + k].height = 14
    if not total and any(official):
        box(ws, r + 3, 1, r + 3, nt, "No se encontraron las dispensaciones del mes en el SISMED (TVENTA ni TMOVIM); "
            "la consola del Toolkit dice qué almacenes trae, para revisarlo.", fnt(7, False, INKT["dev"], True), None, LEFT,
            border=False)
    elif by_type != [int(v) for v in official]:
        box(ws, r + 3, 1, r + 3, nt, "El total por día no coincide con el ICI: el ICI se procesó antes de que se registraran "
            "o anularan algunas dispensaciones del mes.", fnt(7, False, INKT["dev"], True), None, LEFT, border=False)

    # ── Resumen a la derecha, en las mismas filas de la tabla ──
    def section(rr, title, cols=None):
        box(ws, rr, side, rr, nc, title, fnt(7.5, True, WHITE), NAVY, LEFT)
        if cols:
            for j, h in enumerate(cols):
                box(ws, rr + 1, side + j, rr + 1, side + j, h, fnt(7, True, NAVY), SOFT, CENTER if j else LEFT)
        return rr + (2 if cols else 1)

    attended = [d for d in days if sum(d[1][i] for i in idx)]
    busiest = max(days, key=lambda d: sum(d[1][i] for i in idx)) if attended else None
    rr = section(first - 1, "RESUMEN DEL MES")
    kpis = [
        ("Recetas atendidas", total, INT0),
        ("Valor de lo dispensado", total_value, '"S/ "0.00'),
        ("Valor promedio por receta", total_value / total if total else 0, '"S/ "0.00;-0.00;"–"'),
        ("Días con atención", f"{len(attended)} de {len(days)}", None),
        ("Promedio por día de atención", total / len(attended) if attended else 0, '0.0;-0.0;"–"'),
        ("Día con más recetas", (f"{busiest[0]:%d/%m} ({DIAS[busiest[0].weekday()].lower()}) · "
                                 f"{sum(busiest[1][i] for i in idx)}") if busiest else "–", None),
    ]
    for label, value, fmt in kpis:
        box(ws, rr, side, rr, side, label, fnt(7.5, True, MUTED), SOFT, LEFT)
        box(ws, rr, side + 1, rr, nc, value, fnt(8.5, True), None, RIGHT, fmt=fmt)
        rr += 1
    rr = section(rr + 1, "POR TIPO DE ATENCIÓN", ["TIPO", "RECETAS", "%", "VALOR S/"])
    for (_, name), n, v in zip(RECETA_COLUMNS, by_type, value_by_type):
        box(ws, rr, side, rr, side, RECETA_LABELS.get(name, name), fnt(7.5), None, LEFT)
        box(ws, rr, side + 1, rr, side + 1, n, fnt(8, True), None, CENTER, fmt=INT0)
        box(ws, rr, side + 2, rr, side + 2, n / total if total else 0, fnt(7.5), None, CENTER, fmt='0.0%;-0.0%;"–"')
        box(ws, rr, side + 3, rr, side + 3, v, fnt(7.5), None, CENTER, fmt=MONEY)
        rr += 1
    rr = section(rr + 1, "POR DÍA DE LA SEMANA", ["DÍA", "DÍAS", "RECETAS", "PROMEDIO"])
    for wd, name in enumerate(DIAS):
        same = [d for d in days if d[0].weekday() == wd]
        n = sum(sum(d[1][i] for i in idx) for d in same)
        weekend = wd >= 5
        box(ws, rr, side, rr, side, name, fnt(7.5, color=MUTED if weekend else INK), SOFT if weekend else None, LEFT)
        box(ws, rr, side + 1, rr, side + 1, len(same), fnt(7.5), SOFT if weekend else None, CENTER, fmt=INT0)
        box(ws, rr, side + 2, rr, side + 2, n, fnt(8, True), SOFT if weekend else None, CENTER, fmt=INT0)
        box(ws, rr, side + 3, rr, side + 3, n / len(same) if same else 0, fnt(7.5), SOFT if weekend else None, CENTER,
            fmt='0.0;-0.0;"–"')
        rr += 1
    page.setup("Recetas diarias", report, titles="1:2")


TIPO_ATENCION = {"VENTA": "Venta", "SIS": "S.I.S.", "INTERSAN": "Interv. sanitaria", "EXO": "Exoneración",
                 "SOAT": "SOAT", "CREDHOSP": "Crédito hospitalario", "OTR_CONV": "Otros convenios",
                 "DEFNAC": "Defensa nacional", "FAC_PERD": "Factor de pérdida"}


def _moment(value):
    """(fecha, hora) de una venta: la hora solo si el SISMED la guardó."""
    if isinstance(value, dt.datetime):
        return _as_datetime(value.date()), (value.strftime("%H:%M") if value.time() != dt.time() else "—")
    if isinstance(value, dt.date):
        return _as_datetime(value), "—"
    return None, "—"


def _cancelled_by_type(ws, page, r, nc, anuladas) -> int:
    """Al final de las anuladas, cuántas hay de cada tipo de atención y cuánto valen (pedido del usuario,
    2026-10-20)."""
    by_type = collections.OrderedDict()
    for x in anuladas:
        n, value = by_type.get(x.column, (0, 0.0))
        by_type[x.column] = (n + 1, value + x.total)
    order = [c for c in CONSUMO if c in by_type]
    r = page.keep(r, 15 + 18 + 13.5 * (len(order) + 1))
    box(ws, r, 1, r, 5, "ANULADAS POR TIPO DE ATENCIÓN", fnt(7.5, True, WHITE), NAVY, LEFT)
    ws.row_dimensions[r].height = 15
    for (c1, c2), h in zip(((1, 3), (4, 4), (5, 5)), ("TIPO DE ATENCIÓN", "RECETAS", "VALOR S/")):
        box(ws, r + 1, c1, r + 1, c2, h, fnt(7, True, NAVY), SOFT, CENTER)
    ws.row_dimensions[r + 1].height = 18
    r += 2
    for k, column in enumerate(order):
        n, value = by_type[column]
        box(ws, r, 1, r, 3, TIPO_ATENCION.get(column, column), fnt(7.5), ZEBRA if k % 2 else None, LEFT)
        box(ws, r, 4, r, 4, n, fnt(8, True), ZEBRA if k % 2 else None, CENTER, fmt=INT0)
        box(ws, r, 5, r, 5, round(value, 2), fnt(7.5), ZEBRA if k % 2 else None, NUM, fmt=MONEY)
        ws.row_dimensions[r].height = 13.5
        r += 1
    box(ws, r, 1, r, 3, "Total", fnt(7.5, True, WHITE), NAVY, RIGHT)
    box(ws, r, 4, r, 4, len(anuladas), fnt(8, True, WHITE), NAVY, CENTER, fmt=INT0)
    box(ws, r, 5, r, 5, round(sum(x.total for x in anuladas), 2), fnt(7.5, True, WHITE), NAVY, NUM, fmt=MONEY)
    ws.row_dimensions[r].height = 13.5
    return r + 2


def control_sheet(wb, report: IciReport, printable=False):
    """Control de recetas (pedido del usuario, 2026-10-20): cada receta anulada del mes y cada receta SIS
    sin FUA, una por una."""
    ws = wb.create_sheet("Control de recetas")
    ws.sheet_view.showGridLines = False
    widths = [10, 7, 15, 16, 10, 34, 24, 14]
    if report.consolidated:
        widths.append(9)
    nc = len(widths)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    page = Page(ws, widths, printable)
    anuladas, sin_fua = report.anuladas, report.sin_fua
    tipos = " y ".join(TIPO_ATENCION.get(t, t) for t in report.fua_tipos) or "S.I.S."
    _title(ws, nc, "CONTROL DE RECETAS", report,
           f"{report.title}  ·  Recetas anuladas y recetas sin FUA ({tipos}), de las ventas del SISMED", split=3)
    ws.row_dimensions[3].height = 6
    if not report.ventas:
        box(ws, 4, 1, 4, nc, "Sin datos: el SISMED no tiene las ventas del mes (TVENTA).", fnt(7.5, False, MUTED, True), None, LEFT)
        page.setup("Control de recetas", report, titles="1:2")
        return
    # Indicadores
    half = nc // 2
    kpis = [((1, half), "RECETAS ANULADAS", len(anuladas), f"S/ {sum(x.total for x in anuladas):.2f}  ·  no cuentan en el ICI", "venc"),
            ((half + 1, nc), "RECETAS SIN FUA", len(sin_fua), f"de {report.fua_revisadas} recetas {tipos} revisadas", "dev")]
    for (c1, c2), label, value, hint, tone in kpis:
        box(ws, 4, c1, 4, c2, label, fnt(7.5, True, INKT[tone]), TINT[tone], CENTER)
        box(ws, 5, c1, 5, c2, value, fnt(15, True, INKT[tone]), TINT[tone], CENTER, fmt='0;-0;"0"')
        box(ws, 6, c1, 6, c2, hint, fnt(7, False, INKT[tone]), TINT[tone], CENTER)
    ws.row_dimensions[4].height, ws.row_dimensions[5].height, ws.row_dimensions[6].height = 15, 24, 13
    ws.row_dimensions[7].height = 8

    def table(r, title, header, rows, empty):
        def head(rr):
            for i, h in enumerate(header, 1):
                box(ws, rr, i, rr, i, h, fnt(7, True, NAVY), SOFT, CENTER)
            ws.row_dimensions[rr].height = 18
            return rr + 1

        def repeat(rr):
            box(ws, rr, 1, rr, nc, f"{title}  ·  continuación", fnt(7.5, True, WHITE), NAVY, LEFT)
            ws.row_dimensions[rr].height = 15
            return head(rr + 1)

        r = page.keep(r, 15 + 18 + 13.5)
        box(ws, r, 1, r, nc, title, fnt(7.5, True, WHITE), NAVY, LEFT)
        ws.row_dimensions[r].height = 15
        r = head(r + 1)
        if not rows:
            box(ws, r, 1, r, nc, empty, fnt(7.5, False, MUTED, True), None, LEFT)
            return r + 2
        for k, values in enumerate(rows):
            r = page.keep(r, 13.5, repeat)
            for i, v in enumerate(values, 1):
                money = header[i - 1] == "VALOR S/"
                box(ws, r, i, r, i, v, fnt(7.5, money), ZEBRA if k % 2 else None,
                    WRAP_LEFT if header[i - 1] == "MOTIVO DE ANULACIÓN" else (NUM if money else MID),
                    fmt=MONEY if money else ("dd/mm/yyyy" if i == 1 else None))
            ws.row_dimensions[r].height = 13.5
            r += 1
        return r + 1

    farmacia = ["FARMACIA"] if report.consolidated else []
    rows = []
    for x in anuladas:
        fecha, hora = _moment(x.fecha)
        anulada = (x.anulada_el.strftime("%d/%m/%Y %H:%M") if isinstance(x.anulada_el, dt.datetime)
                   else x.anulada_el.strftime("%d/%m/%Y") if isinstance(x.anulada_el, dt.date) else "—")
        rows.append([fecha, hora, x.comprobante or x.numero, TIPO_ATENCION.get(x.column, x.column), x.total,
                     x.motivo or "—", x.anulo or "—", anulada] + ([x.code[-3:]] if farmacia else []))
    r = table(8, f"RECETAS ANULADAS  ·  {len(anuladas)}  ·  S/ {sum(x.total for x in anuladas):.2f}",
              ["FECHA", "HORA", "COMPROBANTE", "TIPO DE ATENCIÓN", "VALOR S/", "MOTIVO DE ANULACIÓN", "ANULÓ", "ANULADA EL"]
              + farmacia, rows, "Sin recetas anuladas en el mes.")
    if anuladas:
        r = _cancelled_by_type(ws, page, r, nc, anuladas)
    # Que se vea si se revisaron recetas: «0 sin FUA» no es lo mismo que no haber encontrado las recetas.
    official_sis = report.recetas[CONSUMO.index("SIS")] if report.recetas else 0
    if report.fua_revisadas:
        no_fua_text = f"Las {report.fua_revisadas} recetas {tipos} del mes tienen su FUA."
    elif official_sis:
        no_fua_text = (f"No se encontraron en las ventas del SISMED (TVENTA) las {int(official_sis)} recetas {tipos} "
                       "que tiene el ICI: no se pudo revisar el FUA.")
    else:
        no_fua_text = f"Sin recetas {tipos} en el mes."
    rows = []
    for x in sin_fua:
        fecha, hora = _moment(x.fecha)
        rows.append([fecha, hora, x.comprobante or x.numero, TIPO_ATENCION.get(x.column, x.column), x.total,
                     x.receta or "—", x.usuario or "—", x.numero or "—"] + ([x.code[-3:]] if farmacia else []))
    table(r, f"RECETAS SIN FUA  ·  {len(sin_fua)}  ·  {tipos}",
          ["FECHA", "HORA", "COMPROBANTE", "TIPO DE ATENCIÓN", "VALOR S/", "N° DE RECETA", "REGISTRÓ", "N° DE VENTA"]
          + farmacia, rows, no_fua_text)
    page.setup("Control de recetas", report, titles="1:2")


EXCEL_ONLY = ("Alertas de farmacia", "Lotes sin movimiento")   # hojas que no van al PDF


def build_workbook(report: IciReport, printable: bool | str = False) -> tuple[Workbook, dict]:
    """Arma el libro completo; `printable` es la versión que se pasa a PDF. Devuelve (libro,
    cifras para la consola). Orden del usuario (2026-10-19): ICI, guías de ingreso, ingresos internos,
    salidas por devolución, vencimientos, recetas diarias y control de recetas; alertas y lotes sin movimiento van al final y solo en el
    Excel, no en el PDF."""
    wb = Workbook()
    products = {**report.products, **{r["CODIGO_MED"]: (r["DESC"], r["MEDFF"]) for r in report.rows}}
    ici_sheet(wb, report, printable)
    guides_sheet(wb, report, products, printable)
    internal_sheet(wb, report, products, printable)
    returns_sheet(wb, report, products, printable)
    expiry_sheet(wb, report, printable)
    recetas_sheet(wb, report, printable)
    control_sheet(wb, report, printable)
    summary, still, still_value = alerts_sheet(wb, report, printable)
    still_sheet(wb, report, still, still_value, printable)
    if printable:
        for name in EXCEL_ONLY:
            wb.remove(wb[name])
    wb.active = 0
    return wb, summary


def _safe_name(value: str) -> str:
    cleaned = "".join("-" if ch in '<>:"/\\|?*' else ch for ch in str(value))
    return " ".join(cleaned.split()).strip(" .")[:90]


def main_report_name(month, consolidated: bool = True) -> str:
    """Nombre que se propone en la ventana de guardar: el del consolidado (o de la única farmacia)."""
    from ici_data import month_label

    label = month_label(month.annomes)
    if not month.establishments:
        return f"ICI {label}"
    est = month.establishments[0]
    if consolidated and len(est.pharmacies) > 1:
        return consolidated_file_name(est, label)
    return pharmacy_file_name(est, est.pharmacies[0], label)


# Nombres de archivo con el establecimiento (pedido del usuario, 2026-10-20): «ICI P.S. HUACHO SEPTIEMBRE 2026».
def consolidated_file_name(est, label: str) -> str:
    return _safe_name(f"ICI CONSOLIDADO {est.name} {label}")


def pharmacy_file_name(est, ph, label: str) -> str:
    if ph.code == est.code:
        return _safe_name(f"ICI {ph.name} {label}")
    return _safe_name(f"ICI {ph.code[-3:]} {ph.name} {label}")


def write_reports(month, out_dir: str, consolidated: bool = True, per_pharmacy: bool = True, pdf: bool = True,
                  log=print, open_exporter=None, main_name: str | None = None) -> list[str]:
    """Escribe un libro por farmacia y el consolidado de cada establecimiento, cada uno en Excel y
    en PDF (todas las hojas, para imprimir). `main_name` es el nombre que eligió el usuario en la
    ventana de guardar para el primero; los demás van a la misma carpeta con su nombre de siempre.
    Devuelve las rutas de todos los archivos."""
    import os
    import tempfile

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
        name = _safe_name(main_name) if (main_name and not paths) else _safe_name(file_name)
        path = os.path.join(out_dir, f"{name}.xlsx")
        wb.save(path)
        paths.append(path)
        log(f"✅ {os.path.basename(path)}  ·  {len(report.rows)} lotes · {summary['desabastecidos']} desabastecidos · "
            f"{summary['sin_movimiento']} lotes sin movimiento")
        if exporter is not None:
            pdf_path = path[:-len(".xlsx")] + ".pdf"
            try:
                # El PDF sale de la versión para imprimir: páginas cortadas y encabezados repetidos.
                engine = getattr(exporter, "engine", True)
                if hasattr(exporter, "render"):
                    exporter.render(build_workbook(report, printable=engine)[0], pdf_path)
                else:
                    with tempfile.TemporaryDirectory(prefix="toolkit_ici_print_") as tmp:
                        printable = os.path.join(tmp, f"{name}.xlsx")
                        build_workbook(report, printable=engine)[0].save(printable)
                        exporter.export(printable, pdf_path)
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
            save(report, consolidated_file_name(est, label))
        if per_pharmacy or len(est.pharmacies) == 1:
            for ph in est.pharmacies:
                save(pharmacy_report(month, est, ph), pharmacy_file_name(est, ph, label))
