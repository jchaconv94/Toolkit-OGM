"""
consulta_tformdet_tool.py
==========================
Herramienta: Consulta TFORMDET Avanzada
Categoría  : Reports SISMED

Encapsula toda la lógica y UI de la consulta avanzada del módulo TFORMDET
del sistema SISMED: selección de periodo(s), directorio SISMED,
opciones de fórmulas, y descarga en Excel.
Depende de: tformdet_report.TformdetManager

El diseño sigue el de Disponibilidad TFORMDET y Consumo Valorizado: campos rellenos con
etiqueta chica arriba, el periodo con flechas ‹ año › / ‹ mes ›, opciones como tarjetas y
un recuadro que dice qué se va a descargar.
"""

import threading
from datetime import datetime

import flet as ft
from tools.app_config import get as cfg_get, set as cfg_set

from tformdet_report import TformdetManager
from tformdet_periods import MESES, clamp_months, last_months, month_range, single_month
from tools.base_tool import SismedTool, ToolMetadata
import activity

ACCENT = ft.colors.BLUE_400
ACCENT_STRONG = ft.colors.BLUE_700
FIELD_BG = ft.colors.with_opacity(0.06, ft.colors.WHITE)
FIELD_BORDER = ft.colors.BLUE_GREY_700
MODOS = ("mes", "rango", "ultimos")


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
        tformdet_log = ft.ListView(expand=True, spacing=5, auto_scroll=True)

        def _log(msg):
            tformdet_log.controls.append(
                ft.Text(msg, size=13, font_family="Consolas",
                        color=ft.colors.GREEN_400)
            )
            page.update()

        # ── Manager (inicializado sin directorio; se asigna al ejecutar) ─────
        tformdet_mgr = TformdetManager("", log_callback=_log)

        # ── Helpers visuales (los mismos de Disponibilidad TFORMDET) ──────────
        def _lbl(text: str) -> ft.Text:
            return ft.Text(text, size=11, color=ft.colors.GREY_400, weight=ft.FontWeight.W_600)

        def _box(content, **kwargs) -> ft.Container:
            return ft.Container(
                content=content, height=46, bgcolor=FIELD_BG, border_radius=8,
                border=ft.border.all(1, FIELD_BORDER),
                padding=ft.padding.symmetric(horizontal=8), **kwargs,
            )

        def _arrow(icon, on_click, tooltip=None):
            return ft.IconButton(
                icon, icon_size=16, icon_color=ACCENT, width=26, height=26, padding=0,
                tooltip=tooltip, on_click=on_click,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4)),
            )

        # ── Directorio SISMED ─────────────────────────────────────────────────
        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed_dir.value = e.path
                cfg_set("tformdet_sismed_dir", e.path)
                input_sismed_dir.update()

        def _on_save_picked(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            rango, _error = _current_range()
            if rango is None:
                return
            periodo_ini, periodo_fin = rango.periodo_ini, rango.periodo_fin
            incluir_formulas = bool(checkbox_formulas.value) and rango.months == 1

            def _process():
                btn_run.disabled = True
                btn_run.update()
                success = tformdet_mgr.generate_report(
                    periodo_ini, periodo_fin, e.path, incluir_formulas=incluir_formulas
                )
                if success:
                    page.snack_bar = ft.SnackBar(
                        ft.Text("✅ Consulta exitosa! Archivo guardado.", color=ft.colors.WHITE),
                        bgcolor=ft.colors.GREEN_700
                    )
                else:
                    page.snack_bar = ft.SnackBar(
                        ft.Text("⚠️ No se generó el archivo o no hubo resultados.", color=ft.colors.WHITE),
                        bgcolor=ft.colors.ORANGE_700
                    )
                page.snack_bar.open = True
                btn_run.disabled = False
                btn_run.update()
                page.update()

            activity.background("Consulta TFORMDET", _process)

        dir_picker = ft.FilePicker(on_result=_on_dir_picked)
        save_picker = ft.FilePicker(on_result=_on_save_picked)
        page.overlay.extend([dir_picker, save_picker])
        page.update()

        input_sismed_dir = ft.TextField(
            value=cfg_get("tformdet_sismed_dir"),
            hint_text="Seleccione la carpeta SISMED…",
            expand=True, border="none", bgcolor="transparent",
            color=ft.colors.WHITE, text_size=13, read_only=True,
            content_padding=ft.padding.only(top=0, bottom=0, left=8, right=8),
            on_click=lambda _: dir_picker.get_directory_path(),
        )
        dir_row = _box(ft.Row([
            ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, size=18, color=ACCENT),
            input_sismed_dir,
            ft.IconButton(
                icon=ft.icons.DRIVE_FOLDER_UPLOAD_ROUNDED, icon_color=ACCENT, icon_size=20,
                tooltip="Seleccionar carpeta SISMED",
                on_click=lambda _: dir_picker.get_directory_path(),
            ),
        ], spacing=4), expand=True)

        # ── Periodo: tres formas (tformdet_periods.py) ────────────────────────
        # Un mes (por defecto, como siempre), un rango de un mes a otro, o «los últimos N
        # meses». Se recuerda la forma elegida y el número de meses.
        now = datetime.now()
        saved_mode = cfg_get("tformdet_period_mode")
        modo = [saved_mode if saved_mode in MODOS else "mes"]

        # El mes es una lista y el año un campo de texto (sirve para cualquier año, también
        # los que vengan), con el mismo estilo relleno de los demás campos.

        def _lista(options, value, width, on_pick):
            return ft.Dropdown(
                options=options, value=value, width=width,
                filled=True, fill_color=FIELD_BG, bgcolor=ft.colors.BLUE_GREY_900,
                border_color=FIELD_BORDER, focused_border_color=ACCENT, border_radius=8,
                text_size=14, color=ft.colors.WHITE, menu_height=320,
                content_padding=ft.padding.symmetric(horizontal=12, vertical=10),
                on_change=on_pick,
            )

        def _period_picker(state: dict):
            def _pick_month(e):
                state["m"] = int(e.control.value)
                _on_range_change()

            def _type_year(e):
                # Se guarda tal cual: un año a medio escribir lo marca el resumen como no válido.
                state["y"] = (e.control.value or "").strip()
                _on_range_change()

            mes = _lista([ft.dropdown.Option(str(i), nombre) for i, nombre in enumerate(MESES, start=1)],
                         str(state["m"]), 150, _pick_month)
            anio = ft.TextField(
                value=str(state["y"]), width=90, hint_text="Año",
                filled=True, fill_color=FIELD_BG, border_color=FIELD_BORDER,
                focused_border_color=ACCENT, border_radius=8,
                text_size=14, color=ft.colors.WHITE, text_align=ft.TextAlign.CENTER,
                keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
                content_padding=ft.padding.symmetric(horizontal=10, vertical=14),
                on_change=_type_year,
            )
            return ft.Row([mes, anio], spacing=8, tight=True,
                          vertical_alignment=ft.CrossAxisAlignment.CENTER)

        inicio = {"y": now.year, "m": now.month}
        fin = {"y": now.year, "m": now.month}
        picker_inicio = _period_picker(inicio)
        picker_fin = _period_picker(fin)
        lbl_inicio = _lbl("Periodo")

        # «Últimos meses»: cantidad con − / + y si entra el mes actual.
        input_meses = ft.TextField(
            value=str(clamp_months(cfg_get("tformdet_last_months") or 12)),
            width=46, border="none", bgcolor="transparent", text_align=ft.TextAlign.CENTER,
            color=ft.colors.WHITE, text_size=15, keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.only(top=0, bottom=0),
        )
        meses_box = _box(ft.Row([
            _arrow(ft.icons.REMOVE_ROUNDED, lambda _: _step(-1), "Un mes menos"),
            input_meses,
            _arrow(ft.icons.ADD_ROUNDED, lambda _: _step(1), "Un mes más"),
        ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, tight=True), width=150)
        checkbox_mes_actual = ft.Checkbox(
            label="Incluir el mes actual",
            label_style=ft.TextStyle(size=13, color=ft.colors.GREY_300),
            tooltip="El mes actual todavía no termina: sus datos están incompletos.",
            value=bool(cfg_get("tformdet_include_current") or False),
        )

        fila_mes_rango = ft.Row([
            ft.Column([lbl_inicio, picker_inicio], spacing=6),
            ft.Icon(ft.icons.ARROW_FORWARD_ROUNDED, color=ft.colors.GREY_500, size=18),
            ft.Column([_lbl("Hasta"), picker_fin], spacing=6),
        ], spacing=14, wrap=True, vertical_alignment=ft.CrossAxisAlignment.END)
        flecha_rango = fila_mes_rango.controls[1]
        columna_fin = fila_mes_rango.controls[2]

        fila_ultimos = ft.Row([
            ft.Column([_lbl("Cantidad de meses"), meses_box], spacing=6),
            checkbox_mes_actual,
        ], spacing=18, vertical_alignment=ft.CrossAxisAlignment.END)

        # ── Tarjetas de forma (como «Tipo de Reporte» de Disponibilidad) ──────
        tarjetas = {}

        def _tarjeta(label: str, icon_name: str, key: str) -> ft.Container:
            icono = ft.Icon(icon_name, size=16)
            texto = ft.Text(label, size=12)
            tarjeta = ft.Container(
                height=46, border_radius=10, expand=1,
                on_click=lambda _, k=key: _set_mode(k),
                content=ft.Row([icono, texto], spacing=6, alignment=ft.MainAxisAlignment.CENTER,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            tarjetas[key] = (tarjeta, icono, texto)
            return tarjeta

        fila_tarjetas = ft.Row([
            _tarjeta("Un mes", ft.icons.CALENDAR_TODAY_ROUNDED, "mes"),
            _tarjeta("Rango de meses", ft.icons.DATE_RANGE_ROUNDED, "rango"),
            _tarjeta("Últimos meses", ft.icons.HISTORY_ROUNDED, "ultimos"),
        ], spacing=10)

        def _paint_cards():
            for key, (tarjeta, icono, texto) in tarjetas.items():
                elegida = key == modo[0]
                tarjeta.bgcolor = ACCENT_STRONG if elegida else FIELD_BG
                tarjeta.border = ft.border.all(1, ACCENT if elegida else FIELD_BORDER)
                icono.color = ft.colors.WHITE if elegida else ft.colors.GREY_500
                texto.color = ft.colors.WHITE if elegida else ft.colors.GREY_400
                texto.weight = ft.FontWeight.W_600 if elegida else ft.FontWeight.NORMAL

        # ── Qué se va a descargar ─────────────────────────────────────────────
        texto_rango = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        texto_periodo = ft.Text("", size=12, font_family="Consolas", color=ft.colors.BLUE_100)
        texto_aviso = ft.Text("", size=11, color=ft.colors.AMBER_300, visible=False)
        icono_resumen = ft.Icon(ft.icons.EVENT_NOTE_ROUNDED, size=22, color=ACCENT)
        resumen = ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            bgcolor=ft.colors.with_opacity(0.08, ACCENT),
            border=ft.border.all(1, ft.colors.with_opacity(0.25, ACCENT)),
            border_radius=10,
            content=ft.Row([
                icono_resumen,
                ft.Column([
                    ft.Text("Se descargará", size=11, color=ft.colors.GREY_400),
                    ft.Row([texto_rango, texto_periodo], spacing=10, wrap=True,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    texto_aviso,
                ], spacing=1, tight=True, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

        checkbox_formulas = ft.Checkbox(
            label="Añadir columnas y fórmulas de código único",
            label_style=ft.TextStyle(size=13, color=ft.colors.GREY_300),
            value=False,
        )

        def _current_range():
            """(rango, mensaje de error) según la forma elegida."""
            if modo[0] == "ultimos":
                return last_months(input_meses.value, bool(checkbox_mes_actual.value)), ""
            if modo[0] == "rango":
                return month_range(inicio["y"], inicio["m"], fin["y"], fin["m"])
            rango = single_month(inicio["y"], inicio["m"])
            return rango, "" if rango else "Escriba un año válido (por ejemplo, 2026)."

        def _refresh_range(save: bool = True):
            actual = modo[0]
            _paint_cards()
            fila_mes_rango.visible = actual in ("mes", "rango")
            flecha_rango.visible = columna_fin.visible = actual == "rango"
            lbl_inicio.value = "Desde" if actual == "rango" else "Periodo"
            fila_ultimos.visible = actual == "ultimos"

            rango, error = _current_range()
            if rango is None:
                texto_rango.value = error
                texto_periodo.value = ""
                texto_aviso.visible = False
                icono_resumen.name = ft.icons.ERROR_OUTLINE_ROUNDED
                icono_resumen.color = ft.colors.RED_300
            else:
                texto_rango.value = rango.short_description()
                texto_periodo.value = rango.period_codes()
                texto_aviso.visible = rango.includes_current
                texto_aviso.value = "⚠ Incluye el mes actual: sus datos todavía están incompletos."
                icono_resumen.name = ft.icons.EVENT_NOTE_ROUNDED
                icono_resumen.color = ACCENT
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

        def _set_mode(key):
            if key in MODOS:
                modo[0] = key
                _on_range_change()

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
                        weight=ft.FontWeight.BOLD, size=14),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ACCENT_STRONG,
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10),
                elevation=4,
            ),
            height=52,
            on_click=_run_query,
        )

        # ── Layout (como Disponibilidad TFORMDET) ─────────────────────────────
        return ft.Container(
            padding=ft.padding.all(28),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                controls=[
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Consulta TFORMDET Avanzada",
                    "Consulta detallada de movimientos SISMED",
                    right_content=self._back_button("Volver a Reports SISMED", navigate_fn, 4)
                ),
                ft.Container(height=14),

                ft.ResponsiveRow([
                    # ── PANEL IZQUIERDO: configuración ────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 7},
                        bgcolor=ft.colors.BLUE_GREY_900,
                        border_radius=16,
                        padding=ft.padding.all(26),
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TUNE_ROUNDED, color=ACCENT, size=20),
                                ft.Text("Configuración de Consulta", size=15,
                                        weight=ft.FontWeight.W_700, color=ft.colors.WHITE),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.WHITE12, height=12),

                            ft.Column([_lbl("Directorio raíz SISMED:"), ft.Row([dir_row])], spacing=6),
                            ft.Container(height=4),
                            ft.Column([_lbl("Periodo a descargar:"), fila_tarjetas], spacing=6),
                            fila_mes_rango,
                            fila_ultimos,
                            ft.Container(height=2),
                            resumen,
                            checkbox_formulas,
                            ft.Container(height=6),
                            ft.Row([
                                ft.Container(content=btn_run, width=360, alignment=ft.alignment.center)
                            ], alignment=ft.MainAxisAlignment.CENTER),
                        ], spacing=12),
                    ),

                    # ── PANEL DERECHO: consola ────────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 5},
                        height=584,  # la altura del panel de configuración
                        bgcolor=ft.colors.BLACK87,
                        border_radius=16,
                        border=ft.border.all(1, ft.colors.BLUE_GREY_800),
                        padding=ft.padding.all(20),
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ACCENT, size=18),
                                ft.Text("Consola de Consulta", color=ft.colors.GREY_300, size=14,
                                        weight=ft.FontWeight.W_700),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.BLUE_GREY_800, height=10),
                            tformdet_log,
                        ], spacing=4, expand=True),
                    ),
                ]),
            ]),
        )
