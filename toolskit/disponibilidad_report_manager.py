"""
disponibilidad_report_manager.py
=================================
Motor de generación de reportes de DISPONIBILIDAD basados en TFORMDET.

Equivale a las consultas TRANSFORM/PIVOT de Access, reimplementadas
en Python puro usando dbfread + openpyxl.

Configuraciones soportadas:
  1. Por Farmacias   → una fila por farmacia (código completo, ej: 06520F01)
  2. Por IPRESS      → consolida farmacias del mismo IPRESS (quita F0... del código)
  3. Excluir EESS    → permite excluir establecimientos por código
  4. Por Red         → consolida todo por RED, sin desglosar por EESS
  5. Meses           → período de N meses hacia atrás desde hoy

Columnas pivot: ANNOMES (yyyymm) → columnas dinámicas con Consumo = venta+sis+intersan
Columna extra: PRECIO = último precio del período | STOCK_FIN = stock del mes seleccionado
"""

import os
import re
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from collections import defaultdict

from dbfread import DBF
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter


# ══════════════════════════════════════════════════════════════════════════════
# Clase principal
# ══════════════════════════════════════════════════════════════════════════════
class DisponibilidadReportManager:
    """
    Genera reportes de Disponibilidad (consumo pivot + stock_fin + precio)
    a partir de los archivos DBF locales del SISMED.
    """

    # ── Columnas fijas de salida ───────────────────────────────────────────────
    COLS_EESS  = ["RED", "MICRORED", "COD EESS", "ESTABLECIMIENTO", "CAT",
                  "MED COD", "DESCRIPCION DEL PRODUCTO", "MEDFF", "PRECIO",
                  "MEDTIP", "MEDPET", "MEDEST"]
    COLS_RED   = ["RED",
                  "MED COD", "DESCRIPCION DEL PRODUCTO", "MEDFF", "PRECIO",
                  "MEDTIP", "MEDPET", "MEDEST"]

    def __init__(self, sismed_dir: str, log_callback=None):
        self.sismed_dir = sismed_dir.strip()
        self._log_fn    = log_callback

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)
        else:
            print(msg)

    # ── Rutas ─────────────────────────────────────────────────────────────────
    def _dbf(self, nombre: str) -> str:
        return os.path.join(self.sismed_dir, "DATOS", nombre)

    def _read_dbf(self, path: str) -> list:
        if not os.path.exists(path):
            self.log(f"  ⚠ No encontrado: {path}")
            return []
        try:
            return list(DBF(path, ignore_missing_memofile=True,
                           char_decode_errors="ignore"))
        except Exception as e:
            self.log(f"  ✗ Error leyendo {os.path.basename(path)}: {e}")
            return []

    # ── Utilidades ────────────────────────────────────────────────────────────
    @staticmethod
    def _s(val) -> str:
        """Valor a string limpio."""
        return str(val).strip() if val is not None else ""

    @staticmethod
    def _f(val) -> float:
        """Valor a float seguro."""
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _strip_farmacia(codigo: str) -> str:
        """
        Quita el sufijo Fxx al final del código de establecimiento.
        Ej: '06520F01' → '06520'  |  '06502F12' → '06502'
        Se busca el patrón 'F' seguido de dígitos al final.
        """
        return re.sub(r'F\d+$', '', codigo.strip(), flags=re.IGNORECASE)

    @staticmethod
    def _build_periodos(meses: int, mes_ref: str = None) -> list[str]:
        """
        Devuelve lista de strings 'yyyymm' desde hace N meses hasta el mes de referencia inclusive.
        Orden ascendente (igual que PIVOT de Access).
        """
        if mes_ref and len(mes_ref) == 6:
            y = int(mes_ref[:4])
            m = int(mes_ref[4:])
            base_date = date(y, m, 1)
        else:
            base_date = date.today()

        resultado = []
        for i in range(meses - 1, -1, -1):
            d = base_date - relativedelta(months=i)
            resultado.append(d.strftime("%Y%m"))
        return resultado

    # ── Cargadores de catálogos ────────────────────────────────────────────────
    def _load_medicam(self) -> dict:
        """Carga MMEDICAM: key=MEDCOD(zfill 5) → dict con atributos."""
        cat = {}
        for rec in self._read_dbf(self._dbf("MMEDICAM.DBF")):
            cod = self._s(rec.get("MEDCOD")).zfill(5)
            if not cod or cod == "00000":
                continue
            nom  = self._s(rec.get("MEDNOM"))
            cnc  = self._s(rec.get("MEDCNC"))
            pres = self._s(rec.get("MEDPRES"))
            ff   = self._s(rec.get("MEDFF"))
            partes = [p for p in [nom, cnc, pres, ff] if p]
            cat[cod] = {
                "medcod": cod,
                "medff":  ff,
                "medtip": self._s(rec.get("MEDTIP")),
                "medpet": self._s(rec.get("MEDPET")),
                "medest": self._s(rec.get("MEDEST")),
                "med":    " - ".join(partes),
            }
        self.log(f"  ✓ Medicamentos cargados: {len(cat)}")
        return cat

    def _load_redes(self) -> tuple[dict, dict]:
        """
        Carga MRED:
        - key=(disa, cod_red) → descripción
        - key_ubi=(disa, dptoprov) → (cod_red, descripción)
        """
        redes = {}
        redes_ubi = {}
        for rec in self._read_dbf(self._dbf("MRED.DBF")):
            disa = self._s(rec.get("REDCDISA"))
            cod  = self._s(rec.get("REDCCODRED"))
            desc = self._s(rec.get("REDTDSCL"))
            dpto = self._s(rec.get("REDCDPTO"))
            prov = self._s(rec.get("REDCPROV"))

            if disa and cod:
                redes[(disa, cod)] = desc
            if disa and dpto and prov:
                redes_ubi[(disa, dpto + prov)] = (cod, desc)
        
        self.log(f"  ✓ Redes cargadas: {len(redes)} (Ubi: {len(redes_ubi)})")
        return redes, redes_ubi

    def _load_microredes(self) -> tuple[dict, dict]:
        """
        Carga MMICRORED:
        - key=(disa, cod_red, cod_mr) → descripción
        - key_ubi=(disa, cod_red, dist) → descripción (fallback por Ubigeo CC)
        """
        mrs = {}
        mrs_ubi = {}
        for rec in self._read_dbf(self._dbf("MMICRORED.DBF")):
            disa = self._s(rec.get("MRECDISA"))
            red  = self._s(rec.get("MRECRED"))
            cod  = self._s(rec.get("MRECMICRO"))
            desc = self._s(rec.get("MRETDSCL"))
            dist = self._s(rec.get("MRECDIST"))

            if disa and red and cod:
                mrs[(disa, red, cod)] = desc
            if disa and red and dist:
                mrs_ubi[(disa, red, dist)] = desc

        self.log(f"  ✓ Microredes cargadas: {len(mrs)} (Ubi: {len(mrs_ubi)})")
        return mrs, mrs_ubi

    def _load_categorias(self) -> dict:
        """Carga MCATES: key=cod_eess (normalizado) → categoria."""
        cat = {}
        for rec in self._read_dbf(self._dbf("MCATES.DBF")):
            cod = self._s(rec.get("ESTCESTS"))
            v   = self._s(rec.get("ESTCCAT"))
            if cod:
                # Guardar bajo varias formas para asegurar el match
                c_clean = cod.strip().lstrip('0')
                if c_clean: cat[c_clean] = v
                cat[cod.strip()] = v
        self.log(f"  ✓ Categorías cargadas (MCATES): {len(cat)}")
        return cat

    def _load_almacen(self) -> dict:
        """
        Carga MALMACEN: key = código raíz -> dict con RED, MR, EESS, CATEGORIA.
        Usa fallbacks si los campos directos de RED/MR están vacíos.
        """
        cat_redes, cat_redes_ubi = self._load_redes()
        cat_mrs, cat_mrs_ubi     = self._load_microredes()
        cat_cates_extra          = self._load_categorias()
        
        cat_raw = {}
        for rec in self._read_dbf(self._dbf("MALMACEN.DBF")):
            cod  = self._s(rec.get("ALMCOD"))
            if not cod:
                continue
            
            disa = self._s(rec.get("ALMCDISA"))
            r_c  = self._s(rec.get("ALMCRED"))
            m_c  = self._s(rec.get("ALMCMRED"))
            ubi  = self._s(rec.get("ALMUBIGEO")) # DDPPCC
            des  = self._s(rec.get("ALMDES"))
            
            # 1. Resolver RED
            red_desc = cat_redes.get((disa, r_c))
            red_resolvida = r_c
            if not red_desc and len(ubi) >= 4:
                info_red = cat_redes_ubi.get((disa, ubi[:4]))
                if info_red:
                    red_resolvida, red_desc = info_red
            
            if not red_desc:
                red_desc = r_c

            # 2. Resolver Microred (MR)
            mr_desc = cat_mrs.get((disa, r_c, m_c))
            if not mr_desc and len(ubi) >= 6:
                # Usar red_resolvida para afinar la búsqueda del distrito
                mr_desc = cat_mrs_ubi.get((disa, red_resolvida, ubi[4:]))
                
                if not mr_desc:
                    # Búsqueda ciega en todas las REDES de esa DISA
                    for (d, r, dist), desc in cat_mrs_ubi.items():
                        if d == disa and dist == ubi[4:]:
                            mr_desc = desc
                            break
            if not mr_desc:
                mr_desc = m_c

            # 3. Categoría (Prioridad: P.C. -> MCATES -> Heurística por nombre)
            categ = ""
            des_up = des.upper()

            # REGLA 1: P.C. (Farmacias Punto de Canje / Prov de Consumo)
            if "P.C." in des_up or "P.C " in des_up or "PTOCANJE" in des_up.replace(" ",""):
                categ = "P.C"
            
            if not categ:
                # REGLA 2: Buscar en MCATES con el código base (5 dígitos)
                cod_base = self._strip_farmacia(cod)
                # Extraer solo números por si acaso hay letras residuales
                # (Ej: 06502A -> 06502)
                cod_base_num = "".join(filter(str.isdigit, cod_base))[:5]
                
                # Intentos de match en MCATES
                categ = (cat_cates_extra.get(cod_base) or 
                         cat_cates_extra.get(cod_base_num) or
                         cat_cates_extra.get(cod_base.lstrip('0')) or
                         cat_cates_extra.get(cod_base_num.lstrip('0')))

            if not categ:
                # REGLA 3: Heurística basada en el nombre (identificadores SISMED)
                if any(x in des_up for x in ["HOSPITAL", "HOSP.", "H. "]): 
                    categ = "II-1"
                elif any(x in des_up for x in ["CENTRO SALUD", "C.S.", "C. S."]):
                    categ = "I-3"
                elif any(x in des_up for x in ["PUESTO SALUD", "P.S.", "PS.", "P. S."]):
                    categ = "I-1"
                elif self._s(rec.get("ALMTIPO")).upper() == "P":
                    categ = "I-2"
            
            # Limpieza final
            if categ == "0": categ = ""

            cat_raw[cod] = {
                "cod_eess":  cod,
                "eess":      des,
                "red":       red_desc,
                "mr":        mr_desc,
                "categoria": categ,
            }
        
        # Log de diagnóstico
        con_cat = len([x for x in cat_raw.values() if x["categoria"]])
        self.log(f"  ✓ Almacenes cargados: {len(cat_raw)} ({con_cat} con categoría)")
        return cat_raw

    # ── Generador principal ────────────────────────────────────────────────────
    def generate(
        self,
        output_path:     str,
        meses:           int   = 12,
        modo:            str   = "farmacias",   # 'farmacias' | 'ipress' | 'red'
        excluir_codigos: list  = None,
        mes_stock_fin:   str   = None,          # 'yyyymm'; si None → mes más reciente del rango
    ) -> bool:
        """
        Genera el reporte de disponibilidad y lo guarda en *output_path* (.xlsx).

        Parámetros:
          meses           → cuántos meses atrás incluir (ej: 12)
          modo            → 'farmacias'  = por código completo de farmacia
                            'ipress'     = consolida quitando Fxx del código
                            'red'        = consolida por RED (sin EESS)
          excluir_codigos → lista de códigos_pre a excluir (exacto, ej: ['06502', '06502F01'])
          mes_stock_fin   → mes de STOCK_FIN y PRECIO (ej: '202602'); None = último del rango
        """
        try:
            excluir  = set(c.strip() for c in (excluir_codigos or []))
            
            # ── Paso 1: Leer TFORMDET para saber periodos reales ────────────────
            self.log("▶ Iniciando Reporte de Disponibilidad...")
            self.log(f"  Modo     : {modo}")
            self.log(f"  Cargando Catálogos...")
            cat_med = self._load_medicam()
            cat_alm = self._load_almacen()

            self.log("  Analizando TFORMDET.DBF...")
            t_path = self._dbf("TFORMDET.DBF")
            # Leemos solo ANNOMES primero para validar (o todos si no es muy pesado)
            # Para SISMED, TFORMDET suele leerse completo.
            tformdet_recs = self._read_dbf(t_path)
            self.log(f"  ✓ Registros TFORMDET: {len(tformdet_recs)}")

            meses_en_archivo = sorted(list(set(self._s(r.get("ANNOMES")) for r in tformdet_recs)))
            meses_en_archivo = [m for m in meses_en_archivo if len(m) == 6 and m.isdigit()]
            
            if not meses_en_archivo:
                self.log("  ✗ El archivo TFORMDET.DBF no contiene periodos válidos.")
                return False
            
            # ── Paso 2: Validar mes de referencia (Stock Fin / Fin de Rango) ────
            mes_fin = mes_stock_fin
            if mes_fin:
                if mes_fin not in meses_en_archivo:
                    ultimo_real = meses_en_archivo[-1] if meses_en_archivo else "ERR"
                    self.log(f"  ⚠ El periodo seleccionado {mes_fin} NO tiene datos en TFORMDET.")
                    self.log(f"    Se usará el último disponible: {ultimo_real}")
                    mes_fin = ultimo_real
            else:
                mes_fin = meses_en_archivo[-1] if meses_en_archivo else "190001"

            # ── Paso 3: Construir periodo de consumo móvil ──────────────────────
            periodos_teoricos = self._build_periodos(meses, mes_fin)
            
            # Intersectar con los meses que REALMENTE tienen datos para no mostrar celdas vacías
            periodos = [p for p in periodos_teoricos if p in meses_en_archivo]
            
            if len(periodos) < meses:
                self.log(f"  ⚠ Aviso: Solo se encontraron {len(periodos)} meses con datos en el")
                self.log(f"  ⚠ historial de TFORMDET (de los {meses} solicitados).")

            if not periodos:
                # Caso borde: si la intersección es vacía pero el mes de fin es válido
                periodos = [mes_fin]
                self.log(f"  ✗ Sin datos de consumo en el rango solicitado.")
            
            self.log(f"  Período  : {periodos[0]} → {periodos[-1]}  ({len(periodos)} meses con datos)")
            self.log(f"  Stock fin: {mes_fin}")
            self.log(f"  Excluir  : {excluir or '(ninguno)'}")

            # ── Procesar registros ─────────────────────────────────────────────
            #  Estructura acumulada:
            #  data[grupo_key] = {
            #    "meta":    {...attrs fijos...},
            #    "consumo": {yyyymm: float},
            #    "precio":  {yyyymm: float},
            #    "stock":   {yyyymm: float},
            #  }
            data: dict = {}
            periodos_set = set(periodos)

            for rec in tformdet_recs:
                annomes   = self._s(rec.get("ANNOMES"))
                if annomes not in periodos_set:
                    continue

                cod_pre_orig = self._s(rec.get("CODIGO_PRE"))
                cod_med      = self._s(rec.get("CODIGO_MED")).zfill(5)

                if not cod_pre_orig or not cod_med:
                    continue

                # Aplicar modo (normalizar código)
                if modo == "ipress":
                    cod_pre = self._strip_farmacia(cod_pre_orig)
                else:
                    cod_pre = cod_pre_orig

                # Filtrar excluidos (chequeamos el código normalizado Y el original)
                if cod_pre in excluir or cod_pre_orig in excluir:
                    continue

                # Verificar que el medicamento existe
                if cod_med not in cat_med:
                    continue

                # Calcular consumo
                venta   = self._f(rec.get("VENTA"))
                sis     = self._f(rec.get("SIS"))
                intersan= self._f(rec.get("INTERSAN"))
                consumo = venta + sis + intersan

                precio    = self._f(rec.get("PRECIO"))
                stock_fin = self._f(rec.get("STOCK_FIN"))

                # ── Clave del grupo ────────────────────────────────────────────
                if modo == "red":
                    # Obtener RED del almacén
                    alm = cat_alm.get(cod_pre) or cat_alm.get(cod_pre_orig) or {}
                    red = alm.get("red", "")
                    grupo_key = (red, cod_med)
                else:
                    grupo_key = (cod_pre, cod_med)

                # ── Acumular ───────────────────────────────────────────────────
                if grupo_key not in data:
                    med_info = cat_med[cod_med]
                    if modo == "red":
                        alm = cat_alm.get(cod_pre) or cat_alm.get(cod_pre_orig) or {}
                        meta = {
                            "red":     alm.get("red", ""),
                            "medcod":  cod_med,
                            **{k: med_info[k] for k in ("medff","medtip","medpet","medest","med")},
                        }
                    else:
                        alm = cat_alm.get(cod_pre) or {}
                        meta = {
                            "red":       alm.get("red",      ""),
                            "mr":        alm.get("mr",       ""),
                            "cod_eess":  cod_pre,
                            "eess":      alm.get("eess",     ""),
                            "categoria": alm.get("categoria",""),
                            "medcod":    cod_med,
                            **{k: med_info[k] for k in ("medff","medtip","medpet","medest","med")},
                        }
                    data[grupo_key] = {
                        "meta":    meta,
                        "consumo": defaultdict(float),
                        "precio":  {},
                        "stock":   defaultdict(float),
                    }

                data[grupo_key]["consumo"][annomes] += consumo
                # Precio: tomamos el último (mayor annomes)
                prev = data[grupo_key]["precio"]
                if (annomes not in prev) or (annomes >= max(prev.keys(), default="")):
                    data[grupo_key]["precio"][annomes] = precio
                # Stock_fin acumulado (en consolidación puede sumar varias farmacias)
                data[grupo_key]["stock"][annomes] += stock_fin

            self.log(f"  ✓ Grupos únicos generados: {len(data)}")

            # ── Construir filas ────────────────────────────────────────────────
            es_red   = (modo == "red")
            col_fijos = self.COLS_RED if es_red else self.COLS_EESS

            wb = Workbook()
            ws = wb.active
            ws.title = "Disponibilidad"

            # Cabecera: columnas fijas + periodos dinámicos + STOCK_FIN
            header = col_fijos + periodos + ["STOCK_FIN"]
            self._write_header(ws, header)
 
            row_n = 2
            for grupo_key, grp in sorted(data.items()):
                meta    = grp["meta"]
                consumo = grp["consumo"]
                precios = grp["precio"]
                stocks  = grp["stock"]
 
                # Precio final = último precio del período con datos
                if precios:
                    precio_final = precios[max(precios.keys())]
                else:
                    precio_final = 0.0
 
                stock_fin_val = stocks.get(mes_fin, 0.0)
 
                if es_red:
                    row_base = [
                        meta.get("red",     ""),
                        meta.get("medcod",  ""),
                        meta.get("med",     ""),
                        meta.get("medff",   ""),
                        precio_final,
                        meta.get("medtip",  ""),
                        meta.get("medpet",  ""),
                        meta.get("medest",  ""),
                    ]
                else:
                    row_base = [
                        meta.get("red",      ""),
                        meta.get("mr",       ""),
                        meta.get("cod_eess", ""),
                        meta.get("eess",     ""),
                        meta.get("categoria",""),
                        meta.get("medcod",   ""),
                        meta.get("med",      ""),
                        meta.get("medff",    ""),
                        precio_final,
                        meta.get("medtip",   ""),
                        meta.get("medpet",   ""),
                        meta.get("medest",   ""),
                    ]
 
                # Columnas pivot
                row_pivot = [consumo.get(p, 0) for p in periodos]
                ws.append(row_base + row_pivot + [stock_fin_val])
 
                # Formato especial: medcod como texto
                try:
                    medcod_idx = col_fijos.index("MED COD")
                    ws.cell(row=row_n, column=medcod_idx + 1).number_format = "@"
                    ws.cell(row=row_n, column=medcod_idx + 1).value = meta.get("medcod", "")
                except ValueError:
                    pass
                
                row_n += 1
 
            # ── Estilo tabla ───────────────────────────────────────────────────
            self._auto_style(ws, len(header), row_n - 1)

            wb.save(output_path)
            self.log(f"✅ Reporte guardado en: {output_path}")
            return True

        except Exception as exc:
            import traceback
            self.log(f"✗ ERROR: {exc}")
            self.log(traceback.format_exc())
            return False

    # ── Helpers de escritura Excel ─────────────────────────────────────────────
    def _write_header(self, ws, cols: list):
        """Escribe la fila de cabecera con estilo."""
        fill   = PatternFill("solid", fgColor="1A3A5A")
        font   = Font(bold=True, color="FFFFFF", size=10)
        border = Border(
            bottom=Side(style="medium", color="4472C4"),
        )
        align  = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for i, col in enumerate(cols, start=1):
            cell = ws.cell(row=1, column=i, value=col)
            cell.fill    = fill
            cell.font    = font
            cell.border  = border
            cell.alignment = align
        ws.row_dimensions[1].height = 30

    def _auto_style(self, ws, n_cols: int, last_row: int):
        """Aplica estilo alternado a filas de datos y ajusta anchos."""
        fill_even = PatternFill("solid", fgColor="EEF4FB")
        font_data = Font(size=9)
        align_c   = Alignment(horizontal="center", vertical="center")
        align_l   = Alignment(horizontal="left",   vertical="center")

        # Mapeo de alineaciones por nombre de columna
        left_cols = {"RED", "MICRORED", "ESTABLECIMIENTO", "DESCRIPCION DEL PRODUCTO"}

        for row_i in range(2, last_row + 1):
            for col_i in range(1, n_cols + 1):
                cell = ws.cell(row=row_i, column=col_i)
                header_val = str(ws.cell(row=1, column=col_i).value or "")
                
                if row_i % 2 == 0:
                    cell.fill = fill_even
                cell.font = font_data
                
                if header_val in left_cols or len(header_val) > 15:
                    cell.alignment = align_l
                else:
                    cell.alignment = align_c

        # Ancho de columnas
        for col_i in range(1, n_cols + 1):
            col_letter = get_column_letter(col_i)
            header_val = str(ws.cell(row=1, column=col_i).value or "")
            
            # Períodos (yyyymm) o STOCK_FIN
            if (len(header_val) == 6 and header_val.isdigit()) or header_val == "STOCK_FIN":
                ws.column_dimensions[col_letter].width = 10
            elif header_val == "DESCRIPCION DEL PRODUCTO":
                ws.column_dimensions[col_letter].width = 50
            elif header_val in ("ESTABLECIMIENTO", "RED", "MICRORED"):
                ws.column_dimensions[col_letter].width = 30
            elif header_val == "MED COD":
                ws.column_dimensions[col_letter].width = 12
            elif header_val == "PRECIO":
                ws.column_dimensions[col_letter].width = 10
            else:
                ws.column_dimensions[col_letter].width = 12

        # ws.freeze_panes = None (eliminado por solicitud)
