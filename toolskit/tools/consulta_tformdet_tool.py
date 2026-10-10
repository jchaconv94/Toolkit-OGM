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

import json
import threading
import flet as ft
from tools.app_config import get as cfg_get, set as cfg_set

from tformdet_report import TformdetManager
from datetime import datetime

from tformdet_periods import clamp_months, last_months, month_range, single_month
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
            expand=True, spacing=5, auto_scroll=True
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
                rango, _error = _current_range()
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

        # Periodo, tres formas (tformdet_periods.py): un mes (por defecto, como siempre), un
        # rango de un mes a otro, o «los últimos N meses». Se recuerda lo último elegido.
        now = datetime.now()
        meses_opciones = [
            ("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"),
            ("04", "Abril"), ("05", "Mayo"), ("06", "Junio"),
            ("07", "Julio"), ("08", "Agosto"), ("09", "Septiembre"),
            ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre"),
        ]
        campo = dict(
            dense=True, border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )

        def _dropdown_mes():
            return ft.Dropdown(
                label="Mes",
                options=[ft.dropdown.Option(k, f"{k} - {v}") for k, v in meses_opciones],
                # Flet 0.27 no estira el Dropdown (expand no tiene efecto): ancho fijo.
                value=now.strftime("%m"), width=230,
                prefix_icon=ft.icons.CALENDAR_MONTH, **campo,
            )

        def _input_anio():
            # El año ocupa el resto de la fila, así los bordes quedan alineados.
            return ft.TextField(
                label="Año", value=now.strftime("%Y"), expand=True,
                prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
                input_filter=ft.NumbersOnlyInputFilter(),
                # Misma altura que el Dropdown del mes, que en Flet 0.27 es más alto.
                **{**campo, "content_padding": ft.padding.only(left=10, right=10, top=13, bottom=13)},
            )

        # En «Un mes» se usan solo los de inicio; en «Rango», también los de fin.
        dropdown_mes_ini, input_anio_ini = _dropdown_mes(), _input_anio()
        dropdown_mes_fin, input_anio_fin = _dropdown_mes(), _input_anio()
        etiqueta_desde = ft.Text("Desde", size=13, color=ft.colors.WHITE70, width=44)
        etiqueta_hasta = ft.Text("Hasta", size=13, color=ft.colors.WHITE70, width=44)

        MODOS = ("mes", "rango", "ultimos")
        saved_mode = cfg_get("tformdet_period_mode")
        modo = [saved_mode if saved_mode in MODOS else "mes"]
        selector_modo = ft.SegmentedButton(
            segments=[
                ft.Segment(value="mes", label=ft.Text("Un mes")),
                ft.Segment(value="rango", label=ft.Text("Rango")),
                ft.Segment(value="ultimos", label=ft.Text("Últimos meses")),
            ],
            selected={modo[0]},
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=True,
            expand=True,
        )

        saved_months = clamp_months(cfg_get("tformdet_last_months") or 12)
        input_meses = ft.TextField(
            value=str(saved_months), width=56, text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            **{**campo, "text_size": 17,
               "content_padding": ft.padding.only(left=4, right=4, top=8, bottom=8)},
        )
        checkbox_mes_actual = ft.Checkbox(
            label="Incluir mes actual",
            label_style=ft.TextStyle(size=13),
            tooltip="El mes actual todavía no termina: sus datos están incompletos.",
            value=bool(cfg_get("tformdet_include_current") or False),
        )
        texto_rango = ft.Text("", size=15, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        texto_periodo = ft.Text("", size=13, font_family="Consolas", color=ft.colors.WHITE60)
        texto_aviso = ft.Text("", size=12, color=ft.colors.AMBER_300, visible=False)

        checkbox_formulas = ft.Checkbox(
            label="Añadir columnas y fórmulas de código único",
            label_style=ft.TextStyle(size=13),
            value=False,
        )
        fila_inicio = ft.Row([etiqueta_desde, dropdown_mes_ini, input_anio_ini],
                             spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        fila_fin = ft.Row([etiqueta_hasta, dropdown_mes_fin, input_anio_fin],
                          spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        btn_menos = ft.IconButton(icon=ft.icons.REMOVE_ROUNDED, tooltip="Un mes menos",
                                  icon_size=18, on_click=lambda _: _step(-1))
        btn_mas = ft.IconButton(icon=ft.icons.ADD_ROUNDED, tooltip="Un mes más",
                                icon_size=18, on_click=lambda _: _step(1))
        fila_ultimos = ft.Row([
            ft.Text("Los últimos", size=15, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
            btn_menos, input_meses, btn_mas,
            ft.Text("meses", size=15, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
            ft.Container(expand=True),
            checkbox_mes_actual,
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        resumen = ft.Container(
            expand=True,
            bgcolor=ft.colors.with_opacity(0.25, ft.colors.BLACK),
            border_radius=8,
            padding=ft.padding.symmetric(vertical=8, horizontal=12),
            content=ft.Column([
                ft.Row([texto_rango, texto_periodo], spacing=10, wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                texto_aviso,
            ], spacing=2, tight=True),
        )

        def _current_range():
            """(rango, mensaje de error) según la forma elegida."""
            if modo[0] == "ultimos":
                return last_months(input_meses.value, bool(checkbox_mes_actual.value)), ""
            if modo[0] == "rango":
                return month_range(input_anio_ini.value, dropdown_mes_ini.value,
                                   input_anio_fin.value, dropdown_mes_fin.value)
            rango = single_month(input_anio_ini.value, dropdown_mes_ini.value)
            return rango, "" if rango else "Escriba un año válido (por ejemplo, 2026)."

        def _refresh_range(save: bool = True):
            actual = modo[0]
            fila_inicio.visible = actual in ("mes", "rango")
            fila_fin.visible = actual == "rango"
            etiqueta_desde.visible = actual == "rango"
            fila_ultimos.visible = actual == "ultimos"

            rango, error = _current_range()
            if rango is None:
                texto_rango.value = error
                texto_periodo.value = ""
                texto_aviso.visible = False
            else:
                texto_rango.value = rango.short_description()
                texto_periodo.value = rango.period_codes()
                texto_aviso.visible = rango.includes_current
                texto_aviso.value = "⚠ Incluye el mes actual: sus datos todavía están incompletos."
            texto_periodo.visible = bool(texto_periodo.value)

            # Las fórmulas de código único solo existen para un periodo, como antes.
            un_mes = rango is not None and rango.months == 1
            checkbox_formulas.visible = un_mes
            if not un_mes:
                checkbox_formulas.value = False
            if save:
                cfg_set("tformdet_period_mode", actual)
                if actual == "ultimos":
                    cfg_set("tformdet_last_months", clamp_months(input_meses.value))
                    cfg_set("tformdet_include_current", bool(checkbox_mes_actual.value))

        def _on_range_change(e=None):
            _refresh_range()
            page.update()

        def _on_mode_change(e=None):
            # El evento trae la lista elegida en JSON («["rango"]»); si no, se lee del control.
            elegido = None
            try:
                datos = json.loads(e.data) if e is not None and e.data else []
                elegido = datos[0] if datos else None
            except Exception:
                elegido = None
            if elegido not in MODOS:
                seleccion = list(selector_modo.selected or [])
                elegido = seleccion[0] if seleccion and seleccion[0] in MODOS else modo[0]
            modo[0] = elegido
            selector_modo.selected = {elegido}
            _on_range_change()

        def _on_meses_blur(e=None):
            input_meses.value = str(clamp_months(input_meses.value))
            _on_range_change()

        def _step(delta):
            input_meses.value = str(clamp_months(clamp_months(input_meses.value) + delta))
            _on_range_change()

        selector_modo.on_change = _on_mode_change
        input_meses.on_change = _on_range_change
        input_meses.on_blur = _on_meses_blur
        input_meses.on_submit = _on_meses_blur
        for control in (checkbox_mes_actual, dropdown_mes_ini, input_anio_ini,
                        dropdown_mes_fin, input_anio_fin):
            control.on_change = _on_range_change

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
            rango, error = _current_range()
            if rango is None:
                page.snack_bar = ft.SnackBar(
                    ft.Text(f"❌ {error}", color=ft.colors.WHITE),
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
        # Los dos paneles con la misma altura; el botón queda siempre abajo.
        PANEL_HEIGHT = 480
        btn_run.expand = True
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
                        height=PANEL_HEIGHT,
                        content=ft.Column([
                            ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.SETTINGS_ROUNDED,
                                            color=ft.colors.BLUE_400, size=24),
                                    ft.Text("Configuración de Consulta", size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.colors.WHITE),
                                ], spacing=10),
                                ft.Divider(color=ft.colors.WHITE24, height=8),
                                ft.Row([input_sismed_dir]),
                                ft.Row([selector_modo]),
                                fila_inicio,
                                fila_fin,
                                fila_ultimos,
                            ], spacing=12),
                            # Abajo, el resultado y la acción: qué se va a descargar y el botón.
                            ft.Column([
                                ft.Row([resumen]),
                                checkbox_formulas,
                                ft.Row([btn_run]),
                            ], spacing=10),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ),

                    # ── PANEL DERECHO: consola ──────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 6},
                        bgcolor=ft.colors.BLACK,
                        border_radius=12, padding=20,
                        height=PANEL_HEIGHT,
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
