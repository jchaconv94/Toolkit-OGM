import os
import tempfile

from dbf_utils import live_record_positions, open_dbf, snapshot_dbf
from tmovim_search import BY_MOVEMENT, FIELDS, ListMatcher, normalize_by, simple_match

class EditSismedManager:
    """
    Gestiona la edicion directa de archivos DBF del SISMED.
    Usa escritura binaria controlada para actualizar campos puntuales.
    """
    def __init__(self, sismed_dir: str):
        self.sismed_dir = sismed_dir.strip()
        self.mproducto_path = self._resolve_dbf_path("MPRODUCTO.DBF")
        # Se conserva por compatibilidad con instalaciones antiguas, pero MEDEST
        # se lee y modifica exclusivamente desde MPRODUCTO.DBF.
        self.mmedicam_path = self._resolve_dbf_path("MMEDICAM.DBF")

        # ── TMOVIM ──────────────────────────────────────────────────────────────
        path_tmovim_datos = os.path.join(self.sismed_dir, "DATOS", "TMOVIM.DBF")
        path_tmovim_root  = os.path.join(self.sismed_dir, "TMOVIM.DBF")
        self.tmovim_path = path_tmovim_datos if os.path.exists(path_tmovim_datos) else path_tmovim_root
        self._tmovim_header_len  = None
        self._tmovim_record_len  = None
        self._tmovim_field_info  = {}   # {FIELD_NAME: (offset, length, type_char)}

    def _resolve_dbf_path(self, dbf_name: str) -> str:
        path_datos = os.path.join(self.sismed_dir, "DATOS", dbf_name)
        path_root = os.path.join(self.sismed_dir, dbf_name)
        return path_datos if os.path.exists(path_datos) else path_root

    @staticmethod
    def _medicine_code_keys(value: str) -> set:
        raw = str(value or "").strip().upper()
        keys = {raw} if raw else set()
        if raw.isdigit():
            keys.add(raw.zfill(5))
            keys.add(raw.zfill(7))
        return keys

    def _capture_mproducto_structure(self, table) -> None:
        self.header_len = table.header.headerlen
        self.record_len = table.header.recordlen
        self.medest_offset = -1
        current_offset = 1
        for field in table.fields:
            if field.name.upper() == 'MEDEST':
                self.medest_offset = current_offset
                break
            current_offset += field.length

    @staticmethod
    def _mproducto_records(table):
        """(posición física, registro): dbfread se salta los borrados y el índice no sirve para escribir."""
        records = table.records
        positions = live_record_positions(table)
        if len(positions) != len(records):
            raise RuntimeError("No se pudo ubicar los registros de MPRODUCTO.DBF. Vuelva a intentar.")
        return zip(positions, records)

    @staticmethod
    def _medicine_result(record_index: int, record: dict) -> dict:
        return {
            "id_fisico": record_index,
            "medcod": str(record.get('MEDCOD') or record.get('medcod') or '').strip(),
            "mednom": str(record.get('MEDNOM') or record.get('mednom') or '').strip(),
            "medest": str(record.get('MEDEST') or record.get('medest') or '').strip() or "_",
            "medpres": str(record.get('MEDPRES') or record.get('medpres') or '').strip(),
            "medcnc": str(record.get('MEDCNC') or record.get('medcnc') or '').strip(),
            "medff": str(record.get('MEDFF') or record.get('medff') or '').strip(),
        }

    def search_medicines(self, query: str):
        """
        Busca medicamentos por código o nombre en MPRODUCTO.DBF.
        Devuelve una lista de diccionarios con el índice físico del registro.
        """
        results = []
        if not os.path.exists(self.mproducto_path):
            return results
            
        try:
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mproducto_") as snapshot_dir:
                read_path = snapshot_dbf(self.mproducto_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                q = query.strip().upper()
                self._capture_mproducto_structure(table)

                for i, record in self._mproducto_records(table):
                    m_cod = str(record.get('MEDCOD') or record.get('medcod') or '').strip()
                    m_nom = str(record.get('MEDNOM') or record.get('mednom') or '').strip()
                    
                    if q in m_cod.upper() or q in m_nom.upper():
                        results.append(self._medicine_result(i, record))
        except Exception as e:
            print(f"Error búsqueda MPRODUCTO: {e}")
            
        return results

    def _patch_binary_field(self, record_index: int, new_value: str):
        """Escribe directamente un carácter en la posición binaria de MEDEST."""
        if not os.path.exists(self.mproducto_path):
            return False, "Archivo MPRODUCTO.DBF no encontrado."

        if not hasattr(self, 'header_len') or self.medest_offset == -1:
            self._detect_structure()
            if self.medest_offset == -1:
                return False, "Campo MEDEST no encontrado en MPRODUCTO.DBF."

        try:
            if record_index < 0:
                return False, "Registro fuera de MPRODUCTO.DBF."
            target_pos = self.header_len + (record_index * self.record_len) + self.medest_offset
            with open(self.mproducto_path, "rb+") as f:
                f.seek(self.header_len + (record_index * self.record_len))
                if f.read(1) != b' ':
                    return False, "El registro ya no está en MPRODUCTO.DBF. Vuelva a buscar."
                f.seek(target_pos)
                current_byte = f.read(1).decode('latin1', errors='ignore')
                if current_byte not in [' ', '_', 'E', 'S']:
                    return False, f"Seguridad: Byte '{current_byte}' no es estado."
                f.seek(target_pos)
                f.write(new_value[:1].encode('latin1'))
                f.flush()
                os.fsync(f.fileno()) 
            return True, "Modificado exitosamente."
        except Exception as e:
            return False, str(e)

    def _detect_structure(self):
        try:
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mproducto_") as snapshot_dir:
                read_path = snapshot_dbf(self.mproducto_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                self._capture_mproducto_structure(table)
        except:
            self.medest_offset = -1

    def update_medest_single(self, record_index: int, new_est: str):
        return self._patch_binary_field(record_index, new_est)

    def update_medest_bulk(self, indices_list: list, new_est: str):
        total = 0
        errors = []
        for idx in indices_list:
            success, msg = self._patch_binary_field(idx, new_est)
            if success: total += 1
            else: errors.append(msg)
        return total, f"Actualizados {total}/{len(indices_list)}. {errors[0] if errors else ''}"

    def search_medicines_by_list(self, codes_list: list):
        results = []
        if not os.path.exists(self.mproducto_path) or not codes_list:
            return results
        try:
            search_set = set()
            for code in codes_list:
                search_set.update(self._medicine_code_keys(code))
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mproducto_") as snapshot_dir:
                read_path = snapshot_dbf(self.mproducto_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                self._capture_mproducto_structure(table)

                for i, record in self._mproducto_records(table):
                    m_cod = str(record.get('MEDCOD') or '').strip()
                    if self._medicine_code_keys(m_cod) & search_set:
                        results.append(self._medicine_result(i, record))
        except Exception as e:
            print(f"Error búsqueda masiva MPRODUCTO: {e}")
        return results

    # ════════════════════════════════════════════════════════════════════════════
    # TMOVIM  –  Gestión de guías (MOVSITUA, BLOQUEO, USRBLOQ)
    # ════════════════════════════════════════════════════════════════════════════

    def _detect_tmovim_structure(self):
        """Lee la cabecera de TMOVIM.DBF y guarda offset, longitud y tipo de cada campo."""
        try:
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_tmovim_") as snapshot_dir:
                read_path = snapshot_dbf(self.tmovim_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                self._tmovim_header_len = table.header.headerlen
                self._tmovim_record_len = table.header.recordlen
                self._tmovim_field_info = {}
                current_offset = 1   # byte 0 = flag de eliminación
                for f in table.fields:
                    self._tmovim_field_info[f.name.upper()] = (current_offset, f.length, f.type)
                    current_offset += f.length
        except Exception as e:
            print(f"Error detectando estructura TMOVIM: {e}")
            self._tmovim_field_info = {}

    def _tmovim_records(self):
        """Recorre una copia de TMOVIM.DBF y guarda la estructura para luego escribir en el original."""
        with tempfile.TemporaryDirectory(prefix="toolkit_edit_tmovim_") as snapshot_dir:
            read_path = snapshot_dbf(self.tmovim_path, snapshot_dir)
            table = open_dbf(read_path, encoding='latin1', load=True)
            self._tmovim_header_len = table.header.headerlen
            self._tmovim_record_len = table.header.recordlen
            self._tmovim_field_info = {}
            current_offset = 1
            for f in table.fields:
                self._tmovim_field_info[f.name.upper()] = (current_offset, f.length, f.type)
                current_offset += f.length
            records = table.records
            positions = live_record_positions(table)
            if len(positions) != len(records):
                raise RuntimeError("No se pudo ubicar los registros de TMOVIM.DBF. Vuelva a intentar.")
            yield from zip(positions, records)

    @staticmethod
    def _guia_result(record_index: int, record) -> dict:
        fecha = record.get('MOVFECHREG')
        return {
            "id_fisico":  record_index,
            "movnumero":  str(record.get('MOVNUMERO')  or '').strip(),
            "movnumedco": str(record.get('MOVNUMEDCO') or '').strip(),
            "movsitua":   str(record.get('MOVSITUA')  or '').strip(),
            "movcoditip": str(record.get('MOVCODITIP') or '').strip(),
            "movindprc":  str(record.get('MOVINDPRC') or '').strip(),
            "movfechreg": fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else str(fecha or ''),
            "bloqueo":    str(record.get('BLOQUEO')  or '').strip(),
            "usrbloq":    str(record.get('USRBLOQ')  or '').strip(),
        }

    def search_guias(self, query: str, by: str = BY_MOVEMENT) -> list:
        """Busca guías en TMOVIM.DBF cuyo N° de movimiento (o N° de guía) contenga lo escrito."""
        if not os.path.exists(self.tmovim_path):
            raise FileNotFoundError(f"No se encontró TMOVIM.DBF en: {self.tmovim_path}")
        by = normalize_by(by)
        field = FIELDS[by]
        try:
            return [
                self._guia_result(i, record)
                for i, record in self._tmovim_records()
                if simple_match(query, record.get(field), by)
            ]
        except Exception as e:
            print(f"Error búsqueda TMOVIM: {e}")
            raise

    def search_guias_by_list(self, values: list, by: str = BY_MOVEMENT) -> list:
        """Busca las guías de una lista. Cada resultado dice en "coincide" qué valor pegado lo trajo."""
        if not os.path.exists(self.tmovim_path):
            raise FileNotFoundError(f"No se encontró TMOVIM.DBF en: {self.tmovim_path}")
        matcher = values if isinstance(values, ListMatcher) else ListMatcher(values, by)
        if not matcher.values:
            return []
        field = FIELDS[matcher.by]
        results = []
        try:
            for i, record in self._tmovim_records():
                matches = matcher.match(record.get(field))
                if matches:
                    result = self._guia_result(i, record)
                    result["coincide"] = matches
                    results.append(result)
        except Exception as e:
            print(f"Error búsqueda masiva TMOVIM: {e}")
            raise
        return results

    @staticmethod
    def _tmovim_target(target) -> tuple:
        """(posición física, campos que deben seguir igual) de un resultado de búsqueda o de un número."""
        if isinstance(target, dict):
            return int(target["id_fisico"]), {
                "MOVNUMERO": target.get("movnumero", ""),
                "MOVCODITIP": target.get("movcoditip", ""),
            }
        return int(target), {}

    def _read_tmovim_value(self, f, record_index: int, field_name: str):
        """Valor actual del campo en el archivo abierto; None si el campo no existe o el registro no está."""
        info = self._tmovim_field_info.get(field_name.upper())
        if not info:
            return None
        offset, length, _ftype = info
        f.seek(self._tmovim_header_len + (record_index * self._tmovim_record_len) + offset)
        raw = f.read(length)
        if len(raw) < length:
            return None
        return raw.decode('latin1', errors='replace')

    def _patch_tmovim_fields(self, record_index: int, field_patches: dict, expected: dict | None = None,
                             transform=None) -> tuple:
        """
        Escribe directamente en los bytes del registro indicado para los campos del dict.
        field_patches: {FIELD_NAME: new_value_str}  — pasar '' para limpiar el campo.
        expected: campos que deben seguir como en la búsqueda; si cambiaron, no se escribe nada.
        transform: función que recibe el archivo abierto y devuelve los cambios o un texto de error.
        """
        if not os.path.exists(self.tmovim_path):
            return False, "Archivo TMOVIM.DBF no encontrado."
        if not self._tmovim_field_info:
            self._detect_tmovim_structure()
        if not self._tmovim_field_info:
            return False, "No se pudo detectar la estructura de TMOVIM.DBF."
        if record_index < 0:
            return False, "Registro fuera de TMOVIM.DBF."

        try:
            with open(self.tmovim_path, "rb+") as f:
                f.seek(self._tmovim_header_len + (record_index * self._tmovim_record_len))
                if f.read(1) != b' ':
                    return False, "El registro ya no está en TMOVIM.DBF. Vuelva a buscar."
                for field_name, value in (expected or {}).items():
                    current = self._read_tmovim_value(f, record_index, field_name)
                    if current is not None and current.strip().upper() != str(value or '').strip().upper():
                        return False, "TMOVIM.DBF cambió desde la búsqueda. Vuelva a buscar antes de aplicar."
                if transform is not None:
                    field_patches = transform(f)
                    if isinstance(field_patches, str):
                        return False, field_patches

                for field_name, new_value in field_patches.items():
                    fname = field_name.upper()
                    if fname not in self._tmovim_field_info:
                        continue
                    offset, length, ftype = self._tmovim_field_info[fname]
                    target_pos = self._tmovim_header_len + (record_index * self._tmovim_record_len) + offset

                    if not new_value:                        # limpiar: espacios
                        padded = b' ' * length
                    elif ftype == 'N':                       # numérico: alinear derecha
                        padded = new_value.encode('latin1', errors='replace')[:length].rjust(length, b' ')
                    else:                                    # texto/fecha: alinear izquierda
                        padded = new_value.encode('latin1', errors='replace')[:length].ljust(length, b' ')

                    f.seek(target_pos)
                    f.write(padded)
                f.flush()
                os.fsync(f.fileno())
            return True, "Modificado exitosamente."
        except Exception as e:
            return False, str(e)

    def update_movsitua_bulk(self, indices_list: list, new_situa: str) -> tuple:
        """Cambia MOVSITUA ('0' = anulada, '1' = habilitada) en los registros indicados."""
        total, errors = 0, []
        for target in indices_list:
            idx, expected = self._tmovim_target(target)
            ok, msg = self._patch_tmovim_fields(idx, {"MOVSITUA": new_situa}, expected)
            if ok:
                total += 1
            else:
                errors.append(msg)
        return total, f"Actualizados {total}/{len(indices_list)}. {errors[0] if errors else ''}"

    def clear_bloqueo_bulk(self, indices_list: list) -> tuple:
        """Limpia los campos BLOQUEO y USRBLOQ en los registros indicados."""
        total, errors = 0, []
        for target in indices_list:
            idx, expected = self._tmovim_target(target)
            ok, msg = self._patch_tmovim_fields(idx, {"BLOQUEO": "", "USRBLOQ": ""}, expected)
            if ok:
                total += 1
            else:
                errors.append(msg)
        return total, f"Desbloqueados {total}/{len(indices_list)}. {errors[0] if errors else ''}"

    def toggle_movindprc_bulk(self, indices_list: list) -> tuple:
        """Alterna MOVINDPRC entre 'A' y 'M' en los registros indicados."""
        if not indices_list:
            return 0, "No se recibieron registros para actualizar."

        fuera_de_rango = "MOVINDPRC fuera de A/M"
        total, skipped, errors = 0, 0, []
        for target in indices_list:
            idx, expected = self._tmovim_target(target)

            def _toggle(f, idx=idx):
                current = (self._read_tmovim_value(f, idx, "MOVINDPRC") or "").strip().upper()
                new_value = {"A": "M", "M": "A"}.get(current)
                return {"MOVINDPRC": new_value} if new_value else fuera_de_rango

            ok, msg = self._patch_tmovim_fields(idx, {}, expected, transform=_toggle)
            if ok:
                total += 1
            elif msg == fuera_de_rango:
                skipped += 1
            else:
                errors.append(msg)

        extra = []
        if skipped:
            extra.append(f"Omitidos {skipped} con MOVINDPRC fuera de A/M")
        if errors:
            extra.append(errors[0])
        suffix = f" {' | '.join(extra)}" if extra else ""
        return total, f"Actualizados {total}/{len(indices_list)}.{suffix}"
