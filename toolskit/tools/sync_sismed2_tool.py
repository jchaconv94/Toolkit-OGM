"""
sync_sismed2_tool.py
====================
Herramienta: Sync SISMED 2.0
Categoria  : Sync

Sincroniza el stock SISMED hacia una API/Edge Function que escribe en Supabase.
Mantiene las mismas validaciones locales y reintentos de red del Sync SISMED actual.
"""

import os
import re
from urllib.parse import urlparse

import flet as ft

from sismed_sync_supabase import SismedSyncSupabaseManager
from tools.app_config import append_runtime_log, get as cfg_get, set as cfg_set
from tools.base_tool import SismedTool, ToolMetadata


class SyncSismed2Tool(SismedTool):
    """Sincroniza inventario SISMED directamente a Supabase mediante API segura."""

    def __init__(self):
        super().__init__()
        self._initialized = False
        self._startup_attempted = False
        self.last_startup_status = "not-attempted"
        self.last_startup_error = None
        self.sync_manager = None
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

    def _normalize_facility_code(self, value: str) -> str:
        return re.sub(r"[^0-9A-Za-z]", "", value or "").upper()

    def _record_autostart_result(self, status: str, error: str | None = None):
        self.last_startup_status = status
        self.last_startup_error = error
        append_runtime_log("sync", f"sync2_autostart_status={status}" + (f"; {error}" if error else ""))

    def _load_saved_preferences(self):
        if not self.sync_manager:
            return
        fallback_dir = cfg_get("sync_sismed_dir") or r"C:\SISMEDV2"
        self.sync_manager.base_dir = (cfg_get("sync2_sismed_dir") or fallback_dir).strip()
        self.sync_manager.intervalo_minutos = max(1, self._cfg_int("sync2_interval_minutes", 5))
        self.sync_manager.modo_consolidado = False
        cfg_set("sync2_modo_consolidado", False)
        self.sync_manager.supabase_endpoint_url = (cfg_get("sync2_endpoint_url") or "").strip()
        self.sync_manager.installation_token = (cfg_get("sync2_installation_token") or "").strip()
        self.sync_manager.expected_facility_code = self._normalize_facility_code(
            cfg_get("sync2_expected_facility_code") or ""
        )

    def _validate_sync_settings(self):
        if not self.sync_manager:
            return "sync-manager-unavailable", "No se pudo inicializar Sync SISMED 2.0."

        endpoint = (self.sync_manager.supabase_endpoint_url or "").strip()
        token = (self.sync_manager.installation_token or "").strip()
        expected_facility = self._normalize_facility_code(getattr(self.sync_manager, "expected_facility_code", ""))
        base_dir = (self.sync_manager.base_dir or "").strip()

        if not endpoint:
            return "missing-endpoint", "No se puede iniciar Sync SISMED 2.0: falta la URL API/Edge Function de Supabase."
        parsed_url = urlparse(endpoint)
        if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.hostname:
            return "invalid-endpoint", "No se puede iniciar Sync SISMED 2.0: la URL API/Edge Function no es válida."
        if not token:
            return "missing-installation-token", "No se puede iniciar Sync SISMED 2.0: falta la clave de instalación."
        if not expected_facility:
            return "missing-expected-facility", "No se puede iniciar Sync SISMED 2.0: falta el Codigo IPRESS autorizado."
        if not base_dir:
            return "missing-base-dir", "No se puede iniciar Sync SISMED 2.0: falta el directorio SISMED."
        if not os.path.isdir(base_dir):
            return "base-dir-not-found", f"No se puede iniciar Sync SISMED 2.0: el directorio SISMED no existe: {base_dir}"
        datos_dir = os.path.join(base_dir, "DATOS")
        if not os.path.isdir(datos_dir):
            return "missing-datos-dir", f"No se puede iniciar Sync SISMED 2.0: falta la carpeta DATOS en: {base_dir}"
        required_files = [
            os.path.join(datos_dir, "MMEDICAM.DBF"),
            os.path.join(datos_dir, "MSTKALMDE.DBF"),
        ]
        missing_files = [path for path in required_files if not os.path.exists(path)]
        if missing_files:
            missing_names = ", ".join(os.path.basename(path) for path in missing_files)
            return "missing-required-dbf", f"No se puede iniciar Sync SISMED 2.0: faltan archivos obligatorios: {missing_names}"
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
            busy_message = "No se pudo iniciar Sync SISMED 2.0 porque el motor aún está en transición. Intenta nuevamente en unos segundos."
            if source == "autostart":
                self._record_autostart_result("engine-busy", busy_message)
            self.sync_manager.log(f"⚠ {busy_message}")
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
        if not self._cfg_bool("sync2_auto_start", False):
            self._record_autostart_result("auto-start-disabled")
            return False
        return self._start_sync_if_valid(page, source="autostart")

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            nombre="Sync SISMED 2.0",
            descripcion="Sincroniza el stock de SISMED directamente con Supabase",
            icono=ft.icons.CLOUD_UPLOAD_ROUNDED,
            color=ft.colors.TEAL_500,
            categoria="Sync",
            etiquetas=["sync", "sincronizar", "supabase", "stock", "inventario", "sismed"],
        )

    def _init_components(self, page: ft.Page):
        if self._initialized:
            return

        self.sync_logs = ft.ListView(expand=True, spacing=5, auto_scroll=True, height=210)

        def _on_sync_log(msg):
            try:
                append_runtime_log("sync", f"[2.0] {msg}")
                self.sync_logs.controls.append(ft.Text(value=msg, size=14, font_family="Consolas"))
                if len(self.sync_logs.controls) > 100:
                    del self.sync_logs.controls[: len(self.sync_logs.controls) - 100]
                page.update()
            except Exception:
                pass

        def _on_sync_stopped():
            if self.btn_toggle_sync:
                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE),
                    ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.style.bgcolor = {
                    ft.ControlState.DEFAULT: ft.colors.TEAL_600,
                    ft.ControlState.HOVERED: ft.colors.TEAL_800,
                }
                self.btn_toggle_sync.disabled = False
                page.update()

        self.sync_manager = SismedSyncSupabaseManager(
            log_callback=_on_sync_log,
            on_stop_callback=_on_sync_stopped,
        )
        self._load_saved_preferences()
        self._initialized = True

    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        self._init_components(page)
        if self._view:
            return self._view

        saved_auto_sync = self._cfg_bool("sync2_auto_start", False)
        chk_auto_sync = ft.Checkbox(
            label="Iniciar Sincronización 2.0 al encender la app",
            value=saved_auto_sync,
            fill_color={ft.ControlState.SELECTED: ft.colors.GREEN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
            check_color=ft.colors.WHITE,
            label_style=ft.TextStyle(size=13, color=ft.colors.TEAL_500, weight=ft.FontWeight.W_800),
            on_change=lambda e: cfg_set("sync2_auto_start", bool(e.control.value)),
        )

        opciones_intervalo = [ft.dropdown.Option(str(i)) for i in range(5, 65, 5)]
        val_int = str(self.sync_manager.intervalo_minutos)
        if val_int not in [opt.key for opt in opciones_intervalo]:
            val_int = "5"

        input_intervalo = ft.Dropdown(
            label="Intervalo sugerido (minutos)",
            options=opciones_intervalo,
            value=val_int,
            width=250,
            border_radius=8,
            filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.TIMER_ROUNDED,
            content_padding=10,
            text_size=14,
            menu_height=200,
            on_change=lambda e: (
                setattr(self.sync_manager, "intervalo_minutos", max(1, int(e.control.value or 5))),
                cfg_set("sync2_interval_minutes", max(1, int(e.control.value or 5))),
            ),
        )

        def _toggle_protected(field: ft.TextField, unlocked_color):
            field.read_only = not field.read_only
            field.password = field.read_only
            if field.read_only:
                field.suffix.icon = ft.icons.LOCK_ROUNDED
                field.suffix.icon_color = ft.colors.ON_SURFACE_VARIANT
                field.border_color = ft.colors.OUTLINE_VARIANT
            else:
                field.suffix.icon = ft.icons.LOCK_OPEN_ROUNDED
                field.suffix.icon_color = unlocked_color
                field.border_color = unlocked_color
            field.update()

        input_endpoint = ft.TextField(
            label="URL API Supabase / Edge Function",
            value=self.sync_manager.supabase_endpoint_url,
            expand=True,
            border_radius=8,
            filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.LINK_ROUNDED,
            read_only=True,
            password=True,
            can_reveal_password=False,
            on_change=lambda e: (
                setattr(self.sync_manager, "supabase_endpoint_url", e.control.value.strip()),
                cfg_set("sync2_endpoint_url", e.control.value.strip()),
            ),
            suffix=ft.IconButton(
                icon=ft.icons.LOCK_ROUNDED,
                tooltip="Desbloquear URL para editar",
                icon_color=ft.colors.ON_SURFACE_VARIANT,
                on_click=lambda _: _toggle_protected(input_endpoint, ft.colors.TEAL_500),
            ),
        )

        input_token = ft.TextField(
            label="Clave de Instalación",
            value=self.sync_manager.installation_token,
            expand=True,
            border_radius=8,
            filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.VPN_KEY_ROUNDED,
            read_only=True,
            password=True,
            can_reveal_password=False,
            on_change=lambda e: (
                setattr(self.sync_manager, "installation_token", e.control.value.strip()),
                cfg_set("sync2_installation_token", e.control.value.strip()),
            ),
            suffix=ft.IconButton(
                icon=ft.icons.LOCK_ROUNDED,
                tooltip="Desbloquear clave para editar",
                icon_color=ft.colors.ON_SURFACE_VARIANT,
                on_click=lambda _: _toggle_protected(input_token, ft.colors.TEAL_500),
            ),
        )

        def _on_expected_facility_change(e):
            code = self._normalize_facility_code(e.control.value)
            if e.control.value != code:
                e.control.value = code
                e.control.update()
            self.sync_manager.expected_facility_code = code
            cfg_set("sync2_expected_facility_code", code)

        input_expected_facility = ft.TextField(
            label="Codigo IPRESS autorizado",
            value=self.sync_manager.expected_facility_code,
            expand=True,
            border_radius=8,
            filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.VERIFIED_USER_ROUNDED,
            read_only=True,
            password=True,
            can_reveal_password=False,
            helper_text="Debe coincidir con la IPRESS autorizada para esta clave.",
            on_change=_on_expected_facility_change,
            suffix=ft.IconButton(
                icon=ft.icons.LOCK_ROUNDED,
                tooltip="Desbloquear codigo IPRESS para editar",
                icon_color=ft.colors.ON_SURFACE_VARIANT,
                on_click=lambda _: _toggle_protected(input_expected_facility, ft.colors.TEAL_500),
            ),
        )

        def _on_sismed_dir(e: ft.FilePickerResultEvent):
            if e.path:
                input_sismed_dir.value = e.path
                self.sync_manager.base_dir = e.path
                cfg_set("sync2_sismed_dir", e.path)
                input_sismed_dir.update()

        sismed_dir_picker = ft.FilePicker(on_result=_on_sismed_dir)
        page.overlay.append(sismed_dir_picker)
        page.update()

        input_sismed_dir = ft.TextField(
            label="Directorio SISMED",
            value=self.sync_manager.base_dir,
            expand=True,
            border_radius=8,
            filled=True,
            border_color=ft.colors.OUTLINE_VARIANT,
            prefix_icon=ft.icons.FOLDER_ROUNDED,
            on_change=lambda e: (
                setattr(self.sync_manager, "base_dir", e.control.value.strip()),
                cfg_set("sync2_sismed_dir", e.control.value.strip()),
            ),
            suffix=ft.IconButton(
                icon=ft.icons.FOLDER_OPEN_ROUNDED,
                icon_color=ft.colors.TEAL_500,
                tooltip="Buscar carpeta SISMED",
                on_click=lambda _: sismed_dir_picker.get_directory_path(),
            ),
        )

        def _toggle_sync(e):
            if not self.sync_manager.is_running:
                self.sync_logs.controls.clear()
                try:
                    self.sync_manager.intervalo_minutos = max(1, int(input_intervalo.value or 5))
                except Exception:
                    self.sync_manager.intervalo_minutos = 5

                self.sync_manager.modo_consolidado = False
                self.sync_manager.supabase_endpoint_url = input_endpoint.value.strip()
                self.sync_manager.installation_token = input_token.value.strip()
                self.sync_manager.expected_facility_code = self._normalize_facility_code(input_expected_facility.value)
                self.sync_manager.base_dir = input_sismed_dir.value.strip()
                cfg_set("sync2_interval_minutes", self.sync_manager.intervalo_minutos)
                cfg_set("sync2_modo_consolidado", False)
                cfg_set("sync2_endpoint_url", self.sync_manager.supabase_endpoint_url)
                cfg_set("sync2_installation_token", self.sync_manager.installation_token)
                cfg_set("sync2_expected_facility_code", self.sync_manager.expected_facility_code)
                cfg_set("sync2_sismed_dir", self.sync_manager.base_dir)
                cfg_set("sync2_auto_start", bool(chk_auto_sync.value))

                if not self._start_sync_if_valid(page, source="manual"):
                    return

                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.STOP_ROUNDED, size=24, color=ft.colors.WHITE),
                    ft.Text("DETENER", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.style.bgcolor = {
                    ft.ControlState.DEFAULT: ft.colors.ERROR,
                    ft.ControlState.HOVERED: ft.colors.RED_700,
                }
            else:
                self.sync_manager.stop_sync()
                self.btn_toggle_sync.content = ft.Row([
                    ft.Icon(ft.icons.HOURGLASS_EMPTY, size=24, color=ft.colors.WHITE),
                    ft.Text("DETENIENDO...", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
                ], alignment=ft.MainAxisAlignment.CENTER)
                self.btn_toggle_sync.disabled = True
            page.update()

        self.btn_toggle_sync = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE),
                ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
            ], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.colors.TEAL_600, ft.ControlState.HOVERED: ft.colors.TEAL_800},
                color=ft.colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=20, vertical=15),
            ),
            on_click=_toggle_sync,
            width=180,
        )

        self._view = ft.Container(
            padding=ft.padding.only(top=10, left=40, right=40, bottom=40),
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    self._section_header(
                        self.metadata.icono,
                        self.metadata.color,
                        self.metadata.nombre,
                        self.metadata.descripcion,
                        right_content=self._back_button("Volver a Sync SISMED", navigate_fn, 3),
                    ),
                    ft.Divider(height=30, color=ft.colors.TRANSPARENT),
                    ft.ResponsiveRow([
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 5},
                            padding=ft.padding.only(top=38, bottom=40, left=40, right=40),
                            bgcolor=ft.colors.SURFACE_VARIANT,
                            border_radius=20,
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.TEAL_400),
                                    ft.Text("Preferencias del Sistema", size=20, weight=ft.FontWeight.W_800),
                                ]),
                                ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                                ft.Container(content=input_sismed_dir, padding=ft.padding.only(top=5, bottom=0)),
                                ft.Container(content=input_intervalo, padding=ft.padding.symmetric(vertical=8)),
                                ft.Container(content=input_endpoint, padding=ft.padding.symmetric(vertical=8)),
                                ft.Container(content=input_token, padding=ft.padding.symmetric(vertical=8)),
                                ft.Container(content=input_expected_facility, padding=ft.padding.symmetric(vertical=8)),
                                ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                                ft.Container(content=chk_auto_sync, padding=ft.padding.only(top=5)),
                            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.START),
                        ),
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 7},
                            padding=30,
                            bgcolor=ft.colors.SURFACE_VARIANT,
                            border_radius=20,
                            content=ft.Column([
                                ft.ResponsiveRow([
                                    ft.Container(
                                        content=ft.Row([
                                            ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400),
                                            ft.Text("Consola de Actividad", size=18, weight=ft.FontWeight.BOLD),
                                        ]),
                                        col={"sm": 12, "md": 12, "lg": 6, "xl": 7},
                                    ),
                                    ft.Container(
                                        content=ft.Row([self.btn_toggle_sync], alignment=ft.MainAxisAlignment.END),
                                        col={"sm": 12, "md": 12, "lg": 6, "xl": 5},
                                    ),
                                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                                ft.Container(
                                    content=self.sync_logs,
                                    bgcolor=ft.colors.BACKGROUND,
                                    border_radius=10,
                                    padding=15,
                                    height=350,
                                ),
                            ]),
                        ),
                    ], spacing=30),
                ],
                expand=True,
            ),
        )

        if saved_auto_sync and not self.sync_manager.is_running and not self._startup_attempted:
            self.start_from_saved(page)

        return self._view
