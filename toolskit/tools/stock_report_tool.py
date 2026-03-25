"""
stock_report_tool.py
====================
Herramienta: Reporte de Stock SISMED
Categoría  : Reports SISMED

Genera reportes de Stock General y/o Stock Detallado desde los
archivos DBF del SISMED local hacia un archivo Excel (.xlsx).

Opciones:
  - Stock General  (MSTKALM)
  - Stock Detallado (MSTKALMDE)
    * Modo Consolidado  → una sola hoja con todas las farmacias
    * Modo Por Farmacia → una hoja por farmacia + hoja total

Depende de: stock_report_manager.StockReportManager
Hereda de : tools.base_tool.SismedTool
"""

import threading
import flet as ft

from stock_report_manager import StockReportManager
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import get as cfg_get, set as cfg_set


class StockReportTool(SismedTool):
    """Exporta el Stock General y/o Detallado de SISMED a un archivo Excel local."""

    # ─── Metadata ──────────────────────────────────────────────────────────────
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Stock SISMED",
            descripcion="Exporta stock general y detallado de SISMED a Excel",
            icono=ft.icons.INVENTORY_2_ROUNDED,
            color=ft.colors.BLUE_400,
            categoria="Reports SISMED",
            etiquetas=["stock", "inventario", "sismed", "excel",
                       "farmacia", "reporte", "mstkalm", "mstkalmde"],
        )

    # ─── Vista ─────────────────────────────────────────────────────────────────
    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """UI completa de la herramienta de reporte de Stock."""

        # ── Consola de log ────────────────────────────────────────────────────
        log_view = ft.ListView(expand=True, spacing=4, auto_scroll=True, height=310)

        def _log(msg: str):
            color = ft.colors.GREEN_400 if msg.startswith("✅") else (
                    ft.colors.RED_400   if ("✗" in msg or "✗" in msg) else
                    ft.colors.AMBER_400 if "⚠" in msg else
                    ft.colors.GREY_300)
            log_view.controls.append(
                ft.Text(msg, size=12, font_family="Consolas", color=color)
            )
            if len(log_view.controls) > 200:
                log_view.controls.pop(0)
            page.update()

        # ── Directorio SISMED ─────────────────────────────────────────────────
        saved_dir = cfg_get("stock_sismed_dir")
 
        def _on_dir_picked(e: ft.FilePickerResultEvent):
            if e.path:
                input_dir.value = e.path
                cfg_set("stock_sismed_dir", e.path)
                input_dir.update()

        dir_picker = ft.FilePicker(on_result=_on_dir_picked)
        page.overlay.append(dir_picker)
        page.update()

        input_dir = ft.TextField(
            value=saved_dir,
            expand=True,
            dense=True,
            text_size=13,
            read_only=False,
            text_align=ft.TextAlign.LEFT,
            border_radius=8,
            border_color=ft.colors.BLUE_GREY_700,
            focused_border_color=ft.colors.BLUE_400,
            content_padding=ft.padding.only(left=12, right=4, top=10, bottom=10),
            color=ft.colors.WHITE,
            bgcolor=ft.colors.with_opacity(0.04, ft.colors.WHITE),
        )

        btn_browse = ft.IconButton(
            icon=ft.icons.FOLDER_OPEN_ROUNDED,
            icon_color=ft.colors.BLUE_300,
            icon_size=20,
            tooltip="Seleccionar carpeta SISMED",
            on_click=lambda _: dir_picker.get_directory_path(),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.colors.with_opacity(0.1, ft.colors.BLUE_400)},
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        dir_row = ft.Container(
            border_radius=10,
            border=ft.border.all(1, ft.colors.BLUE_GREY_700),
            bgcolor=ft.colors.with_opacity(0.04, ft.colors.WHITE),
            padding=ft.padding.only(left=10, right=6, top=4, bottom=4),
            content=ft.Row([
                ft.Icon(ft.icons.FOLDER_ROUNDED, size=16,
                        color=ft.colors.BLUE_GREY_400),
                input_dir,
                btn_browse,
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

        # ── Checkboxes de tipo de reporte (radio-button mutuamente exclusivos) ──
        chk_general = ft.Checkbox(
            label="Stock General (MSTKALM)",
            value=False,
            
        )
        chk_detalle = ft.Checkbox(
            label="Stock Detallado (MSTKALMDE)",
            value=False,
            
        )

        # Exclusión mutua: marcar uno desmarca el otro
        def _on_general_change(e):
            if chk_general.value:
                chk_detalle.value = False
                chk_detalle.update()
            _update_modo_section()

        def _on_detalle_change(e):
            if chk_detalle.value:
                chk_general.value = False
                chk_general.update()
            _update_modo_section()

        def _update_modo_section():
            modo_section.visible = chk_detalle.value
            modo_section.update()

        chk_general.on_change = _on_general_change
        chk_detalle.on_change = _on_detalle_change

        modo_state    = {"value": "consolidado"}   # "consolidado" | "por_farmacia"
        modo_row_ref  = [None]

        def _mode_btn(label, icon_name, key):
            is_sel = modo_state["value"] == key

            def _on_tap(e, k=key):
                if not chk_detalle.value:
                    return
                modo_state["value"] = k
                modo_row_ref[0].controls = [
                    _mode_btn("Consolidado",   ft.icons.MERGE_TYPE_ROUNDED,    "consolidado"),
                    ft.Container(width=6),
                    _mode_btn("Por Farmacia",  ft.icons.ACCOUNT_TREE_ROUNDED,  "por_farmacia"),
                ]
                modo_row_ref[0].update()

            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=_on_tap,
                expand=True,
                content=ft.Container(
                    expand=True, height=44,
                    bgcolor=ft.colors.BLUE_GREY_700 if is_sel else ft.colors.TRANSPARENT,
                    border_radius=8,
                    border=ft.border.all(
                        1,
                        ft.colors.BLUE_400 if is_sel else ft.colors.BLUE_GREY_700
                    ),
                    padding=ft.padding.symmetric(horizontal=12),
                    content=ft.Row([
                        ft.Icon(icon_name, size=16,
                                color=ft.colors.WHITE if is_sel else ft.colors.GREY_500),
                        ft.Text(label, size=12,
                                weight=ft.FontWeight.W_600 if is_sel else ft.FontWeight.NORMAL,
                                color=ft.colors.WHITE if is_sel else ft.colors.GREY_500,
                                expand=True,
                                text_align=ft.TextAlign.CENTER),
                        ft.Icon(ft.icons.CHECK_ROUNDED, size=14,
                                color=ft.colors.WHITE if is_sel else ft.colors.TRANSPARENT),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
            )

        modo_row = ft.Row(
            controls=[
                _mode_btn("Consolidado",  ft.icons.MERGE_TYPE_ROUNDED,   "consolidado"),
                ft.Container(width=6),
                _mode_btn("Por Farmacia", ft.icons.ACCOUNT_TREE_ROUNDED, "por_farmacia"),
            ],
            spacing=0, expand=True,
        )
        modo_row_ref[0] = modo_row

        modo_section = ft.Column([
            ft.Text("Modo detallado:", size=12, color=ft.colors.GREY_400),
            modo_row,
        ], spacing=6, visible=False)   # Se muestra solo cuando Stock Detallado está activo

        # ── Botón Generar ─────────────────────────────────────────────────────
        btn_generar = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.DOWNLOAD_ROUNDED, color=ft.colors.WHITE, size=20),
                ft.Text("GENERAR REPORTE EXCEL", color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, size=13),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.BLUE_700, color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10), elevation=4,
            ),
            height=52, on_click=lambda _: _abrir_guardado(),
        )

        # ── FilePicker guardar ────────────────────────────────────────────────
        def _on_save(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            out = e.path if e.path.lower().endswith(".xlsx") else e.path + ".xlsx"

            def _process():
                btn_generar.disabled = True
                btn_generar.update()
                log_view.controls.clear()

                mgr = StockReportManager(
                    sismed_dir=input_dir.value.strip(),
                    log_callback=_log,
                )
                ok = mgr.generate(
                    output_path=out,
                    include_general=chk_general.value,
                    include_detalle=chk_detalle.value,
                    modo_detalle=modo_state["value"],
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
            if not chk_general.value and not chk_detalle.value:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠ Selecciona al menos un tipo de reporte."),
                    bgcolor=ft.colors.AMBER_700,
                )
                page.snack_bar.open = True
                page.update()
                return
            fecha_str = __import__('datetime').datetime.now().strftime('%d%m%Y')
            
            if chk_general.value:
                file_name_out = f"STOCK_GENERAL_{fecha_str}.xlsx"
            else:
                tipo_det = "CONSOLIDADO" if modo_state["value"] == "consolidado" else "POR_FARMACIAS"
                file_name_out = f"STOCK_DETALLADO_{tipo_det}_{fecha_str}.xlsx"

            save_picker.save_file(
                dialog_title="Guardar reporte de Stock",
                file_name=file_name_out,
                allowed_extensions=["xlsx"],
            )

        # ── Layout ────────────────────────────────────────────────────────────
        return ft.Container(
            padding=ft.padding.all(30),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                # Encabezado premium (heredado de SismedTool)
                self._section_header(
                    self.metadata.icono,
                    self.metadata.color,
                    "Reporte de Stock SISMED",
                    "Genera Stock General / Detallado desde los archivos DBF locales",
                    right_content=self._back_button(
                        "Volver a Reports SISMED", navigate_fn, 4
                    ),
                ),
                ft.Divider(height=10, color=ft.colors.TRANSPARENT),

                # Cuerpo: Grid Responsivo
                ft.ResponsiveRow([

                    # ── Panel izquierdo: configuración ────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 5},
                        bgcolor=ft.colors.BLUE_GREY_900,
                        border_radius=16,
                        padding=ft.padding.only(top=32, bottom=32, left=32, right=32),
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TUNE_ROUNDED,
                                        color=ft.colors.BLUE_400, size=22),
                                ft.Text("Parámetros del Reporte", size=15,
                                        weight=ft.FontWeight.W_700,
                                        color=ft.colors.WHITE),
                            ], spacing=10),
                            ft.Divider(color=ft.colors.WHITE24, height=16),

                            # Directorio
                            ft.Text("Directorio raíz SISMED:", size=12,
                                    color=ft.colors.GREY_400),
                            dir_row,
                            ft.Container(height=12),

                            # Tipos de reporte
                            ft.Text("Tipo de reporte a incluir:", size=12,
                                    color=ft.colors.GREY_400),
                            ft.Container(
                                bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
                                border_radius=10,
                                border=ft.border.all(1, ft.colors.BLUE_GREY_700),
                                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                                content=ft.Column([
                                    chk_general,
                                    chk_detalle,
                                ], spacing=4),
                            ),
                            ft.Container(height=12),

                            # Modo detalle (visible/hidden)
                            modo_section,
                            ft.Container(expand=True),  # Pushing el botón hacia el fondo de manera prolija

                            ft.Row([btn_generar],
                                   alignment=ft.MainAxisAlignment.CENTER),
                        ], spacing=8),
                    ),

                    # ── Panel derecho: consola ─────────────────────────────────
                    ft.Container(
                        col={"sm": 12, "lg": 6, "xl": 7},
                        height=422,
                        bgcolor=ft.colors.BLACK,
                        border_radius=16,
                        padding=ft.padding.all(22),
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TERMINAL_ROUNDED,
                                        color=ft.colors.BLUE_400, size=22),
                                ft.Text("Actividad / Log",
                                        color=ft.colors.WHITE, size=16,
                                        weight=ft.FontWeight.W_700),
                            ], spacing=8),
                            ft.Divider(color=ft.colors.GREY_900, height=16),
                            log_view,
                        ], spacing=4, expand=True),
                    ),

                ], spacing=20),
            ]),
        )
