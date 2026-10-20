"""Generar ICI: calcula las fórmulas del libro para dibujar el PDF sin un programa de hojas de cálculo.

El libro del ICI usa pocas fórmulas (SUM, SUBTOTAL, SUMPRODUCT, COUNTIF, COUNTIFS, DATE, EDATE, AND,
ISNUMBER, sumas y productos de celdas). Este evaluador las resuelve igual que Excel: el texto cuenta
como cero en SUMPRODUCT y no cuenta en SUM ni en COUNTIF, y las fechas valen su número de serie.
También evalúa las reglas de formato condicional (con sus referencias relativas desplazadas a cada
celda), para pintar en el PDF lo mismo que pinta Excel.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

EPOCH = dt.datetime(1899, 12, 30)

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>\d+(?:\.\d+)?)
    | (?P<str>"(?:[^"]|"")*")
    | (?P<ref>\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
    | (?P<func>[A-Z][A-Z0-9.]*)\(
    | (?P<op><=|>=|<>|[-+*/&=<>(),])
    )""", re.VERBOSE)
_CELL = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def serial(value):
    """El número con que Excel compara: las fechas valen su número de serie; el texto, None."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dt.datetime):
        return (value - EPOCH).total_seconds() / 86400
    if isinstance(value, dt.date):
        return float((value - EPOCH.date()).days)
    return None


def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"Fórmula no reconocida: {text!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class _Parser:
    """Árbol de una fórmula: ("num", v) ("str", v) ("ref", r1, c1, abs_r1, abs_c1, r2, c2, abs_r2, abs_c2)
    ("call", nombre, [args]) ("bin", op, a, b) ("neg", a)."""

    def __init__(self, text):
        self.toks, self.i = _tokens(text), 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise ValueError(f"Se esperaba {value!r}")
        self.i += 1
        return tok

    def parse(self):
        node = self.compare()
        if self.i != len(self.toks):
            raise ValueError("Sobra texto en la fórmula")
        return node

    def compare(self):
        node = self.concat()
        while self.peek()[1] in ("=", "<", ">", "<=", ">=", "<>"):
            op = self.take()[1]
            node = ("bin", op, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.peek()[1] == "&":
            self.take()
            node = ("bin", "&", node, self.additive())
        return node

    def additive(self):
        node = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek()[1] == "-":
            self.take()
            return ("neg", self.unary())
        if self.peek()[1] == "+":
            self.take()
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", float(value))
        if kind == "str":
            return ("str", value[1:-1].replace('""', '"'))
        if kind == "ref":
            parts = value.split(":")
            a = _CELL.fullmatch(parts[0])
            b = _CELL.fullmatch(parts[-1])
            return ("ref", int(a.group(4)), col_index(a.group(2)), bool(a.group(3)), bool(a.group(1)),
                    int(b.group(4)), col_index(b.group(2)), bool(b.group(3)), bool(b.group(1)), len(parts) == 2)
        if kind == "func":
            args = []
            if self.peek()[1] != ")":
                args.append(self.compare())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.compare())
            self.take(")")
            return ("call", value, args)
        if value == "(":
            node = self.compare()
            self.take(")")
            return node
        raise ValueError(f"Fórmula no reconocida cerca de {value!r}")


def _matches(value, criterion) -> bool:
    """COUNTIF: «>0», «<=46265», 0, …"""
    if isinstance(criterion, str):
        m = re.fullmatch(r"(<=|>=|<>|<|>|=)?(.*)", criterion)
        op, rest = m.group(1) or "=", m.group(2)
        try:
            target = float(rest)
        except ValueError:
            return op == "=" and str(value or "") == rest
    else:
        op, target = "=", serial(criterion)
    number = serial(value)
    if number is None or target is None:
        return False
    return {"=": number == target, "<>": number != target, "<": number < target, ">": number > target,
            "<=": number <= target, ">=": number >= target}[op]


class Evaluator:
    """Valores de las celdas de una hoja de openpyxl, con sus fórmulas calculadas."""

    def __init__(self, ws):
        self.ws = ws
        self.cache = {}
        self.trees = {}
        self.busy = set()

    def raw(self, r, c):
        cell = self.ws._cells.get((r, c))
        return None if cell is None else cell.value

    def value(self, r, c):
        key = (r, c)
        if key in self.cache:
            return self.cache[key]
        raw = self.raw(r, c)
        if isinstance(raw, str) and raw.startswith("="):
            if key in self.busy:          # referencia circular: Excel daría error
                return None
            self.busy.add(key)
            try:
                raw = self.formula(raw[1:])
            except Exception:  # noqa: BLE001 - una fórmula que no se entiende queda vacía
                raw = None
            finally:
                self.busy.discard(key)
            if isinstance(raw, list):
                raw = raw[0] if raw else None
        self.cache[key] = raw
        return raw

    def formula(self, text: str, dr: int = 0, dc: int = 0):
        tree = self.trees.get(text)
        if tree is None:
            tree = self.trees[text] = _Parser(text).parse()
        return self._eval(tree, dr, dc)

    def _range(self, node, dr, dc):
        _, r1, c1, ar1, ac1, r2, c2, ar2, ac2, _ = node
        r1, r2 = r1 + (0 if ar1 else dr), r2 + (0 if ar2 else dr)
        c1, c2 = c1 + (0 if ac1 else dc), c2 + (0 if ac2 else dc)
        return [self.value(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]

    def _scalar(self, node, dr, dc):
        value = self._eval(node, dr, dc)
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def _num(self, node, dr, dc):
        value = serial(self._scalar(node, dr, dc))
        return 0.0 if value is None else value

    def _eval(self, node, dr, dc):
        kind = node[0]
        if kind in ("num", "str"):
            return node[1]
        if kind == "ref":
            values = self._range(node, dr, dc)
            return values if node[-1] else (values[0] if values else None)
        if kind == "neg":
            return -self._num(node[1], dr, dc)
        if kind == "bin":
            op, a, b = node[1], node[2], node[3]
            if op == "&":
                return "".join(_text(self._scalar(x, dr, dc)) for x in (a, b))
            if op in ("+", "-", "*", "/"):
                x, y = self._num(a, dr, dc), self._num(b, dr, dc)
                return x + y if op == "+" else x - y if op == "-" else x * y if op == "*" else (x / y if y else None)
            x, y = serial(self._scalar(a, dr, dc)), serial(self._scalar(b, dr, dc))
            if x is None or y is None:
                return False
            return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        name, args = node[1], node[2]
        if name in ("SUM", "SUBTOTAL"):
            items = args[1:] if name == "SUBTOTAL" else args
            total = 0.0
            for arg in items:
                value = self._eval(arg, dr, dc)
                for v in (value if isinstance(value, list) else [value]):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        total += v
            return total
        if name == "SUMPRODUCT":
            arrays = [self._eval(arg, dr, dc) for arg in args]
            arrays = [a if isinstance(a, list) else [a] for a in arrays]
            total = 0.0
            for items in zip(*arrays):
                product = 1.0
                for v in items:
                    product *= v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
                total += product
            return total
        if name in ("COUNTIF", "COUNTIFS"):
            pairs = [(self._eval(args[k], dr, dc), self._scalar(args[k + 1], dr, dc)) for k in range(0, len(args), 2)]
            pairs = [(rng if isinstance(rng, list) else [rng], crit) for rng, crit in pairs]
            return float(sum(1 for items in zip(*(rng for rng, _ in pairs))
                             if all(_matches(v, crit) for v, (_, crit) in zip(items, pairs))))
        if name == "DATE":
            y, m, d = (int(self._num(a, dr, dc)) for a in args)
            return serial(dt.date(y, m, d))
        if name == "EDATE":
            start = EPOCH.date() + dt.timedelta(days=int(self._num(args[0], dr, dc)))
            months = start.month - 1 + int(self._num(args[1], dr, dc))
            year, month = start.year + months // 12, months % 12 + 1
            day = min(start.day, calendar.monthrange(year, month)[1])
            return serial(dt.date(year, month, day))
        if name == "AND":
            return all(bool(self._scalar(a, dr, dc)) for a in args)
        if name == "ISNUMBER":
            v = self._scalar(args[0], dr, dc)
            return serial(v) is not None and not isinstance(v, bool)
        raise ValueError(f"Función no soportada: {name}")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
