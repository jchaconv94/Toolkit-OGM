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
from tools.app_config import get as cfg_get, set as cfg_set

from tformdet_report import TformdetManager
from datetime import datetime

from tformdet_periods import clamp_months, last_months, single_month
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
                cfg_set("tformdet_sismed_dir", e.path)
                input_sismed_dir.update()

        def _on_save_picked(e: ft.FilePickerResultEvent):
            if e.path:
                rango = _current_range()
                if rango is None:
                    return
                periodo_ini, periodo_fin = rango.periodo_ini, rango.periodo_fin

                def _process():
                    btn_run.disabled = True
                    btn_run.update()
                    success = tformdet_mgr.generate_report(
                        periodo_ini, periodo_fin, e.path,
                        incluir_formulas=bool(checkbox_formulas.value) and rango.months == 1
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
        saved_dir = cfg_get("tformdet_sismed_dir")
 
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
                icon_size=18,
                on_click=lambda _: dir_picker.get_directory_path(),
            ),
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )

        # Periodo: un mes específico (como siempre) o, con la casilla, «los últimos N meses»
        # (tformdet_periods.py). Se recuerda lo último elegido.
        now = datetime.now()
        meses_opciones = [
            ("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"),
            ("04", "Abril"), ("05", "Mayo"), ("06", "Junio"),
            ("07", "Julio"), ("08", "Agosto"), ("09", "Septiembre"),
            ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre"),
        ]
        dropdown_mes = ft.Dropdown(
            label="Mes",
            options=[ft.dropdown.Option(k, f"{k} - {v}") for k, v in meses_opciones],
            value=now.strftime("%m"), expand=1, dense=True,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.CALENDAR_MONTH,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )
        input_anio = ft.TextField(
            label="Año", value=now.strftime("%Y"),
            expand=1, dense=True, border_radius=4,
            border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
            input_filter=ft.NumbersOnlyInputFilter(), max_length=4,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )
        checkbox_ultimos = ft.Checkbox(
            label="Descargar los últimos meses",
            value=bool(cfg_get("tformdet_use_last_months") or False),
        )
        saved_months = clamp_months(cfg_get("tformdet_last_months") or 12)
        saved_current = bool(cfg_get("tformdet_include_current") or False)

        input_meses = ft.TextField(
            value=str(saved_months), width=80, dense=True, text_align=ft.TextAlign.CENTER,
            text_size=18, border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.only(left=6, right=6, top=8, bottom=8),
        )
        checkbox_mes_actual = ft.Checkbox(
            label="Incluir el mes actual (todavía incompleto)",
            value=saved_current,
        )
        texto_rango = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        texto_periodo = ft.Text("", size=13, font_family="Consolas", color=ft.colors.WHITE60)
        texto_aviso = ft.Text("", size=13, color=ft.colors.AMBER_300, visible=False)

        checkbox_formulas = ft.Checkbox(
            label="AÑADIR COLUMNAS Y FÓRMULAS DE CÓDIGO ÚNICO",
            value=False,
        )
        fila_mes = ft.Row([dropdown_mes, input_anio],
                          alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                          vertical_alignment=ft.CrossAxisAlignment.CENTER)
        btn_menos = ft.IconButton(icon=ft.icons.REMOVE_ROUNDED, tooltip="Un mes menos",
                                  on_click=lambda _: _step(-1))
        btn_mas = ft.IconButton(icon=ft.icons.ADD_ROUNDED, tooltip="Un mes más",
                                on_click=lambda _: _step(1))
        fila_ultimos = ft.Row([
            ft.Text("Descargar los últimos", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
            btn_menos, input_meses, btn_mas,
            ft.Text("meses", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
        ], spacing=4, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        def _current_range():
            if checkbox_ultimos.value:
                return last_months(input_meses.value, bool(checkbox_mes_actual.value))
            return single_month(input_anio.value, dropdown_mes.value)

        def _refresh_range(save: bool = True):
            ultimos = bool(checkbox_ultimos.value)
            fila_mes.visible = not ultimos
            fila_ultimos.visible = ultimos
            checkbox_mes_actual.visible = ultimos
            rango = _current_range()
            if rango is None:
                texto_rango.value = "Escriba un año válido (por ejemplo, 2026)."
                texto_periodo.value = ""
                texto_aviso.visible = False
                checkbox_formulas.visible = not ultimos
                return
            texto_rango.value = rango.description()
            inicio = f"{rango.periodo_ini[4:]}/{rango.periodo_ini[:4]}"
            fin = f"{rango.periodo_fin[4:]}/{rango.periodo_fin[:4]}"
            texto_periodo.value = f"Periodo {inicio}" if rango.months == 1 else f"Periodo {inicio} – {fin}"
            texto_aviso.visible = rango.includes_current
            texto_aviso.value = "Incluye el mes actual: sus datos todavía están incompletos."
            # Las fórmulas de código único solo existen para un periodo.
            checkbox_formulas.visible = rango.months == 1
            if rango.months != 1:
                checkbox_formulas.value = False
            if save:
                cfg_set("tformdet_use_last_months", ultimos)
                if ultimos:
                    cfg_set("tformdet_last_months", rango.months)
                    cfg_set("tformdet_include_current", bool(checkbox_mes_actual.value))

        def _on_range_change(e=None):
            _refresh_range()
            page.update()

        def _on_meses_blur(e=None):
            input_meses.value = str(clamp_months(input_meses.value))
            _on_range_change()

        def _step(delta):
            input_meses.value = str(clamp_months(clamp_months(input_meses.value) + delta))
            _on_range_change()

        input_meses.on_change = _on_range_change
        input_meses.on_blur = _on_meses_blur
        input_meses.on_submit = _on_meses_blur
        checkbox_mes_actual.on_change = _on_range_change
        checkbox_ultimos.on_change = _on_range_change
        dropdown_mes.on_change = _on_range_change
        input_anio.on_change = _on_range_change

        _refresh_range(save=False)

        def _run_query(e):
            if not input_sismed_dir.value:
                page.snack_bar = ft.SnackBar(
                    ft.Text("❌ Por favor, selecciona la ruta del SISMED."),
                    bgcolor=ft.colors.RED_700
                )
                page.snack_bar.open = True
                page.update()
                return

            input_meses.value = str(clamp_months(input_meses.value))
            _refresh_range()
            rango = _current_range()
            if rango is None:
                page.snack_bar = ft.SnackBar(
                    ft.Text("❌ Escriba un año válido (por ejemplo, 2026).", color=ft.colors.WHITE),
                    bgcolor=ft.colors.RED_700
                )
                page.snack_bar.open = True
                page.update()
                return
            if rango.months == 1:
                file_name_out = f"TFORMDET_Consulta_{rango.periodo_ini}.xlsx"
            else:
                file_name_out = f"TFORMDET_Consulta_{rango.periodo_ini}_al_{rango.periodo_fin}.xlsx"

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
                            ft.Row([checkbox_ultimos]),
                            fila_mes,
                            fila_ultimos,
                            ft.Row([checkbox_mes_actual]),
                            ft.Container(
                                bgcolor=ft.colors.with_opacity(0.25, ft.colors.BLACK),
                                border_radius=8, padding=12,
                                content=ft.Column([texto_rango, texto_periodo, texto_aviso], spacing=2),
                            ),
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
