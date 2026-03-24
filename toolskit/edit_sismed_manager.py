import os
from dbfread import DBF

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

    def search_medicines(self, query: str):
        """
        Busca medicamentos por código o nombre en MMEDICAM.DBF.
        Devuelve una lista de diccionarios con el índice físico del registro.
        """
        results = []
        if not os.path.exists(self.mmedicam_path):
            return results
            
        try:
            table = DBF(self.mmedicam_path, encoding='latin1', load=True) 
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
            table = DBF(self.mmedicam_path, encoding='latin1', load=True)
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
            table = DBF(self.mmedicam_path, encoding='latin1', load=True)
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
