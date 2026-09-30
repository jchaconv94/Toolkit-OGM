"""Versión del SISMED instalada, para la pestaña «Equipos» de ToolkitSISMED Web.

El SISMED la guarda en ``DATOS\\MCONFIG.DBF``, en la fila ``CFGCODMOD = 'SIS'`` y
``CFGCODIGO = 'AB'`` («FECHA ULTIMA VERSION SISMED»), con un valor como
``V2.5.3 vf 12/01/2026``.

Esa tabla guarda también usuarios y claves de los servicios web del SISMED (filas ``HTP``):
de aquí sale **solo** el valor de la fila SIS / AB. Si la tabla no está, está bloqueada o no
tiene la fila, se devuelve vacío y el envío sigue igual.
"""

from __future__ import annotations

import os
import re

from dbf_utils import open_dbf

MAX_LENGTH = 60


def _find_mconfig(base_dir: str) -> str:
    datos = os.path.join(base_dir, "DATOS")
    for name in ("MCONFIG.DBF", "mconfig.dbf", "Mconfig.dbf"):
        path = os.path.join(datos, name)
        if os.path.exists(path):
            return path
    return ""


def read_sismed_version(base_dir: str) -> str:
    """Valor de la fila SIS / AB de MCONFIG, o vacío si no se puede leer."""
    try:
        path = _find_mconfig(str(base_dir or "").strip())
        if not path:
            return ""
        for record in open_dbf(path):
            if str(record.get("CFGCODMOD") or "").strip().upper() != "SIS":
                continue
            if str(record.get("CFGCODIGO") or "").strip().upper() != "AB":
                continue
            value = re.sub(r"[\x00-\x1f\x7f]", "", str(record.get("CFGVALACT") or "")).strip()
            return value[:MAX_LENGTH]
    except Exception:
        return ""
    return ""
