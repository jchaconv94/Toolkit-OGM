"""
pdf_tool.py
===========
Herramienta: Editor Visual de PDFs
Muestra miniaturas de cada pagina: arrastra para reordenar,
haz clic en x para eliminar y selecciona paginas para exportar.
"""

import os
import base64
import threading
import io
import flet as ft
from pathlib import Path

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from tools.base_tool import SismedTool, ToolMetadata
from pdf_manager import PdfManager
import activity

_CARD_W = 140
_CARD_H = 188
_CARD_PAD = 6
_THUMB_W = 180
_PREVIEW_W = 920
_PREVIEW_BOX_W = 760
_PREVIEW_BOX_H = 540


def _render_b64(doc, page_idx: int, target_w: int = _THUMB_W) -> str:
    page = doc[page_idx]
    scale = target_w / page.rect.width
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return base64.b64encode(pix.tobytes("png")).decode()


def _rotate_b64_image(b64_png: str, degrees_clockwise: int) -> str:
    if not _HAS_PIL or not b64_png:
        return b64_png
    raw = base64.b64decode(b64_png)
    img = Image.open(io.BytesIO(raw))
    rotated = img.rotate(-degrees_clockwise, expand=True)
    out = io.BytesIO()
    rotated.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


class PdfTool(SismedTool):

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Editor PDF",
            descripcion="Editor visual: reorganiza, elimina y convierte paginas",
            icono=ft.icons.PICTURE_AS_PDF_ROUNDED,
            color=ft.colors.RED_400,
            categoria="Herramientas",
            etiquetas=["pdf", "word", "excel", "jpg", "unir", "dividir", "convertir", "extraer", "ordenar"],
        )

    TASKS = [
        {"id": "edit", "label": "Organizar", "icon": ft.icons.EDIT_NOTE_ROUNDED, "color": ft.colors.RED_400,
         "desc": "Arrastra paginas para reordenar y usa x para eliminar"},
        {"id": "merge", "label": "Unir PDFs", "icon": ft.icons.MERGE_ROUNDED, "color": ft.colors.PURPLE_400,
         "desc": "Carga varios PDFs y combinalos en el orden que quieras"},
        {"id": "split", "label": "Dividir PDF", "icon": ft.icons.CALL_SPLIT_ROUNDED, "color": ft.colors.AMBER_400,
         "desc": "Haz clic en paginas para marcar puntos de corte"},
        {"id": "to_word", "label": "PDF a Word", "icon": ft.icons.DESCRIPTION_ROUNDED, "color": ft.colors.BLUE_400,
         "desc": "Convierte el PDF a documento Word editable (.docx)"},
        {"id": "to_excel", "label": "PDF a Excel", "icon": ft.icons.TABLE_CHART_ROUNDED, "color": ft.colors.GREEN_400,
         "desc": "Extrae tablas y texto del PDF a Excel (.xlsx)"},
        {"id": "to_jpg", "label": "PDF a JPG", "icon": ft.icons.IMAGE_ROUNDED, "color": ft.colors.ORANGE_400,
         "desc": "Selecciona paginas y exportalas como imagenes JPG"},
    ]

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        mgr = PdfManager()

        pages_state = []
        loaded_files = []
        current_task = {"id": "edit"}
        save_btn_ref = {"ctrl": None, "busy": False, "idle_text": "GUARDAR", "idle_icon": ft.icons.SAVE_ROUNDED}
        pick_mode_ref = {"append": False}
        jpg_export_ref = {"dpi": "150"}
        preview_state = {"pos": 0, "zoom": 1.0}

        def tid() -> str:
            return current_task["id"]

        def _safe_up(*ctrls):
            for c in ctrls:
                try:
                    if c.page:
                        c.update()
                except Exception:
                    pass

        def _rebuild_grid():
            n = len(pages_state)
            pg_count_txt.value = f"{n} pagina{'s' if n != 1 else ''}" if n else "Sin paginas"
            sel = sum(1 for p in pages_state if p.get("selected"))
            sel_count_txt.value = f"- {sel} selec." if sel else ""

            if n == 0:
                grid_area.content = empty_hint
            else:
                pages_wrap.controls = [_make_card(i, p) for i, p in enumerate(pages_state)]
                grid_area.content = ft.Container(
                    content=ft.Column(
                        [pages_wrap],
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                    padding=ft.padding.only(right=14),
                    expand=True,
                )
            if save_btn_ref["ctrl"] is not None:
                _update_save_button()
            _safe_up(grid_area, pg_count_txt, sel_count_txt, save_btn_ref["ctrl"])

        def _set_load_overlay(visible: bool, pct: float = 0.0, msg: str = ""):
            load_overlay.visible = visible
            load_prog_bar.value = max(0.0, min(1.0, pct))
            load_pct_txt.value = f"{int(round(max(0.0, min(1.0, pct)) * 100))}%"
            load_msg_txt.value = msg
            _safe_up(load_overlay, load_prog_bar, load_pct_txt, load_msg_txt)

        def _load_pdf_async(path: str):
            loading_spin.visible = True
            loading_txt.value = "Cargando..."
            _set_load_overlay(True, 0.0, "Subiendo y preparando archivo PDF...")
            _safe_up(loading_spin, loading_txt)

            def _thread():
                try:
                    if not _HAS_FITZ:
                        raise RuntimeError("PyMuPDF no esta instalado.")
                    doc = fitz.open(path)
                    total = len(doc)
                    _set_load_overlay(True, 0.02, f"Procesando 0/{total} paginas...")
                    for i in range(total):
                        page_ref = doc[i]
                        b64 = _render_b64(doc, i)
                        pages_state.append({
                            "img_b64": b64,
                            "base_img_b64": b64,
                            "rotation": 0,
                            "orig_page": i,
                            "src_file": path,
                            "selected": False,
                            "split_before": False,
                            "is_blank": False,
                            "page_w": page_ref.rect.width,
                            "page_h": page_ref.rect.height,
                        })
                        loading_txt.value = f"Cargando... {i + 1}/{total}"
                        pct = (i + 1) / max(total, 1)
                        _set_load_overlay(True, pct, f"Procesando {i + 1}/{total} paginas...")
                        if (i + 1) % 4 == 0 or i == total - 1:
                            _rebuild_grid()
                            _safe_up(loading_txt)
                    doc.close()
                except Exception as ex:
                    loading_txt.value = f"Error: {ex}"
                    _set_load_overlay(True, 0.0, f"Error al cargar: {ex}")
                    _safe_up(loading_txt)
                finally:
                    loading_spin.visible = False
                    loading_txt.value = ""
                    _set_load_overlay(False, 0.0, "")
                    _safe_up(loading_spin, loading_txt)
                    _rebuild_grid()

            activity.background("PDF", _thread)

        def _on_file_pick(e: ft.FilePickerResultEvent):
            if not e.files:
                pick_mode_ref["append"] = False
                return
            paths = [f.path for f in e.files]
            append_mode = pick_mode_ref["append"] or tid() == "merge"
            pick_mode_ref["append"] = False
            if append_mode:
                for p in paths:
                    loaded_files.append(p)
                    _load_pdf_async(p)
            else:
                loaded_files.clear()
                pages_state.clear()
                loaded_files.append(paths[0])
                _load_pdf_async(paths[0])

        def _ensure_ext(path_str: str, ext: str) -> str:
            p = Path(path_str)
            if p.suffix.lower() != ext.lower():
                p = p.with_suffix(ext)
            return str(p)

        def _suggest_save_name():
            task = tid()
            stem = Path(loaded_files[0]).stem if loaded_files else "resultado"
            if task == "edit":
                return f"{stem}_editado.pdf", ".pdf"
            if task == "merge":
                return "PDFs_unidos.pdf", ".pdf"
            if task == "to_word":
                return f"{stem}.docx", ".docx"
            if task == "to_excel":
                return f"{stem}.xlsx", ".xlsx"
            if task == "split":
                return f"{stem}_partes.pdf", ".pdf"
            if task == "to_jpg":
                return f"{stem}_imagenes.jpg", ".jpg"
            return "resultado.pdf", ".pdf"

        def _on_save_result(e: ft.FilePickerResultEvent):
            if e.path:
                _run_task(e.path)

        file_picker = ft.FilePicker(on_result=_on_file_pick)
        save_picker = ft.FilePicker(on_result=_on_save_result)

        loading_spin = ft.ProgressRing(width=15, height=15, stroke_width=2, color=ft.colors.RED_400, visible=False)
        loading_txt = ft.Text("", size=11, color=ft.colors.GREY_500)
        pg_count_txt = ft.Text("Sin paginas", size=11, color=ft.colors.GREY_600)
        sel_count_txt = ft.Text("", size=10, color=ft.colors.RED_300)

        def _pick_files(_=None):
            pick_mode_ref["append"] = False
            file_picker.pick_files(
                allowed_extensions=["pdf"],
                allow_multiple=(tid() == "merge"),
                dialog_title="Seleccionar PDF(s)",
            )

        def _pick_more_files(_=None):
            pick_mode_ref["append"] = True
            file_picker.pick_files(
                allowed_extensions=["pdf"],
                allow_multiple=True,
                dialog_title="Anadir PDF(s)",
            )

        drop_zone = ft.Container(
            content=ft.Container(
                expand=True,
                alignment=ft.alignment.center,
                content=ft.Column([
                    ft.Container(
                        width=44,
                        height=44,
                        border_radius=22,
                        bgcolor=ft.colors.with_opacity(0.18, ft.colors.RED_400),
                        alignment=ft.alignment.center,
                        content=ft.Icon(ft.icons.PICTURE_AS_PDF_ROUNDED, size=22, color=ft.colors.RED_200),
                    ),
                    ft.Text("Cargar PDF", size=16, weight="w700", color=ft.colors.WHITE),
                    ft.Text(
                        "Haz clic para seleccionar tu archivo",
                        size=11,
                        color=ft.colors.with_opacity(0.78, ft.colors.WHITE),
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=7,
                ),
            ),
            alignment=ft.alignment.center,
            height=152,
            border_radius=18,
            border=ft.border.all(1.2, ft.colors.with_opacity(0.5, ft.colors.RED_400)),
            bgcolor=ft.colors.with_opacity(0.09, ft.colors.RED_400),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=18,
                color=ft.colors.with_opacity(0.2, ft.colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
            on_click=_pick_files,
            animate=ft.animation.Animation(150, ft.AnimationCurve.EASE_OUT),
        )

        options_col = ft.Column([], spacing=10)
        hint_txt = ft.Text("", size=10, color=ft.colors.GREY_600, italic=True)

        def _update_options():
            t = tid()
            ctrls = []
            hints = {
                "merge": "Carga varios PDFs y reordena visualmente",
                "split": "Haz clic en paginas para marcar cortes",
                "to_jpg": "Haz clic en paginas para seleccionar cuales exportar",
            }
            hint_txt.value = hints.get(t, "")
            if hint_txt.value:
                ctrls.append(hint_txt)
            options_col.controls = ctrls
            _safe_up(options_col)

        chips_row = ft.Row([], wrap=True, spacing=8, run_spacing=8)

        def _select_task(new_tid: str):
            current_task["id"] = new_tid
            pages_state.clear()
            loaded_files.clear()
            _rebuild_chips()
            _update_options()
            _update_action_row()
            _rebuild_grid()
            _reset_result()

        def _rebuild_chips():
            chips_row.controls = [
                ft.Container(
                    width=124,
                    height=114,
                    padding=ft.padding.symmetric(horizontal=8, vertical=9),
                    border_radius=14,
                    bgcolor=ft.colors.with_opacity(0.18, t["color"]) if t["id"] == tid() else ft.colors.WHITE10,
                    border=ft.border.all(1.2, t["color"] if t["id"] == tid() else ft.colors.WHITE24),
                    shadow=ft.BoxShadow(
                        spread_radius=0,
                        blur_radius=10,
                        color=ft.colors.with_opacity(0.25 if t["id"] == tid() else 0.12, t["color"] if t["id"] == tid() else ft.colors.BLACK),
                        offset=ft.Offset(0, 3),
                    ),
                    ink=True,
                    content=ft.Column([
                        ft.Container(
                            width=34,
                            height=34,
                            border_radius=17,
                            alignment=ft.alignment.center,
                            bgcolor=ft.colors.with_opacity(0.22, t["color"]) if t["id"] == tid() else ft.colors.with_opacity(0.10, ft.colors.WHITE),
                            content=ft.Icon(
                                t["icon"],
                                size=18,
                                color=t["color"] if t["id"] == tid() else ft.colors.GREY_400,
                            ),
                        ),
                        ft.Text(
                            t["label"],
                            size=12,
                            weight="bold",
                            color=ft.colors.WHITE if t["id"] == tid() else ft.colors.GREY_300,
                            text_align=ft.TextAlign.CENTER,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            t.get("desc", ""),
                            size=9,
                            color=ft.colors.GREY_300 if t["id"] == tid() else ft.colors.GREY_500,
                            text_align=ft.TextAlign.CENTER,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                        spacing=5,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    on_click=lambda _, tid_=t["id"]: _select_task(tid_),
                ) for t in self.TASKS
            ]
            _safe_up(chips_row)

        def _on_drop(e: ft.DragTargetEvent, target_pos: int):
            src = page.get_control(e.src_id)
            if not src:
                return
            try:
                from_pos = int(src.data)
            except Exception:
                return
            if from_pos < 0 or from_pos >= len(pages_state) or from_pos == target_pos:
                return
            item = pages_state.pop(from_pos)
            if from_pos < target_pos:
                target_pos -= 1
            pages_state.insert(target_pos, item)
            _rebuild_grid()

        def _on_card_click(pos: int):
            if tid() == "split":
                pages_state[pos]["split_before"] = not pages_state[pos].get("split_before", False)
            else:
                pages_state[pos]["selected"] = not pages_state[pos].get("selected", False)
            _rebuild_grid()

        def _delete_page(pos: int):
            if 0 <= pos < len(pages_state):
                pages_state.pop(pos)
                _rebuild_grid()

        def _insert_blank_after(pos: int):
            if tid() != "edit":
                return
            ref = pages_state[pos] if 0 <= pos < len(pages_state) else None
            w = ref.get("page_w", 595) if ref else 595
            h = ref.get("page_h", 842) if ref else 842
            blank_page = {
                "img_b64": "",
                "base_img_b64": "",
                "rotation": 0,
                "orig_page": -1,
                "src_file": loaded_files[0] if loaded_files else "",
                "selected": False,
                "split_before": False,
                "is_blank": True,
                "page_w": w,
                "page_h": h,
            }
            pages_state.insert(pos + 1, blank_page)
            _rebuild_grid()

        def _rotate_page(pos: int):
            if not (0 <= pos < len(pages_state)):
                return
            pd = pages_state[pos]
            new_rot = (int(pd.get("rotation", 0)) + 90) % 360
            pd["rotation"] = new_rot

            if pd.get("is_blank"):
                if new_rot in (90, 270):
                    pd["page_w"], pd["page_h"] = pd.get("page_h", 842), pd.get("page_w", 595)
            else:
                base_img = pd.get("base_img_b64", pd.get("img_b64", ""))
                pd["img_b64"] = _rotate_b64_image(base_img, new_rot)

            _rebuild_grid()

        def _apply_preview_zoom():
            zoom = max(0.5, min(2.5, float(preview_state["zoom"])))
            preview_state["zoom"] = zoom
            preview_zoom_txt.value = f"{int(round(zoom * 100))}%"
            preview_image.width = int(_PREVIEW_BOX_W * zoom)
            preview_image.height = int(_PREVIEW_BOX_H * zoom)
            preview_placeholder.width = int(_PREVIEW_BOX_W * zoom)
            preview_placeholder.height = int(_PREVIEW_BOX_H * zoom)
            prev_btn.disabled = preview_state["pos"] <= 0
            next_btn.disabled = preview_state["pos"] >= max(len(pages_state) - 1, 0)
            try:
                if preview_viewer.page:
                    preview_viewer.reset()
            except Exception:
                pass
            _safe_up(preview_zoom_txt, preview_image, preview_placeholder, prev_btn, next_btn, preview_viewer)

        def _preview_on_scroll(e):
            delta_y = getattr(e, "scroll_delta_y", 0) or 0
            if delta_y == 0:
                return
            if delta_y < 0:
                preview_state["zoom"] = min(2.5, float(preview_state["zoom"]) + 0.12)
            else:
                preview_state["zoom"] = max(0.5, float(preview_state["zoom"]) - 0.12)
            _apply_preview_zoom()

        def _open_preview(pos: int, reset_zoom: bool = True):
            if not (0 <= pos < len(pages_state)):
                return

            preview_state["pos"] = pos
            if reset_zoom:
                preview_state["zoom"] = 1.0

            pd = pages_state[pos]
            preview_title.value = f"Vista previa - Pagina {pos + 1}"
            preview_page_txt.value = f"Pagina {pos + 1} de {len(pages_state)}"

            if pd.get("is_blank"):
                preview_image.visible = False
                preview_placeholder.visible = True
                preview_placeholder.content = ft.Column([
                    ft.Icon(ft.icons.ARTICLE_OUTLINED, size=48, color=ft.colors.GREY_300),
                    ft.Text("Pagina en blanco", size=16, color=ft.colors.WHITE),
                ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            else:
                src_path = pd.get("src_file") or (loaded_files[0] if loaded_files else "")
                if not src_path or not _HAS_FITZ:
                    return
                try:
                    doc = fitz.open(src_path)
                    preview_b64 = _render_b64(doc, int(pd["orig_page"]), _PREVIEW_W)
                    doc.close()
                    rot = int(pd.get("rotation", 0)) % 360
                    if rot:
                        preview_b64 = _rotate_b64_image(preview_b64, rot)
                    preview_image.src_base64 = preview_b64
                    preview_image.visible = True
                    preview_placeholder.visible = False
                except Exception as ex:
                    preview_placeholder.visible = True
                    preview_image.visible = False
                    preview_placeholder.content = ft.Column([
                        ft.Icon(ft.icons.ERROR_OUTLINE_ROUNDED, size=40, color=ft.colors.RED_300),
                        ft.Text("No se pudo abrir la vista previa", size=14, color=ft.colors.WHITE),
                        ft.Text(str(ex), size=10, color=ft.colors.GREY_400, text_align=ft.TextAlign.CENTER),
                    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

            preview_overlay.visible = True
            _apply_preview_zoom()
            _safe_up(preview_title, preview_page_txt, preview_image, preview_placeholder, preview_overlay)

        def _close_preview(_=None):
            preview_overlay.visible = False
            _safe_up(preview_overlay)

        def _preview_prev(_=None):
            if preview_state["pos"] > 0:
                _open_preview(preview_state["pos"] - 1, reset_zoom=False)

        def _preview_next(_=None):
            if preview_state["pos"] < len(pages_state) - 1:
                _open_preview(preview_state["pos"] + 1, reset_zoom=False)

        def _preview_zoom_in(_=None):
            preview_state["zoom"] = min(2.5, float(preview_state["zoom"]) + 0.25)
            _apply_preview_zoom()

        def _preview_zoom_out(_=None):
            preview_state["zoom"] = max(0.5, float(preview_state["zoom"]) - 0.25)
            _apply_preview_zoom()

        def _preview_zoom_reset(_=None):
            preview_state["zoom"] = 1.0
            _apply_preview_zoom()

        def _make_card(pos: int, pd: dict) -> ft.Control:
            task_color = next(t["color"] for t in self.TASKS if t["id"] == tid())
            is_sel = pd.get("selected", False)
            is_split = pd.get("split_before", False) and tid() == "split"
            is_blank = pd.get("is_blank", False)
            is_marked = is_split if tid() == "split" else is_sel

            thumb = (
                ft.Container(
                    width=_CARD_W,
                    height=_CARD_H,
                    bgcolor=ft.colors.WHITE,
                    border_radius=5,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    alignment=ft.alignment.center,
                    content=ft.Column([
                        ft.Icon(ft.icons.ARTICLE_OUTLINED, color=ft.colors.GREY_500, size=30),
                        ft.Text("Pagina en blanco", size=10, color=ft.colors.GREY_600),
                    ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                )
                if is_blank
                else ft.Image(
                    src_base64=pd["img_b64"],
                    width=_CARD_W,
                    height=_CARD_H,
                    fit=ft.ImageFit.CONTAIN,
                    border_radius=5,
                )
            )

            rotate_btn = ft.Container(
                right=30,
                top=2,
                visible=False,
                content=ft.IconButton(
                    icon=ft.icons.ROTATE_RIGHT_ROUNDED,
                    icon_size=14,
                    icon_color=ft.colors.RED_500,
                    width=26,
                    height=26,
                    tooltip="Rotar 90°",
                    on_click=lambda _, p=pos: _rotate_page(p),
                    style=ft.ButtonStyle(
                        bgcolor=ft.colors.with_opacity(0.9, ft.colors.WHITE),
                        padding=ft.padding.all(2),
                        shape=ft.CircleBorder(),
                    ),
                ),
            )

            x_btn = ft.Container(
                right=2,
                top=2,
                visible=False,
                content=ft.IconButton(
                    icon=ft.icons.CLOSE_ROUNDED,
                    icon_size=14,
                    icon_color=ft.colors.GREY_800,
                    width=26,
                    height=26,
                    tooltip="Eliminar pagina",
                    on_click=lambda _, p=pos: _delete_page(p),
                    style=ft.ButtonStyle(
                        bgcolor=ft.colors.with_opacity(0.9, ft.colors.WHITE),
                        padding=ft.padding.all(2),
                        shape=ft.CircleBorder(),
                    ),
                ),
            )

            sel_icon = ft.Container(
                left=4,
                top=4,
                visible=(tid() in ("edit", "merge", "split", "to_word", "to_excel", "to_jpg")),
                content=ft.Icon(
                    ft.icons.CHECK_CIRCLE_ROUNDED if is_marked else ft.icons.RADIO_BUTTON_UNCHECKED_ROUNDED,
                    color=task_color if is_marked else ft.colors.WHITE38,
                    size=17,
                ),
            )

            split_badge = ft.Container(
                left=4,
                bottom=4,
                visible=is_split,
                content=ft.Container(
                    content=ft.Text("corte", size=8, color=ft.colors.WHITE, weight="bold"),
                    bgcolor=ft.colors.BLUE_700,
                    border_radius=5,
                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                ),
            )

            rot_badge = ft.Container(
                left=4,
                top=24,
                visible=int(pd.get("rotation", 0)) > 0,
                content=ft.Container(
                    content=ft.Text(f"{int(pd.get('rotation', 0))}°", size=8, color=ft.colors.WHITE, weight="bold"),
                    bgcolor=ft.colors.with_opacity(0.8, ft.colors.BLUE_600),
                    border_radius=5,
                    padding=ft.padding.symmetric(horizontal=4, vertical=2),
                ),
            )

            drag_handle = ft.Container(
                right=4,
                bottom=4,
                content=ft.Icon(ft.icons.DRAG_INDICATOR_ROUNDED, color=ft.colors.WHITE24, size=14),
            )

            add_blank_btn = ft.Container(
                right=-16,
                top=(_CARD_H + _CARD_PAD * 2) / 2 - 16,
                visible=(tid() == "edit"),
                tooltip="Insertar hoja en blanco despues",
                on_click=lambda _, p=pos: _insert_blank_after(p),
                width=32,
                height=32,
                border_radius=16,
                bgcolor=ft.colors.WHITE,
                border=ft.border.all(1, ft.colors.with_opacity(0.18, ft.colors.BLACK)),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=10,
                    color=ft.colors.with_opacity(0.22, ft.colors.BLACK),
                    offset=ft.Offset(0, 3),
                ),
                content=ft.Stack([
                    ft.Icon(ft.icons.INSERT_DRIVE_FILE_OUTLINED, size=17, color=ft.colors.GREY_500),
                    ft.Container(
                        right=1,
                        bottom=1,
                        width=11,
                        height=11,
                        border_radius=5.5,
                        bgcolor=ft.colors.RED_500,
                        alignment=ft.alignment.center,
                        content=ft.Icon(ft.icons.ADD_ROUNDED, size=8, color=ft.colors.WHITE),
                    ),
                ], clip_behavior=ft.ClipBehavior.NONE),
                alignment=ft.alignment.center,
            )
            add_blank_btn.visible = False

            card_stack = ft.Stack([
                ft.Container(content=thumb, bgcolor=ft.colors.WHITE, border_radius=6, padding=2),
                drag_handle,
                sel_icon,
                rotate_btn,
                x_btn,
                split_badge,
                rot_badge,
                add_blank_btn,
            ], clip_behavior=ft.ClipBehavior.NONE)

            def _on_card_hover(e):
                hovered = e.data == "true"
                x_btn.visible = hovered
                rotate_btn.visible = hovered
                add_blank_btn.visible = hovered and tid() == "edit"
                card_stack.update()

            card = ft.Container(
                content=card_stack,
                width=_CARD_W + _CARD_PAD * 2,
                height=_CARD_H + _CARD_PAD * 2,
                padding=_CARD_PAD,
                border_radius=10,
                border=None,
                clip_behavior=ft.ClipBehavior.NONE,
                bgcolor=ft.colors.with_opacity(
                    0.14 if is_sel else (0.08 if is_split else 0.04),
                    task_color if is_sel else (ft.colors.BLUE_400 if is_split else ft.colors.WHITE),
                ),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=10 if (is_sel or is_split) else 6,
                    color=ft.colors.with_opacity(
                        0.35 if (is_sel or is_split) else 0.16,
                        task_color if is_sel else (ft.colors.BLUE_400 if is_split else ft.colors.BLACK),
                    ),
                    offset=ft.Offset(0, 2),
                ),
                on_click=lambda _, p=pos: _on_card_click(p),
                on_hover=_on_card_hover,
            )

            card_col = ft.Column([
                card,
                ft.Text(str(pos + 1), size=10, color=ft.colors.GREY_500, text_align=ft.TextAlign.CENTER),
            ], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

            interactive_card = ft.GestureDetector(
                content=card_col,
                on_double_tap=lambda _, p=pos: _open_preview(p),
            )

            draggable = ft.Draggable(
                group="pdf_pages",
                data=str(pos),
                content=interactive_card,
                content_when_dragging=ft.Container(
                    width=_CARD_W + _CARD_PAD * 2,
                    height=_CARD_H + _CARD_PAD * 2 + 22,
                    bgcolor=ft.colors.with_opacity(0.07, ft.colors.RED_400),
                    border=ft.border.all(2, ft.colors.with_opacity(0.25, ft.colors.RED_400)),
                    border_radius=10,
                ),
                content_feedback=ft.Container(
                    content=(
                        ft.Container(
                            width=90,
                            height=120,
                            bgcolor=ft.colors.WHITE,
                            border_radius=6,
                            border=ft.border.all(1, ft.colors.GREY_300),
                            alignment=ft.alignment.center,
                            content=ft.Text("Blanco", size=10, color=ft.colors.GREY_700),
                        )
                        if is_blank
                        else ft.Image(
                            src_base64=pd["img_b64"],
                            width=90,
                            height=120,
                            fit=ft.ImageFit.CONTAIN,
                            border_radius=6,
                        )
                    ),
                    bgcolor=ft.colors.WHITE,
                    border_radius=8,
                    padding=4,
                    shadow=ft.BoxShadow(blur_radius=18, color=ft.colors.BLACK54),
                    opacity=0.88,
                ),
            )

            # Placeholder visual de destino mientras se arrastra una pagina.
            drop_placeholder = ft.Container(
                width=_CARD_W + _CARD_PAD * 2,
                height=_CARD_H + _CARD_PAD * 2 + 22,
                visible=False,
                border=ft.border.all(2, ft.colors.CYAN_300),
                border_radius=10,
                bgcolor=ft.colors.with_opacity(0.08, ft.colors.CYAN_300),
                alignment=ft.alignment.center,
                content=ft.Text("Soltar aqui", size=10, color=ft.colors.CYAN_200, weight="bold"),
            )

            target_content = ft.Stack([
                draggable,
                drop_placeholder,
            ])

            def _on_will_accept(e):
                drop_placeholder.visible = e.data == "true"
                target_content.update()

            def _on_leave(_):
                drop_placeholder.visible = False
                target_content.update()

            def _on_accept(e, tp=pos):
                drop_placeholder.visible = False
                target_content.update()
                _on_drop(e, tp)

            return ft.DragTarget(
                group="pdf_pages",
                on_will_accept=_on_will_accept,
                on_leave=_on_leave,
                on_accept=_on_accept,
                content=target_content,
            )

        def _select_all(_=None):
            if tid() == "split":
                for i, p in enumerate(pages_state):
                    p["split_before"] = i > 0
            else:
                for p in pages_state:
                    p["selected"] = True
            _rebuild_grid()

        def _deselect_all(_=None):
            if tid() == "split":
                for p in pages_state:
                    p["split_before"] = False
            else:
                for p in pages_state:
                    p["selected"] = False
            _rebuild_grid()

        def _are_all_marked() -> bool:
            if not pages_state:
                return False
            if tid() == "split":
                if len(pages_state) <= 1:
                    return False
                return all(pages_state[i].get("split_before", False) for i in range(1, len(pages_state)))
            return all(p.get("selected", False) for p in pages_state)

        def _toggle_all(_=None):
            if _are_all_marked():
                _deselect_all()
            else:
                _select_all()

        def _invert_sel(_=None):
            if tid() == "split":
                for i, p in enumerate(pages_state):
                    if i > 0:
                        p["split_before"] = not p.get("split_before", False)
            else:
                for p in pages_state:
                    p["selected"] = not p.get("selected", False)
            _rebuild_grid()

        def _delete_selected(_=None):
            if tid() == "split":
                pages_state[:] = [
                    p for i, p in enumerate(pages_state)
                    if not (i > 0 and p.get("split_before", False))
                ]
            else:
                pages_state[:] = [p for p in pages_state if not p.get("selected")]
            _rebuild_grid()

        def _chip_btn(label: str, on_click, color=ft.colors.GREY_400, icon=None):
            return ft.OutlinedButton(
                label,
                icon=icon,
                on_click=on_click,
                height=30,
                style=ft.ButtonStyle(
                    color=color,
                    side=ft.BorderSide(1, ft.colors.WHITE24),
                    shape=ft.RoundedRectangleBorder(radius=16),
                    padding=ft.padding.symmetric(horizontal=10, vertical=0),
                ),
            )

        btn_toggle_all = _chip_btn("Todas", _toggle_all, icon=ft.icons.DONE_ALL_ROUNDED)
        btn_invert = _chip_btn("Invertir", _invert_sel, icon=ft.icons.SWAP_HORIZ_ROUNDED)
        btn_delete_sel = _chip_btn("Eliminar selec.", _delete_selected, ft.colors.RED_400, ft.icons.DELETE_OUTLINE_ROUNDED)
        btn_add_more = _chip_btn("Anadir PDF", _pick_more_files, ft.colors.CYAN_300, ft.icons.ADD_ROUNDED)

        action_row = ft.Row([
            btn_toggle_all,
            btn_invert,
            btn_delete_sel,
            btn_add_more,
        ], spacing=6, wrap=False, visible=False)

        actions_help = ft.Text(
            "Tip: arrastra hojas para moverlas. En hover aparecen +, rotar y eliminar.",
            size=10,
            color=ft.colors.GREY_500,
            italic=True,
            visible=False,
        )

        def _update_action_row():
            show_actions = True
            all_marked = _are_all_marked()
            btn_toggle_all.text = "Ninguna" if all_marked else "Todas"
            btn_toggle_all.icon = ft.icons.REMOVE_DONE_ROUNDED if all_marked else ft.icons.DONE_ALL_ROUNDED

            btn_toggle_all.visible = show_actions
            btn_invert.visible = show_actions
            btn_delete_sel.visible = show_actions
            btn_add_more.visible = len(loaded_files) > 0

            tips = {
                "edit": "Tip: arrastra hojas para moverlas. En hover aparecen +, rotar y eliminar.",
                "merge": "Tip: carga uno o varios PDFs, ordena paginas y luego guarda el PDF unido.",
                "split": "Tip: marca puntos de corte con clic y guarda para generar partes separadas.",
                "to_word": "Tip: selecciona paginas si deseas filtrar y guarda para exportar a Word.",
                "to_excel": "Tip: selecciona paginas si deseas filtrar y guarda para exportar a Excel.",
                "to_jpg": "Tip: marca paginas a exportar y guarda para generar imagenes JPG.",
            }
            actions_help.value = tips.get(tid(), "")
            actions_help.visible = bool(actions_help.value)
            show_save = bool(save_btn_ref.get("ctrl") and save_btn_ref["ctrl"].visible)
            action_row.visible = show_actions or show_save or btn_add_more.visible
            _safe_up(btn_toggle_all, btn_invert, btn_delete_sel, btn_add_more, action_row, actions_help)

        pages_wrap = ft.Row([], wrap=True, spacing=12, run_spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)
        empty_hint = ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            content=ft.Column([
                drop_zone,
                ft.Row([loading_spin, loading_txt], spacing=6, alignment=ft.MainAxisAlignment.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
        )
        grid_area = ft.Container(expand=True, content=empty_hint)

        prog_bar = ft.ProgressBar(value=0, visible=False, expand=True,
                                  color=ft.colors.RED_400, bgcolor=ft.colors.WHITE10,
                                  bar_height=5, border_radius=3)
        prog_txt = ft.Text("", size=10, color=ft.colors.GREY_500)
        result_box = ft.Container(visible=False)

        def _on_progress(pct: float, msg: str):
            prog_bar.value = pct
            prog_bar.visible = True
            prog_txt.value = msg
            page.update()

        def _reset_result():
            prog_bar.value = 0
            prog_bar.visible = False
            prog_txt.value = ""
            result_box.visible = False
            _safe_up(prog_bar, prog_txt, result_box)

        def _show_result(ok: bool, res: str):
            is_file = os.path.isfile(res) if ok else False
            result_box.visible = True
            result_box.content = ft.Container(
                padding=ft.padding.all(12),
                border_radius=10,
                bgcolor=ft.colors.with_opacity(0.10, ft.colors.GREEN_400 if ok else ft.colors.RED_400),
                border=ft.border.all(1, ft.colors.with_opacity(0.4, ft.colors.GREEN_400 if ok else ft.colors.RED_400)),
                content=ft.Row([
                    ft.Icon(ft.icons.CHECK_CIRCLE_ROUNDED if ok else ft.icons.ERROR_ROUNDED,
                            color=ft.colors.GREEN_400 if ok else ft.colors.RED_400, size=22),
                    ft.Column([
                        ft.Text("Listo" if ok else "Error", size=12, weight="bold",
                                color=ft.colors.GREEN_300 if ok else ft.colors.RED_300),
                        ft.Text(Path(res).name if is_file else res, size=9, color=ft.colors.GREY_400,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, expand=True),
                    ft.ElevatedButton(
                        "Abrir",
                        icon=ft.icons.FOLDER_OPEN_ROUNDED,
                        visible=ok,
                        on_click=lambda _: os.startfile(str(Path(res).parent) if is_file else res),
                        bgcolor=ft.colors.GREEN_700,
                        color=ft.colors.WHITE,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            page.update()

        def _run_task(save_path=None):
            if not loaded_files:
                _show_result(False, "Carga un archivo PDF primero.")
                return

            _reset_result()
            _set_save_busy(True)

            def _thread():
                try:
                    task = tid()
                    out_dir = str(Path(loaded_files[0]).parent)
                    stem = Path(loaded_files[0]).stem
                    if save_path:
                        out_dir = str(Path(save_path).parent)
                        stem = Path(save_path).stem

                    def _export_pages_fitz(seq, out_file, progress_base=0.0, progress_span=1.0):
                        if not _HAS_FITZ:
                            raise RuntimeError("PyMuPDF no esta instalado.")

                        src_docs = {}
                        out_doc = fitz.open()
                        try:
                            total = max(len(seq), 1)
                            for i, pd in enumerate(seq):
                                if pd.get("is_blank"):
                                    pw = float(pd.get("page_w", 595))
                                    ph = float(pd.get("page_h", 842))
                                    out_doc.new_page(width=pw, height=ph)
                                else:
                                    src_path = pd.get("src_file") or loaded_files[0]
                                    if src_path not in src_docs:
                                        src_docs[src_path] = fitz.open(src_path)
                                    src_doc = src_docs[src_path]
                                    pno = int(pd["orig_page"])
                                    src_page = src_doc[pno]
                                    rot = int(pd.get("rotation", 0)) % 360

                                    if rot in (90, 270):
                                        pw, ph = float(src_page.rect.height), float(src_page.rect.width)
                                    else:
                                        pw, ph = float(src_page.rect.width), float(src_page.rect.height)

                                    out_page = out_doc.new_page(width=pw, height=ph)
                                    out_page.show_pdf_page(out_page.rect, src_doc, pno, rotate=rot)

                                pct = progress_base + progress_span * ((i + 1) / total)
                                _on_progress(pct, f"Procesando pagina {i + 1}/{total}...")

                            out_doc.save(out_file, garbage=4, deflate=True)
                        finally:
                            try:
                                out_doc.close()
                            except Exception:
                                pass
                            for d in src_docs.values():
                                try:
                                    d.close()
                                except Exception:
                                    pass

                    if task == "edit":
                        out = _ensure_ext(save_path, ".pdf") if save_path else os.path.join(out_dir, f"{stem}_editado.pdf")
                        _export_pages_fitz(pages_state, out)
                        _on_progress(1.0, "Completado")
                        _show_result(True, out)

                    elif task == "merge":
                        out = _ensure_ext(save_path, ".pdf") if save_path else os.path.join(out_dir, "PDFs_unidos.pdf")
                        _export_pages_fitz(pages_state, out)
                        _show_result(True, out)

                    elif task == "split":
                        split_idxs = sorted(i for i, p in enumerate(pages_state) if p.get("split_before") and i > 0)
                        if not split_idxs:
                            _show_result(False, "Marca cortes haciendo clic en paginas.")
                            return
                        seg_dir = os.path.join(out_dir, f"{stem}_partes")
                        os.makedirs(seg_dir, exist_ok=True)
                        bounds = [0] + split_idxs + [len(pages_state)]
                        segs = list(zip(bounds, bounds[1:]))
                        for idx, (s, e_) in enumerate(segs):
                            sp = os.path.join(seg_dir, f"{stem}_parte_{idx + 1:02d}.pdf")
                            base = idx / len(segs)
                            span = 1 / len(segs)
                            _export_pages_fitz(pages_state[s:e_], sp, base, span)
                        _show_result(True, seg_dir)

                    elif task == "to_word":
                        out = _ensure_ext(save_path, ".docx") if save_path else os.path.join(out_dir, f"{stem}.docx")
                        selected_seq = [p for p in pages_state if p.get("selected")]
                        seq = selected_seq if selected_seq else list(pages_state)
                        seq = [p for p in seq if not p.get("is_blank")]
                        if not seq:
                            _show_result(False, "No hay paginas validas para exportar a Word.")
                            return

                        import tempfile
                        tmp_pdf = os.path.join(tempfile.gettempdir(), f"tk_word_{os.getpid()}_{threading.get_ident()}.pdf")
                        try:
                            _export_pages_fitz(seq, tmp_pdf)
                            ok, res = mgr.pdf_to_word(tmp_pdf, out, _on_progress)
                        finally:
                            try:
                                if os.path.exists(tmp_pdf):
                                    os.remove(tmp_pdf)
                            except Exception:
                                pass
                        _show_result(ok, res)

                    elif task == "to_excel":
                        out = _ensure_ext(save_path, ".xlsx") if save_path else os.path.join(out_dir, f"{stem}.xlsx")
                        selected_seq = [p for p in pages_state if p.get("selected")]
                        seq = selected_seq if selected_seq else list(pages_state)
                        seq = [p for p in seq if not p.get("is_blank")]
                        if not seq:
                            _show_result(False, "No hay paginas validas para exportar a Excel.")
                            return

                        import tempfile
                        tmp_pdf = os.path.join(tempfile.gettempdir(), f"tk_excel_{os.getpid()}_{threading.get_ident()}.pdf")
                        try:
                            _export_pages_fitz(seq, tmp_pdf)
                            ok, res = mgr.pdf_to_excel(tmp_pdf, out, _on_progress)
                        finally:
                            try:
                                if os.path.exists(tmp_pdf):
                                    os.remove(tmp_pdf)
                            except Exception:
                                pass
                        _show_result(ok, res)

                    elif task == "to_jpg":
                        selected_seq = [p for p in pages_state if p.get("selected")]
                        seq = selected_seq if selected_seq else list(pages_state)
                        seq = [p for p in seq if not p.get("is_blank")]
                        if not seq:
                            _show_result(False, "No hay paginas del PDF original para exportar a JPG.")
                            return

                        img_dir = os.path.join(out_dir, f"{stem}_imagenes")
                        import tempfile
                        tmp_pdf = os.path.join(tempfile.gettempdir(), f"tk_jpg_{os.getpid()}_{threading.get_ident()}.pdf")
                        try:
                            _export_pages_fitz(seq, tmp_pdf)
                            ok, res = mgr.pdf_to_images(tmp_pdf, img_dir, int(jpg_export_ref["dpi"] or 150), _on_progress)
                        finally:
                            try:
                                if os.path.exists(tmp_pdf):
                                    os.remove(tmp_pdf)
                            except Exception:
                                pass
                        _show_result(ok, res)

                except Exception as ex:
                    _show_result(False, str(ex))
                finally:
                    _set_save_busy(False)

            activity.background("PDF", _thread)

        save_btn_icon = ft.Icon(ft.icons.SAVE_ROUNDED, size=18, color=ft.colors.WHITE)
        save_btn_text = ft.Text("GUARDAR", size=13, weight="w700", color=ft.colors.WHITE)

        def _update_save_button():
            if save_btn_ref["ctrl"] is None:
                return

            task = tid()
            task_color = next((t["color"] for t in self.TASKS if t["id"] == task), ft.colors.RED_500)
            labels = {
                "edit": "GUARDAR PDF",
                "merge": "UNIR Y GUARDAR",
                "split": "DIVIDIR PDF",
                "to_word": "EXPORTAR WORD",
                "to_excel": "EXPORTAR EXCEL",
                "to_jpg": "EXPORTAR JPG",
            }
            icons = {
                "edit": ft.icons.SAVE_ROUNDED,
                "merge": ft.icons.FILE_COPY_ROUNDED,
                "split": ft.icons.CONTENT_CUT_ROUNDED,
                "to_word": ft.icons.DESCRIPTION_ROUNDED,
                "to_excel": ft.icons.TABLE_CHART_ROUNDED,
                "to_jpg": ft.icons.IMAGE_ROUNDED,
            }

            save_btn_ref["idle_text"] = labels.get(task, "GUARDAR")
            save_btn_ref["idle_icon"] = icons.get(task, ft.icons.SAVE_ROUNDED)

            btn = save_btn_ref["ctrl"]
            btn.visible = len(loaded_files) > 0
            btn.gradient = ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=[ft.colors.with_opacity(0.82, task_color), task_color],
            )
            btn.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=16,
                color=ft.colors.with_opacity(0.32, task_color),
                offset=ft.Offset(0, 5),
            )

            if not save_btn_ref["busy"]:
                save_btn_icon.name = save_btn_ref["idle_icon"]
                save_btn_text.value = save_btn_ref["idle_text"]

            _safe_up(save_btn_icon, save_btn_text, btn)
            _update_action_row()

        def _open_save_dialog(_=None):
            if save_btn_ref["busy"]:
                return
            if not loaded_files:
                _show_result(False, "Carga un archivo PDF primero.")
                return
            if tid() == "to_jpg":
                jpg_quality_overlay.visible = True
                _safe_up(jpg_quality_overlay)
                return
            suggested_name, ext = _suggest_save_name()
            save_picker.save_file(
                dialog_title="Guardar resultado",
                file_name=suggested_name,
                allowed_extensions=[ext.replace(".", "")],
                initial_directory=str(Path(loaded_files[0]).parent),
            )

        def _set_save_busy(is_busy: bool):
            save_btn_ref["busy"] = is_busy
            if is_busy:
                save_btn_icon.name = ft.icons.HOURGLASS_TOP_ROUNDED
                save_btn_text.value = "PROCESANDO..."
            else:
                save_btn_icon.name = save_btn_ref.get("idle_icon", ft.icons.SAVE_ROUNDED)
                save_btn_text.value = save_btn_ref.get("idle_text", "GUARDAR")
            save_btn_ref["ctrl"].opacity = 0.78 if is_busy else 1.0
            _safe_up(save_btn_icon, save_btn_text, save_btn_ref["ctrl"])

        btn_save = ft.Container(
            visible=False,
            width=182,
            height=50,
            alignment=ft.alignment.center,
            border_radius=14,
            gradient=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=[ft.colors.RED_700, ft.colors.RED_500],
            ),
            border=ft.border.all(1, ft.colors.with_opacity(0.38, ft.colors.WHITE)),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=16,
                color=ft.colors.with_opacity(0.32, ft.colors.RED_700),
                offset=ft.Offset(0, 5),
            ),
            on_click=_open_save_dialog,
            ink=True,
            content=ft.Row([
                ft.Container(
                    width=28,
                    height=28,
                    border_radius=14,
                    bgcolor=ft.colors.with_opacity(0.22, ft.colors.WHITE),
                    alignment=ft.alignment.center,
                    content=save_btn_icon,
                ),
                save_btn_text,
            ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
        )
        save_btn_ref["ctrl"] = btn_save
        save_btn_ref["busy"] = False
        action_row.controls.extend([
            ft.Container(expand=True),
            btn_save,
        ])
        _update_save_button()

        _rebuild_chips()
        _update_options()
        _update_action_row()
        _rebuild_grid()

        left_panel = ft.Container(
            width=300,
            bgcolor=ft.colors.BLACK26,
            border_radius=18,
            padding=ft.padding.all(18),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.RED_400, size=17),
                    ft.Text("HERRAMIENTAS", weight="bold", size=14, color=ft.colors.WHITE),
                ], spacing=8),
                ft.Divider(height=1, color=ft.colors.WHITE10),
                ft.Container(height=4),
                chips_row,
                ft.Container(height=8),
                options_col,
                ft.Container(height=12),
            ], scroll=ft.ScrollMode.AUTO),
        )

        right_panel = ft.Container(
            expand=True,
            bgcolor=ft.colors.BLACK26,
            border_radius=18,
            padding=ft.padding.all(18),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.icons.GRID_VIEW_ROUNDED, color=ft.colors.RED_400, size=17),
                    ft.Text("PAGINAS", weight="bold", size=14, color=ft.colors.WHITE),
                    pg_count_txt,
                    sel_count_txt,
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                action_row,
                actions_help,
                ft.Divider(height=1, color=ft.colors.WHITE10),
                grid_area,
                ft.Container(height=6),
                ft.Row([prog_bar]),
                prog_txt,
                ft.Container(height=4),
                result_box,
            ], expand=True),
        )

        load_prog_bar = ft.ProgressBar(
            value=0,
            width=320,
            bar_height=8,
            border_radius=999,
            color=ft.colors.RED_400,
            bgcolor=ft.colors.with_opacity(0.18, ft.colors.WHITE),
        )
        load_pct_txt = ft.Text("0%", size=18, weight="bold", color=ft.colors.WHITE)
        load_msg_txt = ft.Text(
            "Subiendo archivo PDF...",
            size=11,
            color=ft.colors.with_opacity(0.82, ft.colors.WHITE),
            text_align=ft.TextAlign.CENTER,
        )
        load_overlay = ft.Container(
            visible=False,
            expand=True,
            bgcolor=ft.colors.with_opacity(0.42, ft.colors.BLACK),
            alignment=ft.alignment.center,
            content=ft.Container(
                width=420,
                height=232,
                alignment=ft.alignment.center,
                padding=ft.padding.symmetric(horizontal=24, vertical=22),
                border_radius=22,
                bgcolor=ft.colors.with_opacity(0.92, ft.colors.BLUE_GREY_900),
                border=ft.border.all(1, ft.colors.with_opacity(0.14, ft.colors.WHITE)),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=30,
                    color=ft.colors.with_opacity(0.35, ft.colors.BLACK),
                    offset=ft.Offset(0, 10),
                ),
                content=ft.Column([
                    ft.Container(
                        width=56,
                        height=56,
                        border_radius=28,
                        alignment=ft.alignment.center,
                        bgcolor=ft.colors.with_opacity(0.16, ft.colors.RED_400),
                        content=ft.Icon(ft.icons.UPLOAD_FILE_ROUNDED, size=28, color=ft.colors.RED_200),
                    ),
                    ft.Text("Cargando PDF", size=20, weight="w700", color=ft.colors.WHITE),
                    load_prog_bar,
                    load_pct_txt,
                    load_msg_txt,
                ],
                    spacing=12,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ),
        )

        def _set_jpg_quality(dpi: str):
            jpg_export_ref["dpi"] = dpi
            jpg_96_card.border = ft.border.all(1.4, ft.colors.ORANGE_300 if dpi == "96" else ft.colors.WHITE12)
            jpg_150_card.border = ft.border.all(1.4, ft.colors.ORANGE_300 if dpi == "150" else ft.colors.WHITE12)
            jpg_300_card.border = ft.border.all(1.4, ft.colors.ORANGE_300 if dpi == "300" else ft.colors.WHITE12)
            jpg_96_card.bgcolor = ft.colors.with_opacity(0.18, ft.colors.ORANGE_400) if dpi == "96" else ft.colors.with_opacity(0.06, ft.colors.WHITE)
            jpg_150_card.bgcolor = ft.colors.with_opacity(0.18, ft.colors.ORANGE_400) if dpi == "150" else ft.colors.with_opacity(0.06, ft.colors.WHITE)
            jpg_300_card.bgcolor = ft.colors.with_opacity(0.18, ft.colors.ORANGE_400) if dpi == "300" else ft.colors.with_opacity(0.06, ft.colors.WHITE)
            _safe_up(jpg_96_card, jpg_150_card, jpg_300_card)

        def _close_jpg_quality(_=None):
            jpg_quality_overlay.visible = False
            _safe_up(jpg_quality_overlay)

        def _confirm_jpg_quality(_=None):
            jpg_quality_overlay.visible = False
            _safe_up(jpg_quality_overlay)
            suggested_name, ext = _suggest_save_name()
            save_picker.save_file(
                dialog_title="Guardar imagenes JPG",
                file_name=suggested_name,
                allowed_extensions=[ext.replace(".", "")],
                initial_directory=str(Path(loaded_files[0]).parent),
            )

        def _jpg_quality_card(title: str, subtitle: str, dpi: str, recommended: bool = False):
            return ft.Container(
                width=160,
                height=108,
                border_radius=16,
                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                border=ft.border.all(1.4, ft.colors.WHITE12),
                bgcolor=ft.colors.with_opacity(0.06, ft.colors.WHITE),
                on_click=lambda _, v=dpi: (_set_jpg_quality(v)),
                ink=True,
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            width=34,
                            height=34,
                            border_radius=17,
                            alignment=ft.alignment.center,
                            bgcolor=ft.colors.with_opacity(0.14, ft.colors.ORANGE_400),
                            content=ft.Icon(ft.icons.IMAGE_ROUNDED, size=18, color=ft.colors.ORANGE_300),
                        ),
                        ft.Container(expand=True),
                        ft.Container(
                            visible=recommended,
                            padding=ft.padding.symmetric(horizontal=8, vertical=4),
                            border_radius=999,
                            bgcolor=ft.colors.with_opacity(0.14, ft.colors.ORANGE_300),
                            content=ft.Text("Recomendado", size=8, color=ft.colors.ORANGE_200, weight="bold"),
                        ),
                    ]),
                    ft.Text(title, size=16, weight="w700", color=ft.colors.WHITE),
                    ft.Text(subtitle, size=10, color=ft.colors.GREY_300),
                ], spacing=10),
            )

        jpg_96_card = _jpg_quality_card("96 DPI", "Rapido y ligero", "96")
        jpg_150_card = _jpg_quality_card("150 DPI", "Balanceado para compartir", "150", recommended=True)
        jpg_300_card = _jpg_quality_card("300 DPI", "Alta calidad para imprimir", "300")
        _set_jpg_quality(jpg_export_ref["dpi"])
        jpg_continue_btn = ft.Container(
            height=44,
            padding=ft.padding.symmetric(horizontal=18),
            border_radius=14,
            gradient=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=[ft.colors.ORANGE_400, ft.colors.ORANGE_600],
            ),
            border=ft.border.all(1, ft.colors.with_opacity(0.20, ft.colors.WHITE)),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=16,
                color=ft.colors.with_opacity(0.30, ft.colors.ORANGE_700),
                offset=ft.Offset(0, 5),
            ),
            on_click=_confirm_jpg_quality,
            ink=True,
            content=ft.Row([
                ft.Icon(ft.icons.ARROW_FORWARD_ROUNDED, size=18, color=ft.colors.WHITE),
                ft.Text("Continuar", size=13, weight="w700", color=ft.colors.WHITE),
            ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        )

        jpg_quality_overlay = ft.Container(
            visible=False,
            expand=True,
            bgcolor=ft.colors.with_opacity(0.55, ft.colors.BLACK),
            alignment=ft.alignment.center,
            content=ft.Container(
                width=620,
                height=288,
                alignment=ft.alignment.center,
                padding=ft.padding.symmetric(horizontal=24, vertical=22),
                border_radius=24,
                bgcolor=ft.colors.with_opacity(0.97, ft.colors.BLUE_GREY_900),
                border=ft.border.all(1, ft.colors.with_opacity(0.14, ft.colors.WHITE)),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=34,
                    color=ft.colors.with_opacity(0.4, ft.colors.BLACK),
                    offset=ft.Offset(0, 12),
                ),
                content=ft.Column([
                    ft.Row([
                        ft.Column([
                            ft.Text("Calidad de exportacion JPG", size=22, weight="w700", color=ft.colors.WHITE),
                            ft.Text("Selecciona la resolucion antes de elegir la ruta de salida.", size=11, color=ft.colors.GREY_400),
                        ], spacing=4),
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.icons.CLOSE_ROUNDED,
                            icon_color=ft.colors.WHITE,
                            on_click=_close_jpg_quality,
                            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE)),
                        ),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Row([
                        jpg_96_card,
                        jpg_150_card,
                        jpg_300_card,
                    ], spacing=12, wrap=True),
                    ft.Row([
                        ft.TextButton("Cancelar", on_click=_close_jpg_quality),
                        ft.Container(expand=True),
                        jpg_continue_btn,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=18, alignment=ft.MainAxisAlignment.CENTER),
            ),
            on_click=_close_jpg_quality,
        )

        preview_title = ft.Text("Vista previa", size=18, weight="w700", color=ft.colors.WHITE)
        preview_page_txt = ft.Text("Pagina 1 de 1", size=11, color=ft.colors.GREY_400)
        preview_zoom_txt = ft.Text("100%", size=11, color=ft.colors.GREY_300, weight="bold")
        prev_btn = ft.OutlinedButton("Anterior", icon=ft.icons.CHEVRON_LEFT_ROUNDED, on_click=_preview_prev, height=34)
        next_btn = ft.OutlinedButton("Siguiente", icon=ft.icons.CHEVRON_RIGHT_ROUNDED, on_click=_preview_next, height=34)
        preview_image = ft.Image(
            visible=False,
            width=_PREVIEW_BOX_W,
            height=_PREVIEW_BOX_H,
            fit=ft.ImageFit.CONTAIN,
            border_radius=14,
        )
        preview_placeholder = ft.Container(
            visible=False,
            width=_PREVIEW_BOX_W,
            height=_PREVIEW_BOX_H,
            border_radius=14,
            bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE),
            alignment=ft.alignment.center,
            content=ft.Column([
                ft.Icon(ft.icons.ARTICLE_OUTLINED, size=48, color=ft.colors.GREY_300),
                ft.Text("Pagina en blanco", size=16, color=ft.colors.WHITE),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )
        preview_surface = ft.Stack([
            preview_placeholder,
            preview_image,
        ], alignment=ft.alignment.center)
        preview_viewer = ft.InteractiveViewer(
            content=preview_surface,
            pan_enabled=True,
            scale_enabled=False,
            constrained=False,
            alignment=ft.alignment.center,
            boundary_margin=ft.margin.all(120),
            min_scale=1.0,
            max_scale=1.0,
        )
        preview_zoom_area = ft.GestureDetector(
            content=preview_viewer,
            on_scroll=_preview_on_scroll,
            mouse_cursor=ft.MouseCursor.GRAB,
        )
        preview_overlay = ft.Container(
            visible=False,
            expand=True,
            bgcolor=ft.colors.with_opacity(0.58, ft.colors.BLACK),
            alignment=ft.alignment.center,
            content=ft.Container(
                width=840,
                height=670,
                padding=ft.padding.symmetric(horizontal=20, vertical=18),
                border_radius=24,
                bgcolor=ft.colors.with_opacity(0.97, ft.colors.BLUE_GREY_900),
                border=ft.border.all(1, ft.colors.with_opacity(0.12, ft.colors.WHITE)),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=32,
                    color=ft.colors.with_opacity(0.38, ft.colors.BLACK),
                    offset=ft.Offset(0, 12),
                ),
                content=ft.Column([
                    ft.Row([
                        ft.Column([preview_title, preview_page_txt], spacing=2),
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.icons.ZOOM_OUT_ROUNDED,
                            icon_color=ft.colors.WHITE,
                            tooltip="Alejar",
                            on_click=_preview_zoom_out,
                            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE)),
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=8),
                            border_radius=999,
                            bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE),
                            content=preview_zoom_txt,
                        ),
                        ft.IconButton(
                            icon=ft.icons.ZOOM_IN_ROUNDED,
                            icon_color=ft.colors.WHITE,
                            tooltip="Acercar",
                            on_click=_preview_zoom_in,
                            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.08, ft.colors.WHITE)),
                        ),
                        ft.TextButton("Ajustar", on_click=_preview_zoom_reset),
                        ft.IconButton(
                            icon=ft.icons.CLOSE_ROUNDED,
                            icon_color=ft.colors.WHITE,
                            tooltip="Cerrar vista previa",
                            on_click=_close_preview,
                            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.10, ft.colors.WHITE)),
                        ),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(
                        expand=True,
                        alignment=ft.alignment.center,
                        content=ft.Column([
                            ft.Row([
                                ft.Container(expand=True),
                                prev_btn,
                                ft.Container(width=8),
                                next_btn,
                                ft.Container(expand=True),
                            ], alignment=ft.MainAxisAlignment.CENTER),
                            ft.Container(
                                expand=True,
                                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                                border_radius=16,
                                bgcolor=ft.colors.with_opacity(0.04, ft.colors.WHITE),
                                content=ft.Container(
                                    expand=True,
                                    alignment=ft.alignment.center,
                                    content=preview_zoom_area,
                                ),
                            ),
                        ], spacing=10, expand=True),
                    ),
                    ft.Text(
                        "Doble clic para abrir. Usa Anterior/Siguiente y los controles de zoom para revisar el documento.",
                        size=11,
                        color=ft.colors.GREY_400,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ], spacing=12),
            ),
            on_click=_close_preview,
        )

        return ft.Container(
            expand=True,
            padding=10,
            content=ft.Stack([
                ft.Column([
                    self._section_header(
                        ft.icons.PICTURE_AS_PDF_ROUNDED,
                        ft.colors.RED_400,
                        "Editor PDF",
                        "Reorganiza, elimina y convierte paginas de PDF",
                        self._back_button("Volver a Herramientas", navigate_fn, 2),
                    ),
                    ft.Row([left_panel, right_panel], expand=True, spacing=16,
                           vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                    file_picker,
                    save_picker,
                ], expand=True),
                load_overlay,
                jpg_quality_overlay,
                preview_overlay,
            ], expand=True),
        )
