import datetime
import os
import shutil
from dataclasses import dataclass, field

from dbfread import DBF
from dbfread.field_parser import FieldParser


@dataclass
class DbfReadMetrics:
    label: str = "DBF"
    total_records: int = 0
    corrupted_records: int = 0
    omitted_records: int = 0
    field_fallbacks: int = 0
    fallback_by_field: dict[str, int] = field(default_factory=dict)
    fallback_by_type: dict[str, int] = field(default_factory=dict)
    omitted_by_reason: dict[str, int] = field(default_factory=dict)
    _pending_record_fallback: bool = False

    @property
    def problem_records(self) -> int:
        return self.corrupted_records + self.omitted_records

    @property
    def corruption_ratio(self) -> float:
        if self.total_records <= 0:
            return 0.0
        return self.corrupted_records / self.total_records

    @property
    def problem_ratio(self) -> float:
        if self.total_records <= 0:
            return 0.0
        return self.problem_records / self.total_records

    def note_fallback(self, field_name: str, field_type: str):
        self.field_fallbacks += 1
        self._pending_record_fallback = True
        self.fallback_by_field[field_name] = self.fallback_by_field.get(field_name, 0) + 1
        self.fallback_by_type[field_type] = self.fallback_by_type.get(field_type, 0) + 1

    def note_record(self, *, had_fallback: bool | None = None):
        if had_fallback is None:
            had_fallback = self._pending_record_fallback
        self.total_records += 1
        if had_fallback:
            self.corrupted_records += 1
        self._pending_record_fallback = False

    def note_omission(self, reason: str, count: int = 1):
        count = max(0, int(count or 0))
        if count == 0:
            return
        self.omitted_records += count
        self.omitted_by_reason[reason] = self.omitted_by_reason.get(reason, 0) + count

    def summary(self) -> str:
        base = (
            f"{self.label}: total={self.total_records}, corruptos={self.corrupted_records}, "
            f"omitidos={self.omitted_records}, fallbacks={self.field_fallbacks}, ratio={self.problem_ratio:.2%}"
        )
        if not self.fallback_by_field:
            return base

        top_fields = ", ".join(
            f"{name}={count}"
            for name, count in sorted(
                self.fallback_by_field.items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        )
        return f"{base}, campos={top_fields}"


class SafeDbfFieldParser(FieldParser):
    """Parser tolerante para DBF con fechas, números o flags corruptos."""

    def __init__(self, table, memofile=None):
        super().__init__(table, memofile)
        self._metrics = getattr(table, "_dbf_read_metrics", None)

    @staticmethod
    def _to_bytes(data) -> bytes:
        if data is None:
            return b""
        return bytes(data)

    def _note_fallback(self, field):
        if self._metrics is not None:
            self._metrics.note_fallback(field.name, field.type)

    @classmethod
    def _clean_number_bytes(cls, data) -> bytes:
        return cls._to_bytes(data).replace(b"\x00", b"").strip().strip(b"*")

    def parse(self, field, data):
        try:
            return super().parse(field, data)
        except (ValueError, TypeError, OverflowError):
            self._note_fallback(field)
            if field.type == "C":
                return ""
            if field.type in {"D", "T", "N", "F", "L", "M", "I", "O", "Y", "B", "P", "G", "+"}:
                return None
            raise

    def parseC(self, field, data):
        return self.decode_text(self._to_bytes(data).rstrip(b"\0 "))

    def parseD(self, field, data):
        clean = self._to_bytes(data).replace(b"\x00", b"").strip()
        if not clean or clean.strip(b"0") == b"":
            return None
        if len(clean) != 8 or not clean.isdigit():
            self._note_fallback(field)
            return None
        try:
            return datetime.date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        except ValueError:
            self._note_fallback(field)
            return None

    def parseF(self, field, data):
        clean = self._clean_number_bytes(data)
        if not clean:
            return None
        try:
            return float(clean.replace(b",", b"."))
        except ValueError:
            self._note_fallback(field)
            return None

    def parseL(self, field, data):
        clean = self._to_bytes(data).replace(b"\x00", b"").strip()
        if not clean or clean in b"?":
            return None
        if clean in b"TtYy":
            return True
        if clean in b"FfNn":
            return False
        self._note_fallback(field)
        return None

    def _parse_memo_index(self, data):
        clean = self._clean_number_bytes(data)
        if not clean:
            return 0
        try:
            return super()._parse_memo_index(clean)
        except ValueError:
            return 0

    def parseN(self, field, data):
        clean = self._clean_number_bytes(data)
        if not clean:
            return None
        try:
            return int(clean)
        except ValueError:
            try:
                return float(clean.replace(b",", b"."))
            except ValueError:
                self._note_fallback(field)
                return None

    def parseT(self, field, data):
        clean = self._to_bytes(data)
        try:
            return super().parseT(field, clean)
        except (ValueError, TypeError, OverflowError):
            if clean.strip() or clean.strip(b"\x00"):
                self._note_fallback(field)
            return None


def _bind_metrics_parser(parserclass, metrics: DbfReadMetrics):
    class MetricsParser(parserclass):
        def __init__(self, table, memofile=None):
            table._dbf_read_metrics = metrics
            super().__init__(table, memofile)

    MetricsParser.__name__ = f"Metrics{parserclass.__name__}"
    return MetricsParser


def open_dbf(path: str, **overrides) -> DBF:
    metrics = overrides.pop("metrics", None)
    parserclass = overrides.pop("parserclass", SafeDbfFieldParser)
    if metrics is not None:
        parserclass = _bind_metrics_parser(parserclass, metrics)

    options = {
        "ignore_missing_memofile": True,
        "char_decode_errors": "ignore",
        "parserclass": parserclass,
    }
    options.update(overrides)
    return DBF(path, **options)


def iter_dbf_records(table: DBF, metrics: DbfReadMetrics | None = None):
    for record in table:
        yield record
        if metrics is not None:
            metrics.note_record()


def live_record_positions(table: DBF) -> list[int]:
    """Posición física (0, 1, 2…) de cada registro que entrega dbfread, en el mismo orden.

    dbfread se salta los registros marcados como borrados (DELETE de FoxPro sin PACK): el
    registro n que se lee no es el registro n del archivo. Para escribir sobre el registro
    correcto hay que usar esta posición.
    """
    positions = []
    record_len = table.header.recordlen
    with open(table.filename, "rb") as fh:
        fh.seek(table.header.headerlen)
        position = 0
        while True:
            flag = fh.read(1)
            if flag in (b"\x1a", b""):
                break
            if flag == b" ":
                positions.append(position)
            fh.seek(record_len - 1, os.SEEK_CUR)
            position += 1
    return positions


def snapshot_dbf(path: str, snapshot_dir: str) -> str:
    """Copia el DBF y sidecars relacionados a una carpeta temporal."""
    if not os.path.exists(path):
        return path

    destination = os.path.join(snapshot_dir, os.path.basename(path))
    shutil.copy2(path, destination)

    source_base, _ = os.path.splitext(path)
    for extension in (".fpt", ".dbt", ".mdx", ".cdx"):
        for candidate in (source_base + extension, source_base + extension.upper()):
            if os.path.exists(candidate):
                shutil.copy2(candidate, os.path.join(snapshot_dir, os.path.basename(candidate)))
                break

    return destination