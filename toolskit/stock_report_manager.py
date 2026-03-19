"""
stock_report_manager.py
=======================
Motor de lógica para generación LOCAL de reportes de Stock SISMED.

Genera un archivo Excel con:
  - Hoja "Stock General"  → MMEDICAM + MSTKALM (stock consolidado por medicamento)
    Campos: Medcod, Descripcion, Unidad, Stock, Precio, Almcod, Medest, Codigo_SIG

  - Hojas "Stock Detallado" → MSTKALMDE (por lote, opcionalmente por farmacia)
    Campos: Almcod, Medcod, Codigo_SIG, Tipsum, Ffinan, Lote, Reg. Sanitario,
            Fecha, Saldo, Precio_Det, Mednom, Preciocab, Xnom

Soporta:
  * Modo CONSOLIDADO  → una sola hoja con todas las farmacias sumadas.
  * Modo POR FARMACIA → una hoja por cada farmacia + hoja resumen total.

CORRECCIONES v2:
  - Stock General: auto-detección de campos reales del DBF (STKSAL/STKSALDO/etc.)
  - Medcod se escribe como TEXTO para preservar ceros iniciales (00125, etc.)
  - Tipsum y Ffinan exportan solo la abreviatura/código, no el nombre completo.
  - Precio Det → campo STKPRED; Precio Cab → campo STKPRECAB (fallback STKPREO).
  - Se excluyen registros con saldo == 0.
"""

import os
import traceback

from dbfread import DBF

try:
    import openpyxl
    from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side)
    from openpyxl.utils import get_column_letter
    OPENPYXL_OK = True
except ImportError:
    OPENPYXL_OK = False


# ─── Columnas cuyo valor debe escribirse como texto (string) en Excel ────────
_TEXT_COLS = {"Medcod", "Almcod", "Codigo_SIG", "Lote"}

# ─── Helpers de estilos Excel ────────────────────────────────────────────────

_HEADER_FILL  = PatternFill("solid", fgColor="1E3A5F")   if OPENPYXL_OK else None
_HEADER_FONT  = Font(bold=True, color="FFFFFF", size=10)  if OPENPYXL_OK else None
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True) if OPENPYXL_OK else None
_THIN_BORDER  = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"),  bottom=Side(style="thin")
) if OPENPYXL_OK else None
_ALT_FILL     = PatternFill("solid", fgColor="EEF4FF")    if OPENPYXL_OK else None


def _style_header_row(ws, row=1, last_col=1):
    for col in range(1, last_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill      = _HEADER_FILL
        cell.font      = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border    = _THIN_BORDER


def _style_data_row(ws, row, last_col):
    fill = _ALT_FILL if row % 2 == 0 else None
    for col in range(1, last_col + 1):
        cell = ws.cell(row=row, column=col)
        if fill:
            cell.fill = fill
        cell.border    = _THIN_BORDER
        cell.alignment = Alignment(vertical="center")


def _autofit(ws, min_w=8, max_w=50):
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                max_len = max(max_len, len(str(cell.value or "")))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, min_w), max_w)


def _freeze(ws, cell="A2"):
    ws.freeze_panes = cell


# ─── Manager principal ───────────────────────────────────────────────────────

class StockReportManager:
    """Lee los DBFs del SISMED y exporta reportes de stock a Excel."""

    COLS_GENERAL = ["Medcod", "Descripcion (Consolidada)", "Unidad",
                    "Stock", "Precio", "Almcod", "Medest", "Codigo_SIG"]

    COLS_DETALLE = ["Almcod", "Medcod", "Codigo_SIG", "Tipsum", "Ffinan",
                    "Lote", "Reg. Sanitario", "Fecha Venc.", "Saldo", "Precio Det.",
                    "Nombre Med.", "Precio Cab.", "Descripcion (Completa)"]

    def __init__(self, sismed_dir: str, log_callback=None):
        self.sismed_dir = sismed_dir.strip()
        self._log_fn    = log_callback

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)
        else:
            print(msg)

    # ── Rutas DBF ─────────────────────────────────────────────────────────────
    def _dbf(self, nombre: str) -> str:
        return os.path.join(self.sismed_dir, "DATOS", nombre)

    def _read_dbf(self, path: str):
        if not os.path.exists(path):
            self.log(f"  ⚠ No encontrado: {path}")
            return []
        try:
            records = list(DBF(path, ignore_missing_memofile=True,
                               char_decode_errors="ignore"))
            return records
        except Exception as e:
            self.log(f"  ✗ Error leyendo {os.path.basename(path)}: {e}")
            return []

    # ── Catálogos ─────────────────────────────────────────────────────────────
    def _load_medicam(self):
        cat = {}
        for rec in self._read_dbf(self._dbf("MMEDICAM.DBF")):
            cod = str(rec.get("MEDCOD", "")).strip().zfill(5)
            if not cod:
                continue
            nom  = str(rec.get("MEDNOM",  "")).strip()   # nombre genérico
            cnc  = str(rec.get("MEDCNC",  "")).strip()   # concentración  (ej: 70°, 500 mg)
            ff   = str(rec.get("MEDFF",   "")).strip()   # forma farmacéutica → TABLETA, SOLUCION, etc.
            pres = str(rec.get("MEDPRES", "")).strip()   # presentación   (ej: 1 L, 100 Tab)
            est  = str(rec.get("MEDEST",  "")).strip()

            # Descripción consolidada: MEDNOM - MEDCNC - MEDFF - MEDPRES
            partes = [p for p in [nom, cnc, ff, pres] if p]

            cat[cod] = {
                "mednom":     nom,
                "xpro":       " - ".join(partes),
                "xnom":       " - ".join(partes),
                "unidad":     ff,      # MEDFF = forma farmacéutica (TABLETA, SOLUCION, etc.)
                "medest":     est,
                "codigo_sig": str(rec.get("CODIGO_SIG", "")).strip(),
            }
        self.log(f"  ✓ Medicamentos cargados: {len(cat)}")
        return cat


    def _load_almacenes(self):
        cat = {}
        for rec in self._read_dbf(self._dbf("MALMACEN.DBF")):
            cod = str(rec.get("ALMCOD", "")).strip()
            if cod:
                cat[cod] = str(rec.get("ALMDES", "")).strip()
        return cat

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(str(val).strip()) if val is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _fmt_date(val) -> str:
        if val is None:
            return ""
        if hasattr(val, "strftime"):
            return val.strftime("%d/%m/%Y")
        return str(val).strip()

    @staticmethod
    def _pick_field(rec: dict, *candidates):
        """Devuelve el valor del primer campo candidato que exista y no sea None/vacío."""
        for key in candidates:
            val = rec.get(key)
            if val is not None and str(val).strip() not in ("", "0", "0.0"):
                return val
        # Si todos vacíos, devuelve el valor del primero que exista
        for key in candidates:
            if key in rec:
                return rec[key]
        return None

    # ── Lectura STOCK GENERAL (consolidado desde MSTKALMDE por MEDCOD) ────────
    def _read_stock_general(self, cat_med: dict, cat_alm: dict) -> list:
        """
        No existe MSTKALM: el stock general se consolida desde MSTKALMDE
        agrupando por MEDCOD y sumando el saldo de todos los lotes/almacenes.
        Precio de referencia → STKPREO (precio cabecera).
        Orden final: alfabético por Descripcion (Consolidada).
        """
        consolidado: dict = {}

        for rec in self._read_dbf(self._dbf("MSTKALMDE.DBF")):
            medcod = str(rec.get("MEDCOD", "")).strip().zfill(5)
            if not medcod:
                continue

            saldo = self._safe_float(rec.get("STKSALDODE"))

            # Precio cabecera como referencia para el reporte general
            precio = self._safe_float(
                self._pick_field(rec, "STKPREO", "STKPRECAB", "STKPRECAD", "STKPRED")
            )

            almcod = str(rec.get("ALMCOD", "")).strip()

            if medcod not in consolidado:
                med = cat_med.get(medcod, {})
                consolidado[medcod] = {
                    "Medcod":                    medcod,
                    "Descripcion (Consolidada)": med.get("xpro", ""),
                    "Unidad":                    med.get("unidad", ""),
                    "Stock":                     saldo,
                    "Precio":                    precio,
                    "Almcod":                    almcod,
                    "Medest":                    med.get("medest", ""),
                    "Codigo_SIG":                med.get("codigo_sig", ""),
                }
            else:
                consolidado[medcod]["Stock"] += saldo
                if precio > consolidado[medcod]["Precio"]:
                    consolidado[medcod]["Precio"] = precio

        # Filtrar stock=0 y ordenar alfabéticamente por descripción
        rows = sorted(
            [r for r in consolidado.values() if r["Stock"] > 0],
            key=lambda r: r["Descripcion (Consolidada)"].upper()
        )
        skipped = len(consolidado) - len(rows)
        self.log(f"  ✓ Medicamentos Stock General: {len(rows)}  (omitidos stock=0: {skipped})")
        return rows


    # ── Lectura STOCK DETALLADO (MSTKALMDE) ───────────────────────────────────
    def _read_stock_detallado(self, cat_med: dict, cat_alm: dict) -> list:
        rows    = []
        skipped = 0

        for rec in self._read_dbf(self._dbf("MSTKALMDE.DBF")):
            medcod = str(rec.get("MEDCOD", "")).strip().zfill(5)
            if not medcod:
                continue

            saldo = self._safe_float(rec.get("STKSALDODE"))

            # Excluir stock 0
            if saldo == 0.0:
                skipped += 1
                continue

            almcod = str(rec.get("ALMCOD", "")).strip()
            med    = cat_med.get(medcod, {})

            # Tipsum y Ffinan → solo abreviatura/código, NO el nombre completo
            tipsum = str(rec.get("TIPSUM", "")).strip()
            ffinan = str(rec.get("FFINAN", "")).strip()

            # Precio Det: STKPRECIO  |  Precio Cab: STKPRECAB → fallback STKPREO
            precio_det = self._safe_float(rec.get("STKPRECIO"))
            precio_cab = self._safe_float(
                self._pick_field(rec, "STKPRECAB", "STKPREO", "STKPRECAD")
            )

            rows.append({
                "Almcod":               almcod,
                "Medcod":               medcod,
                "Codigo_SIG":           med.get("codigo_sig", ""),
                "Tipsum":               tipsum,       # solo código
                "Ffinan":               ffinan,       # solo código
                "Lote":                 str(rec.get("MEDLOTE",   "")).strip(),
                "Reg. Sanitario":       str(rec.get("MEDREGSAN", "")).strip(),
                "Fecha Venc.":          self._fmt_date(rec.get("MEDFECHVTO")),
                "Saldo":                saldo,
                "Precio Det.":          precio_det,
                "Nombre Med.":          med.get("mednom", ""),
                "Precio Cab.":          precio_cab,
                "Descripcion (Completa)": med.get("xnom", ""),
            })

        # Ordenar alfabéticamente por 'Nombre Med.'
        rows = sorted(rows, key=lambda r: str(r["Nombre Med."]).upper())

        self.log(f"  ✓ Registros Stock Detallado: {len(rows)}  (omitidos con stock=0: {skipped})")
        return rows

    # ── Escritura de hoja ─────────────────────────────────────────────────────
    def _write_sheet(self, wb, sheet_name: str, cols: list, rows: list):
        ws = wb.create_sheet(title=sheet_name[:31])
        ws.row_dimensions[1].height = 30

        # Encabezados
        for c_idx, col in enumerate(cols, start=1):
            ws.cell(row=1, column=c_idx, value=col)
        _style_header_row(ws, row=1, last_col=len(cols))

        # Datos
        for r_idx, row in enumerate(rows, start=2):
            for c_idx, col in enumerate(cols, start=1):
                val  = row.get(col)
                cell = ws.cell(row=r_idx, column=c_idx)

                # Columnas que deben ser texto para preservar ceros iniciales
                if col in _TEXT_COLS:
                    cell.data_type = "s"        # string
                    cell.number_format = "@"    # formato texto en Excel
                    cell.value = str(val) if val is not None else ""
                else:
                    cell.value = val

            _style_data_row(ws, row=r_idx, last_col=len(cols))

        _autofit(ws)
        _freeze(ws)
        return ws

    # ── Agrupar detallado por farmacia (prefijo 5 chars) ─────────────────────
    @staticmethod
    def _agrupar_por_farmacia(rows: list) -> dict:
        grupos: dict = {}
        for row in rows:
            prefijo = row["Almcod"][:5] if len(row["Almcod"]) >= 5 else row["Almcod"]
            grupos.setdefault(prefijo, []).append(row)
        return grupos

    # ── PUNTO DE ENTRADA PRINCIPAL ─────────────────────────────────────────────
    def generate(self,
                 output_path: str,
                 include_general: bool = True,
                 include_detalle: bool = True,
                 modo_detalle: str = "consolidado") -> bool:
        """
        Genera el archivo Excel de stock.
        Devuelve True si fue exitoso, False si ocurrió algún error.
        """
        if not OPENPYXL_OK:
            self.log("  ✗ openpyxl no está instalado. Ejecuta: pip install openpyxl")
            return False

        self.log(f"📂 Leyendo SISMED desde: {self.sismed_dir}")
        self.log("─" * 52)

        try:
            cat_med = self._load_medicam()
            cat_alm = self._load_almacenes()

            wb = openpyxl.Workbook()
            wb.remove(wb.active)   # elimina la hoja "Sheet" por defecto

            # ── Hoja: Stock General ───────────────────────────────────────────
            if include_general:
                self.log("📊 Generando Stock General (MSTKALM)...")
                rows_gen = self._read_stock_general(cat_med, cat_alm)
                self._write_sheet(wb, "Stock General", self.COLS_GENERAL, rows_gen)

            # ── Hojas: Stock Detallado ────────────────────────────────────────
            if include_detalle:
                self.log("📋 Generando Stock Detallado (MSTKALMDE)...")
                rows_det = self._read_stock_detallado(cat_med, cat_alm)

                if modo_detalle == "consolidado":
                    self._write_sheet(wb, "Stock Detallado", self.COLS_DETALLE, rows_det)

                elif modo_detalle == "por_farmacia":
                    grupos = self._agrupar_por_farmacia(rows_det)
                    self.log(f"  → {len(grupos)} farmacia(s) detectada(s).")
                    # Hoja resumen total primero
                    self._write_sheet(wb, "Det. TOTAL", self.COLS_DETALLE, rows_det)
                    for prefijo, filas in sorted(grupos.items()):
                        nombre_hoja = f"Det. {prefijo}"
                        self._write_sheet(wb, nombre_hoja, self.COLS_DETALLE, filas)
                        self.log(f"    ✓ '{nombre_hoja}': {len(filas)} registros")

            # ── Guardar ───────────────────────────────────────────────────────
            if not output_path.lower().endswith(".xlsx"):
                output_path += ".xlsx"
            wb.save(output_path)
            self.log(f"✅ Archivo guardado en: {output_path}")
            return True

        except (PermissionError, OSError) as err:
            self.log(f"  ✗ Error de archivo (¿está abierto en Excel?): {err}")
            return False
        except Exception as err:
            self.log(f"  ✗ Error crítico: {err}")
            self.log(traceback.format_exc())
            return False
