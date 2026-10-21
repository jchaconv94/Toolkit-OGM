"""
consumo_valorizado_report_tool.py
=================================
Herramienta: Consumo Valorizado
Categoria  : Reports SISMED

Genera un reporte pivotado por MEDTIP con consumo valorizado por
establecimiento y periodo a partir de TFORMDET, MALMACEN y MMEDICAM.
"""

import threading
from datetime import datetime

import flet as ft

from consumo_valorizado_report_manager import ConsumoValorizadoReportManager
from tools.app_config import get as cfg_get, set as cfg_set
from tools.base_tool import SismedTool, ToolMetadata
import activity


class ConsumoValorizadoReportTool(SismedTool):
    """UI del reporte valorizado por establecimiento."""

    REPORT_UI = {
        "sis": {
            "label": "SIS",
            "icon": ft.icons.LOCAL_HOSPITAL_ROUNDED,
            "formula": "Sum([SIS]*[PRECIO])",
            "subtitle": "Calcula el consumo valorizado de atenciones SIS por periodo y establecimiento.",
        },
        "intersan": {
            "label": "Intervencion Sanitaria",
            "icon": ft.icons.HEALTH_AND_SAFETY_ROUNDED,
            "formula": "Sum([INTERSAN]*[PRECIO])",
            "subtitle": "Calcula el consumo valorizado de intervencion sanitaria por periodo y establecimiento.",
        },
        "venta": {
            "label": "Venta",
            "icon": ft.icons.POINT_OF_SALE_ROUNDED,
            "formula": "Sum([VENTA]*[PRECIO])",
            "subtitle": "Calcula el consumo valorizado de ventas por periodo y establecimiento.",
        },
    }

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Consumo Valorizado",
            descripcion="Pivot valorizado por establecimiento para SIS, intervencion y venta",
            icono=ft.icons.REQUEST_QUOTE_ROUNDED,
            color=ft.colors.CYAN_400,
            categoria="Reports SISMED",
            etiquetas=[
                "consumo",
                "valorizado",
                "sismed",
                "tformdet",
                "sis",
                "intersan",
                "venta",
                "medtip",
                "excel",
                "reporte",
            ],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        log_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)

        def _log(msg: str):
            color = (
                ft.colors.GREEN_400 if msg.startswith("✅") else
                ft.colors.RED_400 if ("✗" in msg or msg.startswith("❌")) else
                ft.colors.AMBER_400 if "⚠" in msg else
                ft.colors.CYAN_300 if msg.startswith("▶") else
                ft.colors.GREY_300
            )
            log_view.controls.append(
                ft.Text(msg, size=12, font_family="Consolas", color=color)
            )
            if len(log_view.controls) > 250:
                log_view.controls.pop(0)
            page.update()

        def _safe_update(*controls: ft.Control):
            for control in controls:
                if control is not None and getattr(control, "page", None):
                    control.update()

        report_state = {
            "sis": True,
            "intersan": False,
            "venta": False,
        }
        saved_dir = cfg_get("consumo_valorizado_sismed_dir")
        period_start_state = {
            "value": cfg_get("consumo_valorizado_period_start") or cfg_get("consumo_valorizado_period") or ""
        }
        period_end_state = {
            "value": cfg_get("consumo_valorizado_period_end") or ""
        }
        period_end_enabled = {
            "value": bool(cfg_get("consumo_valorizado_period_end_enabled"))
        }
        periods_state = {"loaded_dir": "", "values": []}

        def _selected_report_types() -> list[str]:
            return [key for key in self.REPORT_UI if report_state.get(key)]

        def _primary_report_type() -> str:
            selected = _selected_report_types()
            return selected[0] if selected else "sis"

        def _month_name(month_value: str) -> str:
            return month_value if month_value and len(month_value) == 2 else "--"

        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_dir.value = e.path
                cfg_set("consumo_valorizado_sismed_dir", e.path)
                input_dir.update()
                _load_periods_async(show_snackbar=False)

        dir_picker = ft.FilePicker(on_result=_on_dir_picked)
        page.overlay.append(dir_picker)
        page.update()

        input_dir = ft.TextField(
            value=saved_dir,
            expand=True,
            dense=True,
            text_size=13,
            border="none",
            bgcolor="transparent",
            color=ft.colors.WHITE,
            read_only=True,
            content_padding=ft.padding.only(left=8, right=8, top=0, bottom=0),
            hint_text="Seleccione la ruta SISMED...",
            hint_style=ft.TextStyle(color=ft.colors.GREY_600),
        )

        def _format_period(period: str) -> str:
            if period and len(period) == 6 and period.isdigit():
                return f"{period[:4]}-{period[4:]}"
            return period or ""

        def _split_period(period: str) -> tuple[str, str]:
            if period and len(period) == 6 and period.isdigit():
                return period[:4], period[4:]
            return "----", "--"

        def _period_sort_key(period: str) -> tuple[int, int]:
            return int(period[:4]), int(period[4:6])

        period_status = ft.Text(
            "Cargando periodos desde la ruta SISMED guardada..." if saved_dir else "Seleccione una ruta SISMED para cargar periodos reales.",
            size=11,
            color=ft.colors.GREY_500,
            visible=True,
        )

        start_year_txt = ft.Text("----", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        start_month_txt = ft.Text("--", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        end_year_txt = ft.Text("----", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        end_month_txt = ft.Text("--", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        period_end_section_ref = [None]

        def _find_period_by_month_step(current: str, step: int) -> str:
            periods = periods_state["values"]
            if not periods:
                return current

            current_period = current if current in periods else periods[-1]
            year = int(current_period[:4])
            month = int(current_period[4:6])
            min_period = periods[0]
            max_period = periods[-1]

            while True:
                month += step
                if month > 12:
                    month = 1
                    year += 1
                elif month < 1:
                    month = 12
                    year -= 1

                candidate = f"{year}{month:02d}"
                if candidate in periods:
                    return candidate
                if candidate < min_period or candidate > max_period:
                    return current_period

        def _find_period_by_year_step(current: str, step: int) -> str:
            periods = periods_state["values"]
            if not periods:
                return current

            current_period = current if current in periods else periods[-1]
            current_year = int(current_period[:4])
            current_month = current_period[4:6]
            years = sorted({int(period[:4]) for period in periods})
            candidate_years = [year for year in years if year > current_year] if step > 0 else [year for year in years if year < current_year]
            if not candidate_years:
                return current_period

            target_year = min(candidate_years) if step > 0 else max(candidate_years)
            target_periods = [period for period in periods if int(period[:4]) == target_year]
            same_month = next((period for period in target_periods if period[4:6] == current_month), None)
            if same_month:
                return same_month

            return min(
                target_periods,
                key=lambda period: abs(int(period[4:6]) - int(current_month)),
            )

        def _update_period_labels():
            if not periods_state["values"]:
                start_year_txt.value = "----"
                start_month_txt.value = "--"
                end_year_txt.value = "----"
                end_month_txt.value = "--"
                period_status.value = "Seleccione una ruta SISMED para cargar periodos reales."
                period_status.color = ft.colors.GREY_500
                period_status.visible = True
            else:
                start_year, start_month = _split_period(period_start_state["value"])
                end_year, end_month = _split_period(period_end_state["value"])
                start_year_txt.value = start_year
                start_month_txt.value = _month_name(start_month)
                end_year_txt.value = end_year
                end_month_txt.value = _month_name(end_month)
                if period_end_enabled["value"]:
                    if _period_sort_key(period_start_state["value"]) > _period_sort_key(period_end_state["value"]):
                        period_status.value = "El periodo inicial no puede ser mayor al periodo final."
                        period_status.color = ft.colors.AMBER_300
                        period_status.visible = True
                    else:
                        period_status.visible = False
                else:
                    period_status.visible = False
            _safe_update(start_year_txt, start_month_txt, end_year_txt, end_month_txt)
            _safe_update(period_status)

        def _set_period(which: str, value: str, persist: bool = True):
            target_state = period_start_state if which == "start" else period_end_state
            target_state["value"] = value
            if persist:
                if which == "start":
                    cfg_set("consumo_valorizado_period_start", value)
                    cfg_set("consumo_valorizado_period", value)
                else:
                    cfg_set("consumo_valorizado_period_end", value)
            _update_period_labels()

        def _change_period(which: str, mode: str, step: int):
            if not periods_state["values"]:
                return
            current = period_start_state["value"] if which == "start" else period_end_state["value"]
            if mode == "year":
                new_period = _find_period_by_year_step(current, step)
            else:
                new_period = _find_period_by_month_step(current, step)
            _set_period(which, new_period)

        def _period_arrow(icon_name: str, on_click):
            return ft.IconButton(
                icon_name,
                icon_size=15,
                icon_color=ft.colors.CYAN_300,
                width=22,
                height=22,
                padding=0,
                on_click=on_click,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4)),
            )

        def _build_period_card(title: str, which: str, year_txt: ft.Text, month_txt: ft.Text) -> ft.Control:
            return ft.Column([
                ft.Text(title, size=12, color=ft.colors.GREY_400),
                ft.Container(
                    height=46,
                    bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
                    border_radius=8,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_600),
                    padding=ft.padding.symmetric(horizontal=8),
                    content=ft.Row([
                        ft.Container(
                            width=94,
                            alignment=ft.alignment.center,
                            content=ft.Row([
                                _period_arrow(ft.icons.KEYBOARD_ARROW_LEFT_ROUNDED, lambda _e, w=which: _change_period(w, "year", -1)),
                                ft.Container(width=34, alignment=ft.alignment.center, content=year_txt),
                                _period_arrow(ft.icons.KEYBOARD_ARROW_RIGHT_ROUNDED, lambda _e, w=which: _change_period(w, "year", 1)),
                            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ),
                        ft.Text("/", color=ft.colors.BLUE_GREY_600, size=16),
                        ft.Container(
                            width=86,
                            alignment=ft.alignment.center,
                            content=ft.Row([
                                _period_arrow(ft.icons.KEYBOARD_ARROW_LEFT_ROUNDED, lambda _e, w=which: _change_period(w, "month", -1)),
                                ft.Container(width=28, alignment=ft.alignment.center, content=month_txt),
                                _period_arrow(ft.icons.KEYBOARD_ARROW_RIGHT_ROUNDED, lambda _e, w=which: _change_period(w, "month", 1)),
                            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ),
                    ], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                ),
            ], spacing=6)

        def _toggle_period_end(e: ft.ControlEvent):
            enabled = bool(e.control.value)
            period_end_enabled["value"] = enabled
            cfg_set("consumo_valorizado_period_end_enabled", enabled)
            if enabled and not period_end_state["value"]:
                _set_period("end", period_start_state["value"])
            period_end_section_ref[0].visible = enabled
            _safe_update(period_end_section_ref[0])
            _update_period_labels()

        period_end_checkbox = ft.Checkbox(
            label="Activar periodo fin",
            value=period_end_enabled["value"],
            active_color=ft.colors.CYAN_600,
            on_change=_toggle_period_end,
        )

        def _load_periods_async(show_snackbar: bool):
            sismed_dir = input_dir.value.strip()
            if not sismed_dir:
                periods_state["values"] = []
                period_start_state["value"] = ""
                period_end_state["value"] = ""
                _update_period_labels()
                period_status.value = "Seleccione una ruta SISMED para cargar periodos reales."
                period_status.color = ft.colors.GREY_500
                period_status.visible = True
                _safe_update(period_status)
                if show_snackbar:
                    page.snack_bar = ft.SnackBar(
                        ft.Text("⚠ Selecciona primero la ruta del SISMED."),
                        bgcolor=ft.colors.AMBER_700,
                    )
                    page.snack_bar.open = True
                    page.update()
                return

            def _process_periods():
                period_status.value = "Leyendo periodos disponibles desde TFORMDET..."
                period_status.color = ft.colors.CYAN_200
                period_status.visible = True
                _safe_update(period_status)

                mgr = ConsumoValorizadoReportManager(sismed_dir=sismed_dir, log_callback=_log)
                periods = mgr.get_available_periods()

                periods_sorted = sorted(periods)
                periods_state["values"] = periods_sorted
                if periods:
                    selected_start = (
                        period_start_state["value"] if period_start_state["value"] in periods_sorted else periods_sorted[-1]
                    )
                    selected_end = (
                        period_end_state["value"] if period_end_state["value"] in periods_sorted else selected_start
                    )
                    _set_period("start", selected_start, persist=True)
                    _set_period("end", selected_end, persist=True)
                    periods_state["loaded_dir"] = sismed_dir
                else:
                    period_start_state["value"] = ""
                    period_end_state["value"] = ""
                    period_status.value = "No se encontraron periodos validos con datos en TFORMDET."
                    period_status.color = ft.colors.AMBER_300
                    period_status.visible = True
                    periods_state["loaded_dir"] = sismed_dir
                    _update_period_labels()

                _safe_update(period_status)

                if show_snackbar:
                    page.snack_bar = ft.SnackBar(
                        ft.Text(
                            "✅ Periodos cargados correctamente." if periods
                            else "⚠ No se encontraron periodos validos."
                        ),
                        bgcolor=ft.colors.GREEN_700 if periods else ft.colors.AMBER_700,
                    )
                    page.snack_bar.open = True
                    page.update()

            activity.background("Consumo valorizado", _process_periods)

        dir_row = ft.Container(
            height=48,
            bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
            border=ft.border.all(1, ft.colors.BLUE_GREY_700),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=10),
            content=ft.Row([
                ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, size=18, color=ft.colors.CYAN_300),
                input_dir,
                ft.IconButton(
                    icon=ft.icons.DRIVE_FOLDER_UPLOAD_ROUNDED,
                    icon_color=ft.colors.CYAN_300,
                    icon_size=20,
                    tooltip="Seleccionar carpeta SISMED",
                    on_click=lambda _: dir_picker.get_directory_path(),
                ),
            ], spacing=4),
        )

        info_text = ft.Text(
            self.REPORT_UI[_primary_report_type()]["subtitle"],
            size=12,
            color=ft.colors.GREY_400,
        )
        formula_text = ft.Text(
            self.REPORT_UI[_primary_report_type()]["formula"],
            size=12,
            color=ft.colors.CYAN_200,
            font_family="Consolas",
        )

        def _update_report_info():
            selected = _selected_report_types()
            if not selected:
                formula_text.value = "Seleccione al menos un tipo de reporte."
                formula_text.color = ft.colors.AMBER_300
                info_text.value = "Debe elegir uno o más reportes para generar el Excel."
            elif len(selected) == 1:
                report_key = selected[0]
                formula_text.value = self.REPORT_UI[report_key]["formula"]
                formula_text.color = ft.colors.CYAN_200
                info_text.value = self.REPORT_UI[report_key]["subtitle"]
            else:
                include_total_summary = set(selected) == set(self.REPORT_UI)
                total_sheets = len(selected) + (1 if include_total_summary else 0)
                formula_text.value = "\n".join(self.REPORT_UI[report_key]["formula"] for report_key in selected)
                formula_text.color = ft.colors.CYAN_200
                labels = ", ".join(self.REPORT_UI[report_key]["label"] for report_key in selected)
                if include_total_summary:
                    info_text.value = (
                        f"Se generará un solo archivo con {total_sheets} hojas: "
                        + labels
                        + ", mas Resumen Total."
                    )
                else:
                    info_text.value = (
                        f"Se generará un solo archivo con {total_sheets} hojas: "
                        + labels
                        + "."
                    )
            _safe_update(info_text, formula_text)

        selector_row_ref = [None]

        def _build_report_buttons():
            return [
                ft.Container(
                    col={"sm": 12, "lg": 4},
                    content=_report_btn(self.REPORT_UI["sis"]["label"], self.REPORT_UI["sis"]["icon"], "sis"),
                ),
                ft.Container(
                    col={"sm": 12, "lg": 4},
                    content=_report_btn(self.REPORT_UI["intersan"]["label"], self.REPORT_UI["intersan"]["icon"], "intersan"),
                ),
                ft.Container(
                    col={"sm": 12, "lg": 4},
                    content=_report_btn(self.REPORT_UI["venta"]["label"], self.REPORT_UI["venta"]["icon"], "venta"),
                ),
            ]

        def _report_btn(label: str, icon_name: str, key: str) -> ft.Control:
            is_selected = bool(report_state.get(key))

            def _click(_):
                report_state[key] = not report_state[key]
                if not any(report_state.values()):
                    report_state[key] = True
                selector_row_ref[0].controls = _build_report_buttons()
                selector_row_ref[0].update()
                _update_report_info()

            return ft.Container(
                height=52,
                bgcolor=ft.colors.CYAN_700 if is_selected else ft.colors.with_opacity(0.05, ft.colors.WHITE),
                border=ft.border.all(
                    1,
                    ft.colors.CYAN_300 if is_selected else ft.colors.BLUE_GREY_700,
                ),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=14),
                on_click=_click,
                content=ft.Row([
                    ft.Icon(
                        icon_name,
                        size=18,
                        color=ft.colors.WHITE if is_selected else ft.colors.GREY_400,
                    ),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_600 if is_selected else ft.FontWeight.NORMAL,
                        color=ft.colors.WHITE if is_selected else ft.colors.GREY_300,
                        text_align=ft.TextAlign.CENTER,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Icon(
                        ft.icons.CHECK_ROUNDED,
                        size=16,
                        color=ft.colors.WHITE if is_selected else ft.colors.TRANSPARENT,
                    ),
                ], spacing=8, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )

        selector_row = ft.ResponsiveRow(
            controls=_build_report_buttons(),
            spacing=10,
            run_spacing=10,
        )
        selector_row_ref[0] = selector_row

        def _on_save(e: ft.FilePickerResultEvent):
            if not e.path:
                return

            output_path = e.path if e.path.lower().endswith(".xlsx") else f"{e.path}.xlsx"
            selected_report_types = _selected_report_types()

            def _process():
                btn_generar.disabled = True
                btn_generar.update()
                log_view.controls.clear()
                _log("▶ Preparando generacion del reporte...")

                mgr = ConsumoValorizadoReportManager(
                    sismed_dir=input_dir.value.strip(),
                    log_callback=_log,
                )
                end_period = period_end_state["value"] if period_end_enabled["value"] else None
                ok = mgr.generate(
                    output_path=output_path,
                    report_types=selected_report_types,
                    period_start=period_start_state["value"],
                    period_end=end_period,
                )

                page.snack_bar = ft.SnackBar(
                    ft.Text(
                        "✅ Reporte generado exitosamente." if ok
                        else "❌ Hubo un error al generar el reporte."
                    ),
                    bgcolor=ft.colors.GREEN_700 if ok else ft.colors.RED_700,
                )
                page.snack_bar.open = True
                btn_generar.disabled = False
                btn_generar.update()
                page.update()

            activity.background("Consumo valorizado", _process)

        save_picker = ft.FilePicker(on_result=_on_save)
        page.overlay.append(save_picker)
        page.update()

        def _open_save_dialog():
            sismed_dir = input_dir.value.strip()
            if not sismed_dir:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ Selecciona primero la ruta del SISMED."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return

            selected_report_types = _selected_report_types()
            if not selected_report_types:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ Selecciona al menos un tipo de reporte."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return

            selected_start = period_start_state["value"]
            selected_end = period_end_state["value"] if period_end_enabled["value"] else period_start_state["value"]
            if periods_state["loaded_dir"] != sismed_dir or not periods_state["values"]:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ Carga primero los periodos del SISMED seleccionado."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return

            if not selected_start:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ Selecciona un periodo valido para continuar."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return

            if period_end_enabled["value"] and (not selected_end or selected_start > selected_end):
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ El periodo inicial no puede ser mayor al periodo final."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return

            range_suffix = selected_start if selected_start == selected_end else f"{selected_start}_AL_{selected_end}"
            report_suffix = "_".join(
                ConsumoValorizadoReportManager.REPORT_TYPES[report_type]["file_label"]
                for report_type in selected_report_types
            )
            save_picker.save_file(
                dialog_title="Guardar reporte de consumo valorizado",
                file_name=f"CONSUMO_VALORIZADO_{report_suffix}_{range_suffix}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                allowed_extensions=["xlsx"],
            )

        period_start_card = _build_period_card("Periodo inicio", "start", start_year_txt, start_month_txt)
        period_end_card = _build_period_card("Periodo fin", "end", end_year_txt, end_month_txt)
        period_start_section = ft.Container(
            col={"sm": 12, "md": 6},
            content=period_start_card,
        )
        period_end_section = ft.Container(
            col={"sm": 12, "md": 6},
            content=period_end_card,
            visible=period_end_enabled["value"],
        )
        period_end_section_ref[0] = period_end_section

        btn_generar = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.DOWNLOAD_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text(
                    "GENERAR REPORTE EXCEL",
                    color=ft.colors.WHITE,
                    weight=ft.FontWeight.BOLD,
                    size=13,
                ),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.CYAN_700,
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10),
                elevation=4,
            ),
            height=52,
            on_click=lambda _: _open_save_dialog(),
        )

        view = ft.Container(
            padding=ft.padding.all(30),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    self._section_header(
                        self.metadata.icono,
                        self.metadata.color,
                        "Consumo Valorizado por EESS",
                        "Pivot por MEDTIP desde TFORMDET, MMEDICAM y MALMACEN",
                        right_content=self._back_button("Volver a Reports SISMED", navigate_fn, 4),
                    ),
                    ft.Divider(height=10, color=ft.colors.TRANSPARENT),
                    ft.ResponsiveRow([
                        ft.Container(
                            col={"sm": 12, "lg": 6, "xl": 5},
                            bgcolor=ft.colors.BLUE_GREY_900,
                            border_radius=16,
                            padding=ft.padding.all(30),
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.CYAN_300, size=22),
                                    ft.Text(
                                        "Parametros del reporte",
                                        size=15,
                                        weight=ft.FontWeight.W_700,
                                        color=ft.colors.WHITE,
                                    ),
                                ], spacing=10),
                                ft.Divider(color=ft.colors.WHITE24, height=16),
                                ft.Text("Directorio raiz SISMED:", size=12, color=ft.colors.GREY_400),
                                dir_row,
                                ft.Container(height=10),
                                ft.ResponsiveRow([period_start_section, period_end_section], spacing=12, run_spacing=12),
                                period_end_checkbox,
                                period_status,
                                ft.Container(height=10),
                                ft.Text("Tipos de reporte valorizado:", size=12, color=ft.colors.GREY_400),
                                selector_row,
                                ft.Container(height=10),
                                ft.Container(
                                    border_radius=12,
                                    bgcolor=ft.colors.with_opacity(0.05, ft.colors.CYAN_400),
                                    border=ft.border.all(1, ft.colors.with_opacity(0.2, ft.colors.CYAN_400)),
                                    padding=ft.padding.all(14),
                                    content=ft.Column([
                                        ft.Text("Consulta equivalente", size=11, color=ft.colors.GREY_400),
                                        formula_text,
                                        ft.Container(height=6),
                                        info_text,
                                        ft.Container(height=6),
                                        ft.Text(
                                            "El Excel agrupa por ANNOMES, ALMCOD y ALMDES, y crea columnas dinamicas por MEDTIP.",
                                            size=11,
                                            color=ft.colors.GREY_500,
                                        ),
                                    ], spacing=4),
                                ),
                                ft.Container(expand=True),
                                ft.Row([btn_generar], alignment=ft.MainAxisAlignment.CENTER),
                            ], spacing=8),
                        ),
                        ft.Container(
                            col={"sm": 12, "lg": 6, "xl": 7},
                            height=430,
                            bgcolor=ft.colors.BLACK,
                            border_radius=16,
                            padding=ft.padding.all(22),
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.CYAN_300, size=22),
                                    ft.Text(
                                        "Actividad y resultados",
                                        size=15,
                                        weight=ft.FontWeight.W_700,
                                        color=ft.colors.WHITE,
                                    ),
                                ], spacing=10),
                                ft.Divider(color=ft.colors.WHITE24, height=16),
                                ft.Text(
                                    "Aqui se mostrara la validacion de archivos DBF, el numero de filas exportadas y cualquier incidencia del cruce de datos.",
                                    size=12,
                                    color=ft.colors.GREY_500,
                                ),
                                ft.Container(height=8),
                                log_view,
                            ], spacing=8),
                        ),
                    ], spacing=22, run_spacing=22),
                ],
            ),
        )

        if saved_dir:
            _load_periods_async(show_snackbar=False)
        else:
            _update_period_labels()

        return view