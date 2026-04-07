import os
import threading

import flet as ft

from excel_merge_manager import ExcelMergeManager
from tools.base_tool import SismedTool, ToolMetadata


class ExcelMergeTool(SismedTool):
    """Une varios archivos Excel en un solo consolidado validando cabeceras."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Unir EXCEL",
            descripcion="Consolida varios Excel en uno validando cabeceras compatibles",
            icono=ft.icons.FILE_COPY_ROUNDED,
            color=ft.colors.TEAL_400,
            categoria="Herramientas",
            etiquetas=["excel", "unir", "combinar", "consolidar", "cabeceras", "xlsx"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        state = {"paths": [], "busy": False, "append_mode": False}
        merge_manager = ExcelMergeManager()
        alert_dialog = None

        def build_format_chip(label: str) -> ft.Control:
            return ft.Container(
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                border_radius=999,
                bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE),
                border=ft.border.all(1, ft.colors.with_opacity(0.12, ft.colors.TEAL_200)),
                content=ft.Text(
                    label,
                    size=10,
                    color=ft.colors.TEAL_100,
                    weight=ft.FontWeight.W_700,
                ),
            )

        selected_count = ft.Text(
            "0 archivos seleccionados",
            size=12,
            color=ft.colors.TEAL_200,
            italic=False,
            weight=ft.FontWeight.W_700,
            visible=False,
        )
        add_more_link = ft.TextButton(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.ADD_ROUNDED, size=14, color=ft.colors.TEAL_200),
                    ft.Text(
                        "Añadir más archivos",
                        size=12,
                        color=ft.colors.TEAL_200,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
        )
        selection_toolbar = ft.Row(
            [selected_count, add_more_link],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        upload_zone_badge_text = ft.Text(
            "LISTO PARA CARGAR",
            size=10,
            color=ft.colors.TEAL_100,
            weight=ft.FontWeight.W_800,
        )
        upload_zone_badge = ft.Container(
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            border_radius=999,
            bgcolor=ft.colors.with_opacity(0.14, ft.colors.TEAL_300),
            border=ft.border.all(1, ft.colors.with_opacity(0.20, ft.colors.TEAL_100)),
            content=upload_zone_badge_text,
        )
        upload_zone_icon = ft.Container(
            width=68,
            height=68,
            border_radius=34,
            bgcolor=ft.colors.with_opacity(0.15, ft.colors.TEAL_300),
            alignment=ft.alignment.center,
            content=ft.Icon(ft.icons.UPLOAD_FILE_ROUNDED, size=32, color=ft.colors.TEAL_100),
        )
        upload_zone_title = ft.Text(
            "Clcc aquí para Cargar tus archivos",
            size=22,
            weight=ft.FontWeight.W_900,
            color=ft.colors.WHITE,
            text_align=ft.TextAlign.CENTER,
        )
        upload_zone_subtitle = ft.Text(
            "Haz clic aqui para seleccionar 2 o mas archivos y empezar la consolidacion.",
            size=12,
            color=ft.colors.GREY_300,
            text_align=ft.TextAlign.CENTER,
        )
        upload_zone_action = ft.Container(
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            border_radius=12,
            bgcolor=ft.colors.with_opacity(0.10, ft.colors.BLUE_300),
            content=ft.Row(
                [
                    ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, size=16, color=ft.colors.WHITE),
                    ft.Text(
                        "Haz clic para explorar archivos",
                        size=12,
                        color=ft.colors.WHITE,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                tight=True,
            ),
        )
        upload_zone = ft.Container(
            height=220,
            border_radius=22,
            padding=ft.padding.only(left=24, right=24, top=22, bottom=38),
            bgcolor=ft.colors.with_opacity(0.07, ft.colors.TEAL_400),
            border=ft.border.all(1.4, ft.colors.with_opacity(0.32, ft.colors.TEAL_200)),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.colors.with_opacity(0.18, ft.colors.BLACK),
                offset=ft.Offset(0, 8),
            ),
            animate=ft.animation.Animation(180, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                [
                    ft.Row([upload_zone_badge], alignment=ft.MainAxisAlignment.CENTER),
                    upload_zone_icon,
                    upload_zone_title,
                    upload_zone_subtitle,
                    ft.Row(
                        [
                            build_format_chip("XLS"),
                            build_format_chip("XLSX"),
                            build_format_chip("XLSM"),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8,
                        wrap=True,
                    ),
                    upload_zone_action,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=12,
            ),
        )
        files_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        files_container = ft.Container(
            height=220,
            padding=10,
            border_radius=12,
            bgcolor=ft.colors.with_opacity(0.05, ft.colors.WHITE),
            content=files_list,
            visible=False,
        )
        logs_list = ft.ListView(expand=True, spacing=6, auto_scroll=True, height=260)
        progress_bar = ft.ProgressBar(
            expand=True,
            visible=False,
            color=ft.colors.TEAL_400,
            bgcolor=ft.colors.WHITE24,
        )

        def append_log(message: str, color=ft.colors.WHITE):
            logs_list.controls.append(
                ft.Text(message, size=12, color=color, font_family="Consolas")
            )
            if len(logs_list.controls) > 300:
                del logs_list.controls[: len(logs_list.controls) - 300]
            page.update()

        def post_notice(message: str, level: str = "info", clear_logs: bool = False):
            styles = {
                "info": ("[INFO]", ft.colors.BLUE_300),
                "success": ("[OK]", ft.colors.GREEN_400),
                "warning": ("[WARN]", ft.colors.AMBER_300),
                "error": ("[ERROR]", ft.colors.RED_400),
            }
            prefix, color = styles.get(level, styles["info"])
            if clear_logs:
                logs_list.controls.clear()
            append_log(f"{prefix} {message}", color=color)

        merge_manager._log_fn = append_log

        def remove_selected_file(index_to_remove: int):
            if state["busy"]:
                return
            if index_to_remove < 0 or index_to_remove >= len(state["paths"]):
                return

            removed_name = os.path.basename(state["paths"][index_to_remove])

            state["paths"] = [
                path for idx, path in enumerate(state["paths"])
                if idx != index_to_remove
            ]
            post_notice(f"Se quitó {removed_name} de la selección.", level="info")

            remaining = len(state["paths"])
            if remaining == 0:
                post_notice("La selección quedó vacía.", level="info")
            elif remaining < 2:
                post_notice("Carga al menos 2 archivos para habilitar la consolidacion.", level="info")

            refresh_file_list()

        def merge_selected_paths(new_paths: list[str], append: bool) -> tuple[list[str], list[str], list[str]]:
            base_paths = state["paths"] if append else []
            merged_paths = []
            seen = set()
            added_paths = []
            duplicate_paths = []

            for path in base_paths:
                normalized = os.path.normcase(os.path.abspath(path))
                if normalized in seen:
                    continue
                seen.add(normalized)
                merged_paths.append(path)

            for path in new_paths:
                normalized = os.path.normcase(os.path.abspath(path))
                if normalized in seen:
                    duplicate_paths.append(path)
                    continue
                seen.add(normalized)
                merged_paths.append(path)
                added_paths.append(path)

            return merged_paths, added_paths, duplicate_paths

        def open_files_picker(_=None, append=False):
            if state["busy"]:
                return
            state["append_mode"] = append
            files_picker.pick_files(
                allow_multiple=True,
                allowed_extensions=["xlsx", "xlsm", "xls"],
            )

        add_more_link.on_click = lambda _: open_files_picker(append=True)

        def update_upload_zone(total: int):
            is_ready = total >= 2
            if total <= 0:
                upload_zone_badge_text.value = "LISTO PARA CARGAR"
                upload_zone_badge.bgcolor = ft.colors.with_opacity(0.14, ft.colors.TEAL_300)
                upload_zone_badge.border = ft.border.all(1, ft.colors.with_opacity(0.20, ft.colors.TEAL_100))
                upload_zone_icon.bgcolor = ft.colors.with_opacity(0.15, ft.colors.TEAL_300)
                upload_zone_icon.content = ft.Icon(ft.icons.UPLOAD_FILE_ROUNDED, size=32, color=ft.colors.TEAL_100)
                upload_zone_title.value = "Clic aquí para cargar archivos"
                upload_zone_subtitle.value = (
                    "Haz clic aqui para seleccionar 2 o mas archivos y empezar la consolidacion."
                )
                upload_zone_action.bgcolor = ft.colors.with_opacity(0.10, ft.colors.BLUE_300)
                upload_zone.bgcolor = ft.colors.with_opacity(0.07, ft.colors.TEAL_400)
                upload_zone.border = ft.border.all(1.4, ft.colors.with_opacity(0.32, ft.colors.TEAL_200))
                return

            upload_zone_badge_text.value = f"{total} ARCHIVO(S) CARGADO(S)"
            upload_zone_icon.content = ft.Icon(
                ft.icons.TASK_ALT_ROUNDED if is_ready else ft.icons.UPLOAD_FILE_ROUNDED,
                size=32,
                color=ft.colors.GREEN_100 if is_ready else ft.colors.TEAL_100,
            )
            upload_zone_icon.bgcolor = ft.colors.with_opacity(
                0.18,
                ft.colors.GREEN_400 if is_ready else ft.colors.TEAL_300,
            )
            upload_zone_badge.bgcolor = ft.colors.with_opacity(
                0.16,
                ft.colors.GREEN_400 if is_ready else ft.colors.AMBER_400,
            )
            upload_zone_badge.border = ft.border.all(
                1,
                ft.colors.with_opacity(0.22, ft.colors.GREEN_100 if is_ready else ft.colors.AMBER_100),
            )
            upload_zone_title.value = "Archivos listos para consolidar" if is_ready else "Carga al menos 2 archivos"
            upload_zone_subtitle.value = (
                "Puedes hacer clic aqui para reemplazar la seleccion actual antes de generar el consolidado."
                if is_ready
                else "Aun falta al menos 1 archivo mas. Haz clic aqui para reemplazar la seleccion actual."
            )
            upload_zone_action.bgcolor = ft.colors.with_opacity(
                0.10,
                ft.colors.GREEN_500 if is_ready else ft.colors.BLUE_300,
            )
            upload_zone.bgcolor = ft.colors.with_opacity(
                0.08,
                ft.colors.GREEN_500 if is_ready else ft.colors.TEAL_400,
            )
            upload_zone.border = ft.border.all(
                1.4,
                ft.colors.with_opacity(0.34, ft.colors.GREEN_200 if is_ready else ft.colors.TEAL_200),
            )

        def on_upload_zone_hover(e: ft.HoverEvent):
            if state["busy"]:
                return
            is_hover = e.data == "true"
            total = len(state["paths"])
            is_ready = total >= 2
            base_color = ft.colors.GREEN_500 if is_ready else ft.colors.TEAL_400
            border_color = ft.colors.GREEN_200 if is_ready else ft.colors.TEAL_200
            e.control.bgcolor = ft.colors.with_opacity(0.11 if is_hover else 0.08 if total > 0 else 0.07, base_color)
            e.control.border = ft.border.all(1.6 if is_hover else 1.4, ft.colors.with_opacity(0.48 if is_hover else 0.34 if total > 0 else 0.32, border_color))
            e.control.update()

        upload_zone.on_click = open_files_picker
        upload_zone.on_hover = on_upload_zone_hover
        update_upload_zone(0)

        def refresh_file_list():
            files_list.controls.clear()
            for index, path in enumerate(state["paths"], start=1):
                files_list.controls.append(
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=12, vertical=10),
                        border_radius=10,
                        bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
                        content=ft.Row(
                            [
                                ft.Text(f"{index}.", width=26, color=ft.colors.TEAL_300, weight=ft.FontWeight.BOLD),
                                ft.Icon(ft.icons.DESCRIPTION_ROUNDED, size=18, color=ft.colors.TEAL_300),
                                ft.Text(os.path.basename(path), expand=True, color=ft.colors.WHITE, no_wrap=False),
                                ft.Container(
                                    width=28,
                                    height=28,
                                    border_radius=14,
                                    bgcolor=ft.colors.with_opacity(0.14, ft.colors.RED_400),
                                    alignment=ft.alignment.center,
                                    ink=True,
                                    tooltip="Quitar archivo",
                                    on_click=lambda _, idx=index - 1: remove_selected_file(idx),
                                    content=ft.Text(
                                        "X",
                                        size=12,
                                        color=ft.colors.RED_100,
                                        weight=ft.FontWeight.W_900,
                                    ),
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            total = len(state["paths"])
            selected_count.value = f"{total} archivo(s) seleccionado(s)"
            selected_count.visible = total > 0
            add_more_link.visible = total > 0
            selection_toolbar.visible = total > 0
            upload_zone.visible = total == 0
            files_container.visible = total > 0
            update_upload_zone(total)
            btn_merge.disabled = state["busy"] or total < 2

            page.update()

        def get_suggested_output_name() -> str:
            if not state["paths"]:
                return "excel_unificado.xlsx"
            base_name = os.path.splitext(os.path.basename(state["paths"][0]))[0]
            return f"{base_name}_unificado.xlsx"

        def set_action_buttons(disabled: bool):
            state["busy"] = disabled
            btn_merge.disabled = disabled or len(state["paths"]) < 2
            if disabled:
                upload_zone.bgcolor = ft.colors.with_opacity(0.06, ft.colors.GREY_700)
                upload_zone.border = ft.border.all(1.4, ft.colors.with_opacity(0.18, ft.colors.GREY_400))
            else:
                update_upload_zone(len(state["paths"]))
            page.update()

        def on_files_picked(e: ft.FilePickerResultEvent):
            append_mode = state["append_mode"]
            state["append_mode"] = False
            if not e.files:
                return

            selected_paths = [f.path for f in e.files if f.path]
            if not selected_paths:
                return

            if not append_mode:
                logs_list.controls.clear()

            state["paths"], added_paths, duplicate_paths = merge_selected_paths(
                selected_paths,
                append=append_mode,
            )

            if len(state["paths"]) < 2:
                if duplicate_paths:
                    post_notice(
                        f"Se omitieron {len(duplicate_paths)} archivo(s) repetidos. Carga al menos 2 archivos para habilitar la consolidacion.",
                        level="warning",
                    )
                else:
                    post_notice("Carga al menos 2 archivos para habilitar la consolidacion.", level="info")
            else:
                if duplicate_paths and added_paths:
                    post_notice(
                        f"Se añadieron {len(added_paths)} archivo(s) y se omitieron {len(duplicate_paths)} repetidos.",
                        level="warning",
                    )
                elif duplicate_paths:
                    post_notice(
                        f"No se añadió ningún archivo nuevo. {len(duplicate_paths)} archivo(s) ya estaban en la selección.",
                        level="warning",
                    )
                elif append_mode and added_paths:
                    post_notice(f"Se añadieron {len(added_paths)} archivo(s) a la selección.", level="success")
                elif not append_mode:
                    post_notice(
                        "La carpeta destino y el nombre del archivo se pedirán al presionar Unir archivos.",
                        level="info",
                    )
            refresh_file_list()

        def on_save_picked(e: ft.FilePickerResultEvent):
            if not e.path:
                set_action_buttons(False)
                post_notice("Guardado cancelado por el usuario.", level="info")
                return

            output_path = e.path
            if not output_path.lower().endswith(".xlsx"):
                output_path += ".xlsx"

            normalized_output = os.path.normcase(os.path.abspath(output_path))
            selected_inputs = {os.path.normcase(os.path.abspath(path)) for path in state["paths"]}
            if normalized_output in selected_inputs:
                set_action_buttons(False)
                post_notice("El archivo de salida no puede ser uno de los archivos seleccionados como origen.", level="error")
                return

            process_merge(output_path)

        files_picker = ft.FilePicker(on_result=on_files_picked)
        save_picker = ft.FilePicker(on_result=on_save_picked)
        page.overlay.extend([files_picker, save_picker])
        page.update()

        def close_alert(e):
            nonlocal alert_dialog
            if alert_dialog:
                alert_dialog.open = False
                page.update()

        def process_merge(output_path: str):
            nonlocal alert_dialog
            def process_merge():
                nonlocal alert_dialog
                progress_bar.visible = True
                progress_bar.value = None
                post_notice("Validando cabeceras y consolidando archivos Excel...", level="info", clear_logs=True)
                page.update()

                try:
                    result = merge_manager.merge_files(state["paths"], output_path)
                    excluded_count = len(result.excluded_files)
                    post_notice(
                        f"Consolidado completado. {len(result.included_files)} aceptados, {excluded_count} excluidos, {result.total_rows_written} filas.",
                        level="success",
                    )

                    excluded_summary = "\n".join(
                        f"- {os.path.basename(item['path'])}: {item['reason']}"
                        for item in result.excluded_files
                    ) or "Ningún archivo fue excluido."

                    alert_dialog = ft.AlertDialog(
                        title=ft.Row([
                            ft.Icon(ft.icons.CHECK_CIRCLE_ROUNDED, color=ft.colors.GREEN_400),
                            ft.Text("Consolidación completada", weight=ft.FontWeight.W_900),
                        ]),
                        content=ft.Column(
                            [
                                ft.Text(f"Archivo generado: {result.output_path}", selectable=True),
                                ft.Text(
                                    f"Archivos aceptados: {len(result.included_files)} | Excluidos: {excluded_count} | Filas unificadas: {result.total_rows_written}",
                                    size=13,
                                ),
                                ft.Text("Archivos excluidos:", weight=ft.FontWeight.BOLD),
                                ft.Text(excluded_summary, size=12, selectable=True),
                            ],
                            tight=True,
                            spacing=10,
                        ),
                        actions=[ft.ElevatedButton("Entendido", on_click=close_alert)],
                        open=True,
                        shape=ft.RoundedRectangleBorder(radius=16),
                    )
                    page.overlay.append(alert_dialog)
                except Exception as exc:
                    post_notice(f"Error: {exc}", level="error")
                finally:
                    progress_bar.visible = False
                    set_action_buttons(False)

            threading.Thread(target=process_merge, daemon=True).start()

        def run_merge(e):
            if len(state["paths"]) < 2:
                post_notice("Debes seleccionar 2 o más archivos Excel.", level="error")
                return

            set_action_buttons(True)
            post_notice("Selecciona la carpeta destino y el nombre del archivo consolidado.", level="info")

            initial_directory = os.path.dirname(state["paths"][0]) if state["paths"] else None
            save_picker.save_file(
                dialog_title="Guardar consolidado Excel",
                file_name=get_suggested_output_name(),
                initial_directory=initial_directory,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx"],
            )
        btn_merge = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.SAVE, color=ft.colors.WHITE, size=20),
                ft.Text("UNIR ARCHIVOS", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=13),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            style=ft.ButtonStyle(
                bgcolor=ft.colors.TEAL_700,
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            height=45,
            width=220,
            disabled=True,
            on_click=run_merge,
        )

        return ft.Container(
            padding=40,
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    self._section_header(
                        self.metadata.icono,
                        self.metadata.color,
                        "Unir archivos Excel",
                        "Consolida varios Excel en uno solo validando que compartan las mismas cabeceras.",
                        right_content=self._back_button("Volver a Herramientas", navigate_fn, 2),
                    ),
                    ft.Divider(height=10, color=ft.colors.TRANSPARENT),
                    ft.ResponsiveRow([
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 5},
                            padding=ft.padding.only(top=35, bottom=35, left=35, right=35),
                            bgcolor=ft.colors.BLUE_GREY_900,
                            border_radius=16,
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.SETTINGS_ROUNDED, color=ft.colors.TEAL_400, size=24),
                                    ft.Text("Parámetros de consolidación", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                                ], spacing=10),
                                ft.Divider(color=ft.colors.WHITE24, height=15),
                                upload_zone,
                                selection_toolbar,
                                files_container,
                                ft.Container(height=10),
                                progress_bar,
                                ft.Row([btn_merge], alignment=ft.MainAxisAlignment.END),
                            ], spacing=8),
                        ),
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 7},
                            padding=30,
                            bgcolor=ft.colors.SURFACE_VARIANT,
                            border_radius=20,
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400),
                                    ft.Text("Validación y resultados", size=18, weight=ft.FontWeight.BOLD),
                                ]),
                                ft.Divider(height=15, color=ft.colors.TRANSPARENT),
                                ft.Container(
                                    content=logs_list,
                                    bgcolor=ft.colors.BACKGROUND,
                                    border_radius=10,
                                    padding=15,
                                    height=420,
                                ),
                            ])
                        ),
                    ], spacing=30),
                ],
                spacing=10,
            ),
        )