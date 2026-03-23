"""
consulta_tformdet_tool.py
==========================
Herramienta: Consulta TFORMDET Avanzada
Categoría  : Reports SISMED

Encapsula toda la lógica y UI de la consulta avanzada del módulo TFORMDET
del sistema SISMED: selección de periodo(s), directorio SISMED,
opciones de fórmulas, y descarga en Excel.
Depende de: tformdet_report.TformdetManager
"""

import threading
import flet as ft
from datetime import datetime

from tformdet_report import TformdetManager
from tools.base_tool import SismedTool, ToolMetadata


class ConsultaTformdetTool(SismedTool):
    """Consulta detallada de movimientos SISMED desde archivos TFORMDET.DBF."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Consul. TFORMDET",
            descripcion="Consulta detallada de movimientos SISMED",
            icono=ft.icons.SEARCH_ROUNDED,
            color=ft.colors.BLUE_400,
            categoria="Reports SISMED",
            etiquetas=["tformdet", "consulta", "sismed", "movimientos",
                       "reporte", "dbf", "excel"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """Construye la vista completa de Consulta TFORMDET."""

        now = datetime.now()

        # ── Consola de log ────────────────────────────────────────────────────
        tformdet_log = ft.ListView(
            height=310, spacing=5, auto_scroll=True
        )

        def _log(msg):
            tformdet_log.controls.append(
                ft.Text(msg, size=13, font_family="Consolas",
                        color=ft.colors.GREEN_400)
            )
            page.update()

        # ── Manager (inicializado sin directorio; se asigna al ejecutar) ─────
        tformdet_mgr = TformdetManager("", log_callback=_log)

        # ── FilePickers ───────────────────────────────────────────────────────
        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed_dir.value = e.path
                input_sismed_dir.update()

        def _on_save_picked(e: ft.FilePickerResultEvent):
            if e.path:
                periodo_ini = f"{input_anio_ini.value}{dropdown_mes_ini.value}"
                periodo_fin = (
                    f"{input_anio_fin.value}{dropdown_mes_fin.value}"
                    if checkbox_mas_periodos.value else periodo_ini
                )

                def _process():
                    btn_run.disabled = True
                    btn_run.update()
                    success = tformdet_mgr.generate_report(
                        periodo_ini, periodo_fin, e.path,
                        incluir_formulas=checkbox_formulas.value
                    )
                    if success:
                        page.snack_bar = ft.SnackBar(
                            ft.Text("✅ Consulta exitosa! Archivo guardado.",
                                    color=ft.colors.WHITE),
                            bgcolor=ft.colors.GREEN_700
                        )
                    else:
                        page.snack_bar = ft.SnackBar(
                            ft.Text("⚠️ No se generó el archivo o no hubo resultados.",
                                    color=ft.colors.WHITE),
                            bgcolor=ft.colors.ORANGE_700
                        )
                    page.snack_bar.open = True
                    btn_run.disabled = False
                    btn_run.update()
                    page.update()

                threading.Thread(target=_process, daemon=True).start()

        dir_picker  = ft.FilePicker(on_result=_on_dir_picked)
        save_picker = ft.FilePicker(on_result=_on_save_picked)
        page.overlay.extend([dir_picker, save_picker])
        page.update()

        # ── Controles de UI ───────────────────────────────────────────────────
        saved_dir = page.client_storage.get("sismed_dir_consulta") or ""

        input_sismed_dir = ft.TextField(
            label="Ruta carpeta SISMED",
            value=saved_dir,
            hint_text="Ej: C:\\SISMED",
            expand=True, dense=True, read_only=True,
            prefix_icon=ft.icons.FOLDER,
            border_radius=4,
            border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE,
            text_size=15,
            suffix=ft.IconButton(
                icon=ft.icons.SEARCH_ROUNDED,
                on_click=lambda _: dir_picker.get_directory_path(),
                icon_size=18
            ),
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )

        meses_opciones = [
            ("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"),
            ("04", "Abril"), ("05", "Mayo"), ("06", "Junio"),
            ("07", "Julio"), ("08", "Agosto"), ("09", "Septiembre"),
            ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre"),
        ]

        dropdown_mes_ini = ft.Dropdown(
            label="Mes Inicio",
            options=[ft.dropdown.Option(k, f"{k} - {v}")
                     for k, v in meses_opciones],
            value=now.strftime("%m"), expand=1, dense=True,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.CALENDAR_MONTH,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )
        input_anio_ini = ft.TextField(
            label="Año Inicio", value=now.strftime("%Y"),
            expand=1, dense=True, border_radius=4,
            border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )
        dropdown_mes_fin = ft.Dropdown(
            label="Mes Fin",
            options=[ft.dropdown.Option(k, f"{k} - {v}")
                     for k, v in meses_opciones],
            value=now.strftime("%m"), expand=1, dense=True,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.CALENDAR_MONTH,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
            visible=False,
        )
        input_anio_fin = ft.TextField(
            label="Año Fin", value=now.strftime("%Y"),
            expand=1, dense=True, border_radius=4,
            border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
            visible=False,
        )

        checkbox_formulas = ft.Checkbox(
            label="AÑADIR COLUMNAS Y FÓRMULAS DE CÓDIGO ÚNICO",
            value=False, visible=True,
        )

        def _on_multi_periodo(e):
            show = checkbox_mas_periodos.value
            dropdown_mes_fin.visible = show
            input_anio_fin.visible   = show
            if show:
                checkbox_formulas.value   = False
                checkbox_formulas.visible = False
            else:
                checkbox_formulas.visible = True
            dropdown_mes_fin.update()
            input_anio_fin.update()
            checkbox_formulas.update()

        checkbox_mas_periodos = ft.Checkbox(
            label="Incluir rango de periodos",
            value=False,
            on_change=_on_multi_periodo,
        )

        def _run_query(e):
            if not input_sismed_dir.value:
                page.snack_bar = ft.SnackBar(
                    ft.Text("❌ Por favor, selecciona la ruta del SISMED."),
                    bgcolor=ft.colors.RED_700
                )
                page.snack_bar.open = True
                page.update()
                return

            periodo_ini = f"{input_anio_ini.value}{dropdown_mes_ini.value}"
            if checkbox_mas_periodos.value:
                periodo_fin = f"{input_anio_fin.value}{dropdown_mes_fin.value}"
                if periodo_ini > periodo_fin:
                    page.snack_bar = ft.SnackBar(
                        ft.Text("❌ El Periodo Inicial no puede ser mayor al Final.",
                                color=ft.colors.WHITE),
                        bgcolor=ft.colors.RED_700
                    )
                    page.snack_bar.open = True
                    page.update()
                    return
                file_name_out = f"TFORMDET_Consulta_{periodo_ini}_al_{periodo_fin}.xlsx"
            else:
                periodo_fin   = periodo_ini
                file_name_out = f"TFORMDET_Consulta_{periodo_ini}.xlsx"

            tformdet_mgr.sismed_dir = input_sismed_dir.value
            tformdet_log.controls.clear()

            save_picker.save_file(
                dialog_title="Guardar archivo de Consulta TFORMDET",
                file_name=file_name_out,
                allowed_extensions=["xlsx"],
            )

        btn_run = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.DOWNLOAD_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text("CONSULTAR Y DESCARGAR EXCEL", color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, size=13),
            ], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.BLUE_700,
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=4),
                padding=ft.padding.all(15),
            ),
            on_click=_run_query, height=50,
        )

        # ── Layout ────────────────────────────────────────────────────────────
        return ft.Container(
            padding=40, expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                # Cabecera Premium
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Consulta TFORMDET Avanzada",
                    "Consulta detallada de movimientos SISMED",
                    right_content=self._back_button("Volver a Reports SISMED", navigate_fn, 4)
                ),
                ft.Divider(height=8, color=ft.colors.TRANSPARENT),

                # Cuerpo: Grid Responsivo
                ft.ResponsiveRow([
                    # ── PANEL IZQUIERDO: configuración ────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 6},
                        bgcolor=ft.colors.BLUE_GREY_900,
                        border_radius=12, padding=20,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.SETTINGS_ROUNDED,
                                        color=ft.colors.BLUE_400, size=24),
                                ft.Text("Configuración de Consulta", size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.colors.WHITE),
                            ], spacing=10),
                            ft.Divider(color=ft.colors.WHITE24, height=15),

                            ft.Row([input_sismed_dir]),
                            ft.Row([checkbox_mas_periodos]),
                            ft.Row([dropdown_mes_ini, input_anio_ini],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ft.Row([dropdown_mes_fin, input_anio_fin],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ft.Row([checkbox_formulas]),
                            ft.Container(height=5),
                            ft.Row([btn_run],
                                   alignment=ft.MainAxisAlignment.CENTER),
                        ], spacing=15),
                    ),

                    # ── PANEL DERECHO: consola ──────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 6},
                        bgcolor=ft.colors.BLACK,
                        border_radius=12, padding=20,
                        height=412,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TERMINAL_ROUNDED,
                                        color=ft.colors.BLUE_400, size=22),
                                ft.Text("Consola de Consulta",
                                        color=ft.colors.WHITE, size=18,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=10),
                            ft.Divider(color=ft.colors.GREY_900, height=20),
                            tformdet_log,
                        ], spacing=10),
                    ),
                ], spacing=20),
            ]),
        )
