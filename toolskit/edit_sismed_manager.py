import os
import tempfile

from dbf_utils import open_dbf, snapshot_dbf

class EditSismedManager:
    """
    Gestiona la edición directa de archivos DBF del SISMED.
    Usa el método de 'Inyección Binaria' para evitar bloqueos y asegurar persistencia,
    incluso si el SISMED está abierto (en modo compartido).
    """
    def __init__(self, sismed_dir: str):
        self.sismed_dir = sismed_dir.strip()
        path_datos = os.path.join(self.sismed_dir, "DATOS", "MMEDICAM.DBF")
        path_root  = os.path.join(self.sismed_dir, "MMEDICAM.DBF")
        self.mmedicam_path = path_datos if os.path.exists(path_datos) else path_root

        # ── TMOVIM ──────────────────────────────────────────────────────────────
        path_tmovim_datos = os.path.join(self.sismed_dir, "DATOS", "TMOVIM.DBF")
        path_tmovim_root  = os.path.join(self.sismed_dir, "TMOVIM.DBF")
        self.tmovim_path = path_tmovim_datos if os.path.exists(path_tmovim_datos) else path_tmovim_root
        self._tmovim_header_len  = None
        self._tmovim_record_len  = None
        self._tmovim_field_info  = {}   # {FIELD_NAME: (offset, length, type_char)}

    def search_medicines(self, query: str):
        """
        Busca medicamentos por código o nombre en MMEDICAM.DBF.
        Devuelve una lista de diccionarios con el índice físico del registro.
        """
        results = []
        if not os.path.exists(self.mmedicam_path):
            return results
            
        try:
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mmedicam_") as snapshot_dir:
                read_path = snapshot_dbf(self.mmedicam_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                q = query.strip().upper()
                
                self.header_len = table.header.headerlen
                self.record_len = table.header.recordlen
                
                self.medest_offset = -1
                current_offset = 1 
                for field in table.fields:
                    if field.name.upper() == 'MEDEST':
                        self.medest_offset = current_offset
                        break
                    current_offset += field.length

                for i, record in enumerate(table.records):
                    m_cod = str(record.get('MEDCOD') or record.get('medcod') or '').strip()
                    m_nom = str(record.get('MEDNOM') or record.get('mednom') or '').strip()
                    m_est = str(record.get('MEDEST') or record.get('medest') or '').strip() or "_"
                    
                    if q in m_cod.upper() or q in m_nom.upper():
                        results.append({
                            "id_fisico": i,
                            "medcod": m_cod,
                            "mednom": m_nom,
                            "medest": m_est,
                            "medpres": str(record.get('MEDPRES') or '').strip(),
                            "medcnc": str(record.get('MEDCNC') or '').strip(),
                            "medff": str(record.get('MEDFF') or '').strip(),
                        })
        except Exception as e:
            print(f"Error búsqueda binaria: {e}")
            
        return results

    def _patch_binary_field(self, record_index: int, new_value: str):
        """Escribe directamente un carácter en la posición binaria de MEDEST."""
        if not os.path.exists(self.mmedicam_path):
            return False, "Archivo no encontrado."

        if not hasattr(self, 'header_len') or self.medest_offset == -1:
            self._detect_structure()
            if self.medest_offset == -1:
                return False, "Campo MEDEST no encontrado."

        try:
            target_pos = self.header_len + (record_index * self.record_len) + self.medest_offset
            with open(self.mmedicam_path, "rb+") as f:
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
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mmedicam_") as snapshot_dir:
                read_path = snapshot_dbf(self.mmedicam_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                self.header_len = table.header.headerlen
                self.record_len = table.header.recordlen
                current_offset = 1
                for field in table.fields:
                    if field.name.upper() == 'MEDEST':
                        self.medest_offset = current_offset
                        break
                    current_offset += field.length
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
        if not os.path.exists(self.mmedicam_path) or not codes_list:
            return results
        try:
            search_set = set(str(c).strip().upper() for c in codes_list)
            with tempfile.TemporaryDirectory(prefix="toolkit_edit_mmedicam_") as snapshot_dir:
                read_path = snapshot_dbf(self.mmedicam_path, snapshot_dir)
                table = open_dbf(read_path, encoding='latin1', load=True)
                self.header_len = table.header.headerlen
                self.record_len = table.header.recordlen
                self.medest_offset = -1
                current_offset = 1
                for field in table.fields:
                    if field.name.upper() == 'MEDEST':
                        self.medest_offset = current_offset
                        break
                    current_offset += field.length

                for i, record in enumerate(table.records):
                    m_cod = str(record.get('MEDCOD') or '').strip()
                    if m_cod.upper() in search_set:
                        results.append({
                            "id_fisico": i,
                            "medcod": m_cod,
                            "mednom": str(record.get('MEDNOM') or '').strip(),
                            "medest": str(record.get('MEDEST') or '').strip() or "_",
                            "medpres": str(record.get('MEDPRES') or '').strip(),
                            "medcnc": str(record.get('MEDCNC') or '').strip(),
                            "medff": str(record.get('MEDFF') or '').strip(),
                        })
        except Exception as e:
            print(f"Error búsqueda masiva: {e}")
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

    def search_guias(self, query: str) -> list:
        """Busca guías en TMOVIM.DBF por MOVNUMERO."""
        results = []
        if not os.path.exists(self.tmovim_path):
            raise FileNotFoundError(f"No se encontró TMOVIM.DBF en: {self.tmovim_path}")
        try:
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

                q = query.strip().upper()
                for i, record in enumerate(table.records):
                    movnum  = str(record.get('MOVNUMERO')  or '').strip()
                    movguia = str(record.get('MOVNUMEDCO') or '').strip()
                    if q in movnum.upper():
                        fecha = record.get('MOVFECHREG')
                        results.append({
                            "id_fisico":  i,
                            "movnumero":  movnum,
                            "movnumedco": movguia,
                            "movsitua":   str(record.get('MOVSITUA')  or '').strip(),
                            "movcoditip": str(record.get('MOVCODITIP') or '').strip(),
                            "movfechreg": fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else str(fecha or ''),
                            "bloqueo":    str(record.get('BLOQUEO')  or '').strip(),
                            "usrbloq":    str(record.get('USRBLOQ')  or '').strip(),
                        })
        except Exception as e:
            print(f"Error búsqueda TMOVIM: {e}")
            raise
        return results

    def search_guias_by_list(self, numeros_list: list) -> list:
        """Busca guías cuyo MOVNUMERO esté en la lista proporcionada."""
        results = []
        if not os.path.exists(self.tmovim_path) or not numeros_list:
            return results
        try:
            search_set = set(str(n).strip().upper() for n in numeros_list)
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

                for i, record in enumerate(table.records):
                    movnum  = str(record.get('MOVNUMERO')  or '').strip()
                    movguia = str(record.get('MOVNUMEDCO') or '').strip()
                    if movnum.upper() in search_set:
                        fecha = record.get('MOVFECHREG')
                        results.append({
                            "id_fisico":  i,
                            "movnumero":  movnum,
                            "movnumedco": movguia,
                            "movsitua":   str(record.get('MOVSITUA')  or '').strip(),
                            "movcoditip": str(record.get('MOVCODITIP') or '').strip(),
                            "movfechreg": fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else str(fecha or ''),
                            "bloqueo":    str(record.get('BLOQUEO')  or '').strip(),
                            "usrbloq":    str(record.get('USRBLOQ')  or '').strip(),
                        })
        except Exception as e:
            print(f"Error búsqueda masiva TMOVIM: {e}")
            raise
        return results

    def _patch_tmovim_fields(self, record_index: int, field_patches: dict) -> tuple:
        """
        Escribe directamente en los bytes del registro indicado para los campos del dict.
        field_patches: {FIELD_NAME: new_value_str}  — pasar '' para limpiar el campo.
        """
        if not os.path.exists(self.tmovim_path):
            return False, "Archivo TMOVIM.DBF no encontrado."
        if not self._tmovim_field_info:
            self._detect_tmovim_structure()
        if not self._tmovim_field_info:
            return False, "No se pudo detectar la estructura de TMOVIM.DBF."

        try:
            with open(self.tmovim_path, "rb+") as f:
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
        for idx in indices_list:
            ok, msg = self._patch_tmovim_fields(idx, {"MOVSITUA": new_situa})
            if ok:
                total += 1
            else:
                errors.append(msg)
        return total, f"Actualizados {total}/{len(indices_list)}. {errors[0] if errors else ''}"

    def clear_bloqueo_bulk(self, indices_list: list) -> tuple:
        """Limpia los campos BLOQUEO y USRBLOQ en los registros indicados."""
        total, errors = 0, []
        for idx in indices_list:
            ok, msg = self._patch_tmovim_fields(idx, {"BLOQUEO": "", "USRBLOQ": ""})
            if ok:
                total += 1
            else:
                errors.append(msg)
        return total, f"Desbloqueados {total}/{len(indices_list)}. {errors[0] if errors else ''}"
