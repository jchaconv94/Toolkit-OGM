from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable
import os
import re
import shutil
import struct

try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows app, fallback for tests elsewhere.
    msvcrt = None


CRITICAL_FIELDS = (
    "CODIGO_EJE",
    "CODIGO_PRE",
    "TIPSUM",
    "ANNOMES",
    "CODIGO_MED",
    "SALDO",
    "PRECIO",
)

INDEX_SIDECARE_EXTENSIONS = {".CDX", ".IDX", ".NTX"}
BACKUP_SIDECARE_EXTENSIONS = {
    ".DBF",
    ".FPT",
    ".DBT",
    ".CDX",
    ".IDX",
    ".NTX",
    ".INF",
}
NUMERIC_FIELD_TYPES = {"N", "F"}
CHAR_FIELD_TYPES = {"C"}
ProgressCallback = Callable[[str], None]


class TformdetAppendError(Exception):
    pass


@dataclass(frozen=True)
class DbfField:
    name: str
    type: str
    length: int
    decimals: int
    offset: int


@dataclass
class DbfHeader:
    path: Path
    version: int
    record_count: int
    header_length: int
    record_length: int
    fields: list[DbfField]

    @property
    def field_map(self) -> dict[str, DbfField]:
        return {field.name: field for field in self.fields}


@dataclass
class AppendAnalysis:
    source_path: Path
    destination_path: Path
    source_header: DbfHeader
    destination_header: DbfHeader
    source_period_counts: dict[str, int]
    source_codigo_pre_counts: dict[str, int]
    source_key_counts: dict[str, int]
    destination_periods: set[str]
    destination_codigo_pres: set[str]
    destination_keys: set[str]
    periods_to_import: list[str]
    duplicate_periods: list[str]
    keys_to_import: list[str]
    duplicate_keys: list[str]
    codigo_pres_to_import_counts: dict[str, int]
    records_to_import: int
    invalid_source_records: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_import(self) -> bool:
        return not self.errors and self.records_to_import > 0


@dataclass
class AppendResult:
    backup_dir: Path | None
    imported_records: int
    imported_periods: list[str]
    skipped_periods: list[str]
    previous_record_count: int
    new_record_count: int


class TformdetAppendManager:
    def analyze(
        self,
        source_path: str | Path,
        destination_path: str | Path,
        *,
        progress: ProgressCallback | None = None,
    ) -> AppendAnalysis:
        source = Path(source_path).expanduser()
        destination = Path(destination_path).expanduser()
        errors: list[str] = []
        warnings: list[str] = []

        self._validate_basic_paths(source, destination, errors)

        self._notify(progress, "Revisando la estructura del archivo DBF seleccionado...")
        source_header = self._read_header(source) if not errors else None
        self._notify(progress, "Revisando la estructura del TFORMDET destino...")
        destination_header = self._read_header(destination) if not errors else None
        if source_header is None or destination_header is None:
            raise TformdetAppendError("; ".join(errors) or "No se pudo leer la estructura DBF.")

        self._notify(progress, "Validando que ambos archivos sean compatibles...")
        errors.extend(self._validate_tformdet_header(source_header, "origen"))
        errors.extend(self._validate_tformdet_header(destination_header, "destino"))
        schema_errors, schema_warnings = self._validate_schema_compatibility(
            source_header, destination_header
        )
        errors.extend(schema_errors)
        warnings.extend(schema_warnings)

        source_period_counts: dict[str, int] = {}
        source_codigo_pre_counts: dict[str, int] = {}
        source_key_counts: dict[str, int] = {}
        invalid_source_records = 0
        self._notify(progress, "Leyendo registros del archivo que se va a agregar...")
        for index, record in enumerate(self._iter_active_records(source_header), start=1):
            if index % 50000 == 0:
                self._notify(progress, f"   Archivo origen: {index:,} filas revisadas...")
            codigo_pre = self._record_field_value(record, source_header, "CODIGO_PRE")
            if codigo_pre:
                source_codigo_pre_counts[codigo_pre] = (
                    source_codigo_pre_counts.get(codigo_pre, 0) + 1
                )
            period = self._record_period(record, source_header)
            if not period:
                invalid_source_records += 1
                continue
            source_period_counts[period] = source_period_counts.get(period, 0) + 1
            if not codigo_pre:
                invalid_source_records += 1
                continue
            key = self._code_period_key(codigo_pre, period)
            source_key_counts[key] = source_key_counts.get(key, 0) + 1

        destination_periods: set[str] = set()
        destination_codigo_pres: set[str] = set()
        destination_keys: set[str] = set()
        self._notify(progress, "Leyendo registros que ya existen en el SISMED destino...")
        for index, record in enumerate(self._iter_active_records(destination_header), start=1):
            if index % 50000 == 0:
                self._notify(progress, f"   SISMED destino: {index:,} filas revisadas...")
            if period := self._record_period(record, destination_header):
                destination_periods.add(period)
            codigo_pre = self._record_field_value(record, destination_header, "CODIGO_PRE")
            if codigo_pre:
                destination_codigo_pres.add(codigo_pre)
            if codigo_pre and period:
                destination_keys.add(self._code_period_key(codigo_pre, period))

        self._notify(progress, "Comparando datos para evitar registros duplicados...")
        duplicate_keys = sorted(
            key for key in source_key_counts if key in destination_keys
        )
        keys_to_import = sorted(
            key for key in source_key_counts if key not in destination_keys
        )
        records_to_import = sum(source_key_counts[key] for key in keys_to_import)
        duplicate_periods = sorted(
            {self._period_from_key(key) for key in duplicate_keys}
        )
        periods_to_import = sorted(
            {self._period_from_key(key) for key in keys_to_import}
        )
        codigo_pres_to_import_counts: dict[str, int] = {}
        for key in keys_to_import:
            codigo_pre = self._codigo_pre_from_key(key)
            codigo_pres_to_import_counts[codigo_pre] = (
                codigo_pres_to_import_counts.get(codigo_pre, 0) + source_key_counts[key]
            )

        if invalid_source_records:
            warnings.append(
                f"Se omitiran {invalid_source_records} filas del archivo porque no tienen establecimiento o mes valido."
            )
        if records_to_import > 0 and not codigo_pres_to_import_counts:
            errors.append("Las filas nuevas no tienen codigo de establecimiento valido.")
        if records_to_import > 0:
            destination_indexes = self._find_sidecars(destination, INDEX_SIDECARE_EXTENSIONS)
            if destination_indexes:
                names = ", ".join(path.name for path in destination_indexes)
                warnings.append(
                    "El TFORMDET destino tiene indices DBF (" + names + "). "
                    "Se respaldaran junto con el DBF antes de anexar."
                )
        if periods_to_import and not errors:
            self._notify(progress, "Verificando que las filas nuevas puedan guardarse...")
            errors.extend(
                self._validate_records_fit(
                    source_header,
                    destination_header,
                    set(keys_to_import),
                )
            )
        if not source_key_counts:
            errors.append(
                "El archivo seleccionado no contiene filas activas con establecimiento y mes validos."
            )
        if not keys_to_import and source_key_counts:
            warnings.append(
                "Todo el archivo ya estaba cargado para el mismo establecimiento y mes."
            )

        return AppendAnalysis(
            source_path=source,
            destination_path=destination,
            source_header=source_header,
            destination_header=destination_header,
            source_period_counts=source_period_counts,
            source_codigo_pre_counts=source_codigo_pre_counts,
            source_key_counts=source_key_counts,
            destination_periods=destination_periods,
            destination_codigo_pres=destination_codigo_pres,
            destination_keys=destination_keys,
            periods_to_import=periods_to_import,
            duplicate_periods=duplicate_periods,
            keys_to_import=keys_to_import,
            duplicate_keys=duplicate_keys,
            codigo_pres_to_import_counts=codigo_pres_to_import_counts,
            records_to_import=records_to_import,
            invalid_source_records=invalid_source_records,
            errors=errors,
            warnings=warnings,
        )

    def append_new_periods(
        self,
        source_path: str | Path,
        destination_path: str | Path,
        *,
        backup_root: str | Path | None = None,
        analysis: AppendAnalysis | None = None,
        progress: ProgressCallback | None = None,
    ) -> AppendResult:
        if analysis is None:
            analysis = self.analyze(source_path, destination_path, progress=progress)
        if analysis.errors:
            raise TformdetAppendError("; ".join(analysis.errors))

        if analysis.records_to_import == 0:
            return AppendResult(
                backup_dir=None,
                imported_records=0,
                imported_periods=[],
                skipped_periods=analysis.duplicate_periods,
                previous_record_count=analysis.destination_header.record_count,
                new_record_count=analysis.destination_header.record_count,
            )

        try:
            self._notify(progress, "Creando copia de seguridad del TFORMDET destino...")
            backup_dir = self._backup_destination(analysis.destination_path, backup_root)
            self._notify(progress, "   Copia de seguridad creada correctamente.")
        except PermissionError as exc:
            raise TformdetAppendError(
                "No se puede crear el backup del destino. Cierre SISMED o FoxPro y vuelva a intentar."
            ) from exc

        destination_file = open(analysis.destination_path, "r+b")
        locked = False
        try:
            locked = self._try_lock(destination_file)

            self._notify(progress, "Preparando solo las filas nuevas...")
            records = list(self._build_destination_records(analysis, progress=progress))
            if len(records) != analysis.records_to_import:
                raise TformdetAppendError(
                    "La cantidad de registros preparada no coincide con el analisis."
                )

            new_count = analysis.destination_header.record_count + len(records)
            self._notify(progress, "Escribiendo las filas nuevas en TFORMDET...")
            self._append_records(destination_file, analysis.destination_header, records, new_count)
            self._notify(progress, "   Escritura finalizada correctamente.")

            return AppendResult(
                backup_dir=backup_dir,
                imported_records=len(records),
                imported_periods=analysis.periods_to_import,
                skipped_periods=analysis.duplicate_periods,
                previous_record_count=analysis.destination_header.record_count,
                new_record_count=new_count,
            )
        except PermissionError as exc:
            raise TformdetAppendError(
                "No se puede escribir en el destino. Cierre SISMED o FoxPro y vuelva a intentar."
            ) from exc
        finally:
            if locked and msvcrt is not None:
                try:
                    destination_file.seek(0)
                    msvcrt.locking(destination_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            destination_file.close()

    def _notify(self, progress: ProgressCallback | None, message: str) -> None:
        if progress is not None:
            progress(message)

    def _validate_basic_paths(self, source: Path, destination: Path, errors: list[str]) -> None:
        if not source.exists():
            errors.append("El DBF origen no existe.")
        if not destination.exists():
            errors.append("El DBF destino no existe.")
        if source.suffix.upper() != ".DBF":
            errors.append("El origen debe ser un archivo .DBF.")
        if destination.suffix.upper() != ".DBF":
            errors.append("El destino debe ser un archivo .DBF.")
        if destination.name.upper() != "TFORMDET.DBF":
            errors.append("Por seguridad, el destino debe llamarse TFORMDET.DBF.")
        try:
            if source.resolve() == destination.resolve():
                errors.append("El origen y el destino no pueden ser el mismo archivo.")
        except OSError:
            pass

    def _validate_tformdet_header(self, header: DbfHeader, label: str) -> list[str]:
        errors: list[str] = []
        field_names = set(header.field_map)
        missing = [field for field in CRITICAL_FIELDS if field not in field_names]
        if missing:
            errors.append(
                f"El DBF {label} no parece TFORMDET. Faltan campos: {', '.join(missing)}."
            )
        return errors

    def _validate_schema_compatibility(
        self, source_header: DbfHeader, destination_header: DbfHeader
    ) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        source_fields = source_header.field_map
        destination_fields = destination_header.field_map

        for field_name in CRITICAL_FIELDS:
            source_field = source_fields.get(field_name)
            destination_field = destination_fields.get(field_name)
            if source_field and destination_field and not self._types_compatible(
                source_field, destination_field
            ):
                errors.append(
                    "Campo critico incompatible "
                    f"{field_name}: origen {source_field.type} vs destino "
                    f"{destination_field.type}."
                )

        source_only = [
            field.name for field in source_header.fields if field.name not in destination_fields
        ]
        destination_only = [
            field.name for field in destination_header.fields if field.name not in source_fields
        ]
        incompatible_common = [
            field.name
            for field in source_header.fields
            if field.name in destination_fields
            and field.name not in CRITICAL_FIELDS
            and not self._types_compatible(field, destination_fields[field.name])
        ]
        converted_common = [
            field.name
            for field in source_header.fields
            if field.name in destination_fields
            and self._types_compatible(field, destination_fields[field.name])
            and (
                field.length != destination_fields[field.name].length
                or field.decimals != destination_fields[field.name].decimals
            )
        ]

        if source_only:
            warnings.append(
                "El origen tiene columnas que el destino no tiene y se ignoraran: "
                + self._preview_names(source_only)
            )
        if destination_only:
            warnings.append(
                "El destino tiene columnas adicionales; quedaran en blanco en los registros anexados: "
                + self._preview_names(destination_only)
            )
        if incompatible_common:
            warnings.append(
                "Campos no criticos con tipo incompatible quedaran en blanco: "
                + self._preview_names(incompatible_common)
            )
        if converted_common:
            warnings.append(
                "Campos comunes con longitud/decimales distintos se convertiran al formato destino: "
                + self._preview_names(converted_common)
            )

        return errors, warnings

    def _read_header(self, path: Path) -> DbfHeader:
        with path.open("rb") as handle:
            header = handle.read(32)
            if len(header) < 32:
                raise TformdetAppendError(f"{path.name} no tiene cabecera DBF valida.")

            version = header[0]
            record_count = struct.unpack("<I", header[4:8])[0]
            header_length = struct.unpack("<H", header[8:10])[0]
            record_length = struct.unpack("<H", header[10:12])[0]

            fields: list[DbfField] = []
            offset = 1
            while True:
                descriptor = handle.read(32)
                if not descriptor:
                    raise TformdetAppendError(f"{path.name} no tiene terminador de campos DBF.")
                if descriptor[0] == 0x0D:
                    break

                raw_name = descriptor[:11].split(b"\x00", 1)[0]
                name = raw_name.decode("ascii", errors="ignore").strip().upper()
                field_type = chr(descriptor[11]).upper()
                length = descriptor[16]
                decimals = descriptor[17]
                if name:
                    fields.append(
                        DbfField(
                            name=name,
                            type=field_type,
                            length=length,
                            decimals=decimals,
                            offset=offset,
                        )
                    )
                    offset += length

                if handle.tell() >= header_length:
                    break

        if not fields or record_length <= 1:
            raise TformdetAppendError(f"{path.name} tiene estructura DBF incompleta.")
        return DbfHeader(
            path=path,
            version=version,
            record_count=record_count,
            header_length=header_length,
            record_length=record_length,
            fields=fields,
        )

    def _iter_active_records(self, header: DbfHeader) -> Iterable[bytes]:
        with header.path.open("rb") as handle:
            handle.seek(header.header_length)
            for _ in range(header.record_count):
                record = handle.read(header.record_length)
                if len(record) < header.record_length:
                    break
                if record[:1] == b"*":
                    continue
                yield record

    def _record_period(self, record: bytes, header: DbfHeader) -> str:
        value = self._record_field_value(record, header, "ANNOMES")
        digits = re.sub(r"\D", "", value)
        return digits if len(digits) == 6 else ""

    def _record_field_value(self, record: bytes, header: DbfHeader, field_name: str) -> str:
        field = header.field_map.get(field_name)
        if field is None:
            return ""
        raw = record[field.offset : field.offset + field.length]
        value = raw.decode("latin1", errors="ignore").strip().upper()
        return re.sub(r"[^0-9A-Z]", "", value)

    def _code_period_key(self, codigo_pre: str, period: str) -> str:
        return f"{codigo_pre}|{period}"

    def _codigo_pre_from_key(self, key: str) -> str:
        return key.split("|", 1)[0]

    def _period_from_key(self, key: str) -> str:
        parts = key.split("|", 1)
        return parts[1] if len(parts) == 2 else ""

    def _build_destination_records(
        self,
        analysis: AppendAnalysis,
        *,
        progress: ProgressCallback | None = None,
    ) -> Iterable[bytes]:
        copy_pairs = self._copyable_field_pairs(
            analysis.source_header, analysis.destination_header
        )
        keys = set(analysis.keys_to_import)
        prepared = 0

        for source_record in self._iter_active_records(analysis.source_header):
            codigo_pre = self._record_field_value(
                source_record, analysis.source_header, "CODIGO_PRE"
            )
            period = self._record_period(source_record, analysis.source_header)
            if self._code_period_key(codigo_pre, period) not in keys:
                continue
            destination_record = bytearray(b" " * analysis.destination_header.record_length)
            destination_record[0] = 0x20
            for source_field, destination_field in copy_pairs:
                source_value = self._field_text(source_record, source_field)
                destination_value = self._format_for_destination(
                    source_value,
                    source_field,
                    destination_field,
                )
                destination_record[
                    destination_field.offset : destination_field.offset + destination_field.length
                ] = destination_value
            prepared += 1
            if prepared % 50000 == 0:
                self._notify(progress, f"   Filas nuevas preparadas: {prepared:,}...")
            yield bytes(destination_record)

    def _copyable_field_pairs(
        self, source_header: DbfHeader, destination_header: DbfHeader
    ) -> list[tuple[DbfField, DbfField]]:
        destination_fields = destination_header.field_map
        pairs: list[tuple[DbfField, DbfField]] = []
        for source_field in source_header.fields:
            destination_field = destination_fields.get(source_field.name)
            if destination_field and self._types_compatible(source_field, destination_field):
                pairs.append((source_field, destination_field))
        return pairs

    def _validate_records_fit(
        self,
        source_header: DbfHeader,
        destination_header: DbfHeader,
        keys_to_import: set[str],
        limit: int = 10,
    ) -> list[str]:
        errors: list[str] = []
        copy_pairs = self._copyable_field_pairs(source_header, destination_header)

        for record_index, source_record in enumerate(
            self._iter_active_records(source_header), start=1
        ):
            codigo_pre = self._record_field_value(source_record, source_header, "CODIGO_PRE")
            period = self._record_period(source_record, source_header)
            if self._code_period_key(codigo_pre, period) not in keys_to_import:
                continue

            for source_field, destination_field in copy_pairs:
                value = self._field_text(source_record, source_field)
                try:
                    self._format_for_destination(value, source_field, destination_field)
                except TformdetAppendError as exc:
                    errors.append(
                        f"Registro {record_index}, CODIGO_PRE {codigo_pre}, periodo {period}: {exc}"
                    )
                    if len(errors) >= limit:
                        errors.append(
                            "Hay mas valores que no caben; se muestran solo los primeros."
                        )
                        return errors
        return errors

    def _types_compatible(self, source_field: DbfField, destination_field: DbfField) -> bool:
        if source_field.type == destination_field.type:
            return True
        if source_field.type in NUMERIC_FIELD_TYPES and destination_field.type in NUMERIC_FIELD_TYPES:
            return True
        if source_field.type in CHAR_FIELD_TYPES and destination_field.type in CHAR_FIELD_TYPES:
            return True
        return False

    def _field_text(self, record: bytes, field: DbfField) -> str:
        raw = record[field.offset : field.offset + field.length]
        return raw.decode("latin1", errors="ignore").strip()

    def _format_for_destination(
        self,
        value: str,
        source_field: DbfField,
        destination_field: DbfField,
    ) -> bytes:
        if not value:
            return b" " * destination_field.length

        if destination_field.type in NUMERIC_FIELD_TYPES:
            text = self._format_numeric(value, source_field, destination_field)
            encoded = text.encode("ascii", errors="ignore")
            if len(encoded) > destination_field.length:
                raise TformdetAppendError(
                    f"Valor numerico no cabe en {destination_field.name}: {value}"
                )
            return encoded.rjust(destination_field.length, b" ")

        encoded = value.encode("latin1", errors="replace")
        if len(encoded) > destination_field.length:
            if destination_field.name in CRITICAL_FIELDS:
                raise TformdetAppendError(
                    f"Valor no cabe en campo critico {destination_field.name}: {value}"
                )
            encoded = encoded[: destination_field.length]
        return encoded.ljust(destination_field.length, b" ")

    def _format_numeric(
        self,
        value: str,
        source_field: DbfField,
        destination_field: DbfField,
    ) -> str:
        text = value.strip().replace(",", ".")
        try:
            number = Decimal(text)
            if destination_field.decimals > 0:
                quantum = Decimal("1").scaleb(-destination_field.decimals)
                number = number.quantize(quantum, rounding=ROUND_HALF_UP)
                formatted = f"{number:f}"
                if len(formatted) <= destination_field.length:
                    return formatted

                trimmed = formatted.rstrip("0").rstrip(".")
                if len(trimmed) <= destination_field.length:
                    return trimmed

                integer_digits = len(str(abs(int(number))))
                sign_len = 1 if number < 0 else 0
                decimal_slots = destination_field.length - integer_digits - sign_len - 1
                if decimal_slots > 0:
                    quantum = Decimal("1").scaleb(-decimal_slots)
                    number = number.quantize(quantum, rounding=ROUND_HALF_UP)
                    formatted = f"{number:f}".rstrip("0").rstrip(".")
                    if len(formatted) <= destination_field.length:
                        return formatted

                integer_text = f"{number.quantize(Decimal('1'), rounding=ROUND_HALF_UP):f}"
                if len(integer_text) <= destination_field.length:
                    return integer_text
                return formatted
            number = number.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            return f"{number:f}"
        except InvalidOperation as exc:
            if source_field.name in CRITICAL_FIELDS:
                raise TformdetAppendError(
                    f"Valor numerico invalido en campo critico {source_field.name}: {value}"
                ) from exc
            return text

    def _preview_names(self, names: list[str], limit: int = 8) -> str:
        shown = ", ".join(names[:limit])
        if len(names) > limit:
            shown += f" ... (+{len(names) - limit})"
        return shown

    def _append_records(
        self,
        handle,
        destination_header: DbfHeader,
        records: list[bytes],
        new_count: int,
    ) -> None:
        handle.seek(0, os.SEEK_END)
        end_pos = handle.tell()
        if end_pos > 0:
            handle.seek(end_pos - 1)
            if handle.read(1) == b"\x1A":
                handle.truncate(end_pos - 1)

        handle.seek(0, os.SEEK_END)
        for record in records:
            if len(record) != destination_header.record_length:
                raise TformdetAppendError("Registro preparado con longitud invalida.")
            handle.write(record)
        handle.write(b"\x1A")

        now = datetime.now()
        handle.seek(1)
        handle.write(bytes([now.year - 1900, now.month, now.day]))
        handle.seek(4)
        handle.write(struct.pack("<I", new_count))
        handle.flush()
        os.fsync(handle.fileno())

    def _find_sidecars(self, dbf_path: Path, extensions: set[str]) -> list[Path]:
        found: list[Path] = []
        for candidate in dbf_path.parent.glob(dbf_path.stem + ".*"):
            if candidate.suffix.upper() in extensions and candidate.exists():
                found.append(candidate)
        return found

    def _backup_destination(self, destination: Path, backup_root: str | Path | None) -> Path:
        if backup_root is None:
            backup_root = (
                Path(os.getenv("APPDATA", str(Path.home())))
                / "ToolkitOGM"
                / "backups"
                / "tformdet_append"
            )
        backup_dir = Path(backup_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)

        sidecars = self._find_sidecars(destination, BACKUP_SIDECARE_EXTENSIONS)
        if destination not in sidecars:
            sidecars.insert(0, destination)
        for path in sidecars:
            shutil.copy2(path, backup_dir / path.name)
        return backup_dir

    def _try_lock(self, handle) -> bool:
        if msvcrt is None:
            return False
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            raise PermissionError("Destino bloqueado por otro proceso.") from exc
