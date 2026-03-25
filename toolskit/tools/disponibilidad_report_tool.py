"""
disponibilidad_report_tool.py
==============================
Herramienta: Reporte de Disponibilidad TFORMDET
Categoría  : Reports SISMED

Genera reportes PIVOT de consumo + stock + precio desde TFORMDET,
similar a las consultas TRANSFORM de Access.

5 configuraciones:
  1. Por Farmacias (código completo)
  2. Por IPRESS    (consolida Fxx del mismo establecimiento)
  3. Excluir EESS  (filtrar por códigos a excluir)
  4. Por Red       (consolida todo por RED, sin desglosar EESS)
  5. Meses         (N meses hacia atrás; default 12)

Hereda de: tools.base_tool.SismedTool
"""

import threading
import flet as ft
from datetime import date

from disponibilidad_report_manager import DisponibilidadReportManager
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import get as cfg_get, set as cfg_set


class DisponibilidadReportTool(SismedTool):
    """Genera reportes de disponibilidad (TFORMDET pivot) a Excel."""

    # ─── Metadata ──────────────────────────────────────────────────────────────
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Disponibilidad TFORMDET",
            descripcion="Reporte de consumos y stock desde TFORMDET",
            icono=ft.icons.PIVOT_TABLE_CHART_ROUNDED,
            color=ft.colors.INDIGO_400,
            categoria="Reports SISMED",
            etiquetas=["disponibilidad", "tformdet", "consumo", "pivot",
                       "farmacia", "ipress", "red", "reporte", "excel"],
        )

    # ─── Vista ─────────────────────────────────────────────────────────────────
    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """UI siguiendo el mockup: panel config izq. + panel actividad der."""

        # ── Consola ───────────────────────────────────────────────────────────
        log_view = ft.ListView(expand=True, spacing=3, auto_scroll=True)

        def _log(msg: str):
            color = (ft.colors.GREEN_400  if msg.startswith("✅") else
                     ft.colors.RED_400    if "✗" in msg else
                     ft.colors.AMBER_400  if "⚠" in msg else
                     ft.colors.CYAN_300   if msg.startswith("▶") else
                     ft.colors.GREY_300)
            log_view.controls.append(
                ft.Text(msg, size=12, font_family="Consolas", color=color)
            )
            if len(log_view.controls) > 250:
                log_view.controls.pop(0)
            page.update()

        # ── Estado ────────────────────────────────────────────────────────────
        modo_state = {"value": "farmacias"}

        # ── Directorio SISMED ─────────────────────────────────────────────────
        saved_dir = cfg_get("disponibilidad_sismed_dir")
 
        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_dir.value = e.path
                cfg_set("disponibilidad_sismed_dir", e.path)
                input_dir.update()

        dir_picker = ft.FilePicker(on_result=_on_dir_picked)
        page.overlay.append(dir_picker)
        page.update()

        input_dir = ft.TextField(
            value=saved_dir,
            expand=True,
            border="none",
            bgcolor="transparent",
            color=ft.colors.WHITE,
            text_size=13,
            read_only=True,
            content_padding=ft.padding.only(top=0, bottom=0, left=8, right=8),
            on_click=lambda _: dir_picker.get_directory_path(),
        )

        dir_row = ft.Container(
            height=46,
            content=ft.Row([
                ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, size=18,
                        color=ft.colors.INDIGO_300),
                input_dir,
                ft.IconButton(
                    icon=ft.icons.DRIVE_FOLDER_UPLOAD_ROUNDED,
                    icon_color=ft.colors.INDIGO_300, icon_size=20,
                    tooltip="Seleccionar carpeta SISMED",
                    on_click=lambda _: dir_picker.get_directory_path(),
                ),
            ], spacing=4),
            bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
            border=ft.border.all(1, ft.colors.BLUE_GREY_700),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=10),
            expand=True,
        )

        # ── Meses ─────────────────────────────────────────────────────────────
        meses_field = ft.TextField(
            value="12",
            width=80,
            height=46,
            text_align=ft.TextAlign.CENTER,
            content_padding=ft.padding.symmetric(vertical=10),
            border_radius=8,
            border_color=ft.colors.BLUE_GREY_600,
            color=ft.colors.WHITE,
            text_size=14,
            bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        # ── Mes de STOCK_FIN (Periodo con inc/dec) ────────────────────────────
        anio_ref = [date.today().year]
        mes_ref = [date.today().month]
        
        txt_anio = ft.Text(str(anio_ref[0]), size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        txt_mes = ft.Text(f"{mes_ref[0]:02d}", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
        
        def chg_anio(d):
            anio_ref[0] += d
            txt_anio.value = str(anio_ref[0])
            txt_anio.update()

        def chg_mes(d):
            mes_ref[0] += d
            if mes_ref[0] > 12:
                mes_ref[0] = 1
            elif mes_ref[0] < 1:
                mes_ref[0] = 12
            txt_mes.value = f"{mes_ref[0]:02d}"
            txt_mes.update()

        def _ibtn(icon, offset, is_anio):
            return ft.IconButton(
                icon, icon_size=15, icon_color=ft.colors.INDIGO_300,
                on_click=lambda e, o=offset, a=is_anio: chg_anio(o) if a else chg_mes(o),
                width=22, height=22, padding=0,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4))
            )

        mes_stock_field = ft.Container(
            height=46,
            bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
            border_radius=8,
            border=ft.border.all(1, ft.colors.BLUE_GREY_600),
            padding=ft.padding.symmetric(horizontal=8),
            content=ft.Row([
                # Selector año
                ft.Row([
                    _ibtn(ft.icons.KEYBOARD_ARROW_LEFT_ROUNDED, -1, True),
                    txt_anio,
                    _ibtn(ft.icons.KEYBOARD_ARROW_RIGHT_ROUNDED, 1, True),
                ], spacing=2),
                
                ft.Text("/", color=ft.colors.BLUE_GREY_600, size=16),
                
                # Selector mes
                ft.Row([
                    _ibtn(ft.icons.KEYBOARD_ARROW_LEFT_ROUNDED, -1, False),
                    txt_mes,
                    _ibtn(ft.icons.KEYBOARD_ARROW_RIGHT_ROUNDED, 1, False),
                ], spacing=2),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
        )

        # ── Textos Informativos Dinámicos ─────────────────────────────────────
        info_texts = {
            "farmacias": "Por Farmacias: No agrupa consumos, lista cada unidad de forma independiente sin quitar sufijos.",
            "ipress": "Por IPRESS: Consolida farmacias del mismo establecimiento quitando el sufijo F01, F02, etc.",
            "red": "Por Red: Agrupa todos los establecimientos de forma integral a nivel de Red."
        }
        
        info_lbl = ft.Text(
            info_texts[modo_state["value"]],
            size=10, color=ft.colors.GREY_400, expand=True,
        )

        # ── Excluir con Chips ─────────────────────────────────────────────────
        saved_excluir = ""
        excluir_chips = [c.strip() for c in saved_excluir.split(",") if c.strip()]
        
        chips_wrap = ft.Row(wrap=True, spacing=6, run_spacing=6)
 
        chk_recordar = ft.Checkbox(
            label="Recordar estas exclusiones",
            value=False,
            
            active_color=ft.colors.INDIGO_600,
            visible=len(excluir_chips) > 0,
        )

        def _update_chips():
            chk_recordar.visible = len(excluir_chips) > 0
            if chk_recordar.page:
                chk_recordar.update()

            chips_wrap.controls.clear()
            for code in excluir_chips:
                def _del_chip(e, c=code):
                    excluir_chips.remove(c)
                    _update_chips()
                chips_wrap.controls.append(
                    ft.Container(
                        width=len(code)*8 + 45, # Ancho ajustado a la lóngitud del código
                        bgcolor=ft.colors.with_opacity(0.1, ft.colors.BLUE_GREY_400),
                        border=ft.border.all(1, ft.colors.BLUE_GREY_600),
                        border_radius=16,
                        padding=ft.padding.only(left=8, right=4, top=2, bottom=2),
                        content=ft.Row([
                            ft.Text(code, size=11, color=ft.colors.WHITE),
                            ft.IconButton(
                                ft.icons.CLOSE_ROUNDED, icon_size=12, width=20, height=20,
                                padding=0, style=ft.ButtonStyle(padding=0, shape=ft.CircleBorder()),
                                on_click=_del_chip
                            )
                        ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                )
            if chips_wrap.page:
                chips_wrap.update()

        _update_chips()

        def _on_exclude_change(e):
            val = e.control.value
            if val and (val.endswith(" ") or val.endswith(",")):
                v_clean = val.replace(",", " ").strip()
                if v_clean and v_clean not in excluir_chips:
                    excluir_chips.append(v_clean)
                e.control.value = ""
                e.control.update()
                _update_chips()
        
        def _on_exclude_submit(e):
            val = e.control.value.strip()
            if val and val not in excluir_chips:
                excluir_chips.append(val)
            e.control.value = ""
            e.control.update()
            _update_chips()

        excluir_input = ft.TextField(
            hint_text="Escriba código y presione Espacio o Enter...",
            hint_style=ft.TextStyle(color=ft.colors.GREY_600, size=12),
            border="none",
            bgcolor="transparent",
            color=ft.colors.WHITE,
            text_size=13,
            content_padding=ft.padding.symmetric(vertical=6),
            on_change=_on_exclude_change,
            on_submit=_on_exclude_submit,
        )

        excluir_container = ft.Container(
            height=160,
            bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
            border_radius=8,
            border=ft.border.all(1, ft.colors.BLUE_GREY_600),
            padding=ft.padding.all(10),
            content=ft.Column([
                chips_wrap,
                excluir_input
            ], spacing=6, scroll=ft.ScrollMode.AUTO)
        )

        # (Definido arriba para visibilidad dinámica)

        # ── Botón Generar ─────────────────────────────────────────────────────
        btn_generar = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.DOWNLOAD_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text("GENERAR REPORTE EXCEL", color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, size=14),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.INDIGO_700,
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10),
                elevation=4,
            ),
            height=52,
            on_click=lambda _: _abrir_guardado(),
        )

        # ── Botones de modo (3 verticales) ────────────────────────────────────
        modo_col_ref = [None]

        def _modo_btn(label: str, icon_name: str, key: str) -> ft.Container:
            is_sel = (modo_state["value"] == key)

            def _click(e, k=key):
                modo_state["value"] = k
                modo_col_ref[0].controls = [
                    _modo_btn("Por Farmacias", ft.icons.STORE_ROUNDED,           "farmacias"),
                    _modo_btn("Por IPRESS",    ft.icons.ACCOUNT_BALANCE_ROUNDED, "ipress"),
                    _modo_btn("Por Red",       ft.icons.HUB_ROUNDED,             "red"),
                ]
                modo_col_ref[0].update()
                info_lbl.value = info_texts[k]
                info_lbl.update()

            bg = ft.colors.INDIGO_700 if is_sel else ft.colors.with_opacity(0.06, ft.colors.WHITE)
            border_c = ft.colors.INDIGO_400 if is_sel else ft.colors.BLUE_GREY_700
            txt_c = ft.colors.WHITE if is_sel else ft.colors.GREY_400
            ico_c = ft.colors.WHITE if is_sel else ft.colors.GREY_500

            return ft.Container(
                height=46,
                bgcolor=bg,
                border_radius=10,
                border=ft.border.all(1, border_c),
                on_click=_click,
                content=ft.Row([
                    ft.Icon(icon_name, size=16, color=ico_c),
                    ft.Text(label, size=12,
                            weight=ft.FontWeight.W_600 if is_sel else ft.FontWeight.NORMAL,
                            color=txt_c),
                ], spacing=6, alignment=ft.MainAxisAlignment.CENTER,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )

        modo_col = ft.Column(
            controls=[
                _modo_btn("Por Farmacias", ft.icons.STORE_ROUNDED,           "farmacias"),
                _modo_btn("Por IPRESS",    ft.icons.ACCOUNT_BALANCE_ROUNDED, "ipress"),
                _modo_btn("Por Red",       ft.icons.HUB_ROUNDED,             "red"),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        modo_col_ref[0] = modo_col

        # ── FilePicker guardar ────────────────────────────────────────────────
        def _on_save(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            out = e.path if e.path.lower().endswith(".xlsx") else e.path + ".xlsx"

            def _process():
                btn_generar.disabled = True
                btn_generar.update()
                log_view.controls.clear()

                try:
                    n_meses = max(1, int(meses_field.value.strip() or "12"))
                except ValueError:
                    n_meses = 12

                mes_stock = f"{anio_ref[0]}{mes_ref[0]:02d}"
                excluir_lista = excluir_chips.copy()
 
                mgr = DisponibilidadReportManager(
                    sismed_dir=input_dir.value.strip(),
                    log_callback=_log,
                )
                ok = mgr.generate(
                    output_path=out,
                    meses=n_meses,
                    modo=modo_state["value"],
                    excluir_codigos=excluir_lista,
                    mes_stock_fin=mes_stock,
                )

                page.snack_bar = ft.SnackBar(
                    ft.Text("✅ Reporte generado exitosamente." if ok
                            else "❌ Hubo un error al generar el reporte."),
                    bgcolor=ft.colors.GREEN_700 if ok else ft.colors.RED_700,
                )
                page.snack_bar.open = True
                btn_generar.disabled = False
                btn_generar.update()
                page.update()

            threading.Thread(target=_process, daemon=True).start()

        save_picker = ft.FilePicker(on_result=_on_save)
        page.overlay.append(save_picker)
        page.update()

        def _abrir_guardado():
            fecha_str  = date.today().strftime("%d%m%Y")
            modo_label = {
                "farmacias": "POR_FARMACIAS",
                "ipress":    "POR_IPRESS",
                "red":       "POR_RED",
            }.get(modo_state["value"], "REPORTE")
            save_picker.save_file(
                dialog_title="Guardar reporte de Disponibilidad",
                file_name=f"DISPONIBILIDAD_{modo_label}_{fecha_str}.xlsx",
                allowed_extensions=["xlsx"],
            )

        # ── Helpers visuales ──────────────────────────────────────────────────
        def _lbl(text: str) -> ft.Text:
            return ft.Text(text, size=11, color=ft.colors.GREY_400,
                           weight=ft.FontWeight.W_600)

        # ══════════════════════════════════════════════════════════════════════
        # LAYOUT  (idéntico al mockup del usuario)
        # ══════════════════════════════════════════════════════════════════════
        return ft.Container(
            padding=ft.padding.all(28),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                controls=[

                # ── Encabezado ─────────────────────────────────────────────
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Disponibilidad TFORMDET",
                    "Reporte de consumo, stock y precio por mes desde TFORMDET",
                    right_content=self._back_button(
                        "Volver a Reports SISMED", navigate_fn, 4
                    ),
                ),
                ft.Container(height=14),

                # ── Cuerpo: config (izq) + actividad (der) ─────────────────
                ft.ResponsiveRow([

                    # ─────────────────────────────────────────────────────────
                    # PANEL IZQUIERDO – Configuración del Reporte
                    # ─────────────────────────────────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 7},
                        bgcolor=ft.colors.BLUE_GREY_900,
                        border_radius=16,
                        padding=ft.padding.all(26),
                        content=ft.Column([

                            # Título de sección
                            ft.Row([
                                ft.Icon(ft.icons.TUNE_ROUNDED,
                                        color=ft.colors.INDIGO_400, size=20),
                                ft.Text("Configuración del Reporte",
                                        size=15, weight=ft.FontWeight.W_700,
                                        color=ft.colors.WHITE),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.WHITE12, height=12),

                            # ── Fila 1: Dir | Parámetros de Tiempo ─────────────
                            ft.ResponsiveRow([
                                # Directorio
                                ft.Container(
                                    col={"sm": 12, "lg": 12, "xl": 6},
                                    content=ft.Column([
                                        _lbl("Directorio raíz SISMED:"),
                                        dir_row,
                                    ], spacing=6),
                                ),

                                # Parámetros de fecha/variables (Agrupados)
                                ft.Container(
                                    col={"sm": 12, "lg": 12, "xl": 6},
                                    content=ft.Row([
                                        # Meses
                                        ft.Column([
                                            _lbl("Meses consumo"),
                                            meses_field,
                                        ], spacing=6),

                                        ft.Container(width=24), # Espaciador

                                        # Periodo
                                        ft.Column([
                                            _lbl("Último periodo de consumo"),
                                            mes_stock_field,
                                        ], spacing=6)
                                    ], vertical_alignment=ft.CrossAxisAlignment.END, spacing=0)
                                ),
                            ], vertical_alignment=ft.CrossAxisAlignment.END),

                            ft.Container(height=16),

                            # ── Fila 2: Grid 2 Columnas abajo ─────────────────
                            ft.ResponsiveRow([
                                # Izquierda: Tipo de agrupación
                                ft.Container(
                                    col={"sm": 12, "lg": 6},
                                    content=ft.Column([
                                        _lbl("Tipo de Reporte:"),
                                        modo_col,
                                        
                                        ft.Container(height=4),
                                        
                                        # Nota informativa
                                        ft.Container(
                                            padding=ft.padding.symmetric(horizontal=10, vertical=8),
                                            bgcolor=ft.colors.with_opacity(0.07, ft.colors.INDIGO_400),
                                            border_radius=8,
                                            content=ft.Row([
                                                ft.Icon(ft.icons.INFO_OUTLINE_ROUNDED,
                                                        size=13, color=ft.colors.INDIGO_300),
                                                info_lbl,
                                            ], spacing=8),
                                        ),
                                    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                ),
                                
                                # Derecha: Excluir
                                ft.Container(
                                    col={"sm": 12, "lg": 6},
                                    content=ft.Column([
                                        _lbl("Excluir establecimientos"),
                                        excluir_container,
                                        ft.Row([chk_recordar], alignment=ft.MainAxisAlignment.END),
                                    ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                ),
                                
                            ]),

                            ft.Container(height=20),

                            # ── Botón Generar (centrado) ──────────────────────
                            ft.Row([
                                ft.Container(
                                    content=btn_generar,
                                    width=350,  # Un ancho fijo razonable para este botón
                                    alignment=ft.alignment.center
                                )
                            ], alignment=ft.MainAxisAlignment.CENTER),

                        ], spacing=10),
                    ),

                    # ─────────────────────────────────────────────────────────
                    # PANEL DERECHO – Actividad / Log
                    # ─────────────────────────────────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 5},
                        height=555,  # Fijo en layout responsive para que ListView no colapse
                        bgcolor=ft.colors.BLACK87,
                        border_radius=16,
                        border=ft.border.all(1, ft.colors.BLUE_GREY_800),
                        padding=ft.padding.all(20),
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TERMINAL_ROUNDED,
                                        color=ft.colors.INDIGO_400, size=18),
                                ft.Text("Console/Actividad",
                                        color=ft.colors.GREY_300, size=14,
                                        weight=ft.FontWeight.W_700),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.BLUE_GREY_800, height=10),
                            log_view,
                        ], spacing=4, expand=True),
                    ),

                ]),
            ]),
        )
