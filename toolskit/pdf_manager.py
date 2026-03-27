"""
pdf_manager.py
==============
Lógica de negocio para todas las operaciones PDF del ToolKit SISMED.
Librerías: PyPDF2, pdf2docx, python-docx, Pillow

Operaciones disponibles:
  - pdf_to_word        → PDF  → .docx
  - pdf_to_excel       → PDF  → .xlsx (tablas extraídas)
  - pdf_to_images      → PDF  → carpeta de JPGs
  - merge_pdfs         → N × PDF → 1 PDF
  - split_pdf          → 1 PDF → N PDFs (por rangos)
  - reorder_pages      → 1 PDF → 1 PDF (páginas reordenadas)
  - extract_pages      → 1 PDF → 1 PDF (páginas seleccionadas)
"""

import os
import re
import threading
from pathlib import Path
from typing import List, Tuple, Callable


class PdfManager:

    # ──────────────────────────────────────────────────────────────────────────
    # PDF → WORD
    # ──────────────────────────────────────────────────────────────────────────
    def pdf_to_word(self, pdf_path: str, output_path: str,
                    progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            from pdf2docx import Converter
            progress_cb and progress_cb(0.05, "Iniciando conversion editable a Word...")
            cv = Converter(pdf_path)
            progress_cb and progress_cb(0.20, "Analizando paginas del PDF...")
            cv.convert(output_path, start=0, end=None)
            cv.close()
            progress_cb and progress_cb(1.0, "✅ Word editable generado")
            return True, output_path
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # PDF → EXCEL (extrae tablas con PyMuPDF o cae en texto tabulado)
    # ──────────────────────────────────────────────────────────────────────────
    def pdf_to_excel(self, pdf_path: str, output_path: str,
                     progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            import fitz  # PyMuPDF
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            progress_cb and progress_cb(0.05, "Abriendo PDF...")
            doc = fitz.open(pdf_path)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "PDF Data"

            header_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)

            current_row = 1
            total_pages = len(doc)

            for page_num, page in enumerate(doc):
                progress_cb and progress_cb(
                    0.1 + 0.8 * (page_num / total_pages),
                    f"Procesando página {page_num + 1}/{total_pages}..."
                )
                # Encabezado de página
                cell = ws.cell(row=current_row, column=1, value=f"── Página {page_num + 1} ──")
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
                ws.merge_cells(start_row=current_row, start_column=1,
                               end_row=current_row, end_column=5)
                current_row += 1

                # Extraer tablas
                tables = page.find_tables()
                if tables.tables:
                    for table in tables.tables:
                        data = table.extract()
                        for row_data in data:
                            for col_idx, cell_val in enumerate(row_data):
                                ws.cell(row=current_row, column=col_idx + 1,
                                        value=cell_val or "")
                            current_row += 1
                        current_row += 1
                else:
                    # Sin tablas: volcado de texto
                    text = page.get_text("text")
                    for line in text.splitlines():
                        if line.strip():
                            ws.cell(row=current_row, column=1, value=line.strip())
                            current_row += 1

                current_row += 1

            # Ajustar anchos
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        max_len = max(max_len, len(str(cell.value or "")))
                    except Exception:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 4, 60)

            wb.save(output_path)
            doc.close()
            progress_cb and progress_cb(1.0, "✅ Excel generado")
            return True, output_path
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # PDF → IMÁGENES JPG
    # ──────────────────────────────────────────────────────────────────────────
    def pdf_to_images(self, pdf_path: str, output_dir: str, dpi: int = 150,
                      progress_cb: Callable[[float, str], None] = None,
                      page_indices: List[int] = None) -> Tuple[bool, str]:
        """Convierte páginas del PDF a imágenes JPG.

        page_indices: lista de índices 0-based a exportar; None = todas.
        """
        try:
            import fitz
            os.makedirs(output_dir, exist_ok=True)
            doc = fitz.open(pdf_path)
            indices = page_indices if page_indices is not None else list(range(len(doc)))
            total   = len(indices)
            zoom    = dpi / 72
            mat     = fitz.Matrix(zoom, zoom)

            for n, idx in enumerate(indices):
                progress_cb and progress_cb(
                    (n + 1) / total,
                    f"Convirtiendo página {idx + 1} ({n + 1}/{total})..."
                )
                pix      = doc[idx].get_pixmap(matrix=mat)
                img_path = os.path.join(output_dir, f"pagina_{n + 1:03d}.jpg")
                pix.save(img_path)

            doc.close()
            progress_cb and progress_cb(1.0, f"✅ {total} imágenes guardadas")
            return True, output_dir
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # UNIR PDFs
    # ──────────────────────────────────────────────────────────────────────────
    def merge_pdfs(self, pdf_paths: List[str], output_path: str,
                   progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            import PyPDF2
            writer = PyPDF2.PdfWriter()
            total = len(pdf_paths)

            for i, path in enumerate(pdf_paths):
                progress_cb and progress_cb(
                    (i + 1) / total,
                    f"Agregando {os.path.basename(path)} ({i + 1}/{total})..."
                )
                reader = PyPDF2.PdfReader(path)
                for page in reader.pages:
                    writer.add_page(page)

            with open(output_path, "wb") as f:
                writer.write(f)

            progress_cb and progress_cb(1.0, f"✅ PDF unido guardado: {os.path.basename(output_path)}")
            return True, output_path
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # DIVIDIR PDF (por rango de páginas, ej: "1-3, 4-6, 7")
    # ──────────────────────────────────────────────────────────────────────────
    def split_pdf(self, pdf_path: str, output_dir: str, ranges_str: str,
                  progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            import PyPDF2
            os.makedirs(output_dir, exist_ok=True)
            reader = PyPDF2.PdfReader(pdf_path)
            total_pages = len(reader.pages)
            base_name = Path(pdf_path).stem

            ranges = self._parse_ranges(ranges_str, total_pages)
            if not ranges:
                return False, "Rango inválido. Use formato: 1-3, 4-6, 7"

            for idx, (start, end) in enumerate(ranges):
                progress_cb and progress_cb(
                    (idx + 1) / len(ranges),
                    f"Generando parte {idx + 1}/{len(ranges)} (pág. {start}-{end})..."
                )
                writer = PyPDF2.PdfWriter()
                for p in range(start - 1, end):
                    writer.add_page(reader.pages[p])
                out_file = os.path.join(output_dir, f"{base_name}_parte{idx + 1:02d}.pdf")
                with open(out_file, "wb") as f:
                    writer.write(f)

            progress_cb and progress_cb(1.0, f"✅ {len(ranges)} archivos creados en {output_dir}")
            return True, output_dir
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # REORDENAR PÁGINAS (ej: "3,1,2,4" o "4,3,2,1")
    # ──────────────────────────────────────────────────────────────────────────
    def reorder_pages(self, pdf_path: str, output_path: str, order_str: str,
                      progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(pdf_path)
            total = len(reader.pages)

            order = [int(x.strip()) for x in order_str.split(",") if x.strip().isdigit()]
            if not order:
                return False, "Orden inválido. Use números separados por comas: 3,1,2,4"
            if max(order) > total or min(order) < 1:
                return False, f"El PDF tiene {total} páginas. Verifique los números."

            writer = PyPDF2.PdfWriter()
            for i, page_num in enumerate(order):
                progress_cb and progress_cb((i + 1) / len(order), f"Ordenando página {page_num}...")
                writer.add_page(reader.pages[page_num - 1])

            with open(output_path, "wb") as f:
                writer.write(f)

            progress_cb and progress_cb(1.0, "✅ PDF reordenado guardado")
            return True, output_path
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # EXTRAER PÁGINAS (ej: "1,3,5-7")
    # ──────────────────────────────────────────────────────────────────────────
    def extract_pages(self, pdf_path: str, output_path: str, pages_str: str,
                      progress_cb: Callable[[float, str], None] = None) -> Tuple[bool, str]:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(pdf_path)
            total = len(reader.pages)

            pages = self._parse_page_list(pages_str, total)
            if not pages:
                return False, "Páginas inválidas. Use: 1,3,5-7"

            writer = PyPDF2.PdfWriter()
            for i, p in enumerate(pages):
                progress_cb and progress_cb((i + 1) / len(pages), f"Extrayendo página {p}...")
                writer.add_page(reader.pages[p - 1])

            with open(output_path, "wb") as f:
                writer.write(f)

            progress_cb and progress_cb(1.0, f"✅ {len(pages)} páginas extraídas")
            return True, output_path
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────────────
    # UTILIDADES INTERNAS
    # ──────────────────────────────────────────────────────────────────────────
    def get_page_count(self, pdf_path: str) -> int:
        try:
            import PyPDF2
            r = PyPDF2.PdfReader(pdf_path)
            return len(r.pages)
        except Exception:
            return 0

    def _parse_ranges(self, ranges_str: str, total: int) -> List[Tuple[int, int]]:
        result = []
        for part in ranges_str.split(","):
            part = part.strip()
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
            if m:
                s, e = int(m.group(1)), int(m.group(2))
                if 1 <= s <= e <= total:
                    result.append((s, e))
            elif part.isdigit():
                p = int(part)
                if 1 <= p <= total:
                    result.append((p, p))
        return result

    def _parse_page_list(self, pages_str: str, total: int) -> List[int]:
        pages = set()
        for part in pages_str.split(","):
            part = part.strip()
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
            if m:
                s, e = int(m.group(1)), int(m.group(2))
                for p in range(s, e + 1):
                    if 1 <= p <= total:
                        pages.add(p)
            elif part.isdigit():
                p = int(part)
                if 1 <= p <= total:
                    pages.add(p)
        return sorted(pages)
