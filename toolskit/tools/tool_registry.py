"""
tool_registry.py
================
Registro central de todas las herramientas del ToolKit SISMED.

Para añadir una nueva herramienta al sistema, solo hace falta:
  1. Crear su clase en tools/ heredando de SismedTool
  2. Importarla aquí y añadirla a TOOLS_REGISTRY

El resto del sistema (Dashboard, buscador, menú) lo recoge automáticamente.
"""

from tools.dbf_tool import DbfExcelTool
from tools.format_tformdet_tool import FormatTformdetTool
from tools.consulta_tformdet_tool import ConsultaTformdetTool
from tools.reporte_guias_tool import ReporteGuiasTool
from tools.sync_sismed_tool import SyncSismedTool
from tools.stock_report_tool import StockReportTool
from tools.disponibilidad_report_tool import DisponibilidadReportTool
from tools.change_medest_tool import ChangeMedestTool
from tools.edit_tmovim_tool import EditTmovimTool
 
 
# ── Instancias únicas (Singleton por herramienta) ──────────────────────────────────────────────────────
# Añade más herramientas aquí a medida que las vayas migrando a OOP.
TOOLS_REGISTRY: list = [
    DbfExcelTool(),
    FormatTformdetTool(),
    ConsultaTformdetTool(),
    ReporteGuiasTool(),
    StockReportTool(),
    DisponibilidadReportTool(),
    ChangeMedestTool(),
    EditTmovimTool(),
    SyncSismedTool(),
]


def get_tool_by_name(nombre: str):
    """Busca una herramienta por nombre exacto (case-insensitive)."""
    nombre_lower = nombre.strip().lower()
    for tool in TOOLS_REGISTRY:
        if tool.metadata.nombre.lower() == nombre_lower:
            return tool
    return None


def search_tools(query: str) -> list:
    """
    Busca herramientas que coincidan con el texto de búsqueda.
    Revisa nombre, descripcion y etiquetas de cada herramienta.
    Devuelve una lista filtrada de instancias SismedTool.
    """
    if not query or not query.strip():
        return TOOLS_REGISTRY

    q = query.strip().lower()
    results = []
    for tool in TOOLS_REGISTRY:
        m = tool.metadata
        haystack = " ".join([
            m.nombre, m.descripcion, m.categoria, " ".join(m.etiquetas)
        ]).lower()
        if q in haystack:
            results.append(tool)
    return results


def get_tools_by_category(categoria: str) -> list:
    """Filtra herramientas por categoría."""
    return [t for t in TOOLS_REGISTRY if t.metadata.categoria == categoria]
