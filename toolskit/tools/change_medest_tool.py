import threading
import flet as ft
import re
import time
from edit_sismed_manager import EditSismedManager
from tools.base_tool import SismedTool, ToolMetadata

class ChangeMedestTool(SismedTool):
    """Herramienta para modificar el estado (MEDEST) de medicamentos en MMEDICAM.DBF."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Cambiar Estado Med.",
            descripcion="Modifica el campo MEDEST de medicamentos en MMEDICAM.DBF",
            icono=ft.icons.EDIT_NOTE,
            color=ft.colors.ORANGE_400,
            categoria="Edit SISMED",
            etiquetas=["editar", "mmedicam", "estado", "medest", "sismed", "modificar"],
        )

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        # --- Variables de Estado ---
        sismed_dir_field = ft.TextField(
            value=r"C:\SISMEDV2", label="Ruta SISMED", read_only=True,
            prefix_icon=ft.icons.FOLDER, border_radius=12, text_size=12, expand=True,
            border_color=ft.colors.WHITE24,
        )
        med_list = []
        selected_indices = set()

        # --- Auxiliares (FilePicker) ---
        def folder_picker_result(e):
            if e.path:
                sismed_dir_field.value = e.path
                sismed_dir_field.update()

        dir_picker = ft.FilePicker(on_result=folder_picker_result)

        log_text = ft.Text("Listo para operar", size=12, color=ft.colors.GREY_500)
        
        # --- Controles de Búsqueda ---
        def on_mode_change(e):
            nonlocal med_list
            input_search.value = ""
            med_list = []
            selected_indices.clear()
            results_table.rows = []
            log_text.value = ""
            _update_actions_visibility()
            
            is_bulk = mode_selector.selected.copy().pop() == "bulk"
            if is_bulk:
                input_search.label = "Pegar Lista de Códigos"
                input_search.hint_text = "Ingrese códigos separados por línea o espacio..."
                input_search.multiline = True
                input_search.min_lines = 5
                input_search.max_lines = 10
            else:
                input_search.label = "Búsqueda"
                input_search.hint_text = "Código o Nombre del Producto..."
                input_search.multiline = False
                input_search.min_lines = 1
                input_search.max_lines = 1
            input_search.update()

        mode_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value="normal", label=ft.Text("Simple", size=11), icon=ft.Icon(ft.icons.SEARCH, size=18)),
                ft.Segment(value="bulk", label=ft.Text("Masivo", size=11), icon=ft.Icon(ft.icons.LIST_ALT, size=18)),
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
            label="Búsqueda",
            hint_text="Código o Nombre del Producto...",
            border_radius=12,
            text_size=14,
            expand=True,
            on_submit=lambda _: _do_search(),
            border_color=ft.colors.WHITE24,
            focused_border_color=ft.colors.ORANGE_400,
        )

        # --- Tabla de Resultados ---
        results_table = ft.DataTable(
            column_spacing=20,
            heading_row_color=ft.colors.WHITE10,
            data_row_min_height=40,
            data_row_max_height=55,
            border_radius=10,
            heading_text_style=ft.TextStyle(weight="bold", color=ft.colors.GREY_300, size=12),
            columns=[
                ft.DataColumn(ft.Text("CÓDIGO")),
                ft.DataColumn(ft.Text("NOMBRE PRODUCTO")),
                ft.DataColumn(ft.Text("PRES.")),
                ft.DataColumn(ft.Text("CONCENTRACIÓN")),
                ft.DataColumn(ft.Text("F.F.")),
                ft.DataColumn(ft.Text("EST.")),
            ],
            rows=[],
            show_checkbox_column=True,
            on_select_all=lambda e: _on_select_all(e.data == "true"),
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
                if selected: selected_indices.add(i)
            _update_actions_visibility()
            results_table.update()

        btn_edit = ft.ElevatedButton(
            "MODIFICAR SELECCIONADOS",
            icon=ft.icons.EDIT_DOCUMENT,
            on_click=lambda _: _show_edit_dialog(),
            bgcolor=ft.colors.BLUE_700,
            color=ft.colors.WHITE,
            visible=False,
            height=50,
            width=300,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))
        )

        def _update_actions_visibility():
            btn_edit.visible = len(selected_indices) > 0
            btn_edit.update()

        def _do_search():
            q = input_search.value.strip()
            if not q: return
            input_search.disabled = True
            log_text.value = "🔍 Buscando..."
            log_text.color = ft.colors.BLUE_200
            page.update()

            def _thread_search():
                nonlocal med_list
                selected_indices.clear()
                mgr = EditSismedManager(sismed_dir_field.value)
                
                is_bulk = mode_selector.selected.copy().pop() == "bulk"
                if is_bulk:
                    codes = re.split(r'[\n,\s]+', q)
                    codes = [c.strip() for c in codes if c.strip()]
                    med_list = mgr.search_medicines_by_list(codes)
                else:
                    med_list = mgr.search_medicines(q)
                
                rows = []
                for i, m in enumerate(med_list):
                    is_sel = is_bulk
                    if is_sel: selected_indices.add(i)
                    
                    rows.append(ft.DataRow(
                        selected=is_sel,
                        cells=[
                            ft.DataCell(ft.Text(m["medcod"], weight="bold", color=ft.colors.AMBER_100)),
                            ft.DataCell(ft.Text(m["mednom"], size=12)),
                            ft.DataCell(ft.Text(m["medpres"], size=11)),
                            ft.DataCell(ft.Container(content=ft.Text(m["medcnc"], size=11), width=150)),
                            ft.DataCell(ft.Text(m["medff"], size=11)),
                            ft.DataCell(ft.Text(m["medest"], weight="bold")),
                        ],
                        on_select_changed=lambda e, idx=i: _on_row_select(idx, e.data == "true")
                    ))
                
                results_table.rows = rows
                log_text.value = f"✅ {len(med_list)} productos encontrados"
                log_text.color = ft.colors.GREEN_400
                input_search.disabled = False
                _update_actions_visibility()
                page.update()

            threading.Thread(target=_thread_search, daemon=True).start()

        def _show_edit_dialog():
            map_l = {"E": "Estratégico (E)", "S": "Soporte (S)", "_": "Otros (_)"}
            
            def _confirm_update(e):
                val = dropdown.value
                if not val: return
                dialog.open = False
                log_text.value = "⚡ Aplicando..."
                page.update()
                
                def _thread_save():
                    mgr = EditSismedManager(sismed_dir_field.value)
                    ph_idxs = [med_list[i]["id_fisico"] for i in selected_indices]
                    mgr.update_medest_bulk(ph_idxs, val)
                    log_text.value = "✨ Cambios aplicados con éxito"
                    _do_search()

                threading.Thread(target=_thread_save, daemon=True).start()

            dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.icons.EDIT, color=ft.colors.INDIGO_700),
                    ft.Text(" Cambiar Estado (MEDEST)")
                ]),
                content=ft.Column([
                    ft.Text(f"Actualizando {len(selected_indices)} productos.", size=14, color=ft.colors.GREY_300),
                    ft.Container(height=5),
                    dropdown := ft.Dropdown(
                        options=[ft.dropdown.Option(o, map_l[o]) for o in ["_", "E", "S"]],
                        label="Seleccionar Tipo de Estado",
                        border_color=ft.colors.BLUE_700,
                        border_radius=8,
                        width=340,
                    )
                ], tight=True),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: setattr(dialog, "open", False) or page.update()),
                    ft.ElevatedButton(
                        "CONTINUAR", 
                        on_click=_confirm_update, 
                        bgcolor=ft.colors.INDIGO_700,
                        color=ft.colors.WHITE,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(horizontal=30, vertical=18),
                            shape=ft.RoundedRectangleBorder(radius=10),
                            elevation=5,
                        )
                    )
                ],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        # --- UI LAYOUT ---
        sidebar = ft.Container(
            width=420,
            padding=25,
            bgcolor=ft.colors.BLACK26,
            border_radius=15,
            content=ft.Column([
                ft.Text("CONFIGURACIÓN", weight="bold", size=16, color=ft.colors.WHITE),
                ft.Divider(height=1, color=ft.colors.WHITE10),
                
                ft.Row([
                    sismed_dir_field,
                    ft.IconButton(ft.icons.FOLDER_OPEN, on_click=lambda _: dir_picker.get_directory_path())
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
                    width=420, height=50,
                    bgcolor=ft.colors.BLUE_700,
                    color=ft.colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))
                ),
                
                ft.Container(expand=True),
                ft.Container(
                    content=log_text,
                    padding=10,
                    bgcolor=ft.colors.BLACK12,
                    border_radius=8
                )
            ])
        )

        main_content = ft.Container(
            expand=True,
            padding=10,
            content=ft.Column([
                ft.Row([
                    ft.Text("RESULTADOS DE LA BÚSQUEDA", weight="bold", size=18),
                    ft.Container(expand=True),
                    btn_edit
                ]),
                ft.Divider(height=1, color=ft.colors.WHITE10),
                ft.ListView(controls=[results_table], expand=True)
            ])
        )

        return ft.Container(
            padding=10,
            expand=True,
            content=ft.Column([
                self._section_header(
                    ft.icons.EDIT_SQUARE, ft.colors.ORANGE_400, 
                    "Editor de Estados (MEDEST)", "Modifica el campo MEDEST de medicamentos en MMEDICAM.DBF",
                    self._back_button("Cerrar", navigate_fn, 0)
                ),
                ft.Row([sidebar, main_content], expand=True, spacing=20),
                dir_picker
            ], expand=True)
        )
