"""Búsqueda de guías en TMOVIM por N° de movimiento o por N° de guía.

El N° de guía (MOVNUMEDCO) se escribe a mano en SISMED: puede llevar serie
(«001-0012345»), ceros a la izquierda o espacios, y Excel borra los ceros a la izquierda
al copiar una lista. Por eso la guía se compara sin esos ceros y, si se escribe solo el
número, también contra el número sin la serie.

Un error al pegar debe terminar en «no encontrada», nunca en otra guía marcada: en el
modo masivo la guía va una por línea (los espacios son parte de la guía) y una guía que
aparece en varios movimientos (p. ej., la anulada y la que se registró de nuevo) no se
marca sola.
"""

from __future__ import annotations

import re
from collections import Counter

BY_MOVEMENT = "movimiento"
BY_GUIDE = "guia"
FIELDS = {BY_MOVEMENT: "MOVNUMERO", BY_GUIDE: "MOVNUMEDCO"}
SIMPLE_LIMIT = 500

_GROUPS = re.compile(r"[0-9A-Z]+")
_DIGITS = re.compile(r"\d+")


def normalize_by(value) -> str:
    return BY_GUIDE if value == BY_GUIDE else BY_MOVEMENT


def split_values(text, by: str = BY_MOVEMENT) -> list[str]:
    """Valores pegados en el modo masivo, sin repetir y en el orden en que se pegaron."""
    separators = r"[\r\n,;\t]+" if by == BY_GUIDE else r"[\s,;]+"
    values, seen = [], set()
    for raw in re.split(separators, str(text or "")):
        value = raw.strip()
        key = value.upper()
        if value and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def guide_key(value) -> str:
    """«001-0012345», «001 - 12345» y «1-12345» dan la misma clave: «1-12345»."""
    groups = _GROUPS.findall(str(value or "").upper())
    return "-".join((g.lstrip("0") or "0") if g.isdigit() else g for g in groups)


def guide_number(value) -> str:
    """El número de la guía sin la serie: el último grupo de dígitos, sin ceros a la izquierda."""
    digits = _DIGITS.findall(str(value or ""))
    return (digits[-1].lstrip("0") or "0") if digits else ""


def simple_match(query: str, stored, by: str) -> bool:
    """Búsqueda simple: el registro contiene lo escrito."""
    q = str(query or "").strip().upper()
    if not q:
        return False
    value = str(stored or "").strip().upper()
    if by != BY_GUIDE:
        return q in value
    if re.sub(r"\s+", "", q) in re.sub(r"\s+", "", value):
        return True
    key = guide_key(q)
    return bool(key) and key in guide_key(value)


class ListMatcher:
    """Valores pegados en el modo masivo, listos para compararse con cada registro."""

    def __init__(self, values, by: str):
        self.by = normalize_by(by)
        self.values: list[str] = []
        self._exact: dict[str, str] = {}
        self._number: dict[str, str] = {}
        for value in values:
            key = guide_key(value) if self.by == BY_GUIDE else str(value).strip().upper()
            if not key or key in self._exact:
                continue
            self._exact[key] = value
            self.values.append(value)
            if self.by == BY_GUIDE and str(value).strip().isdigit():
                self._number[key] = value

    def match(self, stored) -> list[str]:
        """Valores pegados que corresponden a este registro (normalmente uno o ninguno)."""
        if self.by != BY_GUIDE:
            found = self._exact.get(str(stored or "").strip().upper())
            return [found] if found else []
        found = []
        exact = self._exact.get(guide_key(stored))
        if exact:
            found.append(exact)
        by_number = self._number.get(guide_number(stored))
        if by_number and by_number not in found:
            found.append(by_number)
        return found


def summarize(values: list[str], row_matches: list[list[str]], by: str) -> tuple[set[int], list[str], list[str]]:
    """(filas a marcar, valores no encontrados, guías que están en más de un movimiento)."""
    counts = Counter(value for matches in row_matches for value in matches)
    not_found = [value for value in values if counts[value] == 0]
    if normalize_by(by) != BY_GUIDE:
        return {i for i, matches in enumerate(row_matches) if matches}, not_found, []
    repeated = [value for value in values if counts[value] > 1]
    preselect = {
        i for i, matches in enumerate(row_matches)
        if matches and all(counts[value] == 1 for value in matches)
    }
    return preselect, not_found, repeated


def short_list(values: list[str], limit: int = 5) -> str:
    shown = ", ".join(values[:limit])
    rest = len(values) - limit
    return f"{shown} y {rest} más" if rest > 0 else shown
