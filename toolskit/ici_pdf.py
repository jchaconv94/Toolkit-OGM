"""Generar ICI: el mismo libro en PDF, con todas sus hojas, listo para imprimir.

Si solo se entrega el Excel, se imprime la hoja que está abierta y las demás se quedan
(pedido del usuario del 2026-10-19). El PDF lo arma el programa de hojas de cálculo que
tenga la PC, que respeta lo que el libro ya trae para imprimir (horizontal, a una hoja de
ancho, encabezado de columnas en cada página) y calcula las fórmulas:

1. Microsoft Excel (por COM, con pywin32).
2. WPS Office (mismo COM que Excel).
3. LibreOffice (soffice sin ventana).

Se abre un solo programa para todos los libros de una tanda. Si no hay ninguno, el Excel se
genera igual y la consola lo avisa.
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


class _ComExporter:
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


def open_exporter(log=print, com_programs=COM_PROGRAMS, libreoffice=find_libreoffice):
    """El primer programa disponible para pasar a PDF, o None si la PC no tiene ninguno."""
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
