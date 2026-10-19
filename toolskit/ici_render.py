"""Generar ICI: el PDF lo dibuja el Toolkit, sin Excel, WPS ni LibreOffice.

Antes el PDF lo armaba el programa de hojas de cálculo de la PC, y cada uno dibuja las columnas a su
manera: con Excel la tabla salía más chica de lo calculado y quedaba un espacio en blanco al pie de
cada página, y una hoja angosta no entraba a lo ancho y su última columna se iba sola a otra página
(lo vio el usuario con las versiones 2.3.14 y 2.3.15). Ahora se dibuja aquí la versión de imprimir del
libro, celda por celda, con PyMuPDF: las mismas medidas con que se cortan las páginas (ici_excel.Page),
así cada página llega hasta abajo y cada hoja ocupa el ancho de la página, igual en todas las PC.

Se respeta lo que el libro trae: anchos y altos, celdas combinadas, rellenos, bordes, letra (tamaño,
negrita, cursiva, color), alineación, ajuste de texto, sangría, texto girado, formatos de número, formato
condicional, saltos de página, márgenes, escala y pie de página. Las fórmulas se calculan con
ici_values. Un texto que no cabe se achica: nunca sale cortado ni como «####».
"""

from __future__ import annotations

import datetime as dt
import re

import fitz  # PyMuPDF

from ici_values import EPOCH, Evaluator

A4_LANDSCAPE = (842.0, 595.0)
PT_PER_UNIT = 7 * 0.75          # una unidad de ancho de columna, en puntos (la misma de ici_excel.Page)
DEFAULT_WIDTH = 8.43
DEFAULT_HEIGHT = 15.0
PAD = 1.6                        # margen interior de la celda, en puntos al 100 %
LINE = 1.16                      # alto de línea / tamaño de letra

class _Font:
    """Una de las cuatro Helvetica estándar del PDF (todas las PC y visores la tienen; mide como Arial).
    El texto va escrito directo en la página: con miles de celdas, mucho más rápido que TextWriter."""

    def __init__(self, key: str, base: str, resource: str):
        self.metrics = fitz.Font(key)
        self.base, self.resource = base, resource
        self.ascender, self.descender = self.metrics.ascender, self.metrics.descender
        self.advance = {}

    def text_length(self, text: str, size: float) -> float:
        total = 0.0
        advance = self.advance
        for ch in text:
            width = advance.get(ch)
            if width is None:
                width = advance[ch] = self.metrics.glyph_advance(ord(ch))
            total += width
        return total * size


_FONTS = {}
_FONT_SPECS = {(False, False): ("helv", "Helvetica", "H1"), (True, False): ("hebo", "Helvetica-Bold", "H2"),
               (False, True): ("heit", "Helvetica-Oblique", "H3"), (True, True): ("hebi", "Helvetica-BoldOblique", "H4")}


def font(bold=False, italic=False) -> _Font:
    key = (bool(bold), bool(italic))
    if key not in _FONTS:
        _FONTS[key] = _Font(*_FONT_SPECS[key])
    return _FONTS[key]


# Las fuentes estándar del PDF escriben en WinAnsi: los pocos signos que el libro usa fuera de ella se
# cambian por su equivalente (si no, saldrían como «?»).
_SUBST = str.maketrans({"→": "»", "−": "-", "≠": "<>", "≥": ">=", "≤": "<=", "✓": "Sí", "─": "-"})


def plain(text: str) -> str:
    return text.translate(_SUBST)


def _pdf_string(text: str) -> str:
    """Texto como cadena PDF en WinAnsi (la codificación de las fuentes estándar)."""
    out = []
    for byte in text.encode("cp1252", errors="replace"):
        ch = chr(byte)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= byte < 127:
            out.append(ch)
        else:
            out.append(f"\\{byte:03o}")
    return "(" + "".join(out) + ")"


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def rgb(color, default=(0, 0, 0)):
    """Color de openpyxl («FF1F2933» o «1F2933») a (r, g, b) de 0 a 1."""
    value = getattr(color, "rgb", color)
    if not isinstance(value, str) or len(value) not in (6, 8):
        return default
    value = value[-6:]
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return default


# ── Formatos de número ─────────────────────────────────────────────────────────


def _sections(fmt: str) -> list[str]:
    out, cur, quoted = [], "", False
    for ch in fmt:
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _round_half_up(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return (abs(value) * factor + 0.5 + 1e-9) // 1 / factor * (1 if value >= 0 else -1)


def format_value(value, fmt: str | None) -> str:
    """Texto que muestra Excel para un valor con su formato (los formatos que usa el libro del ICI)."""
    if value is None or isinstance(value, bool):
        return ""
    fmt = fmt or "General"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%d/%m/%Y")
    if not isinstance(value, (int, float)):
        return str(value)
    if "yy" in fmt.lower():                       # número de serie con formato de fecha
        return (EPOCH + dt.timedelta(days=float(value))).strftime("%d/%m/%Y")
    if fmt == "General":
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.10g}"
    parts = _sections(fmt)
    sign = ""
    if value == 0 and len(parts) >= 3:
        section, number = parts[2], 0.0
    elif value < 0 and len(parts) >= 2:
        section, number = parts[1], abs(value)
    else:
        section, number = parts[0], abs(value)
        sign = "-" if value < 0 else ""
    if "%" in re.sub(r'"[^"]*"', "", section):
        number *= 100
    # Piezas: texto entre comillas tal cual; fuera de comillas, el número es el primer grupo de 0 # .
    pieces = re.findall(r'"[^"]*"|[0#]+(?:\.[0#]+)?|.', section)
    out, done = [], False
    for piece in pieces:
        if piece.startswith('"'):
            out.append(piece[1:-1])
        elif not done and piece[0] in "0#":
            done = True
            tail = piece.split(".")[1] if "." in piece else ""
            low, high = tail.count("0"), len(tail)
            text = f"{_round_half_up(number, high):.{high}f}"
            if high > low:
                whole, frac = text.split(".")
                frac = frac.rstrip("0")
                frac += "0" * max(0, low - len(frac))
                text = whole + ("." + frac if frac else "")
            out.append(sign + text)
        else:
            out.append(piece)
    return "".join(out)


# ── Texto ──────────────────────────────────────────────────────────────────────


def wrap(text: str, f: fitz.Font, size: float, width: float) -> list[str]:
    """Líneas de un texto que no pasan de `width`, cortando por palabras como Excel."""
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if not line or f.text_length(candidate, size) <= width:
                line = candidate
                continue
            lines.append(line)
            line = word
            while f.text_length(line, size) > width and len(line) > 1:
                cut = len(line)
                while cut > 1 and f.text_length(line[:cut], size) > width:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line)
    return lines


class _Painter:
    """Lo que se dibuja en una página, escrito directo como contenido PDF: rellenos, bordes y texto,
    en ese orden. Las coordenadas llegan con el origen arriba (como las filas) y se dan vuelta."""

    def __init__(self, height: float):
        self.height = height
        self.fills = []
        self.lines = {}
        self.texts = []

    def text(self, x, y, text, f, size, color):
        self.texts.append(f"BT /{f.resource} {_num(size)} Tf {_color(color)} rg 1 0 0 1 {_num(x)} "
                          f"{_num(self.height - y)} Tm {_pdf_string(text)} Tj ET")

    def rotated(self, x, y, text, f, size, color):
        """Texto que sube desde (x, y), de abajo hacia arriba."""
        self.texts.append(f"BT /{f.resource} {_num(size)} Tf {_color(color)} rg 0 1 -1 0 {_num(x)} "
                          f"{_num(self.height - y)} Tm {_pdf_string(text)} Tj ET")

    def line(self, p1, p2, color, width):
        key = (round(p1[0], 2), round(p1[1], 2), round(p2[0], 2), round(p2[1], 2))
        self.lines[key] = (color, width)

    def content(self) -> bytes:
        h = self.height
        out = ["q"]
        for rect, color in self.fills:
            out.append(f"{_color(color)} rg {_num(rect.x0)} {_num(h - rect.y1)} {_num(rect.width)} {_num(rect.height)} re f")
        styles = {}
        for key, style in self.lines.items():
            styles.setdefault(style, []).append(key)
        for (color, width), keys in styles.items():
            out.append(f"{_num(width)} w {_color(color)} RG")
            out.extend(f"{_num(x1)} {_num(h - y1)} m {_num(x2)} {_num(h - y2)} l" for x1, y1, x2, y2 in keys)
            out.append("S")
        out.extend(self.texts)
        out.append("Q")
        return "\n".join(out).encode("latin-1")


def _color(color) -> str:
    return " ".join(_num(v) for v in color)


# ── Hoja ───────────────────────────────────────────────────────────────────────


class _Sheet:
    def __init__(self, ws):
        self.ws = ws
        self.values = Evaluator(ws)
        self.ncol = ws.max_column
        self.nrow = ws.max_row
        widths = []
        for c in range(1, self.ncol + 1):
            dim = ws.column_dimensions.get(_letter(c))
            widths.append((dim.width if dim is not None and dim.width else DEFAULT_WIDTH) * PT_PER_UNIT)
        self.col_w = widths
        self.merged = {}
        self.inside = set()
        for rng in ws.merged_cells.ranges:
            self.merged[(rng.min_row, rng.min_col)] = (rng.max_row, rng.max_col)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        self.inside.add((r, c))
        self.rules = []
        for cf in ws.conditional_formatting:
            for cr in cf.sqref.ranges:
                for rule in sorted(cf.rules, key=lambda x: x.priority or 0):
                    if rule.formula:
                        self.rules.append((cr.min_row, cr.max_row, cr.min_col, cr.max_col, rule))
        m = ws.page_margins
        self.margins = (m.left * 72, m.right * 72, m.top * 72, m.bottom * 72, (m.footer or 0.2) * 72)
        usable = A4_LANDSCAPE[0] - self.margins[0] - self.margins[1]
        total = sum(widths)
        if ws.sheet_properties.pageSetUpPr is not None and ws.sheet_properties.pageSetUpPr.fitToPage:
            self.scale = min(1.0, usable / total)
        else:
            self.scale = (ws.page_setup.scale or 100) / 100
        self.x0 = self.margins[0] + (usable - total * self.scale) / 2 if ws.print_options.horizontalCentered \
            else self.margins[0]
        xs = [self.x0]
        for w in widths:
            xs.append(xs[-1] + w * self.scale)
        self.xs = xs
        self.breaks = {b.id for b in ws.row_breaks.brk}

    def height(self, r):
        dim = self.ws.row_dimensions.get(r)
        h = dim.height if dim is not None and dim.height is not None else DEFAULT_HEIGHT
        return 0.0 if dim is not None and dim.hidden else h

    def layout(self):
        """Página y posición de cada fila: [(filas con su y)] por página."""
        top, bottom = self.margins[2], A4_LANDSCAPE[1] - self.margins[3]
        pages, current, y = [], [], top
        for r in range(1, self.nrow + 1):
            h = self.height(r) * self.scale
            if current and ((r - 1) in self.breaks or y + h > bottom + 0.01):
                pages.append(current)
                current, y = [], top
            current.append((r, y, h))
            y += h
        if current:
            pages.append(current)
        return pages

    def style(self, r, c):
        """Relleno y letra de una celda, con su formato condicional."""
        cell = self.ws._cells.get((r, c))
        fill = None
        if cell is not None and cell.fill is not None and cell.fill.fill_type == "solid":
            fill = rgb(cell.fill.fgColor, None)
        f = cell.font if cell is not None else None
        bold, italic = bool(f and f.b), bool(f and f.i)
        size = float(f.sz) if f is not None and f.sz else 11.0
        color = rgb(f.color) if f is not None and f.color is not None else (0, 0, 0)
        for r1, r2, c1, c2, rule in self.rules:
            if r1 <= r <= r2 and c1 <= c <= c2:
                try:
                    hit = self.values.formula(rule.formula[0], r - r1, c - c1)
                except Exception:  # noqa: BLE001
                    hit = False
                if hit:
                    dxf = rule.dxf
                    if dxf is not None and dxf.fill is not None:
                        fill = rgb(dxf.fill.fgColor, None) or rgb(dxf.fill.bgColor, None) or fill
                    if dxf is not None and dxf.font is not None:
                        bold = bool(dxf.font.b) or bold
                        if dxf.font.color is not None:
                            color = rgb(dxf.font.color, color)
                    break
        return fill, bold, italic, size, color

    def draw(self, painter, rows):
        ypos = {r: (y, h) for r, y, h in rows}
        s = self.scale
        for r, y, h in rows:
            for c in range(1, self.ncol + 1):
                if (r, c) in self.inside:
                    continue
                r2, c2 = self.merged.get((r, c), (r, c))
                y2 = y + sum(ypos[k][1] if k in ypos else self.height(k) * s for k in range(r, r2 + 1))
                rect = fitz.Rect(self.xs[c - 1], y, self.xs[c2], y2)
                if rect.width <= 0 or rect.height <= 0:
                    continue
                fill, bold, italic, size, color = self.style(r, c)
                if fill is not None:
                    painter.fills.append((rect, fill))
                self._borders(painter, r, c, r2, c2, rect)
                self._text(painter, r, c, rect, bold, italic, size, color)

    def _borders(self, painter, r, c, r2, c2, rect):
        def edge(cell_rc, side_name):
            cell = self.ws._cells.get(cell_rc)
            if cell is None or cell.border is None:
                return None
            side = getattr(cell.border, side_name)
            if side is None or side.style is None:
                return None
            width = {"thin": 0.5, "hair": 0.3, "medium": 1.0, "thick": 1.5}.get(side.style, 0.5)
            return rgb(side.color, (0, 0, 0)), max(0.3, width * min(1.0, self.scale + 0.2))

        for side_name, cell_rc, p1, p2 in (
                ("top", (r, c), rect.tl, rect.tr), ("bottom", (r2, c), rect.bl, rect.br),
                ("left", (r, c), rect.tl, rect.bl), ("right", (r, c2), rect.tr, rect.br)):
            found = edge(cell_rc, side_name)
            if side_name == "bottom" and found is None and c2 > c:
                # Firmas: la línea va en el borde inferior de cada celda de la fila.
                continue
            if found:
                painter.line(p1, p2, found[0], found[1])
        if c2 > c and r2 == r:
            for k in range(c, c2 + 1):
                found = edge((r, k), "bottom")
                if found and edge((r, c), "bottom") is None:
                    painter.line((self.xs[k - 1], rect.y1), (self.xs[k], rect.y1), found[0], found[1])

    def _text(self, painter, r, c, rect, bold, italic, size, color):
        cell = self.ws._cells.get((r, c))
        if cell is None:
            return
        value = self.values.value(r, c)
        text = plain(format_value(value, cell.number_format))
        if text == "":
            return
        f = font(bold, italic)
        s = self.scale
        al = cell.alignment
        horizontal = al.horizontal or ("right" if isinstance(value, (int, float, dt.date)) else "left")
        vertical = al.vertical or "bottom"
        wrap_text = bool(al.wrap_text) or horizontal == "justify"
        rotation = al.text_rotation or 0
        indent = (al.indent or 0) * PT_PER_UNIT * 1.2 * s
        pad = PAD * s
        fs = size * s
        if rotation in (90, 180):
            self._rotated(painter, rect, text, f, fs, color, pad, wrap_text)
            return
        avail_w = rect.width - 2 * pad - indent
        avail_h = rect.height - 2 * pad * 0.5
        if avail_w <= 1:
            return
        # Se achica hasta que entre: nunca se corta ni sale como «####».
        for _ in range(40):
            lines = wrap(text, f, fs, avail_w) if wrap_text else [text]
            widest = max(f.text_length(line, fs) for line in lines)
            if widest <= avail_w + 0.01 and len(lines) * fs * LINE <= avail_h + 0.5:
                break
            if fs <= size * s * 0.45:
                break
            fs *= 0.95
        line_h = fs * LINE
        block = len(lines) * line_h
        if vertical == "top":
            top = rect.y0 + pad * 0.5
        elif vertical == "bottom":
            top = rect.y1 - pad * 0.5 - block
        else:
            top = rect.y0 + (rect.height - block) / 2
        ascent = f.ascender * fs + (line_h - fs * (f.ascender - f.descender)) / 2
        for k, line in enumerate(lines):
            width = f.text_length(line, fs)
            if horizontal in ("center", "centerContinuous", "distributed"):
                x = rect.x0 + (rect.width - width) / 2
            elif horizontal == "right":
                x = rect.x1 - pad - indent - width
            else:
                x = rect.x0 + pad + indent
            painter.text(x, top + k * line_h + ascent, line, f, fs, color)

    def _rotated(self, painter, rect, text, f, fs, color, pad, wrap_text):
        """Texto girado 90° (de abajo hacia arriba), como los encabezados de columna angostos."""
        avail_w = rect.height - 2 * pad          # a lo largo de la celda
        avail_h = rect.width - 2 * pad
        size = fs
        for _ in range(40):
            lines = wrap(text, f, fs, avail_w) if wrap_text else [text]
            widest = max(f.text_length(line, fs) for line in lines)
            if widest <= avail_w + 0.01 and len(lines) * fs * LINE <= avail_h + 0.5:
                break
            if fs <= size * 0.45:
                break
            fs *= 0.95
        line_h = fs * LINE
        block = len(lines) * line_h
        ascent = f.ascender * fs + (line_h - fs * (f.ascender - f.descender)) / 2
        # El texto sube desde abajo, centrado en el alto; las líneas se suceden hacia la derecha y lo alto
        # de cada letra queda a la izquierda de su línea base.
        left = (rect.width - block) / 2
        for k, line in enumerate(lines):
            width = f.text_length(line, fs)
            painter.rotated(rect.x0 + left + k * line_h + ascent, rect.y1 - (rect.height - width) / 2, line, f, fs, color)


def _letter(c: int) -> str:
    out = ""
    while c:
        c, rem = divmod(c - 1, 26)
        out = chr(65 + rem) + out
    return out


def _footer_text(part) -> str:
    return (part.text or "") if part is not None else ""


def render_workbook(wb, pdf_path: str) -> int:
    """Dibuja todas las hojas del libro en un PDF A4 horizontal. Devuelve el número de páginas."""
    doc = fitz.open()
    refs = []
    for key, (_, base, resource) in sorted(_FONT_SPECS.items()):
        xref = doc.get_new_xref()
        doc.update_object(xref, f"<</Type/Font/Subtype/Type1/BaseFont/{base}/Encoding/WinAnsiEncoding>>")
        refs.append(f"/{resource} {xref} 0 R")
    resources = "<</Font<<" + "".join(refs) + ">>>>"
    pages = []
    for ws in wb.worksheets:
        sheet = _Sheet(ws)
        for rows in sheet.layout():
            page = doc.new_page(width=A4_LANDSCAPE[0], height=A4_LANDSCAPE[1])
            painter = _Painter(A4_LANDSCAPE[1])
            sheet.draw(painter, rows)
            pages.append((page.xref, painter, ws, sheet.margins))
    total = len(pages)
    f = font()
    for number, (page_xref, painter, ws, margins) in enumerate(pages, 1):
        y = A4_LANDSCAPE[1] - margins[4]
        footer = ws.oddFooter
        size = float(footer.left.size or 7) if footer.left is not None else 7.0
        left = plain(_footer_text(footer.left)).replace("&P", str(number)).replace("&N", str(total))
        right = plain(_footer_text(footer.right)).replace("&P", str(number)).replace("&N", str(total))
        if left:
            painter.text(margins[0], y, left, f, size, (0, 0, 0))
        if right:
            painter.text(A4_LANDSCAPE[0] - margins[1] - f.text_length(right, size), y, right, f, size, (0, 0, 0))
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, painter.content())
        doc.xref_set_key(page_xref, "Contents", f"{xref} 0 R")
        doc.xref_set_key(page_xref, "Resources", resources)
    doc.save(pdf_path, garbage=3, deflate=True)
    doc.close()
    return total
