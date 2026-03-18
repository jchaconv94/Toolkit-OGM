
import os
import pandas as pd
from dbfread import DBF
import datetime
from datetime import datetime, date
import traceback

class GuiaReportManager:
    def __init__(self, sismed_dir, log_callback=None):
        self.sismed_dir = sismed_dir
        self.log_callback = log_callback

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def generate_report(self, date_start, date_end, type_mov, detailed, output_path, exclude_annulled=True):
        """
        date_start/end: objetos datetime
        type_mov: 'S' o 'E'
        detailed: bool (True = Detallado por Lote, False = Consolidado por Guia)
        exclude_annulled: bool (True = Ignorar registros SITUA='A')
        """
        try:
            self.log(f"🚀 Iniciando proceso de reporte ({'Detallado' if detailed else 'Consolidado'})...")
            
            # 1. Definir rutas
            path_mproducto = os.path.join(self.sismed_dir, "DATOS", "MPRODUCTO.DBF")
            path_malmacen = os.path.join(self.sismed_dir, "DATOS", "MALMACEN.DBF")
            path_tmovim = os.path.join(self.sismed_dir, "DATOS", "TMOVIM.DBF")
            path_tmovimdet = os.path.join(self.sismed_dir, "DATOS", "TMOVIMDET.DBF")

            # Validar existencia
            for p in [path_mproducto, path_malmacen, path_tmovim, path_tmovimdet]:
                if not os.path.exists(p):
                    raise FileNotFoundError(f"No se encontró el archivo: {os.path.basename(p)}")

            # 2. Cargar Tablas Maestras (Pequeñas)
            self.log("📂 Cargando maestros de productos y almacenes...")
            # MPRODUCTO
            prod_list = []
            for rec in DBF(path_mproducto, ignore_missing_memofile=True, char_decode_errors='ignore'):
                prod_list.append({
                    'MEDCOD': str(rec.get('MEDCOD', '')).strip(),
                    'MEDNOM': str(rec.get('MEDNOM', '')).strip()
                })
            df_prod = pd.DataFrame(prod_list)

            # MALMACEN
            alm_list = []
            for rec in DBF(path_malmacen, ignore_missing_memofile=True, char_decode_errors='ignore'):
                alm_list.append({
                    'ALMCOD': str(rec.get('ALMCOD', '')).strip(),
                    'ALMDES': str(rec.get('ALMDES', '')).strip()
                })
            df_alm = pd.DataFrame(alm_list)

            # 3. Cargar Cabeceras de Movimientos (Filtradas)
            self.log(f"🔎 Filtrando movimientos tipo '{type_mov}' entre {date_start.strftime('%d/%m/%Y')} y {date_end.strftime('%d/%m/%Y')}...")
            mov_list = []
            for rec in DBF(path_tmovim, ignore_missing_memofile=True, char_decode_errors='ignore'):
                # Filtro de tipo
                if str(rec.get('MOVCODITIP', '')).strip() != type_mov:
                    continue
                
                # Filtro de Guia Anulada
                # El usuario confirma: MOVSITUA = '0' significa anulado.
                # También verificamos MOVFECANUL por redundancia técnica.
                situa = str(rec.get('MOVSITUA', '1')).strip()
                f_anul = rec.get('MOVFECANUL')
                
                if exclude_annulled:
                    if situa == '0' or f_anul is not None:
                        continue

                f_reg = rec.get('MOVFECHREG')
                if not f_reg or not isinstance(f_reg, date):
                    continue
                
                dt_reg = datetime.combine(f_reg, datetime.min.time())
                
                if date_start <= dt_reg <= date_end:
                    mov_list.append({
                        'MOVNUMERO': str(rec.get('MOVNUMERO', '')).strip(),
                        'MOVCODITIP': str(rec.get('MOVCODITIP', '')).strip(),
                        'FECHA REGISTRO': f_reg.strftime('%d/%m/%Y'),
                        'GUIA': str(rec.get('MOVNUMEDCO', '')).strip(),
                        'COD EESS': str(rec.get('ALMCODIDST', '')).strip(),
                        'MOVREFE': str(rec.get('MOVREFE', '')).strip()
                    })
            
            if not mov_list:
                raise ValueError("No se encontraron movimientos en el rango de fechas seleccionado.")
            
            df_mov = pd.DataFrame(mov_list)

            # 4. Cargar Detalles
            self.log("📝 Cargando detalles de movimientos...")
            det_list = []
            valid_mov_nums = set(df_mov['MOVNUMERO'])
            for rec in DBF(path_tmovimdet, ignore_missing_memofile=True, char_decode_errors='ignore'):
                m_num = str(rec.get('MOVNUMERO', '')).strip()
                m_tip = str(rec.get('MOVCODITIP', '')).strip()
                
                if m_tip == type_mov and m_num in valid_mov_nums:
                    det_list.append({
                        'MOVNUMERO': m_num,
                        'MEDCOD': str(rec.get('MEDCOD', '')).strip(),
                        'LOTE': str(rec.get('MEDLOTE', '')).strip(),
                        'MOVCANTID': float(rec.get('MOVCANTID', 0) or 0),
                        'SUBTOTAL': float(rec.get('MOVTOTAL', 0) or 0) # El total histórico guardado en el movimiento
                    })
            df_det = pd.DataFrame(det_list)

            # 5. JOINS
            self.log("🔗 Cruzando información...")
            # Unir Detalles con Productos (solo para el nombre)
            df_merge = pd.merge(df_det, df_prod, on='MEDCOD', how='left')
            # Ya no recalculamos SUBTOTAL, usamos el grabado en TMOVIMDET
            
            # Unir con Cabeceras
            df_final = pd.merge(df_merge, df_mov, on='MOVNUMERO', how='inner')
            
            # Unir con Almacenes
            df_final = pd.merge(df_final, df_alm, left_on='COD EESS', right_on='ALMCOD', how='left')
            df_final.rename(columns={'ALMDES': 'EESS'}, inplace=True)

            # 6. Formatear y Exportar
            if detailed:
                # Cabeceras: FECHA REGISTRO | GUIA | COD EESS | EESS | COD MED | MEDICAMENTO SALIDA | LOTE | CANTIDAD | MOVREFE
                df_export = df_final[[
                    'FECHA REGISTRO', 'GUIA', 'COD EESS', 'EESS', 
                    'MEDCOD', 'MEDNOM', 'LOTE', 'MOVCANTID', 'MOVREFE'
                ]].copy()
                df_export.rename(columns={'MEDCOD': 'COD MED', 'MEDNOM': 'MEDICAMENTO', 'MOVCANTID': 'CANTIDAD'}, inplace=True)
            else:
                # Cabeceras: FECHA REGISTRO | GUIA | COD EESS | EESS | TOTAL | MOVREFE
                df_export = df_final.groupby(['FECHA REGISTRO', 'GUIA', 'COD EESS', 'EESS', 'MOVREFE'])['SUBTOTAL'].sum().reset_index()
                df_export.rename(columns={'SUBTOTAL': 'TOTAL'}, inplace=True)
                df_export['TOTAL'] = df_export['TOTAL'].round(2)

            self.log(f"💾 Guardando archivo en: {output_path}...")
            df_export.to_excel(output_path, index=False)
            self.log("✅ ¡Reporte generado con éxito!")
            return True

        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
            traceback.print_exc()
            return False
