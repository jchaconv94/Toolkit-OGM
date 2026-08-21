from __future__ import annotations

import threading
from datetime import datetime

import flet as ft

from app_version import get_current_version
from tools.app_config import append_runtime_log, get as cfg_get, set as cfg_set
from update_manager import UpdateError, UpdateInfo, UpdateManager, UpdateSecurityError


class AppUpdaterController:
    CHECK_INTERVAL_SECONDS = 12 * 60 * 60
    RETRY_INTERVAL_SECONDS = 5 * 60
    INTERACTIVE_INITIAL_DELAY_SECONDS = 15
    AUTORUN_INITIAL_DELAY_SECONDS = 120

    def __init__(
        self,
        page: ft.Page,
        *,
        on_installer_launched,
        notify_callback=None,
        startup_hidden: bool = False,
        manager: UpdateManager | None = None,
    ):
        self.page = page
        self.on_installer_launched = on_installer_launched
        self.notify_callback = notify_callback or (lambda _title, _message: None)
        self.startup_hidden = startup_hidden
        self.stop_event = threading.Event()
        self.check_lock = threading.Lock()
        self.download_lock = threading.Lock()
        self.retry_lock = threading.Lock()
        self.retry_timer: threading.Timer | None = None
        self.current_info: UpdateInfo | None = None
        self.installer_path = None
        self.prompted_ready_version = ""
        self.state = "idle"

        self.manager = manager or UpdateManager(
            logger=lambda message: append_runtime_log("update", message)
        )

        self.status_icon = ft.Icon(ft.icons.INFO_OUTLINE_ROUNDED, color=ft.colors.BLUE_400)
        self.status_title = ft.Text("Actualizaciones automáticas", weight=ft.FontWeight.W_800)
        self.status_detail = ft.Text(
            f"Versión instalada: {get_current_version()}",
            size=13,
            color=ft.colors.ON_SURFACE_VARIANT,
        )
        self.progress_bar = ft.ProgressBar(value=0, visible=False, color=ft.colors.CYAN_400)
        self.action_button = ft.ElevatedButton(
            "BUSCAR ACTUALIZACIONES",
            icon=ft.icons.REFRESH_ROUNDED,
            on_click=self.manual_action,
            style=ft.ButtonStyle(
                bgcolor={
                    ft.ControlState.DEFAULT: ft.colors.CYAN_700,
                    ft.ControlState.HOVERED: ft.colors.CYAN_900,
                },
                color=ft.colors.WHITE,
                padding=ft.padding.symmetric(horizontal=18, vertical=14),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self.appbar_button = ft.IconButton(
            icon=ft.icons.SYSTEM_UPDATE_ALT_ROUNDED,
            tooltip="Buscar actualizaciones",
            on_click=self.manual_action,
            icon_color=ft.colors.ON_SURFACE_VARIANT,
        )
        self.auto_check = ft.Checkbox(
            label="Buscar actualizaciones automáticamente",
            value=bool(cfg_get("update_auto_check")),
            on_change=self._change_auto_check,
        )
        self.auto_download = ft.Checkbox(
            label="Descargar automáticamente cuando haya una versión nueva",
            value=bool(cfg_get("update_auto_download")),
            on_change=self._change_auto_download,
        )

        self.settings_container = ft.Container(
            bgcolor=ft.colors.SURFACE_VARIANT,
            border_radius=8,
            padding=30,
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.icons.SYSTEM_UPDATE_ALT_ROUNDED, color=ft.colors.CYAN_400),
                    ft.Text("Actualizaciones de ToolKit SISMED", size=20, weight=ft.FontWeight.W_800),
                ]),
                ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                ft.Row([
                    self.status_icon,
                    ft.Column([self.status_title, self.status_detail], spacing=2, expand=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.progress_bar,
                self.auto_check,
                self.auto_download,
                ft.Row([self.action_button], alignment=ft.MainAxisAlignment.END),
            ], spacing=12),
        )

    def build_settings_card(self):
        return self.settings_container

    def _change_auto_check(self, e) -> None:
        enabled = bool(e.control.value)
        cfg_set("update_auto_check", enabled)
        if enabled and self.state == "error":
            self._schedule_retry()
        elif not enabled:
            self._cancel_retry()

    def _change_auto_download(self, e) -> None:
        enabled = bool(e.control.value)
        cfg_set("update_auto_download", enabled)
        if enabled and self.current_info and not self.installer_path:
            self.download_async(self.current_info)

    def _safe_update(self, *controls) -> None:
        for control in controls:
            try:
                control.update()
            except Exception:
                pass

    def _set_state(self, state: str, title: str, detail: str, progress: float | None = None) -> None:
        self.state = state
        color = {
            "checking": ft.colors.CYAN_400,
            "downloading": ft.colors.CYAN_400,
            "ready": ft.colors.GREEN_400,
            "current": ft.colors.GREEN_400,
            "error": ft.colors.RED_400,
            "available": ft.colors.AMBER_400,
            "installing": ft.colors.CYAN_400,
        }.get(state, ft.colors.BLUE_400)
        icon = {
            "checking": ft.icons.SYNC_ROUNDED,
            "downloading": ft.icons.DOWNLOADING_ROUNDED,
            "ready": ft.icons.DOWNLOAD_DONE_ROUNDED,
            "current": ft.icons.CHECK_CIRCLE_ROUNDED,
            "error": ft.icons.ERROR_OUTLINE_ROUNDED,
            "available": ft.icons.NEW_RELEASES_ROUNDED,
            "installing": ft.icons.INSTALL_DESKTOP_ROUNDED,
        }.get(state, ft.icons.INFO_OUTLINE_ROUNDED)

        self.status_icon.name = icon
        self.status_icon.color = color
        self.status_title.value = title
        self.status_detail.value = detail
        self.progress_bar.visible = progress is not None
        self.progress_bar.value = progress
        self.appbar_button.icon_color = color

        if state == "ready":
            self.action_button.text = "INSTALAR AHORA"
            self.action_button.icon = ft.icons.INSTALL_DESKTOP_ROUNDED
        elif state == "available":
            self.action_button.text = "DESCARGAR ACTUALIZACIÓN"
            self.action_button.icon = ft.icons.DOWNLOAD_ROUNDED
        elif state in {"checking", "downloading", "installing"}:
            self.action_button.text = "PROCESANDO..."
            self.action_button.disabled = True
        else:
            self.action_button.text = "BUSCAR ACTUALIZACIONES"
            self.action_button.icon = ft.icons.REFRESH_ROUNDED
            self.action_button.disabled = False

        if state not in {"checking", "downloading", "installing"}:
            self.action_button.disabled = False
        self._safe_update(
            self.status_icon,
            self.status_title,
            self.status_detail,
            self.progress_bar,
            self.action_button,
            self.appbar_button,
        )

    def _notify(self, title: str, message: str) -> None:
        try:
            self.notify_callback(title, message)
        except Exception:
            pass

    def _cancel_retry(self) -> None:
        with self.retry_lock:
            timer = self.retry_timer
            self.retry_timer = None
        if timer:
            timer.cancel()

    def _schedule_retry(self) -> None:
        if self.stop_event.is_set() or not bool(cfg_get("update_auto_check")):
            return

        def retry() -> None:
            with self.retry_lock:
                self.retry_timer = None
            if not self.stop_event.is_set() and bool(cfg_get("update_auto_check")):
                self.check_async(manual=False)

        with self.retry_lock:
            if self.retry_timer and self.retry_timer.is_alive():
                return
            self.retry_timer = threading.Timer(self.RETRY_INTERVAL_SECONDS, retry)
            self.retry_timer.daemon = True
            self.retry_timer.name = "ToolkitUpdaterRetry"
            self.retry_timer.start()
        append_runtime_log(
            "update",
            f"Se reintentara comprobar la actualizacion en {self.RETRY_INTERVAL_SECONDS // 60} minutos.",
        )

    def _snack(self, message: str) -> None:
        try:
            self.page.snack_bar = ft.SnackBar(content=ft.Text(message))
            self.page.snack_bar.open = True
            self.page.update()
        except Exception:
            pass

    def manual_action(self, _event=None) -> None:
        if self.state == "ready" and self.installer_path:
            self._show_ready_dialog(force=True)
            return
        if self.state == "available" and self.current_info:
            self.download_async(self.current_info)
            return
        if self.state in {"checking", "downloading", "installing"}:
            return
        self.check_async(manual=True)

    def check_async(self, *, manual: bool = False) -> None:
        if self.check_lock.locked() or self.download_lock.locked():
            if manual:
                self._snack("Ya se está comprobando una actualización.")
            return
        threading.Thread(
            target=self._check_worker,
            args=(manual,),
            daemon=True,
            name="ToolkitUpdaterCheck",
        ).start()

    def _check_worker(self, manual: bool) -> None:
        with self.check_lock:
            self._set_state(
                "checking",
                "Buscando actualizaciones",
                "Comprobando si existe una versión nueva...",
                None,
            )
            try:
                info = self.manager.check_for_update()
                self._cancel_retry()
                cfg_set("update_last_check_at", datetime.now().isoformat(timespec="seconds"))
                if not info:
                    self.current_info = None
                    self.installer_path = None
                    self._set_state(
                        "current",
                        "ToolKit SISMED está actualizado",
                        f"Tiene instalada la versión {self.manager.current_version}.",
                    )
                    if manual:
                        self._snack("No hay una versión más reciente disponible.")
                    return

                self.current_info = info
                self._set_state(
                    "available",
                    f"Versión {info.version} disponible",
                    "La nueva versión está lista para descargarse.",
                )
                if bool(cfg_get("update_auto_download")):
                    self.download_async(info)
                elif manual:
                    self._show_available_dialog()
            except (UpdateSecurityError, UpdateError) as exc:
                append_runtime_log("update", f"Error comprobando actualizaciones: {exc}")
                self._set_state(
                    "error",
                    "No se pudo comprobar la actualización",
                    str(exc),
                )
                if manual:
                    self._snack(str(exc))
                self._schedule_retry()
            except Exception as exc:
                append_runtime_log("update", f"Error inesperado del actualizador: {type(exc).__name__}: {exc}")
                self._set_state(
                    "error",
                    "No se pudo comprobar la actualización",
                    "Revise su conexión a internet e inténtelo nuevamente.",
                )

                self._schedule_retry()

    def download_async(self, info: UpdateInfo) -> None:
        if self.download_lock.locked():
            return
        threading.Thread(
            target=self._download_worker,
            args=(info,),
            daemon=True,
            name="ToolkitUpdaterDownload",
        ).start()

    def _download_worker(self, info: UpdateInfo) -> None:
        with self.download_lock:
            last_percent = [-1]

            def _progress(downloaded: int, total: int) -> None:
                percent = min(100, int((downloaded * 100) / max(total, 1)))
                if percent == last_percent[0] or (percent < 100 and percent % 2):
                    return
                last_percent[0] = percent
                self._set_state(
                    "downloading",
                    f"Descargando versión {info.version}",
                    f"Descarga en curso: {percent}%",
                    percent / 100,
                )

            self._set_state(
                "downloading",
                f"Descargando versión {info.version}",
                "Preparando la descarga segura...",
                0,
            )
            try:
                self.installer_path = self.manager.download_update(info, _progress)
                self._cancel_retry()
                self._set_state(
                    "ready",
                    f"Versión {info.version} lista para instalar",
                    "La descarga fue verificada correctamente.",
                )
                self._notify(
                    "Actualización lista",
                    f"ToolKit SISMED {info.version} está listo para instalar.",
                )
                self._show_ready_dialog()
            except (UpdateSecurityError, UpdateError) as exc:
                append_runtime_log("update", f"Error descargando actualizacion: {exc}")
                self.installer_path = None
                self._schedule_retry()
                self._set_state("error", "No se pudo descargar la actualización", str(exc))
            except Exception as exc:
                append_runtime_log("update", f"Error inesperado descargando: {type(exc).__name__}: {exc}")
                self.installer_path = None
                self._set_state(
                    "error",
                    "No se pudo descargar la actualización",
                    "Revise su conexión a internet e inténtelo nuevamente.",
                )

                self._schedule_retry()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _close_dialog(self, dialog) -> None:
        dialog.open = False
        self._safe_update(dialog)

    def _show_available_dialog(self) -> None:
        info = self.current_info
        if not info:
            return

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.NEW_RELEASES_ROUNDED, color=ft.colors.CYAN_400),
                ft.Text("Nueva actualización disponible", weight=ft.FontWeight.W_800),
            ]),
            content=ft.Column([
                ft.Text(f"Versión nueva: {info.version}"),
                ft.Text(f"Tamaño aproximado: {self._format_size(info.size_bytes)}"),
                ft.Text("Puede descargarla ahora y continuar usando la aplicación mientras termina."),
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("MÁS TARDE", on_click=lambda _e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "DESCARGAR",
                    icon=ft.icons.DOWNLOAD_ROUNDED,
                    on_click=lambda _e: (self._close_dialog(dialog), self.download_async(info)),
                ),
            ],
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self._safe_update(self.page)

    def _install_now(self, dialog) -> None:
        self._close_dialog(dialog)
        if not self.installer_path or not self.current_info:
            self._set_state("error", "Instalador no disponible", "Vuelva a descargar la actualización.")
            return

        self._set_state(
            "installing",
            f"Instalando versión {self.current_info.version}",
            "Windows solicitará permiso para actualizar la aplicación.",
        )
        try:
            self.manager.launch_installer(self.installer_path)
        except UpdateError as exc:
            append_runtime_log("update", f"No se pudo iniciar instalador: {exc}")
            self._set_state("ready", "Actualización pendiente", str(exc))
            self._snack(str(exc))
            return

        cfg_set("update_pending_version", self.current_info.version)
        append_runtime_log(
            "update",
            f"Actualizacion {self.current_info.version} preparada. Cerrando la aplicacion.",
        )
        self.stop()
        self.on_installer_launched()

    def _show_ready_dialog(self, *, force: bool = False) -> None:
        info = self.current_info
        if not info or not self.installer_path:
            return
        if self.prompted_ready_version == info.version and not force:
            return
        self.prompted_ready_version = info.version

        notes = info.release_notes.strip()
        if len(notes) > 500:
            notes = notes[:497].rstrip() + "..."

        content_controls = [
            ft.Text(f"La versión {info.version} se descargó y fue verificada correctamente."),
            ft.Text(
                "Al continuar, ToolKit SISMED detendrá las sincronizaciones, se cerrará y Windows solicitará permiso para instalar.",
                size=13,
            ),
        ]
        if notes:
            content_controls.extend([
                ft.Divider(height=16),
                ft.Text("Cambios de esta versión", weight=ft.FontWeight.BOLD),
                ft.Text(notes, size=12, selectable=True),
            ])

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.DOWNLOAD_DONE_ROUNDED, color=ft.colors.GREEN_400),
                ft.Text("Actualización lista", weight=ft.FontWeight.W_800),
            ]),
            content=ft.Container(
                width=520,
                content=ft.Column(content_controls, tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            ),
            actions=[
                ft.TextButton("MÁS TARDE", on_click=lambda _e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "INSTALAR AHORA",
                    icon=ft.icons.INSTALL_DESKTOP_ROUNDED,
                    on_click=lambda _e: self._install_now(dialog),
                    style=ft.ButtonStyle(
                        bgcolor={ft.ControlState.DEFAULT: ft.colors.TEAL_700},
                        color=ft.colors.WHITE,
                    ),
                ),
            ],
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self._safe_update(self.page)

    def _periodic_worker(self) -> None:
        initial_delay = (
            self.AUTORUN_INITIAL_DELAY_SECONDS
            if self.startup_hidden
            else self.INTERACTIVE_INITIAL_DELAY_SECONDS
        )
        if self.stop_event.wait(initial_delay):
            return
        while not self.stop_event.is_set():
            if bool(cfg_get("update_auto_check")):
                self.check_async(manual=False)
            if self.stop_event.wait(self.CHECK_INTERVAL_SECONDS):
                return

    def start(self) -> None:
        threading.Thread(
            target=self._periodic_worker,
            daemon=True,
            name="ToolkitUpdaterScheduler",
        ).start()

    def stop(self) -> None:
        self.stop_event.set()
        self._cancel_retry()
