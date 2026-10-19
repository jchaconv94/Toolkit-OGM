"""
generar_ici_tool.py
===================
Herramienta: Generar ICI
Categoría  : Farmacia

Arma el Informe de Consumo Integrado de un mes, listo para imprimir y firmar, leyendo el
SISMED directamente: el detalle por lote de TFORMDET, las recetas de TFORMATO y los movimientos
de TMOVIM (vencidos, entregas entre farmacias, correcciones de lote y guías de ingreso).
Saca un libro por farmacia y el consolidado del establecimiento, cada uno en Excel y en PDF
(todas las hojas en un solo PDF, para imprimir; ici_pdf.py).

Es aparte de «Consul. TFORMDET», que sigue igual. Depende de ici_data.py e ici_excel.py.
El diseño de la pantalla es el de Consulta TFORMDET: campos rellenos con etiqueta chica arriba,
opciones y un recuadro que dice qué se va a generar.
"""

import os
import threading
from datetime import date

import flet as ft

from ici_data import month_label, read_month
from ici_excel import write_reports
from tformdet_periods import MESES
from tools.app_config import get as cfg_get, set as cfg_set
from tools.base_tool import SismedTool, ToolMetadata

ACCENT = ft.colors.PINK_400
ACCENT_STRONG = ft.colors.PINK_700
FIELD_BG = ft.colors.with_opacity(0.06, ft.colors.WHITE)
FIELD_BORDER = ft.colors.BLUE_GREY_700


def previous_month(today: date | None = None) -> tuple[int, int]:
    """El ICI que toca generar es el del mes que ya cerró."""
    today = today or date.today()
    return (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)


class GenerarIciTool(SismedTool):
    """ICI por farmacia y consolidado, con el diseño aprobado, desde el SISMED."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Generar ICI",
            descripcion="Informe de Consumo Integrado listo para firmar",
            icono=ft.icons.ASSIGNMENT_ROUNDED,
            color=ACCENT,
            categoria="Farmacia",
            etiquetas=["ici", "informe", "consumo", "integrado", "tformdet", "recetas",
                       "vencimientos", "consolidado", "farmacia", "excel"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        log_view = ft.ListView(expand=True, spacing=5, auto_scroll=True)
        generated = {"dir": ""}

        def _log(msg):
            log_view.controls.append(ft.Text(msg, size=13, font_family="Consolas", color=ft.colors.GREEN_400))
            page.update()

        def _lbl(text: str) -> ft.Text:
            return ft.Text(text, size=11, color=ft.colors.GREY_400, weight=ft.FontWeight.W_600)

        def _box(content, **kwargs) -> ft.Container:
            return ft.Container(
                content=content, height=46, bgcolor=FIELD_BG, border_radius=8,
                border=ft.border.all(1, FIELD_BORDER),
                padding=ft.padding.symmetric(horizontal=8), **kwargs,
            )

        def _snack(text: str, color):
            page.snack_bar = ft.SnackBar(ft.Text(text, color=ft.colors.WHITE), bgcolor=color)
            page.snack_bar.open = True
            page.update()

        # ── Carpetas: SISMED y destino ─────────────────────────────────────────
        def _folder_field(value, hint, picker, tooltip):
            field = ft.TextField(
                value=value, hint_text=hint, expand=True, border="none", bgcolor="transparent",
                color=ft.colors.WHITE, text_size=13, read_only=True,
                content_padding=ft.padding.only(top=0, bottom=0, left=8, right=8),
                on_click=lambda _: picker.get_directory_path(),
            )
            row = _box(ft.Row([
                ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, size=18, color=ACCENT),
                field,
                ft.IconButton(icon=ft.icons.DRIVE_FOLDER_UPLOAD_ROUNDED, icon_color=ACCENT, icon_size=20,
                              tooltip=tooltip, on_click=lambda _: picker.get_directory_path()),
            ], spacing=4), expand=True)
            return field, row

        def _on_sismed_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed.value = e.path
                cfg_set("ici_sismed_dir", e.path)
                input_sismed.update()

        def _on_out_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_out.value = e.path
                cfg_set("ici_out_dir", e.path)
                input_out.update()

        sismed_picker = ft.FilePicker(on_result=_on_sismed_picked)
        out_picker = ft.FilePicker(on_result=_on_out_picked)
        page.overlay.extend([sismed_picker, out_picker])
        page.update()

        input_sismed, sismed_row = _folder_field(
            cfg_get("ici_sismed_dir") or cfg_get("tformdet_sismed_dir"), "Seleccione la carpeta SISMED…",
            sismed_picker, "Seleccionar carpeta SISMED")
        input_out, out_row = _folder_field(
            cfg_get("ici_out_dir") or "", "Carpeta donde se guardarán los ICI…", out_picker, "Seleccionar carpeta")

        # ── Mes ────────────────────────────────────────────────────────────────
        year0, month0 = previous_month()
        state = {"y": str(year0), "m": month0}

        dropdown_mes = ft.Dropdown(
            options=[ft.dropdown.Option(str(i), nombre) for i, nombre in enumerate(MESES, start=1)],
            value=str(month0), width=170,
            filled=True, fill_color=FIELD_BG, bgcolor=ft.colors.BLUE_GREY_900,
            border_color=FIELD_BORDER, focused_border_color=ACCENT, border_radius=8,
            text_size=14, color=ft.colors.WHITE, menu_height=320,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=10),
        )
        input_anio = ft.TextField(
            value=str(year0), width=90, hint_text="Año",
            filled=True, fill_color=FIELD_BG, border_color=FIELD_BORDER,
            focused_border_color=ACCENT, border_radius=8,
            text_size=14, color=ft.colors.WHITE, text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.symmetric(horizontal=10, vertical=14),
        )

        # ── Qué se va a generar ────────────────────────────────────────────────
        check_consolidado = ft.Checkbox(
            label="Consolidado del establecimiento",
            label_style=ft.TextStyle(size=13, color=ft.colors.GREY_300),
            tooltip="Suma todas las farmacias y puestos comunales y descuenta lo entregado entre ellos.",
            value=bool(cfg_get("ici_consolidado")),
        )
        check_farmacias = ft.Checkbox(
            label="Un ICI por cada farmacia",
            label_style=ft.TextStyle(size=13, color=ft.colors.GREY_300),
            value=bool(cfg_get("ici_por_farmacia")),
        )
        texto_resumen = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        texto_detalle = ft.Text("", size=12, color=ft.colors.PINK_100)
        icono_resumen = ft.Icon(ft.icons.EVENT_NOTE_ROUNDED, size=22, color=ACCENT)
        resumen = ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            bgcolor=ft.colors.with_opacity(0.08, ACCENT),
            border=ft.border.all(1, ft.colors.with_opacity(0.25, ACCENT)),
            border_radius=10,
            content=ft.Row([
                icono_resumen,
                ft.Column([
                    ft.Text("Se generará", size=11, color=ft.colors.GREY_400),
                    texto_resumen,
                    texto_detalle,
                ], spacing=1, tight=True, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

        def _annomes():
            try:
                y = int(str(input_anio.value or "").strip())
                m = int(dropdown_mes.value)
            except (TypeError, ValueError):
                return None
            if not (2000 <= y <= 2100 and 1 <= m <= 12):
                return None
            return f"{y:04d}{m:02d}"

        def _refresh(e=None):
            annomes = _annomes()
            partes = []
            if check_consolidado.value:
                partes.append("el consolidado del establecimiento")
            if check_farmacias.value:
                partes.append("un ICI por cada farmacia")
            if annomes is None:
                texto_resumen.value = "Escriba un año válido (por ejemplo, 2026)."
                texto_detalle.value = ""
                icono_resumen.name, icono_resumen.color = ft.icons.ERROR_OUTLINE_ROUNDED, ft.colors.RED_300
            else:
                texto_resumen.value = f"ICI de {month_label(annomes).title()}"
                texto_detalle.value = (" y ".join(partes).capitalize() if partes else "Marque qué generar") + \
                    ", en Excel y en PDF (todas las hojas, para imprimir). Hojas: ICI, Vencimientos, Alertas de farmacia, " \
                    "Lotes sin movimiento, Guías de ingreso y Correcciones de lote."
                icono_resumen.name, icono_resumen.color = ft.icons.EVENT_NOTE_ROUNDED, ACCENT
            cfg_set("ici_consolidado", bool(check_consolidado.value))
            cfg_set("ici_por_farmacia", bool(check_farmacias.value))
            if e is not None:
                page.update()

        for control in (dropdown_mes, input_anio, check_consolidado, check_farmacias):
            control.on_change = _refresh
        _refresh()

        # ── Generar ────────────────────────────────────────────────────────────
        def _open_folder(_):
            if generated["dir"] and hasattr(os, "startfile"):
                os.startfile(generated["dir"])

        btn_open = ft.TextButton("Abrir carpeta", icon=ft.icons.FOLDER_ROUNDED, visible=False, on_click=_open_folder,
                                 style=ft.ButtonStyle(color=ACCENT))

        def _run(e):
            annomes = _annomes()
            sismed_dir = input_sismed.value
            out_dir = input_out.value
            if not sismed_dir:
                return _snack("❌ Seleccione la carpeta del SISMED.", ft.colors.RED_700)
            if not out_dir or not os.path.isdir(out_dir):
                return _snack("❌ Seleccione la carpeta donde se guardarán los ICI.", ft.colors.RED_700)
            if annomes is None:
                return _snack("❌ Escriba un año válido (por ejemplo, 2026).", ft.colors.RED_700)
            if not (check_consolidado.value or check_farmacias.value):
                return _snack("❌ Marque el consolidado, los ICI por farmacia o los dos.", ft.colors.RED_700)

            log_view.controls.clear()
            btn_open.visible = False
            btn_run.disabled = True
            page.update()

            def _process():
                try:
                    _log(f"🚀 Generando el ICI de {month_label(annomes).title()}…")
                    month = read_month(sismed_dir, annomes, log=_log)
                    for warning in month.warnings:
                        _log(f"⚠️ {warning}")
                    if not month.establishments:
                        _log(f"❌ El SISMED no tiene el ICI de {month_label(annomes).title()} procesado (TFORMDET vacío "
                             "para ese mes). Procéselo en el SISMED y vuelva a intentar.")
                        _snack("⚠️ No hay datos de ese mes.", ft.colors.ORANGE_700)
                        return
                    for est in month.establishments:
                        _log(f"🏥 {est.name}: {len(est.pharmacies)} farmacia(s) · "
                             f"{sum(len(p.rows) for p in est.pharmacies)} lotes")
                    paths = write_reports(month, out_dir, consolidated=bool(check_consolidado.value),
                                          per_pharmacy=bool(check_farmacias.value), log=_log)
                    generated["dir"] = out_dir
                    btn_open.visible = hasattr(os, "startfile")
                    _log(f"✨ Listo: {len(paths)} archivo(s) en {out_dir}")
                    _snack(f"✅ ICI generado: {len(paths)} archivo(s).", ft.colors.GREEN_700)
                except Exception as exc:  # noqa: BLE001 - se muestra en la consola
                    _log(f"❌ Error al generar el ICI: {exc}")
                    _snack("❌ No se pudo generar el ICI.", ft.colors.RED_700)
                finally:
                    btn_run.disabled = False
                    page.update()

            threading.Thread(target=_process, daemon=True).start()

        btn_run = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.ASSIGNMENT_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text("GENERAR ICI", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=14),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(bgcolor=ACCENT_STRONG, color=ft.colors.WHITE,
                                 shape=ft.RoundedRectangleBorder(radius=10), elevation=4),
            height=52,
            on_click=_run,
        )

        return ft.Container(
            padding=ft.padding.all(28),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                controls=[
                    self._section_header(
                        self.metadata.icono, self.metadata.color, "Generar ICI",
                        "Informe de Consumo Integrado por farmacia y consolidado, listo para firmar",
                        right_content=self._back_button("Volver a Farmacia", navigate_fn, 20),
                    ),
                    ft.Container(height=14),
                    ft.ResponsiveRow([
                        ft.Container(
                            col={"sm": 12, "lg": 7},
                            bgcolor=ft.colors.BLUE_GREY_900,
                            border_radius=16,
                            padding=ft.padding.all(26),
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TUNE_ROUNDED, color=ACCENT, size=20),
                                    ft.Text("Configuración del ICI", size=15, weight=ft.FontWeight.W_700,
                                            color=ft.colors.WHITE),
                                ], spacing=8),
                                ft.Divider(color=ft.colors.WHITE12, height=12),
                                ft.Column([_lbl("Directorio raíz SISMED:"), ft.Row([sismed_row])], spacing=6),
                                ft.Column([_lbl("Mes del ICI:"), ft.Row([dropdown_mes, input_anio], spacing=8)], spacing=6),
                                ft.Column([_lbl("Generar:"), check_consolidado, check_farmacias], spacing=2),
                                ft.Column([_lbl("Guardar en:"), ft.Row([out_row])], spacing=6),
                                resumen,
                                ft.Container(height=4),
                                ft.Row([
                                    ft.Container(content=btn_run, width=360, alignment=ft.alignment.center)
                                ], alignment=ft.MainAxisAlignment.CENTER),
                            ], spacing=12),
                        ),
                        ft.Container(
                            col={"sm": 12, "lg": 5},
                            height=600,
                            bgcolor=ft.colors.BLACK87,
                            border_radius=16,
                            border=ft.border.all(1, ft.colors.BLUE_GREY_800),
                            padding=ft.padding.all(20),
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ACCENT, size=18),
                                    ft.Text("Consola", color=ft.colors.GREY_300, size=14, weight=ft.FontWeight.W_700),
                                    ft.Container(expand=True),
                                    btn_open,
                                ], spacing=8),
                                ft.Divider(color=ft.colors.BLUE_GREY_800, height=10),
                                log_view,
                            ], spacing=4, expand=True),
                        ),
                    ]),
                ],
            ),
        )
