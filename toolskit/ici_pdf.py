"""Generar ICI: el mismo libro en PDF, con todas sus hojas, listo para imprimir.

Si solo se entrega el Excel, se imprime la hoja que está abierta y las demás se quedan
(pedido del usuario del 2026-10-19). El PDF lo dibuja el propio Toolkit (ici_render, con
PyMuPDF): sale igual en todas las PC y cada página llega hasta abajo. Con Excel, WPS o
LibreOffice la tabla salía de otro tamaño que el calculado (espacio en blanco al pie, una
columna sola en otra página), así que esos programas quedan solo de respaldo, en este orden:

1. Microsoft Excel (por COM, con pywin32).
2. WPS Office (mismo COM que Excel).
3. LibreOffice (soffice sin ventana).

Si no hay con qué, el Excel se genera igual y la consola lo avisa.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

XL_TYPE_PDF = 0
COM_PROGRAMS = (("Excel.Application", "Microsoft Excel"), ("KET.Application", "WPS Office"),
                ("ET.Application", "WPS Office"))
LIBREOFFICE_GLOBS = (
    r"C:\Program Files\LibreOffice*\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice*\program\soffice.exe",
)


def find_libreoffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for pattern in LIBREOFFICE_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return None


class _ToolkitExporter:
    """El PDF lo dibuja el propio Toolkit (ici_render, con PyMuPDF): igual en todas las PC, con o sin
    Excel, y cada página llega hasta abajo."""
    name = "el Toolkit"
    engine = "toolkit"

    def __init__(self):
        import ici_render
        self._render = ici_render.render_workbook

    def render(self, wb, pdf: str) -> None:
        self._render(wb, pdf)

    def close(self) -> None:
        pass


class _ComExporter:
    # Medidas de columna con que se arma la versión de imprimir (ver ici_excel.Page).
    engine = "excel"
    def __init__(self, prog_id: str, name: str):
        import pythoncom
        import win32com.client

        self.name = name
        self._pythoncom = pythoncom
        pythoncom.CoInitialize()
        try:
            self.app = win32com.client.DispatchEx(prog_id)
            self.app.Visible = False
            self.app.DisplayAlerts = False
        except Exception:
            pythoncom.CoUninitialize()
            raise

    def export(self, xlsx: str, pdf: str) -> None:
        book = self.app.Workbooks.Open(os.path.abspath(xlsx), 0, True)
        try:
            try:
                self.app.CalculateFull()  # el libro trae fórmulas sin calcular
            except Exception:
                pass
            # El libro completo (todas las hojas), con la configuración de impresión de cada una.
            book.ExportAsFixedFormat(XL_TYPE_PDF, os.path.abspath(pdf))
        finally:
            book.Close(False)

    def close(self) -> None:
        try:
            self.app.Quit()
        finally:
            self._pythoncom.CoUninitialize()


class _LibreOfficeExporter:
    name = "LibreOffice"
    engine = "libreoffice"

    def __init__(self, soffice: str):
        self.soffice = soffice
        # Perfil propio: si el usuario tiene LibreOffice abierto, no choca con su sesión.
        self._profile = tempfile.TemporaryDirectory(prefix="toolkit_ici_lo_")

    def export(self, xlsx: str, pdf: str) -> None:
        with tempfile.TemporaryDirectory(prefix="toolkit_ici_pdf_") as out_dir:
            command = [
                self.soffice, f"-env:UserInstallation={Path(self._profile.name).as_uri()}",
                "--headless", "--norestore", "--convert-to", "pdf", "--outdir", out_dir, os.path.abspath(xlsx),
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(command, check=True, timeout=300, capture_output=True, creationflags=flags)
            produced = os.path.join(out_dir, Path(xlsx).with_suffix(".pdf").name)
            if not os.path.exists(produced):
                raise RuntimeError("LibreOffice no generó el PDF.")
            shutil.move(produced, pdf)

    def close(self) -> None:
        self._profile.cleanup()


def open_exporter(log=print, com_programs=COM_PROGRAMS, libreoffice=find_libreoffice, toolkit=True):
    """Quién arma el PDF: el propio Toolkit; si no pudiera (sin PyMuPDF), el primer programa de hojas de
    cálculo de la PC. None si no hay ninguno."""
    if toolkit:
        try:
            return _ToolkitExporter()
        except Exception:  # noqa: BLE001 - se prueba con los programas de la PC
            pass
    if os.name == "nt":
        for prog_id, name in com_programs:
            try:
                return _ComExporter(prog_id, name)
            except Exception:
                continue
    soffice = libreoffice()
    if soffice:
        return _LibreOfficeExporter(soffice)
    log("⚠️ No se pudo generar el PDF: la PC no tiene Microsoft Excel, WPS ni LibreOffice. "
        "El Excel se generó igual; para imprimir todas las hojas, ábralo y elija «Imprimir todo el libro».")
    return None
