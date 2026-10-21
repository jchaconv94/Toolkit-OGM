"""
reporte_guias_tool.py
======================
Herramienta: Reporte de Guías SISMED
Categoría  : Reports SISMED

Encapsula toda la lógica y UI del generador de Reportes de Guías
de Ingreso / Salida del sistema SISMED.
Depende de: guia_report.GuiaReportManager
"""

import flet as ft
from datetime import datetime

import activity
from guia_report import GuiaReportManager
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import get as cfg_get, set as cfg_set


class ReporteGuiasTool(SismedTool):
    """Genera Reportes de Guías SISMED (Ingresos/Salidas) en Excel."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Reporte Guías",
            descripcion="Reportes de Guías SISMED por Fecha e Item",
            icono=ft.icons.FACT_CHECK_ROUNDED,
            color=ft.colors.AMBER_400,
            categoria="Reports SISMED",
            etiquetas=["guias", "reporte", "sismed", "ingreso",
                       "salida", "excel", "tmovim"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """Construye la vista completa del Reporte de Guías."""

        now       = datetime.now()
        first_day = now.replace(day=1)

        # ── Consola de log ────────────────────────────────────────────────────
        report_log = ft.ListView(expand=True, spacing=5, height=200)

        def _log(msg):
            report_log.controls.append(ft.Text(f"• {msg}", size=13))
            if len(report_log.controls) > 50:
                report_log.controls.pop(0)
            page.update()

        # ── DatePickers ───────────────────────────────────────────────────────
        def _on_picker_ini(e):
            if e.control.value:
                fecha_ini.value = e.control.value.strftime("%d/%m/%Y")
                fecha_ini.update()

        def _on_picker_fin(e):
            if e.control.value:
                fecha_fin.value = e.control.value.strftime("%d/%m/%Y")
                fecha_fin.update()

        datepicker_ini = ft.DatePicker(
            on_change=_on_picker_ini,
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2030, 12, 31),
        )
        datepicker_fin = ft.DatePicker(
            on_change=_on_picker_fin,
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2030, 12, 31),
        )
        page.overlay.extend([datepicker_ini, datepicker_fin])
        page.update()

        # ── Campos de fecha ───────────────────────────────────────────────────
        fecha_ini = ft.TextField(
            label="Fecha Inicio",
            value=first_day.strftime("%d/%m/%Y"),
            hint_text="DD/MM/AAAA", expand=1, dense=True,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.CALENDAR_MONTH,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )
        fecha_fin = ft.TextField(
            label="Fecha Fin",
            value=now.strftime("%d/%m/%Y"),
            hint_text="DD/MM/AAAA", expand=1, dense=True,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, text_size=15,
            prefix_icon=ft.icons.CALENDAR_MONTH,
            content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        )

        # ── Directorio SISMED ─────────────────────────────────────────────────
        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed_dir.value = e.path
                cfg_set("guias_sismed_dir", e.path)
                input_sismed_dir.update()
 
        report_dir_picker = ft.FilePicker(on_result=_on_dir_picked)
        page.overlay.append(report_dir_picker)
        page.update()
 
        input_sismed_dir = ft.TextField(
            label="Ubicación SISMED actual",
            value=cfg_get("guias_sismed_dir"),
            expand=True, dense=False, text_size=15,
            text_align=ft.TextAlign.LEFT,
            prefix_icon=ft.icons.FOLDER,
            border_radius=4, border_color=ft.colors.WHITE38,
            focused_border_color=ft.colors.WHITE, content_padding=11,
            suffix=ft.IconButton(
                icon=ft.icons.SEARCH_ROUNDED,
                on_click=lambda _: report_dir_picker.get_directory_path(),
                icon_size=18,
            ),
        )

        # ── Botones Toggle (Tipo / Modo) ──────────────────────────────────────
        tipo_selected = {"value": "S"}
        modo_selected = {"value": "det"}
        COLOR_SEL   = ft.colors.BLUE_GREY_700
        COLOR_UNSEL = ft.colors.TRANSPARENT

        def _toggle_btn(label, icon_name, key, state_dict, row_ref, rebuild_fn):
            is_sel = state_dict["value"] == key

            def _on_tap(e, k=key):
                state_dict["value"] = k
                row_ref[0].controls = rebuild_fn()
                row_ref[0].update()

            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=_on_tap, expand=True,
                content=ft.Container(
                    expand=True, height=48,
                    bgcolor=COLOR_SEL if is_sel else COLOR_UNSEL,
                    border_radius=6,
                    border=ft.border.all(
                        1,
                        ft.colors.BLUE_GREY_600 if is_sel
                        else ft.colors.BLUE_GREY_800,
                    ),
                    padding=ft.padding.symmetric(horizontal=12),
                    content=ft.Row([
                        ft.Icon(icon_name, size=17,
                                color=ft.colors.WHITE if is_sel
                                else ft.colors.GREY_500),
                        ft.Text(label, size=12,
                                weight=ft.FontWeight.W_600 if is_sel
                                else ft.FontWeight.NORMAL,
                                color=ft.colors.WHITE if is_sel
                                else ft.colors.GREY_500,
                                expand=True,
                                text_align=ft.TextAlign.CENTER),
                        ft.Icon(ft.icons.CHECK_ROUNDED, size=15,
                                color=ft.colors.WHITE if is_sel
                                else ft.colors.TRANSPARENT),
                    ], spacing=6,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
            )

        tipo_row_ref = [None]
        def _build_tipo():
            return [
                _toggle_btn("Guías de Salida (S)",  ft.icons.OUTBOX_ROUNDED,
                            "S", tipo_selected, tipo_row_ref, _build_tipo),
                ft.Container(width=4),
                _toggle_btn("Guías de Ingreso (E)", ft.icons.INBOX_ROUNDED,
                            "E", tipo_selected, tipo_row_ref, _build_tipo),
            ]
        tipo_row_widget = ft.Row(controls=_build_tipo(), spacing=0, expand=True)
        tipo_row_ref[0] = tipo_row_widget

        modo_row_ref = [None]
        def _build_modo():
            return [
                _toggle_btn("Guías detallado por lotes", ft.icons.LIST_ALT_ROUNDED,
                            "det", modo_selected, modo_row_ref, _build_modo),
                ft.Container(width=4),
                _toggle_btn("Reporte valorizado de guías", ft.icons.SUMMARIZE_ROUNDED,
                            "con", modo_selected, modo_row_ref, _build_modo),
            ]
        modo_row_widget = ft.Row(controls=_build_modo(), spacing=0, expand=True)
        modo_row_ref[0] = modo_row_widget

        chk_omitir_anulados = ft.Checkbox(
            label="Omitir guías anuladas", value=True,
            label_style=ft.TextStyle(size=12),
        )

        # ── Lógica de generación ──────────────────────────────────────────────
        def _run_report(output_path):
            try:
                d_start = datetime.strptime(fecha_ini.value, "%d/%m/%Y")
                d_end   = datetime.strptime(fecha_fin.value, "%d/%m/%Y")

                if d_start > d_end:
                    _log("❌ Error: La Fecha Inicio no puede ser posterior a la Fecha Fin.")
                    page.snack_bar = ft.SnackBar(
                        ft.Text("⚠️ Revisa el rango de fechas."),
                        bgcolor=ft.colors.AMBER_800,
                    )
                    page.snack_bar.open = True
                    page.update()
                    return

                t_mov      = tipo_selected["value"]
                is_det     = "det" in modo_selected["value"]
                omit_anul  = chk_omitir_anulados.value
                s_dir      = input_sismed_dir.value.strip()

                mgr = GuiaReportManager(s_dir, log_callback=_log)
                report_log.controls.clear()

                success = mgr.generate_report(
                    d_start, d_end, t_mov, is_det, output_path,
                    exclude_annulled=omit_anul,
                )

                if success:
                    sismed_banner = """\
  ____ ___ ____  __  __ _____ ____  
 / ___|_ _/ ___||  \\/  | ____|  _ \\ 
 \\___ \\| |\\___ \\| |\\/| |  _| | | | |
  ___) | | ___) | |  | | |___| |_| |
 |____/___|____/|_|  |_|_____|____/ """
                    report_log.controls.append(ft.Text(
                        sismed_banner, size=10, font_family="Consolas",
                        color=ft.colors.GREEN_400, weight=ft.FontWeight.W_500,
                    ))
                    page.snack_bar = ft.SnackBar(
                        ft.Text(f"✅ Reporte guardado en: {output_path}")
                    )
                    page.snack_bar.open = True
                else:
                    page.snack_bar = ft.SnackBar(
                        ft.Text("❌ Hubo un error al generar el reporte.")
                    )
                    page.snack_bar.open = True

            except ValueError:
                _log("❌ Error: Formato de fecha inválido. Use DD/MM/AAAA")
            except Exception as ex:
                _log(f"❌ Error crítico: {str(ex)}")
            page.update()

        def _on_save_result(e: ft.FilePickerResultEvent):
            if e.path:
                rp = e.path if e.path.lower().endswith(".xlsx") else f"{e.path}.xlsx"
                with activity.busy("Reporte de Guías"):
                    _run_report(rp)

        report_save_picker = ft.FilePicker(on_result=_on_save_result)
        page.overlay.append(report_save_picker)
        page.update()

        def _generar(_):
            tipo_label = "Salida" if tipo_selected["value"] == "S" else "Ingreso"
            modo_label = "por_Lote" if modo_selected["value"] == "det" else "consolidado"
            report_save_picker.save_file(
                file_name=(
                    f"Reporte_Guias_de_{tipo_label}_{modo_label}_"
                    f"{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                allowed_extensions=["xlsx"],
            )

        btn_generar = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                        color=ft.colors.WHITE, size=20),
                ft.Text("GENERAR REPORTE EN EXCEL", color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, size=13),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.GREEN_700, color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10), elevation=4,
            ),
            height=52, width=320, on_click=_generar,
        )

        # ── Layout ────────────────────────────────────────────────────────────
        return ft.Container(
            padding=ft.padding.all(20),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                # Cabecera Premium
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Reporte de Guías",
                    "Generador de Reportes de Guías SISMED (Ingresos/Salidas)",
                    right_content=self._back_button("Volver a Reports SISMED", navigate_fn, 4)
                ),
                ft.Divider(height=20, color=ft.colors.TRANSPARENT),

                # Cuerpo: Grid Responsivo
                ft.ResponsiveRow([
                    # ── PANEL IZQUIERDO: Filtros ──────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 5},
                        bgcolor=ft.colors.BLUE_GREY_900,
                        padding=ft.padding.all(30),
                        border_radius=16,
                        content=ft.Column([
                            
                            ft.Column([
                                input_sismed_dir,
                            ], spacing=6),

                            ft.Container(height=8),
                            
                            ft.Row([
                                ft.Column([
                                    fecha_ini
                                ], spacing=6, expand=True),
                                ft.Container(content=ft.Text("→", size=18, color=ft.colors.GREY_600), 
                                           margin=ft.margin.only(top=20)),
                                ft.Column([
                                    fecha_fin
                                ], spacing=6, expand=True),
                            ], spacing=12),

                            ft.Container(height=8),
                            
                            ft.Column([
                                ft.Text("Tipo de movimiento:", size=12, color=ft.colors.GREY_400),
                                tipo_row_widget,
                            ], spacing=6),
                            
                            ft.Container(height=8),
                            
                            ft.Column([
                                ft.Text("Modo de reporte:", size=12, color=ft.colors.GREY_400),
                                modo_row_widget,
                            ], spacing=6),
                            
                            ft.Row([chk_omitir_anulados], alignment=ft.MainAxisAlignment.END),
                            
                            ft.Container(height=15),
                            
                            ft.Row([btn_generar], alignment=ft.MainAxisAlignment.CENTER),
                        ], spacing=12),
                    ),

                    # ── PANEL DERECHO: Consola/Actividad ──────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 7},
                        bgcolor=ft.colors.BLACK,
                        padding=ft.padding.all(22),
                        border_radius=20, 
                        height=510,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TERMINAL_ROUNDED,
                                        color=ft.colors.GREEN_400, size=20),
                                ft.Text("Consola de Actividad",
                                        color=ft.colors.WHITE, size=16,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.GREY_900, height=20),
                            report_log,
                        ], spacing=4, expand=True),
                    ),
                ], spacing=20),
            ], spacing=0),
        )
