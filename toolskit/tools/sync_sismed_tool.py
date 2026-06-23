"""
sync_sismed_tool.py
===================
Herramienta: Sync SISMED
Categoría  : Sync

Encapsula la UI de sincronización de stock SISMED a Google Sheets.
Sus controles principales son stateful (singleton) para mantener
la conexión y logs aunque el usuario cambie de pestaña.
"""

import os
import flet as ft
from urllib.parse import urlparse

from sismed_sync import SismedSyncManager
from tools.base_tool import SismedTool, ToolMetadata
from tools.app_config import append_runtime_log, get as cfg_get, set as cfg_set, update_runtime_status

class SyncSismedTool(SismedTool):
    """Sincroniza el inventario en tiempo real con Google Sheets."""

    def __init__(self):
        super().__init__()
        self._initialized = False
        self._startup_attempted = False
        self.last_startup_status = "not-attempted"
        self.last_startup_error = None
        self.sync_manager = None
        
        # UI controls that need to persist state
        self.sync_logs = None
        self.btn_toggle_sync = None
        self._view = None

    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        value = cfg_get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "si", "sí", "yes", "on")
        return default

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(cfg_get(key))
        except Exception:
            return default

    def _record_autostart_result(self, status: str, error: str | None = None):
        self.last_startup_status = status
        self.last_startup_error = error
        update_runtime_status("sync_autostart", status, error)
        if error:
            append_runtime_log("sync", f"autostart_status={status}; {error}")
        else:
            append_runtime_log("sync", f"autostart_status={status}")

    def _load_saved_preferences(self):
        if not self.sync_manager:
            return
        self.sync_manager.base_dir = (cfg_get("sync_sismed_dir") or r"C:\SISMEDV2").strip()
        self.sync_manager.intervalo_minutos = max(1, self._cfg_int("sync_interval_minutes", 5))
        self.sync_manager.modo_consolidado = self._cfg_bool("sync_modo_consolidado", False)
        self.sync_manager.omitir_stock_cero = self._cfg_bool("sync_omit_zero_stock", True)
        self.sync_manager.apps_script_url = (cfg_get("sync_apps_script_url") or "").strip()

    def _validate_sync_settings(self):
        if not self.sync_manager:
            return "sync-manager-unavailable", "No se pudo inicializar el sincronizador."

        url = (self.sync_manager.apps_script_url or "").strip()
        base_dir = (self.sync_manager.base_dir or "").strip()

        if not url:
            return "missing-url", "No se puede iniciar Sync SISMED automáticamente: falta la URL de integración guardada."
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.hostname:
            return "invalid-url", "No se puede iniciar Sync SISMED: la URL de integración no es válida."
        if not base_dir:
            return "missing-base-dir", "No se puede iniciar Sync SISMED: falta el directorio SISMED."
        if not os.path.isdir(base_dir):
            return "base-dir-not-found", f"No se puede iniciar Sync SISMED: el directorio SISMED no existe: {base_dir}"
        datos_dir = os.path.join(base_dir, "DATOS")
        if not os.path.isdir(datos_dir):
            return "missing-datos-dir", f"No se puede iniciar Sync SISMED: falta la carpeta DATOS en: {base_dir}"
        required_files = [
            os.path.join(datos_dir, "MMEDICAM.DBF"),
            os.path.join(datos_dir, "MSTKALMDE.DBF"),
        ]
        missing_files = [path for path in required_files if not os.path.exists(path)]
        if missing_files:
            missing_names = ", ".join(os.path.basename(path) for path in missing_files)
            return "missing-required-dbf", f"No se puede iniciar Sync SISMED: faltan archivos obligatorios: {missing_names}"
        return "ready", None

    def _start_sync_if_valid(self, page: ft.Page = None, source: str = "manual") -> bool:
        status, error = self._validate_sync_settings()
        if error:
            if source == "autostart":
                self._record_autostart_result(status, error)
            if self.sync_manager:
                self.sync_manager.log(f"⚠ {error}")
            if page:
                try:
                    page.snack_bar = ft.SnackBar(content=ft.Text(error))
                    page.snack_bar.open = True
                    page.update()
                except Exception:
                    pass
            return False
        started = self.sync_manager.start_sync()
        if not started:
            busy_message = "No se pudo iniciar Sync SISMED porque el motor aún está en transición. Intenta nuevamente en unos segundos."
            if source == "autostart":
                self._record_autostart_result("engine-busy", busy_message)
            if self.sync_manager:
                self.sync_manager.log(f"⚠ {busy_message}")
            if page:
                try:
                    page.snack_bar = ft.SnackBar(content=ft.Text(busy_message))
                    page.snack_bar.open = True
                    page.update()
                except Exception:
                    pass
            return False
        if source == "autostart":
            self._record_autostart_result("started")
        return True

    def start_from_saved(self, page: ft.Page):
        self._init_components(page)
        self._load_saved_preferences()
        self._startup_attempted = True
        if self.sync_manager.is_running:
            self._record_autostart_result("already-running")
            return False
        if not self._cfg_bool("sync_auto_start", False):
            self._record_autostart_result("auto-start-disabled")
            return False
        return self._start_sync_if_valid(page, source="autostart")

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
                append_runtime_log("sync", msg)
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

        self._load_saved_preferences()

        self._initialized = True

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        self._init_components(page)

        # Si ya se creó la vista antes, simplemente la retornamos para no perder su estado visual
        if self._view:
            return self._view

        saved_auto_sync = self._cfg_bool("sync_auto_start", False)
        chk_auto_sync = ft.Checkbox(
            label="Iniciar Sincronización al encender la app",
            value=saved_auto_sync,
            fill_color={ft.ControlState.SELECTED: ft.colors.GREEN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.CYAN_500, weight=ft.FontWeight.W_800),
            on_change=lambda e: cfg_set("sync_auto_start", bool(e.control.value)),
        )

        switch_consolidado = ft.Checkbox(
            label="Consolidar farmacias (reduce filas)",
            value=self.sync_manager.modo_consolidado,
            fill_color={ft.ControlState.SELECTED: ft.colors.CYAN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.ON_SURFACE),
            on_change=lambda e: (
                setattr(self.sync_manager, "modo_consolidado", bool(e.control.value)),
                cfg_set("sync_modo_consolidado", bool(e.control.value))
            )
        )

        chk_omit_zero_stock = ft.Checkbox(
            label="Omitir lotes con stock 0",
            value=bool(self.sync_manager.omitir_stock_cero),
            fill_color={ft.ControlState.SELECTED: ft.colors.CYAN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.ON_SURFACE),
            on_change=lambda e: (
                setattr(self.sync_manager, "omitir_stock_cero", bool(e.control.value)),
                cfg_set("sync_omit_zero_stock", bool(e.control.value))
            )
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
            content_padding=10, text_size=14, menu_height=200,
            on_change=lambda e: (
                setattr(self.sync_manager, "intervalo_minutos", max(1, int(e.control.value or 5))),
                cfg_set("sync_interval_minutes", max(1, int(e.control.value or 5)))
            )
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
            on_change=lambda e: (
                setattr(self.sync_manager, "apps_script_url", e.control.value.strip()),
                cfg_set("sync_apps_script_url", e.control.value.strip())
            ),
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
                self.sync_manager.base_dir = e.path
                cfg_set("sync_sismed_dir", e.path)
                input_sismed_dir.update()

        sismed_dir_picker = ft.FilePicker(on_result=_on_sismed_dir)
        page.overlay.append(sismed_dir_picker)
        page.update()

        input_sismed_dir = ft.TextField(
            label="Directorio SISMED",
            value=cfg_get("sync_sismed_dir"),
            expand=True, border_radius=8, filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.FOLDER_ROUNDED,
            on_change=lambda e: (
                setattr(self.sync_manager, "base_dir", e.control.value.strip()),
                cfg_set("sync_sismed_dir", e.control.value.strip())
            ),
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
                self.sync_manager.omitir_stock_cero = bool(chk_omit_zero_stock.value)
                self.sync_manager.apps_script_url = input_apps_script.value.strip()
                self.sync_manager.base_dir = input_sismed_dir.value.strip()
                cfg_set("sync_interval_minutes", self.sync_manager.intervalo_minutos)
                cfg_set("sync_modo_consolidado", bool(self.sync_manager.modo_consolidado))
                cfg_set("sync_omit_zero_stock", bool(self.sync_manager.omitir_stock_cero))
                cfg_set("sync_apps_script_url", self.sync_manager.apps_script_url)
                cfg_set("sync_sismed_dir", self.sync_manager.base_dir)
                cfg_set("sync_auto_start", bool(chk_auto_sync.value))

                if not self._start_sync_if_valid(page, source="manual"):
                    return

                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.STOP_ROUNDED, size=24, color=ft.colors.WHITE),
                    ft.Text("DETENER", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.style.bgcolor = {
                    ft.ControlState.DEFAULT: ft.colors.ERROR,
                    ft.ControlState.HOVERED: ft.colors.RED_700
                }
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
                    self.metadata.descripcion,
                    right_content=self._back_button("Volver a Sync SISMED", navigate_fn, 3)
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
                            ft.Container(content=chk_omit_zero_stock, padding=ft.padding.only(bottom=5)),
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

        if saved_auto_sync and not self.sync_manager.is_running and not self._startup_attempted:
            self.start_from_saved(page)

        return self._view
