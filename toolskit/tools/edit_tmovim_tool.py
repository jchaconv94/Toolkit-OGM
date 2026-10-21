import threading
import flet as ft
from edit_sismed_manager import EditSismedManager
from tmovim_search import (
    BY_GUIDE, BY_MOVEMENT, SIMPLE_LIMIT, ListMatcher, normalize_by, short_list, split_values, summarize,
)
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import get as cfg_get, set as cfg_set
import activity


class EditTmovimTool(SismedTool):
    """Herramienta para modificar MOVSITUA, modo de ingreso y bloqueos en TMOVIM.DBF."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Habilitar Guías",
            descripcion="Habilita guías anuladas, quita bloqueos y cambia el modo de ingreso en TMOVIM.DBF",
            icono=ft.icons.EDIT_DOCUMENT,
            color=ft.colors.PURPLE_400,
            categoria="Edit SISMED",
            etiquetas=["editar", "tmovim", "guia", "movnumedco", "movsitua", "movindprc", "bloqueo", "sismed", "modificar", "desbloquear"],
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
        def _is_bulk() -> bool:
            return next(iter(mode_selector.selected), "normal") == "bulk"

        def _search_by() -> str:
            return normalize_by(next(iter(by_selector.selected), BY_MOVEMENT))

        def _apply_input_texts():
            is_bulk = _is_bulk()
            is_guide = _search_by() == BY_GUIDE
            if is_bulk:
                input_search.label = "Pegar Lista de N° Guía" if is_guide else "Pegar Lista de N° Movimiento"
                input_search.hint_text = (
                    "Una guía por línea (puede copiar la columna de Excel)..." if is_guide
                    else "Ingrese N° Movimiento separados por línea o espacio..."
                )
            else:
                input_search.label = "Búsqueda por N° Guía" if is_guide else "Búsqueda por N° Movimiento"
                input_search.hint_text = (
                    "N° de guía, con o sin serie (MOVNUMEDCO)..." if is_guide
                    else "N° Movimiento (MOVNUMERO)..."
                )
            input_search.multiline = is_bulk
            input_search.min_lines = 5 if is_bulk else 1
            input_search.max_lines = 10 if is_bulk else 1

        def on_mode_change(e):
            nonlocal guia_list
            input_search.value = ""
            guia_list = []
            selected_indices.clear()
            results_table.rows = []
            log_text.value = ""
            _update_actions_visibility()
            if e.control is by_selector:
                cfg_set("tmovim_search_by", _search_by())
            _apply_input_texts()
            page.update()

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

        by_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value=BY_MOVEMENT, label=ft.Text("N° Movimiento", size=11), icon=ft.Icon(ft.icons.TAG, size=18)),
                ft.Segment(value=BY_GUIDE,    label=ft.Text("N° Guía", size=11),       icon=ft.Icon(ft.icons.RECEIPT_LONG, size=18)),
            ],
            selected={normalize_by(cfg_get("tmovim_search_by"))},
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
        _apply_input_texts()

        # ── Tabla de Resultados ─────────────────────────────────────────────────
        results_table = ft.DataTable(
            column_spacing=16,
            heading_row_color=ft.colors.WHITE10,
            data_row_min_height=40,
            data_row_max_height=55,
            border_radius=10,
            heading_text_style=ft.TextStyle(weight="bold", color=ft.colors.GREY_300, size=12),
            columns=[
                ft.DataColumn(ft.Text("TIPO")),
                ft.DataColumn(ft.Text("N° MOVIM.")),
                ft.DataColumn(ft.Text("N° GUÍA")),
                ft.DataColumn(ft.Text("FECHA")),
                ft.DataColumn(ft.Text("MODO INGRESO")),
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

        def _indprc_badge(value: str) -> ft.Control:
            current = (value or "").strip().upper()
            if current == "A":
                label = "Automática"
                text_color = ft.colors.CYAN_300
                bg_color = ft.colors.CYAN_400
            elif current == "M":
                label = "Manual"
                text_color = ft.colors.AMBER_300
                bg_color = ft.colors.AMBER_400
            else:
                label = current or "—"
                text_color = ft.colors.GREY_400
                bg_color = ft.colors.GREY_600

            return ft.Container(
                content=ft.Text(label, size=11, weight="bold", color=text_color),
                bgcolor=ft.colors.with_opacity(0.15, bg_color),
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

        def _action_btn(label: str, icon_name: str, bgcolor: str, on_click) -> ft.Control:
            return ft.ElevatedButton(
                content=ft.Row([
                    ft.Icon(icon_name, color=ft.colors.WHITE, size=14),
                    ft.Text(label, color=ft.colors.WHITE, size=10, weight=ft.FontWeight.W_600),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                on_click=on_click,
                bgcolor=bgcolor,
                color=ft.colors.WHITE,
                height=38,
                style=ft.ButtonStyle(
                    padding=ft.padding.symmetric(horizontal=14, vertical=10),
                    shape=ft.RoundedRectangleBorder(radius=9),
                ),
            )

        action_count_text = ft.Text("", size=11, color=ft.colors.CYAN_200, weight=ft.FontWeight.W_600)
        btn_situa = _action_btn("Cambiar Situación", ft.icons.SWAP_HORIZ, ft.colors.BLUE_700, lambda _: _show_situa_dialog())
        btn_bloqueo = _action_btn("Quitar Bloqueo", ft.icons.LOCK_OPEN, ft.colors.ORANGE_700, lambda _: _show_bloqueo_dialog())
        btn_indprc = _action_btn("Cambiar Modo Ingreso", ft.icons.SWAP_HORIZ, ft.colors.PURPLE_700, lambda _: _show_indprc_dialog())

        action_buttons_row = ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.END,
            controls=[
                btn_situa,
                btn_bloqueo,
                btn_indprc,
            ],
        )

        action_bar_container = ft.Container(
            visible=False,
            col={"sm": 12, "md": 8},
            alignment=ft.alignment.center_right,
            content=ft.Column([
                ft.Row([
                    action_count_text,
                ], alignment=ft.MainAxisAlignment.END),
                action_buttons_row,
            ], spacing=6),
        )

        def _update_actions_visibility():
            has_sel = len(selected_indices) > 0
            if has_sel:
                suffix = "guía seleccionada" if len(selected_indices) == 1 else "guías seleccionadas"
                action_count_text.value = f"{len(selected_indices)} {suffix}"
            action_bar_container.visible = has_sel
            if getattr(action_count_text, "page", None):
                action_count_text.update()
            if getattr(action_buttons_row, "page", None):
                action_buttons_row.update()
            if getattr(action_bar_container, "page", None):
                action_bar_container.update()

        # ── Búsqueda ────────────────────────────────────────────────────────────
        def _key_text(value: str, highlighted: bool) -> ft.Text:
            if highlighted:
                return ft.Text(value, weight="bold", color=ft.colors.AMBER_100)
            return ft.Text(value, size=12)

        def _build_rows(lista, preselect, by):
            rows = []
            for i, g in enumerate(lista):
                is_sel = i in preselect
                if is_sel:
                    selected_indices.add(i)
                rows.append(ft.DataRow(
                    selected=is_sel,
                    cells=[
                        ft.DataCell(ft.Text(g["movcoditip"], size=11)),
                        ft.DataCell(_key_text(g["movnumero"], by == BY_MOVEMENT)),
                        ft.DataCell(_key_text(g["movnumedco"] or "—", by == BY_GUIDE)),
                        ft.DataCell(ft.Text(g["movfechreg"], size=11)),
                        ft.DataCell(_indprc_badge(g.get("movindprc", ""))),
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
                    by = _search_by()
                    is_guide = by == BY_GUIDE
                    notes = []
                    if _is_bulk():
                        matcher = ListMatcher(split_values(q, by), by)
                        guia_list = mgr.search_guias_by_list(matcher)
                        preselect, not_found, repeated = summarize(
                            matcher.values, [g["coincide"] for g in guia_list], by,
                        )
                        if repeated:
                            notes.append(
                                f"⚠ {len(repeated)} guía(s) en más de un movimiento; revíselas y márquelas usted: "
                                f"{short_list(repeated)}"
                            )
                        if not_found:
                            nombre = "guía(s) no encontrada(s)" if is_guide else "movimiento(s) no encontrado(s)"
                            notes.append(f"⚠ {len(not_found)} {nombre}: {short_list(not_found)}")
                        found_text = f"✅ {len(guia_list)} registros encontrados"
                    else:
                        guia_list = mgr.search_guias(q, by)
                        preselect = set()
                        total = len(guia_list)
                        found_text = f"✅ {total} registros encontrados"
                        if total > SIMPLE_LIMIT:
                            guia_list = guia_list[:SIMPLE_LIMIT]
                            found_text = (
                                f"✅ {total} registros encontrados; se muestran los primeros {SIMPLE_LIMIT}. "
                                "Escriba más dígitos para acotar."
                            )

                    results_table.rows = _build_rows(guia_list, preselect, by)
                    log_text.value = "\n".join([found_text] + notes)
                    log_text.color = ft.colors.AMBER_300 if notes else ft.colors.GREEN_400
                    _update_actions_visibility()
                except Exception as ex:
                    log_text.value = f"❌ Error: {ex}"
                    log_text.color = ft.colors.RED_400
                finally:
                    input_search.disabled = False
                    page.update()

            activity.background("Editar TMOVIM", _thread)

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
                    ph_idxs = [guia_list[i] for i in sorted(selected_indices)]
                    total, msg = mgr.update_movsitua_bulk(ph_idxs, val)
                    log_text.value = f"✨ {msg}"
                    log_text.color = ft.colors.GREEN_400
                    _do_search()

                activity.background("Editar TMOVIM", _thread)

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
                    ph_idxs = [guia_list[i] for i in sorted(selected_indices)]
                    total, msg = mgr.clear_bloqueo_bulk(ph_idxs)
                    log_text.value = f"🔓 {msg}"
                    log_text.color = ft.colors.GREEN_400
                    _do_search()

                activity.background("Editar TMOVIM", _thread)

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

        def _show_indprc_dialog():
            def _confirm(e):
                dialog.open = False
                log_text.value = "⚡ Cambiando modo de ingreso..."
                log_text.color = ft.colors.PURPLE_300
                page.update()

                def _thread():
                    mgr = EditSismedManager(sismed_dir_field.value)
                    ph_idxs = [guia_list[i] for i in sorted(selected_indices)]
                    total, msg = mgr.toggle_movindprc_bulk(ph_idxs)
                    log_text.value = f"🔄 {msg}"
                    log_text.color = ft.colors.GREEN_400 if total else ft.colors.AMBER_300
                    _do_search()

                activity.background("Editar TMOVIM", _thread)

            dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.icons.SWAP_HORIZ, color=ft.colors.PURPLE_400),
                    ft.Text(" Cambiar Modo de Ingreso"),
                ]),
                content=ft.Column([
                    ft.Text(
                        f"Se cambiará el modo de ingreso en {len(selected_indices)} guía(s).",
                        size=14, color=ft.colors.GREY_300,
                    ),
                    ft.Container(height=6),
                    ft.Container(
                        content=ft.Text(
                            "Automática cambiará a Manual y Manual cambiará a Automática únicamente en los registros seleccionados.",
                            size=12, color=ft.colors.PURPLE_200,
                        ),
                        bgcolor=ft.colors.with_opacity(0.1, ft.colors.PURPLE_400),
                        border_radius=8,
                        padding=ft.padding.all(10),
                    ),
                ], tight=True),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: setattr(dialog, "open", False) or page.update()),
                    ft.ElevatedButton(
                        "CONFIRMAR",
                        on_click=_confirm,
                        bgcolor=ft.colors.PURPLE_700,
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

                ft.Container(height=6),
                ft.Text("Buscar por:", size=11, color=ft.colors.GREY_500),
                by_selector,

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
                ft.ResponsiveRow([
                    ft.Container(
                        col={"sm": 12, "md": 4},
                        alignment=ft.alignment.center_left,
                        content=ft.Text("RESULTADOS DE LA BÚSQUEDA", weight="bold", size=18),
                    ),
                    action_bar_container,
                ], spacing=10, run_spacing=10),
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
                    "Habilita guías anuladas, quita bloqueos y cambia el modo de ingreso en TMOVIM.DBF",
                    self._back_button("Volver a Edit SISMED", navigate_fn, 11),
                ),
                ft.Row([sidebar, main_content], expand=True, spacing=20, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                dir_picker,
            ], expand=True),
        )
