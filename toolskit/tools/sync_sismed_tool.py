"""
sync_sismed_tool.py
===================
Herramienta: Sync SISMED
Categoría  : Sync

Encapsula la UI de sincronización de stock SISMED a Google Sheets.
Sus controles principales son stateful (singleton) para mantener
la conexión y logs aunque el usuario cambie de pestaña.
"""

import sys
import os
import flet as ft

from sismed_sync import SismedSyncManager
from tools.base_tool import SismedTool, ToolMetadata

class SyncSismedTool(SismedTool):
    """Sincroniza el inventario en tiempo real con Google Sheets."""

    def __init__(self):
        super().__init__()
        self._initialized = False
        self.sync_manager = None
        
        # UI controls that need to persist state
        self.sync_logs = None
        self.btn_toggle_sync = None
        self._view = None

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Sync SISMED",
            descripcion="Sincroniza el stock de SISMED con Google Sheets en tiempo real",
            icono=ft.icons.CLOUD_SYNC_ROUNDED,
            color=ft.colors.CYAN_500,
            categoria="Sync",
            etiquetas=["sync", "sincronizar", "nube", "google", "sheets", "inventario"],
        )

    def _init_components(self, page: ft.Page):
        if self._initialized:
            return

        self.sync_logs = ft.ListView(
            expand=True, spacing=5, auto_scroll=True, height=210
        )

        def _on_sync_log(msg):
            try:
                self.sync_logs.controls.append(
                    ft.Text(value=msg, size=14, font_family="Consolas")
                )
                if len(self.sync_logs.controls) > 100:
                    del self.sync_logs.controls[: len(self.sync_logs.controls)-100]
                page.update()
            except Exception:
                pass

        def _on_sync_stopped():
            if self.btn_toggle_sync:
                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE),
                    ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.style.bgcolor = {
                    ft.ControlState.DEFAULT: ft.colors.CYAN_600,
                    ft.ControlState.HOVERED: ft.colors.CYAN_800
                }
                self.btn_toggle_sync.disabled = False
                page.update()

        self.sync_manager = SismedSyncManager(
            log_callback=_on_sync_log,
            on_stop_callback=_on_sync_stopped
        )

        # Cargar Preferencias
        saved_sismed_dir = page.client_storage.get("sismed_dir_sync")
        if saved_sismed_dir: self.sync_manager.base_dir = saved_sismed_dir
        
        saved_interval = page.client_storage.get("sync_interval")
        if saved_interval: self.sync_manager.intervalo_minutos = int(saved_interval)
        
        saved_consolidado = page.client_storage.get("consolidado")
        if saved_consolidado is not None: self.sync_manager.modo_consolidado = saved_consolidado
        
        saved_url = page.client_storage.get("apps_script_url")
        if saved_url: self.sync_manager.apps_script_url = saved_url

        self._initialized = True

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        self._init_components(page)

        # Si ya se creó la vista antes, simplemente la retornamos para no perder su estado visual
        if self._view:
            return self._view

        saved_auto_sync    = page.client_storage.get("auto_sync") or False
        chk_auto_sync = ft.Checkbox(
            label="Iniciar Sincronización al encender la app",
            value=saved_auto_sync,
            fill_color={ft.ControlState.SELECTED: ft.colors.GREEN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.CYAN_500, weight=ft.FontWeight.W_800),
            on_change=lambda e: page.client_storage.set("auto_sync", e.control.value)
        )

        switch_consolidado = ft.Checkbox(
            label="Sumar stock de farmacias",
            value=self.sync_manager.modo_consolidado,
            fill_color={ft.ControlState.SELECTED: ft.colors.CYAN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.ON_SURFACE)
        )

        opciones_intervalo = [ft.dropdown.Option(str(i)) for i in range(5, 65, 5)]
        val_int = str(self.sync_manager.intervalo_minutos)
        if val_int not in [opt.key for opt in opciones_intervalo]:
            val_int = "5"

        input_intervalo = ft.Dropdown(
            label="Intervalo sugerido (minutos)",
            options=opciones_intervalo,
            value=val_int,
            width=250, border_radius=8, filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.TIMER_ROUNDED,
            content_padding=10, text_size=14, menu_height=200
        )

        def _toggle_url_lock(e):
            input_apps_script.read_only = not input_apps_script.read_only
            input_apps_script.password = input_apps_script.read_only
            
            if input_apps_script.read_only:
                input_apps_script.suffix.icon = ft.icons.LOCK_ROUNDED
                input_apps_script.suffix.icon_color = ft.colors.ON_SURFACE_VARIANT
                input_apps_script.suffix.tooltip = "Desbloquear URL para editar"
                input_apps_script.border_color = ft.colors.OUTLINE_VARIANT
            else:
                input_apps_script.suffix.icon = ft.icons.LOCK_OPEN_ROUNDED
                input_apps_script.suffix.icon_color = ft.colors.CYAN_500
                input_apps_script.suffix.tooltip = "Bloquear URL segura"
                input_apps_script.border_color = ft.colors.CYAN_500
            input_apps_script.update()

        input_apps_script = ft.TextField(
            label="URL de Integración (Protegida)",
            value=self.sync_manager.apps_script_url,
            expand=True, border_radius=8, filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.LINK_ROUNDED,
            read_only=True, password=True, can_reveal_password=False,
            suffix=ft.IconButton(
                icon=ft.icons.LOCK_ROUNDED,
                tooltip="Desbloquear URL para editar",
                icon_color=ft.colors.ON_SURFACE_VARIANT,
                on_click=_toggle_url_lock
            )
        )

        def _on_sismed_dir(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed_dir.value = e.path
                input_sismed_dir.update()

        sismed_dir_picker = ft.FilePicker(on_result=_on_sismed_dir)
        page.overlay.append(sismed_dir_picker)
        page.update()

        input_sismed_dir = ft.TextField(
            label="Directorio SISMED",
            value=self.sync_manager.base_dir,
            expand=True, border_radius=8, filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.FOLDER_ROUNDED,
            suffix=ft.IconButton(
                icon=ft.icons.FOLDER_OPEN_ROUNDED,
                icon_color=ft.colors.CYAN_500,
                tooltip="Buscar carpeta SISMED",
                on_click=lambda _: sismed_dir_picker.get_directory_path()
            )
        )

        def _toggle_sync(e):
            if not self.sync_manager.is_running:
                # Iniciar
                self.sync_logs.controls.clear()
                try:
                    mins = int(input_intervalo.value)
                    if mins < 1: mins = 5
                    self.sync_manager.intervalo_minutos = mins
                except:
                    self.sync_manager.intervalo_minutos = 5
                
                self.sync_manager.modo_consolidado = switch_consolidado.value
                self.sync_manager.apps_script_url = input_apps_script.value.strip()
                self.sync_manager.base_dir = input_sismed_dir.value.strip()
                
                page.client_storage.set("sismed_dir_sync", self.sync_manager.base_dir)
                page.client_storage.set("sync_interval", str(self.sync_manager.intervalo_minutos))
                page.client_storage.set("consolidado", self.sync_manager.modo_consolidado)
                page.client_storage.set("apps_script_url", self.sync_manager.apps_script_url)

                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.STOP_ROUNDED, size=24, color=ft.colors.WHITE),
                    ft.Text("DETENER", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.style.bgcolor = {
                    ft.ControlState.DEFAULT: ft.colors.ERROR,
                    ft.ControlState.HOVERED: ft.colors.RED_700
                }
                
                self.sync_manager.start_sync()
            else:
                # Detener
                self.sync_manager.stop_sync()
                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.HOURGLASS_EMPTY, size=24, color=ft.colors.WHITE),
                    ft.Text("DETENIENDO...", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.disabled = True
            
            page.update()

        self.btn_toggle_sync = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE),
                ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
            ], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.colors.CYAN_600, ft.ControlState.HOVERED: ft.colors.CYAN_800},
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=20, vertical=15),
            ),
            on_click=_toggle_sync,
            width=180
        )

        # Si ya estaba corriendo
        if self.sync_manager.is_running:
            self.btn_toggle_sync.content = ft.Row([
                ft.Icon(ft.icons.STOP_ROUNDED, size=24, color=ft.colors.WHITE),
                ft.Text("DETENER", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
            ], alignment=ft.MainAxisAlignment.CENTER)
            self.btn_toggle_sync.style.bgcolor = {
                ft.ControlState.DEFAULT: ft.colors.ERROR,
                ft.ControlState.HOVERED: ft.colors.RED_700
            }


        # ── Layout ────────────────────────────────────────────────────────────
        self._view = ft.Container(
            padding=ft.padding.only(top=10, left=40, right=40, bottom=40),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                # Cabecera Premium
                self._section_header(
                    self.metadata.icono, self.metadata.color,
                    self.metadata.nombre,
                    self.metadata.descripcion
                ),
                ft.Divider(height=30, color=ft.colors.TRANSPARENT),
                
                ft.ResponsiveRow([
                    # Izquierda: Ajustes
                    ft.Container(
                        col={"sm": 12, "md": 12, "lg": 6, "xl": 5},
                        padding=ft.padding.only(top=38, bottom=40, left=40, right=40),
                        bgcolor=ft.colors.SURFACE_VARIANT, border_radius=20,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.CYAN_400),
                                ft.Text("Preferencias del Sistema", size=20, weight=ft.FontWeight.W_800)
                            ]),
                            ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                            ft.Container(content=input_sismed_dir, padding=ft.padding.only(top=5, bottom=0)),
                            ft.Container(content=switch_consolidado, padding=ft.padding.only(bottom=5)),
                            ft.Container(content=input_intervalo, padding=ft.padding.symmetric(vertical=8)),
                            ft.Container(content=input_apps_script, padding=ft.padding.symmetric(vertical=8)),
                            ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                            ft.Container(content=chk_auto_sync, padding=ft.padding.only(top=5))
                        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.START)
                    ),
                    # Derecha: Consola
                    ft.Container(
                        col={"sm": 12, "md": 12, "lg": 6, "xl": 7},
                        padding=30, bgcolor=ft.colors.SURFACE_VARIANT, border_radius=20,
                        content=ft.Column([
                            ft.ResponsiveRow([
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400),
                                        ft.Text("Consola de Actividad", size=18, weight=ft.FontWeight.BOLD)
                                    ]),
                                    col={"sm": 12, "md": 12, "lg": 6, "xl": 7}
                                ),
                                ft.Container(
                                    content=ft.Row([self.btn_toggle_sync], alignment=ft.MainAxisAlignment.END),
                                    col={"sm": 12, "md": 12, "lg": 6, "xl": 5}
                                )
                            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                            ft.Container(
                                content=self.sync_logs,
                                bgcolor=ft.colors.BACKGROUND, border_radius=10,
                                padding=15, height=350
                            )
                        ])
                    )
                ], spacing=30)
            ], expand=True)
        )

        # ── Auto start feature (solicitud transparente en base a checkbox) ──
        if saved_auto_sync and not self.sync_manager.is_running:
            _toggle_sync(None)

        return self._view
