
import os
import pandas as pd
import tempfile
from datetime import datetime, date
import traceback

from dbf_utils import open_dbf, snapshot_dbf


ADDITIONAL_TFORMDET_COLUMNS = (
    'DO_SALDO',
    'DO_INGRE',
    'DO_CON',
    'DO_OTR',
    'DO_TOT',
    'DO_STK',
    'ING_REGULA',
    'SAL_REGULA',
    'SAL_CONINS',
    'ESSALUD',
)

# Clasificación del producto (2026-10-06): la web la necesita para la disponibilidad de
# medicamentos esenciales (DME) armada solo desde el TFORMDET. Van al final para no mover las
# columnas que usan las fórmulas del reporte de un periodo.
PRODUCT_CLASSIFICATION_COLUMNS = ('MEDFF', 'MEDTIP', 'MEDPET', 'MEDEST')


class TformdetManager:
    def __init__(self, sismed_dir, log_callback=None):
        self.sismed_dir = sismed_dir
        self.log_callback = log_callback

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def generate_report(self, periodo_start, periodo_end, output_path, incluir_formulas=False):
        """
        periodo_start: string (ej: '202601')
        periodo_end: string (ej: '202603')
        output_path: ruta donde guardaremos el excel
        incluir_formulas: bool (añade fórmulas para reportes de 1 solo periodo)
        """
        try:
            self.log(f"🚀 Iniciando consulta TFORMDET...")
            texto_rango = f"{periodo_start}" if periodo_start == periodo_end else f"{periodo_start} a {periodo_end}"
            self.log(f"📅 Rango de Periodos: {texto_rango}")
            
            with tempfile.TemporaryDirectory(prefix="toolkit_tformdet_") as snapshot_dir:
                def safe_copy_dbf(dbf_name):
                    original_path = os.path.join(self.sismed_dir, "DATOS", dbf_name)
                    if not os.path.exists(original_path):
                        return None
                    return snapshot_dbf(original_path, snapshot_dir)

                # 1. Definir rutas seguras
                path_tformdet = safe_copy_dbf("TFORMDET.DBF")
                path_malmacen = safe_copy_dbf("MALMACEN.DBF")
                path_mproducto = safe_copy_dbf("MPRODUCTO.DBF")
                path_mmedicam = safe_copy_dbf("MMEDICAM.DBF")

                if not path_tformdet:
                    raise FileNotFoundError(f"No se encontró el archivo principal: TFORMDET.DBF")

                # 2. Cargar tablas cruzadas (MALMACEN y MPRODUCTO)
                self.log("📂 Cargando maestros de Establecimientos y Medicamentos...")
                dict_alm = {}
                if path_malmacen:
                    for rec in open_dbf(path_malmacen):
                        cod = str(rec.get('ALMCOD', '')).strip()
                        des = str(rec.get('ALMDES', '')).strip()
                        if cod:
                            dict_alm[cod] = des

                dict_prod = {}
                dict_clase = {}

                def leer_clase(rec):
                    return {col: str(rec.get(col, '') or '').strip() for col in PRODUCT_CLASSIFICATION_COLUMNS}

                if path_mproducto:
                    for rec in open_dbf(path_mproducto):
                        cod = str(rec.get('MEDCOD', '')).strip()
                        if cod:
                            nom = str(rec.get('MEDNOM', '')).strip()
                            pres = str(rec.get('MEDPRES', '')).strip()
                            cnc = str(rec.get('MEDCNC', '')).strip()
                            desc = f"{nom} {pres} {cnc}".strip()
                            dict_prod[cod] = desc
                            dict_clase[cod] = leer_clase(rec)

                # La clasificación sale de MMEDICAM, como en el reporte de Disponibilidad;
                # MPRODUCTO queda de respaldo para los campos que MMEDICAM no traiga.
                if path_mmedicam:
                    for rec in open_dbf(path_mmedicam):
                        cod = str(rec.get('MEDCOD', '')).strip()
                        if cod:
                            previa = dict_clase.get(cod, {})
                            dict_clase[cod] = {
                                col: valor or previa.get(col, '')
                                for col, valor in leer_clase(rec).items()
                            }

                # 3. Definir columnas requeridas por el usuario
                required_cols = [
                    'CODIGO_PRE', 'EESS', 'CODIGO_MED', 'DESCRIPCION MED', 'MEDLOTE', 'MEDREGSAN', 'FEC_EXP', 
                    'TIPSUM2', 'FFINAN', 'PREADQ', 'SALDO', 'PRECIO', 
                    'INGRE', 'REINGRE', 'VENTA', 'SIS', 'INTERSAN', 
                    'FAC_PERD', 'DEFNAC', 'EXO', 'SOAT', 'CREDHOSP', 
                    'OTR_CONV', 'DEVOL', 'VENCIDO', 'MERMA', 'DISTRI', 
                    'TRANSF', 'VENTAINST', 'DEV_VEN', 'DEV_MERMA', 'OTRAS_SAL', 
                    'STOCK_FIN', 'TOTAL', *ADDITIONAL_TFORMDET_COLUMNS,
                    *PRODUCT_CLASSIFICATION_COLUMNS,
                ]
                
                # Solo agregar ANNOMES si es más de un periodo
                if periodo_start != periodo_end:
                    required_cols.insert(0, 'ANNOMES')
                    
                if incluir_formulas and periodo_start == periodo_end:
                    required_cols.insert(0, 'COD. UNICO MAS CONSUMO SIS.')
                    required_cols.insert(1, 'COD. UNICO')
                    idx_fec_exp = required_cols.index('FEC_EXP')
                    required_cols.insert(idx_fec_exp + 1, 'FECHA CON NUMERO')

                # 4. Leer y filtrar registros (TFORMDET)
                self.log(f"🔎 Procesando registros para periodos {texto_rango} desde copias de seguridad...")
                
                # Generador lógico de periodos esperados
                def generate_periods(ini, fin):
                    periods = []
                    try:
                        y_i, m_i = int(ini[:4]), int(ini[4:])
                        y_f, m_f = int(fin[:4]), int(fin[4:])
                        curr_y, curr_m = y_i, m_i
                        while True:
                            p_str = f"{curr_y}{curr_m:02d}"
                            if p_str not in periods:
                                periods.append(p_str)
                                
                            # Rompemos si ya pasamos o llegamos al final
                            if curr_y > y_f or (curr_y == y_f and curr_m >= m_f):
                                break
                            
                            curr_m += 1
                            if curr_m > 12:
                                curr_m = 1
                                curr_y += 1
                            if len(periods) > 150:
                                break # Seguro
                    except Exception:
                        pass
                    return periods
                
                requested_periods = generate_periods(periodo_start, periodo_end)
                found_periods = set()
                
                data_list = []
                count = 0
                found = 0

                for rec in open_dbf(path_tformdet):
                    count += 1
                    
                    # Intentar obtener el periodo de ANNOMES (también buscar variantes como AÑOMES)
                    val_annomes = str(rec.get('ANNOMES', rec.get('AÑOMES', ''))).strip()
                    
                    # Filtrar por rango de rangos de texto (se comparan bien si tienen YYYYMM)
                    if periodo_start <= val_annomes <= periodo_end:
                        found_periods.add(val_annomes)
                        row_data = {}
                        
                        # Pre-calcular cruces
                        v_codigo_pre = str(rec.get('CODIGO_PRE', '')).strip()
                        v_codigo_med = str(rec.get('CODIGO_MED', '')).strip()
                        
                        row_idx = found + 2
                        
                        # Rellenar datos incluyendo cruces
                        for col in required_cols:
                            if col == 'EESS':
                                val = dict_alm.get(v_codigo_pre, "")
                            elif col == 'DESCRIPCION MED':
                                val = dict_prod.get(v_codigo_med, "")
                            elif col in PRODUCT_CLASSIFICATION_COLUMNS:
                                val = dict_clase.get(v_codigo_med, {}).get(col, "")
                            elif col == 'ANNOMES':
                                val = val_annomes
                            elif col == 'COD. UNICO MAS CONSUMO SIS.':
                                val = f"=CONCATENATE(C{row_idx},E{row_idx},R{row_idx},S{row_idx})"
                            elif col == 'COD. UNICO':
                                val = f"=CONCATENATE(C{row_idx},E{row_idx})"
                            elif col == 'FECHA CON NUMERO':
                                val = f"=CONCATENATE(YEAR(I{row_idx}), IF(MONTH(I{row_idx})<10, CONCATENATE(\"0\", MONTH(I{row_idx})), MONTH(I{row_idx})), IF(DAY(I{row_idx})<10, CONCATENATE(\"0\", DAY(I{row_idx})), DAY(I{row_idx})))"
                            else:
                                val = rec.get(col, "")
                                if isinstance(val, str):
                                    val = val.strip()
                                elif isinstance(val, (date, datetime)) and col == 'FEC_EXP':
                                    val = val.strftime("%d/%m/%Y")
                                    
                            row_data[col] = val
                        
                        data_list.append(row_data)
                        found += 1

                    if count % 10000 == 0:
                        self.log(f"⏳ Procesados {count} registros...")

            missing_periods = [p for p in requested_periods if p not in found_periods]
            if missing_periods:
                self.log(f"❌ ALTO: No se tiene información de ese(os) periodo(s): {', '.join(missing_periods)}")
                self.log(f"⚠️ Por favor, ajuste su rango de búsqueda. La operación fue cancelada.")
                return False

            if not data_list:
                self.log(f"⚠️ No se encontraron registros de datos para la(s) fecha(s).")
                return False

            self.log(f"✅ Se encontraron {found} registros coincidentes.")
            
            # 5. Crear DataFrame y Exportar
            self.log("💾 Generando archivo Excel...")
            df = pd.DataFrame(data_list)
            
            # Reordenar columnas exacto
            cols_to_export = [c for c in required_cols if c in df.columns]
            df = df[cols_to_export]

            df.to_excel(output_path, index=False)
            self.log(f"✨ Archivo guardado con éxito en: {output_path}")
            return True

        except Exception as e:
            self.log(f"❌ Error en TformdetManager: {str(e)}")
            traceback.print_exc()
            return False
