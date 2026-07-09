from pathlib import Path
import threading
import flet as ft

from tformdet_append_manager import TformdetAppendError, TformdetAppendManager
from tools.app_config import get as cfg_get, set as cfg_set
from tools.base_tool import SismedTool, ToolMetadata


class TformdetAppendTool(SismedTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Anexar TFORMDET",
            descripcion="Agrega meses nuevos desde otro DBF TFORMDET",
            icono=ft.icons.DATA_OBJECT_ROUNDED,
            color=ft.colors.TEAL_400,
            categoria="Herramientas",
            etiquetas=[
                "dbf",
                "tformdet",
                "append",
                "anexar",
                "importar",
                "periodos",
                "herramientas",
            ],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        manager = TformdetAppendManager()
        analysis_state = {"value": None}

        def _button_style(color):
            return ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: color},
                color=ft.colors.WHITE,
                padding=ft.padding.symmetric(horizontal=18, vertical=14),
                shape=ft.RoundedRectangleBorder(radius=10),
            )

        def _resolve_destination_from_folder(folder_value: str) -> tuple[str, str]:
            raw = (folder_value or "").strip()
            if not raw:
                return "", ""

            folder = Path(raw)
            if folder.name.lower() == "datos" and (folder / "TFORMDET.DBF").exists():
                return str(folder.parent), str(folder / "TFORMDET.DBF")

            dbf_path = folder / "datos" / "TFORMDET.DBF"
            if dbf_path.exists():
                return str(folder), str(dbf_path)

            dbf_path_upper = folder / "DATOS" / "TFORMDET.DBF"
            if dbf_path_upper.exists():
                return str(folder), str(dbf_path_upper)

            return str(folder), str(folder / "datos" / "TFORMDET.DBF")

        source_field = ft.TextField(
            label="Archivo DBF a importar",
            value=cfg_get("tformdet_append_source_file") or "",
            read_only=True,
            expand=True,
            border_radius=10,
            border_color=ft.colors.WHITE24,
            focused_border_color=self.metadata.color,
            prefix_icon=ft.icons.UPLOAD_FILE_ROUNDED,
            text_size=12,
        )
        sismed_dir_field = ft.TextField(
            label="Carpeta SISMED destino",
            value=cfg_get("tformdet_append_sismed_dir") or cfg_get("tformdet_sismed_dir") or "",
            read_only=True,
            expand=True,
            border_radius=10,
            border_color=ft.colors.WHITE24,
            focused_border_color=self.metadata.color,
            prefix_icon=ft.icons.FOLDER_ROUNDED,
            text_size=12,
        )
        destination_dbf_text = ft.Text("", size=12, color=ft.colors.GREY_500, selectable=True)
        status_icon = ft.Icon(ft.icons.INFO_OUTLINE_ROUNDED, color=ft.colors.BLUE_300, size=22)
        status_title = ft.Text(
            "Pendiente de analisis",
            size=13,
            color=ft.colors.WHITE,
            weight=ft.FontWeight.W_800,
        )
        status_detail = ft.Text(
            "Seleccione el origen y el SISMED destino. Luego presione Procesar.",
            size=12,
            color=ft.colors.GREY_300,
            no_wrap=False,
        )
        status_card = ft.Container(
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            bgcolor=ft.colors.with_opacity(0.10, ft.colors.BLUE_300),
            border=ft.border.all(1, ft.colors.with_opacity(0.28, ft.colors.BLUE_300)),
            content=ft.Row(
                [
                    status_icon,
                    ft.Column([status_title, status_detail], spacing=2, expand=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )
        progress = ft.ProgressBar(
            visible=False,
            value=None,
            color=self.metadata.color,
            bgcolor=ft.colors.WHITE24,
        )
        console = ft.ListView(expand=True, spacing=6, auto_scroll=True)

        btn_action = ft.ElevatedButton(
            "PROCESAR",
            icon=ft.icons.PLAY_ARROW_ROUNDED,
            height=48,
            style=_button_style(ft.colors.BLUE_GREY_700),
        )

        def _destination_dbf_path() -> str:
            _, dbf_path = _resolve_destination_from_folder(sismed_dir_field.value)
            return dbf_path

        def _refresh_destination_preview() -> None:
            folder, dbf_path = _resolve_destination_from_folder(sismed_dir_field.value)
            if not folder:
                destination_dbf_text.value = "TFORMDET destino: pendiente"
                destination_dbf_text.color = ft.colors.GREY_500
            elif Path(dbf_path).exists():
                destination_dbf_text.value = f"TFORMDET detectado: {dbf_path}"
                destination_dbf_text.color = ft.colors.GREEN_300
            else:
                destination_dbf_text.value = f"No se encontro: {dbf_path}"
                destination_dbf_text.color = ft.colors.RED_300

        def _icon_for_log(message: str, color) -> str:
            text = message.strip().lower()
            if color == ft.colors.RED_300 or "error" in text or "no se puede" in text:
                return ft.icons.ERROR_OUTLINE_ROUNDED
            if color == ft.colors.AMBER_300 or text.startswith("aviso"):
                return ft.icons.WARNING_AMBER_ROUNDED
            if color == ft.colors.GREEN_300 or "correctamente" in text or "resultado" in text:
                return ft.icons.CHECK_CIRCLE_ROUNDED
            if text.startswith("archivo origen") or text.startswith("sismed destino"):
                return ft.icons.INFO_OUTLINE_ROUNDED
            if "estructura" in text:
                return ft.icons.DATA_OBJECT_ROUNDED
            if "validando" in text or "verificando" in text:
                return ft.icons.TUNE_ROUNDED
            if "leyendo" in text:
                return ft.icons.DATA_OBJECT_ROUNDED
            if "comparando" in text or "duplicados" in text:
                return ft.icons.SYNC_ROUNDED
            if "copia de seguridad" in text:
                return ft.icons.FOLDER_ROUNDED
            if "preparando" in text or "escribiendo" in text or "agregando" in text:
                return ft.icons.UPLOAD_FILE_ROUNDED
            return ft.icons.INFO_OUTLINE_ROUNDED

        def _log(message: str, color=ft.colors.GREY_300, icon=None) -> None:
            clean_message = message.strip()
            icon_name = icon or _icon_for_log(clean_message, color)
            console.controls.append(
                ft.Row(
                    [
                        ft.Icon(icon_name, size=16, color=color),
                        ft.Text(
                            clean_message,
                            size=12,
                            color=color,
                            selectable=True,
                            no_wrap=False,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )
            page.update()

        def _format_periods(periods, limit=None) -> str:
            values = sorted(set(periods))
            if not values:
                return "-"
            if limit:
                values = values[:limit]
            return ", ".join(_friendly_period(value) for value in values)

        def _records_for_keys(analysis, keys: list[str]) -> int:
            return sum(analysis.source_key_counts.get(key, 0) for key in keys)

        def _friendly_period(period: str) -> str:
            period = str(period or "").strip()
            if len(period) == 6 and period[:4].isdigit() and period[4:].isdigit():
                return f"{period[:4]}-{period[4:]}"
            return period

        def _friendly_warning(message: str) -> str:
            if "indices DBF" in message or "TFORMDET.CDX" in message:
                return "Se encontro el archivo auxiliar de SISMED. Se guardara una copia de seguridad antes de continuar."
            if "columnas" in message or "Campos comunes" in message:
                return "El archivo tiene una estructura distinta, pero el sistema intentara adaptarlo sin perder los datos principales."
            return message

        def _friendly_error(message: str) -> str:
            if "Permission denied" in message or "Errno 13" in message:
                return (
                    "Windows no permitio abrir uno de los archivos DBF. "
                    "Esto suele pasar cuando el archivo esta abierto en SISMED, FoxPro, Excel u otra ventana. "
                    "Cierre ese programa y vuelva a presionar Procesar."
                )
            if "No se puede crear el backup" in message:
                return (
                    "No se pudo crear la copia de seguridad antes de modificar TFORMDET. "
                    "Cierre SISMED o FoxPro si estan usando esa carpeta y vuelva a presionar Procesar."
                )
            if "No se puede escribir en el destino" in message:
                return (
                    "No se pudo modificar el TFORMDET destino. "
                    "Cierre SISMED o FoxPro en esa instalacion y vuelva a presionar Procesar."
                )
            if "Valor numerico no cabe" in message:
                return "Hay un valor demasiado grande para el TFORMDET destino. No se hizo ningun cambio."
            if "no contiene datos\\TFORMDET.DBF" in message:
                return "La carpeta seleccionada no parece ser una carpeta SISMED valida."
            return message

        def _friendly_permission_error(exc: PermissionError) -> tuple[str, str]:
            blocked_path = str(getattr(exc, "filename", "") or "")
            source_path = str(source_field.value or "")
            destination_path = str(_destination_dbf_path() or "")
            normalized_blocked = blocked_path.lower()

            if source_path and normalized_blocked == source_path.lower():
                return (
                    "Archivo origen en uso",
                    (
                        "No pude leer el DBF que quiere agregar porque Windows lo tiene bloqueado. "
                        "Cierre FoxPro, Excel u otra ventana donde este abierto ese archivo, "
                        "luego vuelva a presionar Procesar."
                    ),
                )

            if destination_path and normalized_blocked == destination_path.lower():
                return (
                    "TFORMDET destino en uso",
                    (
                        "No pude abrir el TFORMDET del SISMED destino. "
                        "Cierre SISMED o FoxPro en esa instalacion antes de volver a procesar."
                    ),
                )

            return (
                "Archivo en uso",
                (
                    "Windows bloqueo el acceso a un archivo necesario para anexar los datos. "
                    "Cierre SISMED, FoxPro, Excel o cualquier ventana que use esos DBF y vuelva a presionar Procesar."
                ),
            )

        def _set_import_button(text: str, color) -> None:
            btn_action.text = text
            btn_action.style = _button_style(color)

        def _set_status(title: str, detail: str, icon, color) -> None:
            status_icon.name = icon
            status_icon.color = color
            status_title.value = title
            status_detail.value = detail
            status_card.bgcolor = ft.colors.with_opacity(0.10, color)
            status_card.border = ft.border.all(1, ft.colors.with_opacity(0.28, color))

        def _set_busy(is_busy: bool) -> None:
            progress.visible = is_busy
            btn_action.disabled = is_busy
            if is_busy:
                _set_import_button("PROCESANDO", ft.colors.BLUE_GREY_700)
            else:
                _sync_import_button_state()
            page.update()

        def _sync_import_button_state() -> None:
            analysis = analysis_state["value"]
            if not analysis:
                _set_import_button("PROCESAR", ft.colors.TEAL_700)
                btn_action.icon = ft.icons.PLAY_ARROW_ROUNDED
                return

            if analysis.errors:
                _set_import_button("REINTENTAR", ft.colors.RED_700)
                btn_action.icon = ft.icons.REPLAY_ROUNDED
                _set_status(
                    "Importacion bloqueada",
                    "No se modifico TFORMDET. Revise el detalle en la consola.",
                    ft.icons.BLOCK_ROUNDED,
                    ft.colors.RED_400,
                )
            elif analysis.records_to_import == 0:
                _set_import_button("REVISAR DE NUEVO", ft.colors.AMBER_700)
                btn_action.icon = ft.icons.REFRESH_ROUNDED
                _set_status(
                    "Sin datos nuevos",
                    "Todo el archivo ya estaba cargado para el mismo establecimiento y mes. No se agregara nada.",
                    ft.icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                    ft.colors.AMBER_400,
                )
            else:
                _set_import_button("PROCESAR", ft.colors.TEAL_700)
                btn_action.icon = ft.icons.PLAY_ARROW_ROUNDED
                _set_status(
                    "Listo para procesar",
                    "Hay meses nuevos. Al procesar se creara una copia de seguridad y se agregaran automaticamente.",
                    ft.icons.CHECK_CIRCLE_ROUNDED,
                    ft.colors.GREEN_400,
                )

        def _invalidate_analysis() -> None:
            analysis_state["value"] = None
            _set_status(
                "Cambios pendientes",
                "Las rutas cambiaron. Analice nuevamente antes de importar.",
                ft.icons.WARNING_AMBER_ROUNDED,
                ft.colors.AMBER_400,
            )
            _sync_import_button_state()
            page.update()

        def _set_source(path: str) -> None:
            source_field.value = path
            cfg_set("tformdet_append_source_file", path)
            _invalidate_analysis()

        def _set_sismed_folder(path: str) -> None:
            folder, _ = _resolve_destination_from_folder(path)
            sismed_dir_field.value = folder
            cfg_set("tformdet_append_sismed_dir", folder)
            _refresh_destination_preview()
            _invalidate_analysis()

        def _on_source_picked(e) -> None:
            if e.files:
                _set_source(e.files[0].path)

        def _on_destination_picked(e) -> None:
            if e.path:
                _set_sismed_folder(e.path)

        source_picker = ft.FilePicker(on_result=_on_source_picked)
        destination_picker = ft.FilePicker(on_result=_on_destination_picked)
        page.overlay.extend([source_picker, destination_picker])
        page.update()

        def _validate_paths_for_analysis() -> bool:
            if not source_field.value:
                _set_status(
                    "Falta archivo origen",
                    "Seleccione el DBF que desea agregar.",
                    ft.icons.ERROR_OUTLINE_ROUNDED,
                    ft.colors.RED_400,
                )
                page.update()
                return False
            if not sismed_dir_field.value:
                _set_status(
                    "Falta carpeta SISMED",
                    "Seleccione la carpeta principal del SISMED destino.",
                    ft.icons.ERROR_OUTLINE_ROUNDED,
                    ft.colors.RED_400,
                )
                page.update()
                return False
            destination = _destination_dbf_path()
            if not Path(destination).exists():
                _set_status(
                    "No se encontro TFORMDET",
                    "La carpeta seleccionada no contiene datos\\TFORMDET.DBF.",
                    ft.icons.ERROR_OUTLINE_ROUNDED,
                    ft.colors.RED_400,
                )
                _refresh_destination_preview()
                page.update()
                return False
            return True

        def _process_one_click(e=None) -> None:
            if not _validate_paths_for_analysis():
                return

            def _worker() -> None:
                console.controls.clear()
                _set_busy(True)
                try:
                    destination = _destination_dbf_path()

                    def _progress(message: str) -> None:
                        clean = message.strip().lower()
                        if "correctamente" in clean or "finalizada" in clean:
                            color = ft.colors.GREEN_300
                        elif clean.startswith("aviso"):
                            color = ft.colors.AMBER_300
                        elif "error" in clean or "no se puede" in clean:
                            color = ft.colors.RED_300
                        elif message.startswith("   "):
                            color = ft.colors.GREY_300
                        else:
                            color = ft.colors.CYAN_200
                        _log(message, color)

                    analysis = manager.analyze(
                        source_field.value,
                        destination,
                        progress=_progress,
                    )
                    analysis_state["value"] = analysis

                    _log("Resumen del analisis:", ft.colors.CYAN_200)
                    _log(
                        (
                            f"   Archivo origen: {analysis.source_header.record_count:,} filas, "
                            f"{len(analysis.source_codigo_pre_counts)} establecimiento(s), "
                            f"{len(analysis.source_period_counts)} mes(es)."
                        ),
                        ft.colors.GREY_300,
                    )
                    _log(
                        "   Meses encontrados: " + _format_periods(analysis.source_period_counts),
                        ft.colors.GREY_300,
                    )
                    _log(
                        (
                            f"   Destino actual: {analysis.destination_header.record_count:,} filas, "
                            f"{len(analysis.destination_codigo_pres)} establecimiento(s), "
                            f"{len(analysis.destination_periods)} mes(es) cargados."
                        ),
                        ft.colors.GREY_300,
                    )
                    _log(
                        "   Regla de duplicados: si el mismo establecimiento ya tiene el mismo mes, no se repite.",
                        ft.colors.GREY_300,
                    )
                    duplicate_rows = _records_for_keys(analysis, analysis.duplicate_keys)
                    if duplicate_rows:
                        _log(
                            f"   Ya estaban cargadas: {duplicate_rows:,} filas. Se omitiran.",
                            ft.colors.AMBER_300,
                        )
                    if analysis.records_to_import:
                        _log(
                            (
                                f"   Datos nuevos encontrados: {analysis.records_to_import:,} filas "
                                f"para {len(analysis.codigo_pres_to_import_counts)} establecimiento(s)."
                            ),
                            ft.colors.GREEN_300,
                        )
                        _log(
                            "   Meses que se agregaran: "
                            + _format_periods(analysis.periods_to_import),
                            ft.colors.GREEN_300,
                        )
                    else:
                        _log(
                            "   No se encontro informacion nueva para agregar.",
                            ft.colors.AMBER_300,
                        )

                    for warning in analysis.warnings:
                        _log("Aviso: " + _friendly_warning(warning), ft.colors.AMBER_300)
                    for error in analysis.errors:
                        _log("No se puede continuar: " + _friendly_error(error), ft.colors.RED_300)

                    if analysis.errors:
                        _set_status(
                            "Importacion bloqueada",
                            "No se modifico TFORMDET. Revise el detalle en la consola.",
                            ft.icons.BLOCK_ROUNDED,
                            ft.colors.RED_400,
                        )
                        return

                    if analysis.records_to_import == 0:
                        _set_status(
                            "Sin datos nuevos",
                            "Todo el archivo ya estaba cargado para el mismo establecimiento y mes. No se agrego nada.",
                            ft.icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                            ft.colors.AMBER_400,
                        )
                        return

                    _set_status(
                        "Agregando meses nuevos",
                        "Creando copia de seguridad y agregando filas en TFORMDET.",
                        ft.icons.SYNC_ROUNDED,
                        ft.colors.CYAN_300,
                    )
                    result = manager.append_new_periods(
                        source_field.value,
                        destination,
                        analysis=analysis,
                        progress=_progress,
                    )

                    _log(
                        "Proceso finalizado correctamente.",
                        ft.colors.GREEN_300,
                    )
                    _log(
                        f"Resultado: se agregaron {result.imported_records:,} filas nuevas.",
                        ft.colors.GREEN_300,
                    )
                    _log(
                        f"Establecimientos actualizados: {len(analysis.codigo_pres_to_import_counts)}.",
                        ft.colors.GREEN_300,
                    )
                    _log(
                        "Meses agregados: " + _format_periods(result.imported_periods),
                        ft.colors.GREEN_300,
                    )
                    if duplicate_rows:
                        _log(
                            f"Filas omitidas porque ya existian: {duplicate_rows:,}.",
                            ft.colors.AMBER_300,
                        )
                    _log(
                        f"Total de filas en destino: {result.previous_record_count:,} -> "
                        f"{result.new_record_count:,}.",
                        ft.colors.GREY_300,
                    )
                    _set_status(
                        "Importacion completada",
                        f"Se agregaron {result.imported_records:,} filas correctamente.",
                        ft.icons.CHECK_CIRCLE_ROUNDED,
                        ft.colors.GREEN_400,
                    )
                    analysis_state["value"] = None
                except TformdetAppendError as exc:
                    detail = _friendly_error(str(exc))
                    _set_status(
                        "No se pudo importar",
                        detail,
                        ft.icons.ERROR_OUTLINE_ROUNDED,
                        ft.colors.RED_400,
                    )
                    _log("No se pudo continuar: " + detail, ft.colors.RED_300)
                except PermissionError as exc:
                    title, detail = _friendly_permission_error(exc)
                    _set_status(
                        title,
                        detail,
                        ft.icons.LOCK_ROUNDED,
                        ft.colors.RED_400,
                    )
                    _log("No se pudo continuar: " + detail, ft.colors.RED_300)
                except Exception as exc:
                    detail = _friendly_error(str(exc))
                    _set_status(
                        "No se pudo procesar",
                        detail,
                        ft.icons.ERROR_OUTLINE_ROUNDED,
                        ft.colors.RED_400,
                    )
                    _log("No se pudo continuar: " + detail, ft.colors.RED_300)
                finally:
                    _set_busy(False)

            threading.Thread(target=_worker, daemon=True).start()

        btn_action.on_click = _process_one_click

        btn_pick_source = ft.ElevatedButton(
            "Buscar archivo",
            icon=ft.icons.FOLDER_OPEN_ROUNDED,
            height=48,
            style=_button_style(ft.colors.BLUE_GREY_700),
            on_click=lambda _: source_picker.pick_files(
                allow_multiple=False, allowed_extensions=["dbf"]
            ),
        )
        btn_pick_destination = ft.ElevatedButton(
            "Buscar carpeta",
            icon=ft.icons.FOLDER_OPEN_ROUNDED,
            height=48,
            style=_button_style(ft.colors.BLUE_GREY_700),
            on_click=lambda _: destination_picker.get_directory_path(),
        )

        def _step_title(number: str, text: str) -> ft.Control:
            return ft.Row(
                [
                    ft.Container(
                        content=ft.Text(number, size=12, weight=ft.FontWeight.W_800),
                        width=26,
                        height=26,
                        alignment=ft.alignment.center,
                        border_radius=13,
                        bgcolor=ft.colors.with_opacity(0.16, self.metadata.color),
                    ),
                    ft.Text(text, size=14, weight=ft.FontWeight.W_800),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        config_panel = ft.Container(
            bgcolor=ft.colors.SURFACE_VARIANT,
            border_radius=20,
            padding=30,
            expand=5,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.icons.TUNE_ROUNDED, color=self.metadata.color),
                            ft.Text(
                                "Configuracion",
                                size=18,
                                weight=ft.FontWeight.W_800,
                                color=ft.colors.WHITE,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(color=ft.colors.WHITE24),
                    _step_title("1", "Seleccione el DBF que quiere agregar"),
                    ft.Row([source_field, btn_pick_source], spacing=10),
                    ft.Container(height=2),
                    _step_title("2", "Seleccione la carpeta principal del SISMED destino"),
                    ft.Row([sismed_dir_field, btn_pick_destination], spacing=10),
                    destination_dbf_text,
                    ft.Container(height=4),
                    _step_title("3", "Procese en un clic"),
                    status_card,
                    progress,
                    ft.Row(
                        [btn_action],
                        spacing=12,
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

        console_panel = ft.Container(
            bgcolor=ft.colors.SURFACE_VARIANT,
            border_radius=20,
            padding=30,
            expand=7,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400),
                            ft.Text(
                                "Console/Actividad",
                                size=18,
                                weight=ft.FontWeight.W_800,
                                color=ft.colors.WHITE,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Container(
                        bgcolor="#0E1116",
                        border_radius=10,
                        padding=18,
                        expand=True,
                        content=console,
                    ),
                ],
                spacing=14,
            ),
        )

        _refresh_destination_preview()
        _sync_import_button_state()

        return ft.Container(
            padding=40,
            expand=True,
            content=ft.Column(
                [
                    self._section_header(
                        self.metadata.icono,
                        self.metadata.color,
                        "Anexar TFORMDET",
                        "Agrega meses nuevos desde un DBF hacia SISMED",
                        right_content=self._back_button(
                            "Volver a Herramientas", navigate_fn, 2
                        ),
                    ),
                    ft.Container(height=10),
                    ft.Row(
                        [config_panel, console_panel],
                        expand=True,
                        spacing=20,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ],
                expand=True,
                spacing=0,
            ),
        )
