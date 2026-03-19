"""
dbf_tool.py
============
Herramienta: Convertidor DBF a Excel
Categoría  : Herramientas SISMED

Esta clase encapsula TODA la lógica y UI del convertidor DBF → XLSX.
Ya no vive en main.py. Es un Objeto independiente, reutilizable y testeable.
"""

import os
import threading
import flet as ft
import pandas as pd
from dbfread import DBF

from tools.base_tool import SismedTool, ToolMetadata


class DbfExcelTool(SismedTool):
    """Convierte archivos .dbf de SISMED al formato Excel (.xlsx)."""

    # ─── Metadata (tarjeta del Dashboard) ──────────────────────────────────────
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="DBF a EXCEL",
            descripcion="Convierte archivos .dbf a formato Excel",
            icono=ft.icons.SYNC_ROUNDED,
            color=ft.colors.TEAL_400,
            categoria="Herramientas",
            etiquetas=["dbf", "excel", "xlsx", "convertir", "herramientas"],
        )

    # ─── Vista completa ─────────────────────────────────────────────────────────
    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """Construye y devuelve la vista completa del convertidor."""

        # ── Controles de estado ───────────────────────────────────────────────
        _alert_dialog = None

        selected_file = ft.TextField(
            label="Ruta DBF origen...", read_only=True, expand=True,
            border_color=ft.colors.TEAL_400, border_radius=8,
            content_padding=15, prefix_icon=ft.icons.DATA_OBJECT_ROUNDED
        )
        save_location = ft.TextField(
            label="Ubicación de destino XLSX...", read_only=True, expand=True,
            border_color=ft.colors.TEAL_400, border_radius=8,
            content_padding=15, prefix_icon=ft.icons.FOLDER_SPECIAL_ROUNDED
        )
        result_label = ft.Text(value="", size=14, color=ft.colors.WHITE,
                               weight=ft.FontWeight.W_600)
        progress_bar = ft.ProgressBar(
            expand=True, visible=False,
            color=ft.colors.TEAL_400, bgcolor=ft.colors.WHITE24
        )

        # ── FilePicke rs ──────────────────────────────────────────────────────
        def _on_file_picked(e):
            if e.files:
                fp = e.files[0].path
                if not fp.lower().endswith(".dbf"):
                    selected_file.value = ""
                    save_location.value = ""
                    result_label.value = "Por favor, selecciona un archivo con extensión .dbf."
                    result_label.color = ft.colors.RED_400
                else:
                    selected_file.value = fp
                    save_location.value = os.path.splitext(fp)[0] + ".xlsx"
                    result_label.value = ""
            else:
                selected_file.value = ""
                save_location.value = ""
                result_label.value = "No se seleccionó ningún archivo."
                result_label.color = ft.colors.RED_400
            page.update()

        def _on_save_picked(e):
            if e.path:
                base = os.path.basename(save_location.value) if save_location.value.endswith(".xlsx") else "output.xlsx"
                save_location.value = os.path.join(e.path, base)
                result_label.value = f"Destino actualizado: {save_location.value}"
                result_label.color = ft.colors.BLUE_300
            page.update()

        file_picker = ft.FilePicker(on_result=_on_file_picked)
        save_picker = ft.FilePicker(on_result=_on_save_picked)
        page.overlay.extend([file_picker, save_picker])
        page.update()

        # ── Lógica de conversión (en hilo separado) ───────────────────────────
        def _close_alert(e):
            nonlocal _alert_dialog
            if _alert_dialog:
                _alert_dialog.open = False
                selected_file.value = ""
                save_location.value = ""
                result_label.value = ""
                progress_bar.value = 0
                page.update()

        def _convert(e):
            nonlocal _alert_dialog
            if not selected_file.value:
                result_label.value = "Por favor, selecciona un DBF primero."
                result_label.color = ft.colors.RED_400
                page.update()
                return

            def _process():
                nonlocal _alert_dialog
                btn_convert.disabled = True
                btn_pick.disabled    = True
                btn_dest.disabled    = True
                result_label.value  = "Transformando datos (puede tardar unos segundos)..."
                result_label.color  = ft.colors.AMBER_400
                progress_bar.visible = True
                progress_bar.value  = None
                page.update()

                dbf_path  = selected_file.value
                xlsx_path = save_location.value
                try:
                    table = DBF(dbf_path, encoding="latin1")
                    df    = pd.DataFrame(iter(table))
                    df.to_excel(xlsx_path, index=False, engine="openpyxl")

                    result_label.value = "✔ Conversión completada."
                    result_label.color = ft.colors.GREEN_400
                    progress_bar.value = 1
                    page.update()

                    _alert_dialog = ft.AlertDialog(
                        title=ft.Row([
                            ft.Icon(ft.icons.CHECK_CIRCLE_ROUNDED, color=ft.colors.GREEN_500),
                            ft.Text("Conversión Exitosa", weight=ft.FontWeight.W_900)
                        ]),
                        content=ft.Text(
                            f"El archivo XLSX ha sido generado en:\n\n{xlsx_path}", size=13
                        ),
                        actions=[ft.ElevatedButton("Entendido", on_click=_close_alert)],
                        open=True,
                        shape=ft.RoundedRectangleBorder(radius=16)
                    )
                    page.overlay.append(_alert_dialog)

                except PermissionError as err:
                    result_label.value = f"Error: Archivo en uso. Ciérralo primero. ({err})"
                    result_label.color = ft.colors.RED_400
                except Exception as ex:
                    result_label.value = f"Error: {str(ex)}"
                    result_label.color = ft.colors.RED_400
                finally:
                    progress_bar.visible = False
                    btn_convert.disabled = False
                    btn_pick.disabled    = False
                    btn_dest.disabled    = False
                    page.update()

            threading.Thread(target=_process, daemon=True).start()

        # ── Botones ──────────────────────────────────────────────────────────
        btn_convert = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.SAVE_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text("CONVERTIR A EXCEL", color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, size=13),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.TEAL_700,
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            height=45, width=250, on_click=_convert,
        )
        btn_pick = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.FILE_OPEN_ROUNDED, size=18, color=ft.colors.WHITE),
                ft.Text("Seleccionar DBF", weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
            ]),
            style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_700,
                                 shape=ft.RoundedRectangleBorder(radius=10)),
            height=45,
            on_click=lambda _: file_picker.pick_files(
                allow_multiple=False, allowed_extensions=["dbf"]
            ),
        )
        btn_dest = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.CREATE_NEW_FOLDER_ROUNDED, size=18, color=ft.colors.WHITE),
                ft.Text("Cambiar Destino", weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
            ]),
            style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_700,
                                 shape=ft.RoundedRectangleBorder(radius=10)),
            height=45,
            on_click=lambda _: save_picker.get_directory_path(),
        )

        # ── Layout completo ───────────────────────────────────────────────────
        return ft.Container(
            padding=40,
            expand=True,
            content=ft.Column([
                # Cabecera Premium
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Convertidor DBF a Excel",
                    "Transformación rápida de datos estructurados",
                    right_content=self._back_button("Volver a Herramientas", navigate_fn, 2)
                ),

                ft.Divider(height=10, color=ft.colors.TRANSPARENT),

                # Tarjeta de parámetros centrada horizontalmente
                ft.Row([
                    ft.Container(
                        bgcolor=ft.colors.BLUE_GREY_900,
                        padding=ft.padding.only(top=35, bottom=35, left=40, right=40),
                        border_radius=16,
                        width=800,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.SETTINGS_ROUNDED,
                                        color=ft.colors.TEAL_400, size=24),
                                ft.Text("Parámetros de Conversión", size=16,
                                        weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                            ], spacing=10),
                            ft.Divider(color=ft.colors.WHITE24, height=15),

                            ft.Text("Archivo DBF a procesar:", size=13, color=ft.colors.GREY_400),
                            ft.Row([selected_file, btn_pick], spacing=15,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),

                            ft.Container(height=10),

                            ft.Text("Ruta de salida del archivo Excel (.xlsx):", size=13,
                                    color=ft.colors.GREY_400),
                            ft.Row([save_location, btn_dest], spacing=15,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),

                            ft.Container(height=40),
                            progress_bar,
                            ft.Container(height=5),
                            ft.Row([result_label, btn_convert],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ])
                    )
                ], alignment=ft.MainAxisAlignment.CENTER),

            ], spacing=10)
        )
