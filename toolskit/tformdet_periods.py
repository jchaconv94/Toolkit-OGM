"""Periodo de la Consulta TFORMDET como «los últimos N meses».

Antes había que elegir mes y año de inicio y de fin, y para pedir 12 o 24 meses atrás había
que calcular a mano qué mes y qué año eran. Ahora se pide un número de meses y aquí se
calcula el rango. El mes actual (todavía incompleto) solo entra si se pide.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MESES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
MIN_MONTHS = 1
MAX_MONTHS = 120


@dataclass(frozen=True)
class MonthRange:
    start_year: int
    start_month: int
    end_year: int
    end_month: int
    months: int
    includes_current: bool

    @property
    def periodo_ini(self) -> str:
        """Formato que usa TformdetManager: AAAAMM."""
        return f"{self.start_year:04d}{self.start_month:02d}"

    @property
    def periodo_fin(self) -> str:
        return f"{self.end_year:04d}{self.end_month:02d}"

    def description(self) -> str:
        start = f"{MESES[self.start_month - 1]} {self.start_year}"
        end = f"{MESES[self.end_month - 1]} {self.end_year}"
        meses = "1 mes" if self.months == 1 else f"{self.months} meses"
        if self.months == 1:
            return f"{start} · {meses}"
        return f"De {start} a {end} · {meses}"


def clamp_months(value) -> int:
    """Número de meses válido (1 a 120). Lo que no es número cuenta como 1."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return MIN_MONTHS
    return max(MIN_MONTHS, min(MAX_MONTHS, number))


def last_months(months, include_current: bool, today: date | None = None) -> MonthRange:
    """Los últimos `months` meses hasta el mes anterior (o hasta el actual, si se pide)."""
    today = today or date.today()
    count = clamp_months(months)
    end_index = today.year * 12 + (today.month - 1) - (0 if include_current else 1)
    start_index = end_index - count + 1
    return MonthRange(
        start_year=start_index // 12,
        start_month=start_index % 12 + 1,
        end_year=end_index // 12,
        end_month=end_index % 12 + 1,
        months=count,
        includes_current=include_current,
    )


def single_month(year, month, today: date | None = None) -> MonthRange | None:
    """Un mes específico (el modo de siempre). None si el año o el mes no son válidos."""
    today = today or date.today()
    try:
        y, m = int(str(year).strip()), int(str(month).strip())
    except (TypeError, ValueError):
        return None
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        return None
    return MonthRange(y, m, y, m, 1, (y, m) == (today.year, today.month))


def month_range(start_year, start_month, end_year, end_month,
                today: date | None = None) -> tuple[MonthRange | None, str]:
    """Rango de un mes de inicio a un mes de fin. Devuelve (rango, mensaje de error)."""
    today = today or date.today()
    start = single_month(start_year, start_month, today)
    end = single_month(end_year, end_month, today)
    if start is None or end is None:
        return None, "Escriba un año válido (por ejemplo, 2026)."
    first = start.start_year * 12 + start.start_month - 1
    last = end.start_year * 12 + end.start_month - 1
    if first > last:
        return None, "El mes de inicio no puede ser posterior al mes de fin."
    current = today.year * 12 + today.month - 1
    return MonthRange(
        start.start_year, start.start_month, end.start_year, end.start_month,
        last - first + 1, first <= current <= last,
    ), ""
