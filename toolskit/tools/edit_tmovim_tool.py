import threading
import re
import flet as ft
from edit_sismed_manager import EditSismedManager
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import get as cfg_get, set as cfg_set


class EditTmovimTool(SismedTool):
    """Herramienta para modificar MOVSITUA y eliminar bloqueos en TMOVIM.DBF."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Habilitar Guías",
            descripcion="Habilita guías anuladas y guias cerradas TMOVIM.DBF",
            icono=ft.icons.EDIT_DOCUMENT,
            color=ft.colors.PURPLE_400,
            categoria="Edit SISMED",
            etiquetas=["editar", "tmovim", "guia", "movsitua", "bloqueo", "sismed", "modificar", "desbloquear"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        # ── Variables de Estado ─────────────────────────────────────────────────
        sismed_dir_field = ft.TextField(
            value=cfg_get("tmovim_sismed_dir"), label="Ruta SISMED", read_only=True,
            prefix_icon=ft.icons.FOLDER, border_radius=12, text_size=12, expand=True,
            border_color=ft.colors.WHITE24,
        )
        guia_list = []
        selected_indices = set()

        # ── FilePicker ──────────────────────────────────────────────────────────
        def folder_picker_result(e):
            if e.path:
                sismed_dir_field.value = e.path
                cfg_set("tmovim_sismed_dir", e.path)
                sismed_dir_field.update()

        dir_picker = ft.FilePicker(on_result=folder_picker_result)

        log_text = ft.Text("Listo para operar", size=12, color=ft.colors.GREY_500)

        # ── Selector de modo de búsqueda ────────────────────────────────────────
        def on_mode_change(e):
            nonlocal guia_list
            input_search.value = ""
            guia_list = []
            selected_indices.clear()
            results_table.rows = []
            log_text.value = ""
            _update_actions_visibility()

            is_bulk = mode_selector.selected.copy().pop() == "bulk"
            if is_bulk:
                input_search.label = "Pegar Lista de N° Movimiento"
                input_search.hint_text = "Ingrese N° Movimiento separados por línea o espacio..."
                input_search.multiline = True
                input_search.min_lines = 5
                input_search.max_lines = 10
            else:
                input_search.label = "Búsqueda por N° Movimiento"
                input_search.hint_text = "N° Movimiento (MOVNUMERO)..."
                input_search.multiline = False
                input_search.min_lines = 1
                input_search.max_lines = 1
            input_search.update()

        mode_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value="normal", label=ft.Text("Simple", size=11), icon=ft.Icon(ft.icons.SEARCH, size=18)),
                ft.Segment(value="bulk",   label=ft.Text("Masivo", size=11), icon=ft.Icon(ft.icons.LIST_ALT, size=18)),
            ],
            selected={"normal"},
            on_change=on_mode_change,
            show_selected_icon=False,
            style=ft.ButtonStyle(
                padding=ft.padding.all(20),
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
        )

        input_search = ft.TextField(
            label="Búsqueda por N° Movimiento",
            hint_text="N° Movimiento (MOVNUMERO)...",
            border_radius=12,
            text_size=14,
            width=380,
            on_submit=lambda _: _do_search(),
            border_color=ft.colors.WHITE24,
            focused_border_color=ft.colors.PURPLE_400,
        )

        # ── Selector de acción ──────────────────────────────────────────────────
        def on_action_change(e):
            _update_actions_visibility()

        action_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(
                    value="situa",
                    label=ft.Text("Revertir Anulación", size=11),
                    icon=ft.Icon(ft.icons.SWAP_HORIZ, size=18),
                ),
                ft.Segment(
                    value="bloqueo",
                    label=ft.Text("Quitar Bloqueo", size=11),
                    icon=ft.Icon(ft.icons.LOCK_OPEN, size=18),
                ),
            ],
            selected={"situa"},
            on_change=on_action_change,
            show_selected_icon=False,
            style=ft.ButtonStyle(
                padding=ft.padding.all(20),
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
        )

        # ── Tabla de Resultados ─────────────────────────────────────────────────
        results_table = ft.DataTable(
            column_spacing=16,
            heading_row_color=ft.colors.WHITE10,
            data_row_min_height=40,
            data_row_max_height=55,
            border_radius=10,
            heading_text_style=ft.TextStyle(weight="bold", color=ft.colors.GREY_300, size=12),
            columns=[
                ft.DataColumn(ft.Text("N° MOVIM.")),
                ft.DataColumn(ft.Text("N° GUÍA")),
                ft.DataColumn(ft.Text("FECHA")),
                ft.DataColumn(ft.Text("TIPO")),
                ft.DataColumn(ft.Text("SITUACIÓN")),
                ft.DataColumn(ft.Text("BLOQUEO")),
                ft.DataColumn(ft.Text("USR BLOQ.")),
            ],
            rows=[],
            show_checkbox_column=True,
            on_select_all=lambda e: _on_select_all(e.data == "true"),
        )

        def _situa_badge(situa: str) -> ft.Control:
            is_active = situa == "1"
            return ft.Container(
                content=ft.Text(
                    "Habilitada" if is_active else "Anulada",
                    size=11, weight="bold",
                    color=ft.colors.GREEN_300 if is_active else ft.colors.RED_300,
                ),
                bgcolor=ft.colors.with_opacity(0.15, ft.colors.GREEN_400 if is_active else ft.colors.RED_400),
                border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
            )

        def _on_row_select(idx, selected):
            if selected:
                selected_indices.add(idx)
                results_table.rows[idx].selected = True
            else:
                selected_indices.discard(idx)
                results_table.rows[idx].selected = False
            _update_actions_visibility()
            results_table.update()

        def _on_select_all(selected):
            selected_indices.clear()
            for i, row in enumerate(results_table.rows):
                row.selected = selected
                if selected:
                    selected_indices.add(i)
            _update_actions_visibility()
            results_table.update()

        btn_action = ft.ElevatedButton(
            "MODIFICAR SELECCIONADOS",
            icon=ft.icons.EDIT_DOCUMENT,
            on_click=lambda _: _show_action_dialog(),
            bgcolor=ft.colors.PURPLE_700,
            color=ft.colors.WHITE,
            visible=False,
            height=50,
            width=320,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )

        def _update_actions_visibility():
            has_sel = len(selected_indices) > 0
            current_action = action_selector.selected.copy().pop()
            if has_sel:
                if current_action == "situa":
                    btn_action.text   = "CAMBIAR SITUACIÓN"
                    btn_action.icon   = ft.icons.SWAP_HORIZ
                    btn_action.bgcolor = ft.colors.BLUE_700
                else:
                    btn_action.text   = "QUITAR BLOQUEO"
                    btn_action.icon   = ft.icons.LOCK_OPEN
                    btn_action.bgcolor = ft.colors.ORANGE_700
            btn_action.visible = has_sel
            btn_action.update()

        # ── Búsqueda ────────────────────────────────────────────────────────────
        def _build_rows(lista):
            rows = []
            for i, g in enumerate(lista):
                is_bulk = mode_selector.selected.copy().pop() == "bulk"
                is_sel = is_bulk
                if is_sel:
                    selected_indices.add(i)
                rows.append(ft.DataRow(
                    selected=is_sel,
                    cells=[
                        ft.DataCell(ft.Text(g["movnumero"],  weight="bold", color=ft.colors.AMBER_100)),
                        ft.DataCell(ft.Text(g["movnumedco"], size=12)),
                        ft.DataCell(ft.Text(g["movfechreg"], size=11)),
                        ft.DataCell(ft.Text(g["movcoditip"], size=11)),
                        ft.DataCell(_situa_badge(g["movsitua"])),
                        ft.DataCell(ft.Text(g["bloqueo"] or "—", size=11, color=ft.colors.RED_300 if g["bloqueo"] else ft.colors.GREY_600)),
                        ft.DataCell(ft.Text(g["usrbloq"] or "—", size=11, color=ft.colors.RED_300 if g["usrbloq"] else ft.colors.GREY_600)),
                    ],
                    on_select_changed=lambda e, idx=i: _on_row_select(idx, e.data == "true"),
                ))
            return rows

        def _do_search():
            q = input_search.value.strip()
            if not q:
                return
            input_search.disabled = True
            log_text.value = "🔍 Buscando..."
            log_text.color = ft.colors.BLUE_200
            page.update()

            def _thread():
                nonlocal guia_list
                try:
                    selected_indices.clear()
                    mgr = EditSismedManager(sismed_dir_field.value)
                    is_bulk = mode_selector.selected.copy().pop() == "bulk"
                    if is_bulk:
                        codes = re.split(r'[\n,\s]+', q)
                        codes = [c.strip() for c in codes if c.strip()]
                        guia_list = mgr.search_guias_by_list(codes)
                    else:
                        guia_list = mgr.search_guias(q)

                    results_table.rows = _build_rows(guia_list)
                    log_text.value = f"✅ {len(guia_list)} registros encontrados"
                    log_text.color = ft.colors.GREEN_400
                    _update_actions_visibility()
                except Exception as ex:
                    log_text.value = f"❌ Error: {ex}"
                    log_text.color = ft.colors.RED_400
                finally:
                    input_search.disabled = False
                    page.update()

            threading.Thread(target=_thread, daemon=True).start()

        # ── Diálogo de acción ───────────────────────────────────────────────────
        def _show_action_dialog():
            current_action = action_selector.selected.copy().pop()

            if current_action == "situa":
                _show_situa_dialog()
            else:
                _show_bloqueo_dialog()

        def _show_situa_dialog():
            map_situa = {"1": "1 — Habilitar guía", "0": "0 — Anular guía"}

            def _confirm(e):
                val = dropdown.value
                if not val:
                    return
                dialog.open = False
                log_text.value = "⚡ Aplicando cambio de situación..."
                log_text.color = ft.colors.ORANGE_300
                page.update()

                def _thread():
                    mgr = EditSismedManager(sismed_dir_field.value)
                    ph_idxs = [guia_list[i]["id_fisico"] for i in selected_indices]
                    total, msg = mgr.update_movsitua_bulk(ph_idxs, val)
                    log_text.value = f"✨ {msg}"
                    log_text.color = ft.colors.GREEN_400
                    _do_search()

                threading.Thread(target=_thread, daemon=True).start()

            dropdown = ft.Dropdown(
                options=[ft.dropdown.Option(k, v) for k, v in map_situa.items()],
                label="Nueva Situación",
                border_color=ft.colors.BLUE_700,
                border_radius=8,
                width=340,
            )

            dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.icons.SWAP_HORIZ, color=ft.colors.BLUE_400),
                    ft.Text(" Cambiar Situación (MOVSITUA)"),
                ]),
                content=ft.Column([
                    ft.Text(f"Actualizando {len(selected_indices)} guía(s).", size=14, color=ft.colors.GREY_300),
                    ft.Container(height=5),
                    dropdown,
                ], tight=True),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: setattr(dialog, "open", False) or page.update()),
                    ft.ElevatedButton(
                        "CONTINUAR",
                        on_click=_confirm,
                        bgcolor=ft.colors.BLUE_700,
                        color=ft.colors.WHITE,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(horizontal=30, vertical=18),
                            shape=ft.RoundedRectangleBorder(radius=10),
                            elevation=5,
                        ),
                    ),
                ],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        def _show_bloqueo_dialog():
            def _confirm(e):
                dialog.open = False
                log_text.value = "⚡ Quitando bloqueo..."
                log_text.color = ft.colors.ORANGE_300
                page.update()

                def _thread():
                    mgr = EditSismedManager(sismed_dir_field.value)
                    ph_idxs = [guia_list[i]["id_fisico"] for i in selected_indices]
                    total, msg = mgr.clear_bloqueo_bulk(ph_idxs)
                    log_text.value = f"🔓 {msg}"
                    log_text.color = ft.colors.GREEN_400
                    _do_search()

                threading.Thread(target=_thread, daemon=True).start()

            dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.icons.LOCK_OPEN, color=ft.colors.ORANGE_400),
                    ft.Text(" Quitar Bloqueo de Guías"),
                ]),
                content=ft.Column([
                    ft.Text(
                        f"Se limpiarán los campos BLOQUEO y USRBLOQ de {len(selected_indices)} guía(s).",
                        size=14, color=ft.colors.GREY_300,
                    ),
                    ft.Container(height=6),
                    ft.Container(
                        content=ft.Text(
                            "⚠  Las guías quedarán nuevamente editables en SISMED.",
                            size=12, color=ft.colors.ORANGE_200,
                        ),
                        bgcolor=ft.colors.with_opacity(0.1, ft.colors.ORANGE_400),
                        border_radius=8,
                        padding=ft.padding.all(10),
                    ),
                ], tight=True),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: setattr(dialog, "open", False) or page.update()),
                    ft.ElevatedButton(
                        "CONFIRMAR",
                        on_click=_confirm,
                        bgcolor=ft.colors.ORANGE_700,
                        color=ft.colors.WHITE,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(horizontal=30, vertical=18),
                            shape=ft.RoundedRectangleBorder(radius=10),
                            elevation=5,
                        ),
                    ),
                ],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        # ── Layout ──────────────────────────────────────────────────────────────
        sidebar = ft.Container(
            width=430,
            padding=25,
            bgcolor=ft.colors.BLACK26,
            border_radius=15,
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.PURPLE_400, size=20),
                    ft.Text("CONFIGURACIÓN", weight="bold", size=16, color=ft.colors.WHITE),
                ], spacing=8),
                ft.Divider(height=1, color=ft.colors.WHITE10),
                ft.Container(height=6),

                ft.Row([
                    sismed_dir_field,
                    ft.IconButton(ft.icons.FOLDER_OPEN, on_click=lambda _: dir_picker.get_directory_path()),
                ]),

                ft.Container(height=10),
                ft.Text("Modo de Búsqueda:", size=11, color=ft.colors.GREY_500),
                mode_selector,

                ft.Container(height=10),
                input_search,

                ft.ElevatedButton(
                    "BUSCAR / PROCESAR",
                    icon=ft.icons.PLAY_ARROW_ROUNDED,
                    on_click=lambda _: _do_search(),
                    width=430, height=50,
                    bgcolor=ft.colors.BLUE_700,
                    color=ft.colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                ),

                ft.Container(height=16),
                ft.Text("Acción a Realizar:", size=11, color=ft.colors.GREY_500),
                action_selector,

                ft.Container(height=16),
                ft.Container(
                    content=log_text,
                    padding=10,
                    bgcolor=ft.colors.BLACK12,
                    border_radius=8,
                ),
            ], scroll=ft.ScrollMode.AUTO),
        )

        main_content = ft.Container(
            expand=True,
            padding=10,
            content=ft.Column([
                ft.Row([
                    ft.Text("RESULTADOS DE LA BÚSQUEDA", weight="bold", size=18),
                    ft.Container(expand=True),
                    btn_action,
                ]),
                ft.Divider(height=1, color=ft.colors.WHITE10),
                ft.ListView(controls=[results_table], expand=True),
            ]),
        )

        return ft.Container(
            padding=10,
            expand=True,
            content=ft.Column([
                self._section_header(
                    ft.icons.EDIT_DOCUMENT, ft.colors.PURPLE_400,
                    "Habilitar Guías (TMOVIM)",
                    "Habilita guías anuladas y guías cerradas en TMOVIM.DBF",
                    self._back_button("Volver a Edit SISMED", navigate_fn, 11),
                ),
                ft.Row([sidebar, main_content], expand=True, spacing=20, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                dir_picker,
            ], expand=True),
        )
