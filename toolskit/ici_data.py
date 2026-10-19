"""Generar ICI: los datos del Informe de Consumo Integrado de un mes, leídos del SISMED.

El detalle por lote sale de TFORMDET (lo que el SISMED guardó al procesar el ICI del mes:
cuadra con el ICI de pantalla). Lo demás sale de otras tablas:

- TFORMATO: el número de recetas (dispensaciones) por tipo de atención. El Excel que exporta
  el SISMED pierde el SIS e intercambia otros convenios y crédito; aquí se lee directo.
- TMOVIM / TMOVIMDET: las devoluciones de vencido (concepto 35), las entregas entre farmacias
  del mismo establecimiento, las correcciones de lote y las guías de ingreso.

Reglas acordadas con el usuario (docs/ICI_SISMED.md del ToolKit SISMED Web):

- El concepto 35 va siempre a Vencidos (el SISMED lo manda a Devolución en las farmacias).
- El consolidado suma todas las farmacias y puestos comunales del establecimiento y descuenta
  lo que se movió entre ellos; el stock final es la suma de las farmacias.
- La corrección de lote (sale y vuelve a entrar en la misma farmacia) queda como está, en
  Devolución y Reingreso, marcada, y se lista aparte.

Todo lo de aquí es puro (no escribe nada ni toca la pantalla), para poder probarlo con tablas
de mentira.
"""

from __future__ import annotations

import calendar
import collections
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

CONSUMO = ("VENTA", "SIS", "INTERSAN", "FAC_PERD", "DEFNAC", "EXO", "SOAT", "CREDHOSP", "OTR_CONV")
# Salidas que el ICI junta en «Otras salidas».
OTHER_OUT = ("OTRAS_SAL", "DISTRI", "TRANSF", "VENTAINST", "ESSALUD", "DEV_VEN", "DEV_MERMA")
ENTRADAS = ("INGRE", "REINGRE", "ING_REGULA")
# Columnas de salida del ICI que no son consumo. «OTRAS» es la suma de OTHER_OUT.
SALIDAS = ("DEVOL", "VENCIDO", "MERMA", "OTRAS", "SAL_REGULA", "SAL_CONINS")
NUMS = ("SALDO", *ENTRADAS, *CONSUMO, *SALIDAS, "TOTAL", "STOCK_FIN")

# TFORMATO: recetas en el orden de las columnas de consumo del ICI.
RECETAS_FIELDS = {
    "VENTA": "REC_VTAS", "SIS": "REC_SIS", "INTERSAN": "REC_INTS", "DEFNAC": "REC_DN",
    "EXO": "REC_EXO", "SOAT": "REC_SOAT", "CREDHOSP": "REC_CREHOS", "OTR_CONV": "REC_OTRCON",
}

CONCEPTO_VENCIDO = "35"
# Columna del ICI donde cae una salida según su concepto (procesar_ici del SISMED, con el 35
# en Vencidos). Se usa para descontar del consolidado lo que se entregó entre farmacias.
SALIDA_POR_CONCEPTO = {
    "05": "DEVOL", "07": "DEVOL", "22": "DEVOL", "36": "DEVOL",
    CONCEPTO_VENCIDO: "VENCIDO",
    "06": "MERMA",
    "21": "SAL_REGULA",
    "33": "SAL_CONINS",
}
# Entradas: con estos conceptos son reingreso; con el 21, ajuste; las demás, ingreso.
REINGRESO_CONCEPTOS = {"05", "06", "07", "35", "36"}

CONCEPTOS = {
    "04": "Distribución", "05": "Riesgo de vencimiento", "06": "Deterioro",
    "07": "Devolución por sobrestock", "08": "Transferencia", "09": "Transferencia",
    "21": "Ajuste de inventario", "22": "Devolución por paciente", "32": "Transferencia",
    "33": "Consumo institucional", "35": "Devolución de vencido", "36": "R.S. cancelado o vencido",
}

MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")

_PHARMACY = re.compile(r"^(.+?)F\d{2}$")


def num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def text(value) -> str:
    return str(value or "").strip()


def plain_text(value) -> str:
    """En mayúsculas y sin tildes, para reconocer lo que se escribe a mano («Corrección» = «CORRECCION»)."""
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().upper()


def ipress_of(code: str) -> str:
    """«06502F02» → «06502». Un almacén u otro código sin farmacia es su propio grupo."""
    match = _PHARMACY.match(text(code))
    return match.group(1) if match else text(code)


def pharmacy_suffix(code: str) -> str:
    """«06502F02» → «F02» (o el código entero si no es una farmacia)."""
    code = text(code)
    return code[-3:] if _PHARMACY.match(code) else code


def month_bounds(annomes: str) -> tuple[date, date]:
    year, month = int(annomes[:4]), int(annomes[4:6])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_label(annomes: str) -> str:
    return f"{MESES[int(annomes[4:6]) - 1]} {annomes[:4]}"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _split_virtual(value: str) -> tuple[str, str]:
    """Subalmacén virtual «06502F0101» → («06502F01», «01»)."""
    value = text(value)
    if len(value) <= 2:
        return value, ""
    return value[:-2], value[-2:]


# ── Datos ──────────────────────────────────────────────────────────────────────


@dataclass
class MoveLine:
    code: str
    lote: str
    qty: float
    total: float | None = None
    vence: date | None = None


@dataclass
class Movement:
    tipo: str                 # «S» salida, «E» entrada
    numero: str
    concepto: str
    origen: str               # código de farmacia o almacén (sin el subalmacén)
    origen_sub: str
    destino: str
    destino_sub: str
    doc_tipo: str
    doc_numero: str
    fecha: date | None
    referencia: str = ""
    lines: list[MoveLine] = field(default_factory=list)

    @property
    def valor(self) -> float | None:
        totals = [line.total for line in self.lines]
        if not totals or any(t is None for t in totals):
            return None
        return sum(totals)


@dataclass
class Pharmacy:
    code: str
    name: str
    rows: list[dict]
    recetas: list[float]
    desde: date
    hasta: date


@dataclass
class Establishment:
    code: str
    name: str
    red: str
    microred: str
    pharmacies: list[Pharmacy]


@dataclass
class IciMonth:
    annomes: str
    establishments: list[Establishment]
    movements: list[Movement]
    names: dict[str, str]
    has_movements: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class IciReport:
    """Lo que necesita el Excel de un ICI: una farmacia o el consolidado del establecimiento."""
    annomes: str
    title: str                 # «HOSPITAL II-E BELLAVISTA» o el nombre de la farmacia
    ficha: dict
    rows: list[dict]
    recetas: list[float]
    desde: date
    hasta: date
    guias: list[Movement]
    corrections: list[Movement]
    names: dict[str, str]
    consolidated: bool = False
    internal_value: float = 0.0
    internal_estimated: bool = False
    in_transit: float = 0.0


# ── Lectura del SISMED ─────────────────────────────────────────────────────────


def dbf_tables(sismed_dir: str, snapshot_dir: str, open_dbf, snapshot_dbf):
    """Devuelve open_table(nombre) → registros, o None si la tabla no existe.

    Cada tabla se copia antes a una carpeta temporal (el SISMED puede estar abierto)."""

    def open_table(name: str):
        path = os.path.join(sismed_dir, "DATOS", f"{name}.DBF")
        if not os.path.exists(path):
            return None
        return open_dbf(snapshot_dbf(path, snapshot_dir))

    return open_table


def _load_names(open_table) -> tuple[dict, dict]:
    """(nombre por código de MALMACEN, ficha de red y microred por código)."""
    redes, micro = {}, {}
    for rec in open_table("MRED") or []:
        disa, cod = text(rec.get("REDCDISA")), text(rec.get("REDCCODRED"))
        if disa and cod:
            redes[(disa, cod)] = text(rec.get("REDTDSCL"))
    for rec in open_table("MMICRORED") or []:
        disa, red, cod = text(rec.get("MRECDISA")), text(rec.get("MRECRED")), text(rec.get("MRECMICRO"))
        if disa and red and cod:
            micro[(disa, red, cod)] = text(rec.get("MRETDSCL"))
    names, places = {}, {}
    for rec in open_table("MALMACEN") or []:
        cod = text(rec.get("ALMCOD"))
        if not cod:
            continue
        names[cod] = text(rec.get("ALMDES"))
        disa, red, mr = text(rec.get("ALMCDISA")), text(rec.get("ALMCRED")), text(rec.get("ALMCMRED"))
        places[cod] = (redes.get((disa, red), ""), micro.get((disa, red, mr), ""))
    return names, places


def _load_products(open_table) -> dict:
    """código → (descripción, unidad)."""
    products = {}
    for rec in open_table("MPRODUCTO") or []:
        cod = text(rec.get("MEDCOD"))
        if cod:
            desc = " ".join(f"{text(rec.get('MEDNOM'))} {text(rec.get('MEDPRES'))} {text(rec.get('MEDCNC'))}".split())
            products[cod] = (desc, text(rec.get("MEDFF")))
    for rec in open_table("MMEDICAM") or []:
        cod = text(rec.get("MEDCOD"))
        ff = text(rec.get("MEDFF"))
        if cod in products and ff:
            products[cod] = (products[cod][0], ff)
    return products


def normalize_row(rec: dict, products: dict) -> dict:
    """Fila de TFORMDET con las columnas del ICI.

    «OTRAS» se calcula como TOTAL menos las demás salidas, así el total y el stock final son
    siempre los del SISMED aunque el ajuste o el consumo institucional vengan dentro de
    OTRAS_SAL. Si no cuadra (dato raro), se usa la suma de las otras salidas."""
    code = text(rec.get("CODIGO_MED"))
    desc, unit = products.get(code, ("", ""))
    row = {
        "CODIGO_PRE": text(rec.get("CODIGO_PRE")),
        "CODIGO_MED": code,
        "DESC": desc or text(rec.get("DESCRIPCION MED")),
        "MEDFF": unit or text(rec.get("MEDFF")),
        "MEDLOTE": text(rec.get("MEDLOTE")),
        "MEDREGSAN": text(rec.get("MEDREGSAN")),
        "FEC_EXP": _as_date(rec.get("FEC_EXP")),
        "TIPSUM2": text(rec.get("TIPSUM2")),
        "FFINAN": text(rec.get("FFINAN")),
        "PRECIO": num(rec.get("PRECIO")),
        "flags": set(),
    }
    for name in ("SALDO", *ENTRADAS, *CONSUMO, "DEVOL", "VENCIDO", "MERMA", "SAL_REGULA", "SAL_CONINS",
                 "TOTAL", "STOCK_FIN"):
        row[name] = num(rec.get(name))
    known = sum(row[n] for n in (*CONSUMO, "DEVOL", "VENCIDO", "MERMA", "SAL_REGULA", "SAL_CONINS"))
    rest = row["TOTAL"] - known
    row["OTRAS"] = rest if rest > -1e-6 else sum(num(rec.get(n)) for n in OTHER_OUT)
    row["OTRAS"] = max(0.0, round(row["OTRAS"], 6))
    return row


def _load_recetas(open_table, annomes: str) -> dict:
    """CODIGO_PRE → (recetas en el orden de CONSUMO, desde, hasta)."""
    found = {}
    for rec in open_table("TFORMATO") or []:
        if text(rec.get("ANNOMES")) != annomes:
            continue
        code = text(rec.get("CODIGO_PRE"))
        counts, desde, hasta = found.get(code, ([0.0] * len(CONSUMO), None, None))
        for i, column in enumerate(CONSUMO):
            source = RECETAS_FIELDS.get(column)
            if source:
                counts[i] += num(rec.get(source))
        d, h = _as_date(rec.get("FDESDE")), _as_date(rec.get("FHASTA"))
        desde = min(filter(None, (desde, d)), default=None)
        hasta = max(filter(None, (hasta, h)), default=None)
        found[code] = (counts, desde, hasta)
    return found


def _load_movements(open_table, codes: set[str], desde: date, hasta: date) -> list[Movement]:
    """Movimientos vigentes del periodo en que sale o entra una de las farmacias."""
    heads = {}
    for rec in open_table("TMOVIM") or []:
        if text(rec.get("MOVSITUA")) != "1":
            continue
        fecha = _as_date(rec.get("MOVFECHREG"))
        if not fecha or not (desde <= fecha <= hasta):
            continue
        tipo = text(rec.get("MOVCODITIP")).upper()
        origen, origen_sub = _split_virtual(rec.get("ALMORGVIR"))
        destino, destino_sub = _split_virtual(rec.get("ALMDSTVIR"))
        if not destino:
            destino, destino_sub = text(rec.get("ALMCODIDST")), ""
        mine = (tipo == "S" and origen in codes and origen_sub in ("01", "")) or \
               (tipo == "E" and destino in codes and destino_sub in ("01", ""))
        if not mine:
            continue
        numero = text(rec.get("MOVNUMERO"))
        heads[(tipo, numero)] = Movement(
            tipo=tipo, numero=numero, concepto=text(rec.get("CCTCODIGO")),
            origen=origen, origen_sub=origen_sub, destino=destino, destino_sub=destino_sub,
            doc_tipo=text(rec.get("MOVTIPODCO")), doc_numero=text(rec.get("MOVNUMEDCO")),
            fecha=fecha, referencia=text(rec.get("MOVREFE")),
        )
    if not heads:
        return []
    for rec in open_table("TMOVIMDET") or []:
        move = heads.get((text(rec.get("MOVCODITIP")).upper(), text(rec.get("MOVNUMERO"))))
        if move is None:
            continue
        total = rec.get("MOVTOTAL")
        move.lines.append(MoveLine(
            code=text(rec.get("MEDCOD")), lote=text(rec.get("MEDLOTE")), qty=num(rec.get("MOVCANTID")),
            total=None if total is None else num(total), vence=_as_date(rec.get("MEDFECHVTO")),
        ))
    return list(heads.values())


def load_month(open_table, annomes: str, log=print) -> IciMonth:
    """Lee el mes de todas las farmacias que tienen ICI procesado en TFORMDET."""
    log("📂 Cargando maestros de establecimientos y productos…")
    names, places = _load_names(open_table)
    products = _load_products(open_table)

    log(f"🔎 Leyendo TFORMDET de {month_label(annomes).title()}…")
    tformdet = open_table("TFORMDET")
    if tformdet is None:
        raise FileNotFoundError("No se encontró TFORMDET.DBF en la carpeta DATOS del SISMED.")
    by_pharmacy = collections.defaultdict(list)
    for rec in tformdet:
        if text(rec.get("ANNOMES", rec.get("AÑOMES"))) == annomes:
            row = normalize_row(rec, products)
            by_pharmacy[row["CODIGO_PRE"]].append(row)
    if not by_pharmacy:
        return IciMonth(annomes, [], [], names, False)

    recetas = _load_recetas(open_table, annomes)
    first, last = month_bounds(annomes)
    pharmacies = {}
    for code, rows in by_pharmacy.items():
        counts, desde, hasta = recetas.get(code, ([0.0] * len(CONSUMO), None, None))
        rows.sort(key=lambda r: (r["DESC"], r["CODIGO_MED"], r["MEDLOTE"]))
        pharmacies[code] = Pharmacy(code, names.get(code, code), rows, counts, desde or first, hasta or last)

    warnings = []
    desde = min(p.desde for p in pharmacies.values())
    hasta = max(p.hasta for p in pharmacies.values())
    has_movements = open_table("TMOVIM") is not None and open_table("TMOVIMDET") is not None
    movements = []
    if has_movements:
        log("🔎 Leyendo los movimientos del mes (TMOVIM)…")
        movements = _load_movements(open_table, set(pharmacies), desde, hasta)
    else:
        warnings.append("No se encontró TMOVIM.DBF o TMOVIMDET.DBF: los vencidos quedan como los dejó el "
                        "SISMED y lo entregado entre farmacias se estima por lote.")

    groups = collections.defaultdict(list)
    for code in sorted(pharmacies):
        groups[ipress_of(code)].append(pharmacies[code])
    establishments = []
    for code, items in groups.items():
        place_code = code if code in places else items[0].code
        red, microred = places.get(place_code, ("", ""))
        name = names.get(code) or (items[0].name if len(items) == 1 else code)
        establishments.append(Establishment(code, name, red, microred, items))

    month = IciMonth(annomes, establishments, movements, names, has_movements, warnings)
    apply_vencidos(month)
    return month


# ── Reglas ─────────────────────────────────────────────────────────────────────


def _same_group(a: str, b: str) -> bool:
    return bool(a) and bool(b) and ipress_of(a) == ipress_of(b) and a != ipress_of(a) and b != ipress_of(b)


def is_internal(move: Movement) -> bool:
    """Entrega entre dos farmacias o puestos distintos del mismo establecimiento."""
    return move.origen != move.destino and _same_group(move.origen, move.destino)


def is_correction(move: Movement) -> bool:
    """Corrección de lote o de código: la guía dice «corrección…» en la referencia (en la UNGET del
    usuario las hace el almacén y entran como reingreso), o el producto salió y volvió a entrar en
    la misma farmacia."""
    return "CORREC" in plain_text(move.referencia) or (bool(move.origen) and move.origen == move.destino)


def touches(move: Movement, code: str) -> bool:
    """El movimiento sale de esa farmacia o entra a ella."""
    return (move.tipo == "S" and move.origen == code) or (move.tipo == "E" and move.destino == code)


def apply_vencidos(month: IciMonth) -> None:
    """Pasa a Vencidos las devoluciones de vencido (concepto 35) que el SISMED dejó en Devolución.

    Si el SISMED ya las puso en Vencidos (cuando el ICI lo genera un almacén) no se mueve nada:
    solo se pasa lo que falta para llegar a lo devuelto con el concepto 35."""
    expired = collections.defaultdict(float)
    for move in month.movements:
        if move.tipo == "S" and move.concepto == CONCEPTO_VENCIDO:
            for line in move.lines:
                expired[(move.origen, line.code, line.lote)] += line.qty
    if not expired:
        return
    rows_by_key = collections.defaultdict(list)
    for est in month.establishments:
        for ph in est.pharmacies:
            for row in ph.rows:
                rows_by_key[(row["CODIGO_PRE"], row["CODIGO_MED"], row["MEDLOTE"])].append(row)
    for key, qty in expired.items():
        rows = rows_by_key.get(key, [])
        pending = qty - sum(r["VENCIDO"] for r in rows)
        for row in rows:
            if pending <= 1e-9:
                break
            moved = min(row["DEVOL"], pending)
            if moved > 0:
                row["DEVOL"] -= moved
                row["VENCIDO"] += moved
                pending -= moved


def _mark_corrections(rows: list[dict], corrections: list[Movement]) -> None:
    keys = {(line.code, line.lote) for move in corrections for line in move.lines}
    for row in rows:
        if (row["CODIGO_MED"], row["MEDLOTE"]) in keys:
            row["flags"].add("correccion")


def _copy_rows(rows):
    return [{**row, "flags": set(row["flags"])} for row in rows]


def _place(est: Establishment) -> dict:
    return {"Red": est.red or "—", "Microred": est.microred or "—"}


def pharmacy_report(month: IciMonth, est: Establishment, ph: Pharmacy) -> IciReport:
    rows = _copy_rows(ph.rows)
    guias = [m for m in month.movements
             if m.tipo == "E" and m.destino == ph.code and m.concepto != "21" and not is_correction(m)]
    corrections = [m for m in month.movements if is_correction(m) and touches(m, ph.code)]
    _mark_corrections(rows, corrections)
    ficha = {
        **_place(est),
        "Establecimiento": est.name,
        "Código": est.code,
        "Farmacia": f"{pharmacy_suffix(ph.code)} · {ph.name}" if ph.code != est.code else ph.name,
    }
    return IciReport(
        annomes=month.annomes, title=ph.name, ficha=ficha, rows=rows, recetas=list(ph.recetas),
        desde=ph.desde, hasta=ph.hasta, guias=sorted(guias, key=_move_order), corrections=corrections,
        names=month.names,
    )


def _move_order(move: Movement):
    return (move.fecha or date.min, move.doc_numero, move.numero)


KEY_FIELDS = ("CODIGO_MED", "MEDLOTE", "MEDREGSAN", "TIPSUM2", "FFINAN")


def row_key(row: dict):
    return (*(row[f] for f in KEY_FIELDS), round(row["PRECIO"], 6))


def sum_rows(rows: list[dict]) -> list[dict]:
    """Suma por producto, lote, registro, suministro, financiamiento y precio."""
    groups = collections.OrderedDict()
    for row in sorted(rows, key=lambda r: (r["DESC"], r["CODIGO_MED"], r["MEDLOTE"])):
        key = row_key(row)
        acc = groups.get(key)
        if acc is None:
            acc = groups[key] = {**row, **{n: 0.0 for n in NUMS}, "flags": set(), "where": set()}
        for n in NUMS:
            acc[n] += row[n]
        acc["flags"] |= row["flags"]
        acc["where"].add(pharmacy_suffix(row["CODIGO_PRE"]))
    return list(groups.values())


def _take(rows: list[dict], lines: list[tuple[str, str, float]], column_of) -> dict:
    """Reparte cantidades por (código, lote) entre las filas, sin pasar lo que cada columna tiene.

    Devuelve {(id de fila, columna): cantidad}."""
    by_lot = collections.defaultdict(list)
    for row in rows:
        by_lot[(row["CODIGO_MED"], row["MEDLOTE"])].append(row)
    taken = collections.defaultdict(float)
    for code, lote, qty, column in ((c, l, q, column_of(x)) for c, l, q, x in lines):
        pending = qty
        for row in by_lot.get((code, lote), []):
            if pending <= 1e-9:
                break
            free = row[column] - taken[(id(row), column)]
            part = min(free, pending)
            if part > 0:
                taken[(id(row), column)] += part
                pending -= part
    return taken


def net_internal(rows: list[dict], movements: list[Movement]) -> tuple[float, float]:
    """Descuenta del consolidado lo entregado entre farmacias del establecimiento.

    Cada salida interna se quita de la columna donde la dejó su concepto y cada entrada interna
    de Reingreso, Ingreso o Ajuste. En cada fila se descuenta lo mismo de los dos lados (lo menos),
    para que el stock siga cuadrando: lo que salió a fin de mes y entró al mes siguiente (en
    camino) queda como salida. Devuelve (valor descontado, valor que quedó en camino)."""
    outs, ins = [], []
    for move in movements:
        if not is_internal(move):
            continue
        for line in move.lines:
            if move.tipo == "S":
                outs.append((line.code, line.lote, line.qty, move.concepto))
            else:
                ins.append((line.code, line.lote, line.qty, move.concepto))
    if not outs and not ins:
        return 0.0, 0.0
    out_col = lambda concepto: SALIDA_POR_CONCEPTO.get(concepto, "OTRAS")
    in_col = lambda concepto: ("REINGRE" if concepto in REINGRESO_CONCEPTOS
                               else "ING_REGULA" if concepto == "21" else "INGRE")
    per_row = collections.defaultdict(lambda: ({}, {}))
    for side, taken in ((0, _take(rows, outs, out_col)), (1, _take(rows, ins, in_col))):
        for (rid, col), qty in taken.items():
            per_row[rid][side][col] = qty
    netted = transit = 0.0
    for row in rows:
        if id(row) not in per_row:
            continue
        out_cols, in_cols = per_row[id(row)]
        out_total, in_total = sum(out_cols.values()), sum(in_cols.values())
        net = min(out_total, in_total)
        transit += (out_total - net) * row["PRECIO"]
        if net <= 0:
            continue
        for cols, is_out in ((out_cols, True), (in_cols, False)):
            pending = net
            for col, qty in cols.items():
                part = min(qty, pending)
                row[col] -= part
                pending -= part
            if is_out:
                row["TOTAL"] -= net
        row["flags"].add("interno")
        netted += net * row["PRECIO"]
    return netted, transit


def estimate_internal(rows: list[dict]) -> float:
    """Sin TMOVIM: lo devuelto y reingresado del mismo lote se toma como entrega interna."""
    netted = 0.0
    for row in rows:
        q = min(row["DEVOL"], row["REINGRE"])
        if q > 0:
            row["DEVOL"] -= q
            row["REINGRE"] -= q
            row["TOTAL"] -= q
            row["flags"].add("interno")
            netted += q * row["PRECIO"]
    return netted


def consolidated_report(month: IciMonth, est: Establishment) -> IciReport:
    codes = {ph.code for ph in est.pharmacies}
    rows = sum_rows([row for ph in est.pharmacies for row in ph.rows])
    moves = [m for m in month.movements if m.origen in codes or m.destino in codes]
    estimated = not month.has_movements
    if estimated:
        internal, transit = estimate_internal(rows), 0.0
    else:
        internal, transit = net_internal(rows, moves)
    corrections = [m for m in moves if is_correction(m) and any(touches(m, code) for code in codes)]
    _mark_corrections(rows, corrections)
    guias = [m for m in moves if m.tipo == "E" and m.destino in codes and m.concepto != "21"
             and not is_correction(m) and not is_internal(m)]
    recetas = [sum(ph.recetas[i] for ph in est.pharmacies) for i in range(len(CONSUMO))]
    suffixes = [pharmacy_suffix(ph.code) for ph in est.pharmacies]
    ficha = {
        **_place(est),
        "Establecimiento": est.name,
        "Código": est.code,
        "Farmacias": f"{_join(suffixes)} (consolidado)",
    }
    return IciReport(
        annomes=month.annomes, title=est.name, ficha=ficha, rows=rows, recetas=recetas,
        desde=min(ph.desde for ph in est.pharmacies), hasta=max(ph.hasta for ph in est.pharmacies),
        guias=sorted(guias, key=_move_order), corrections=sorted(corrections, key=_move_order),
        names=month.names, consolidated=True, internal_value=internal, internal_estimated=estimated,
        in_transit=transit,
    )


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} y {items[-1]}"


def balance_errors(rows: list[dict]) -> int:
    """Filas en que saldo + entradas − salidas no da el stock final (debe ser 0)."""
    bad = 0
    for row in rows:
        salidas = sum(row[n] for n in (*CONSUMO, *SALIDAS))
        stock = row["SALDO"] + sum(row[n] for n in ENTRADAS) - salidas
        if abs(salidas - row["TOTAL"]) > 1e-6 or abs(stock - row["STOCK_FIN"]) > 1e-6:
            bad += 1
    return bad


def read_month(sismed_dir: str, annomes: str, log=print) -> IciMonth:
    """Copia las tablas a una carpeta temporal y lee el mes."""
    from dbf_utils import open_dbf, snapshot_dbf

    with tempfile.TemporaryDirectory(prefix="toolkit_ici_") as snapshot_dir:
        cache = {}
        open_raw = dbf_tables(sismed_dir, snapshot_dir, open_dbf, snapshot_dbf)

        def open_table(name):
            if name not in cache:
                cache[name] = open_raw(name)
            return cache[name]

        return load_month(open_table, annomes, log)
