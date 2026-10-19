import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import ctypes
import hashlib
import flet as ft
import os
import sys
import subprocess
import traceback
import winreg as reg
import threading
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import win32event
import win32api
import winerror


def _bootstrap_runtime_directory():
    try:
        runtime_dir = os.path.dirname(
            sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        )
        if runtime_dir and os.path.isdir(runtime_dir):
            os.chdir(runtime_dir)
    except Exception:
        pass


_bootstrap_runtime_directory()

from tools.app_config import append_runtime_log, get as cfg_get, get_config_log_path, get_startup_log_path, set as cfg_set, update_runtime_status
from update_shutdown import arm_update_exit_watchdog
from window_watch import HEARTBEAT_TIMEOUT_SECONDS, WindowHeartbeat, kill_flet_views
from tools.tool_registry import TOOLS_REGISTRY, get_tool_by_name
from app_version import get_current_version
from updater_controller import AppUpdaterController

# ==========================================
# PREVENCIÓN DE MULTI-CLONACIÓN (MUTEX)
# ==========================================
SINGLE_INSTANCE_MUTEX_NAME = "ToolkitOGM_SingleInstanceMutex_v1"
RESTORE_WINDOW_EVENT_NAME = "ToolkitOGM_RestoreWindow_v1"
RESTORE_WINDOW_ACK_EVENT_NAME = "ToolkitOGM_RestoreWindowAck_v1"
SECOND_INSTANCE_TIMEOUT_MS = 3000
AUTORUN_READY_TIMEOUT_MS = 5000
STARTUP_REGISTRY_VALUE_NAME = "ToolkitOGM_Sync"
STARTUP_TASK_NAME = "ToolkitOGM_Autorun"
STARTUP_TASK_DELAY = "0002:00"
single_instance_mutex = None
restore_window_event = None
restore_window_ack_event = None


def _close_handle_safely(handle):
    if not handle:
        return
    try:
        win32api.CloseHandle(handle)
    except Exception:
        pass


def _show_existing_instance_warning():
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "ToolKit SISMED ya se esta ejecutando. Se intento restaurar la ventana existente, pero no respondio a tiempo. Revise la bandeja del sistema o cierre el proceso bloqueado desde el Administrador de tareas.",
            "ToolKit SISMED",
            0x00000030,
        )
    except Exception:
        pass


def _signal_restore_request(timeout_ms: int = SECOND_INSTANCE_TIMEOUT_MS) -> bool:
    request_handle = None
    ack_handle = None
    try:
        request_handle = win32event.OpenEvent(win32event.EVENT_ALL_ACCESS, False, RESTORE_WINDOW_EVENT_NAME)
        ack_handle = win32event.OpenEvent(win32event.EVENT_ALL_ACCESS, False, RESTORE_WINDOW_ACK_EVENT_NAME)
        win32event.ResetEvent(ack_handle)
        win32event.SetEvent(request_handle)
        return win32event.WaitForSingleObject(ack_handle, timeout_ms) == win32event.WAIT_OBJECT_0
    except Exception:
        return False
    finally:
        _close_handle_safely(request_handle)
        _close_handle_safely(ack_handle)


def _release_single_instance_resources():
    global single_instance_mutex, restore_window_event, restore_window_ack_event
    _close_handle_safely(restore_window_ack_event)
    _close_handle_safely(restore_window_event)
    _close_handle_safely(single_instance_mutex)
    restore_window_ack_event = None
    restore_window_event = None
    single_instance_mutex = None


def _acquire_single_instance() -> bool:
    global single_instance_mutex, restore_window_event, restore_window_ack_event

    single_instance_mutex = win32event.CreateMutex(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    mutex_last_error = win32api.GetLastError()
    if mutex_last_error == winerror.ERROR_ALREADY_EXISTS:
        if not _signal_restore_request():
            _show_existing_instance_warning()
        return False

    restore_window_event = win32event.CreateEvent(None, False, False, RESTORE_WINDOW_EVENT_NAME)
    restore_window_ack_event = win32event.CreateEvent(None, False, False, RESTORE_WINDOW_ACK_EVENT_NAME)
    return True


def _expected_startup_command() -> str:
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --autorun'

    python_exe = sys.executable
    pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = python_exe
    script_path = os.path.abspath(__file__)
    return f'"{pythonw_exe}" "{script_path}" --autorun'


def _normalize_startup_command(command: str) -> str:
    return os.path.normcase(" ".join(str(command or "").strip().split()))


def _log_startup_registration(message: str):
    try:
        append_runtime_log("startup", message)
    except Exception:
        pass


def _run_schtasks(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt" and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.run(
        ["schtasks", *arguments],
        capture_output=True,
        text=True,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def _query_startup_registry_command() -> str | None:
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_READ)
        value, _ = reg.QueryValueEx(key, STARTUP_REGISTRY_VALUE_NAME)
        reg.CloseKey(key)
        return value
    except FileNotFoundError:
        return None
    except Exception as exc:
        _log_startup_registration(f"startup_registry_query_error={type(exc).__name__}: {exc}")
        return None


def _set_startup_registry_command(command: str) -> tuple[bool, str]:
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE)
        reg.SetValueEx(key, STARTUP_REGISTRY_VALUE_NAME, 0, reg.REG_SZ, command)
        reg.CloseKey(key)
        return True, "Registro HKCU Run actualizado."
    except Exception as exc:
        return False, f"No se pudo escribir la clave Run: {type(exc).__name__}: {exc}"


def _delete_startup_registry_command() -> tuple[bool, str]:
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE)
        try:
            reg.DeleteValue(key, STARTUP_REGISTRY_VALUE_NAME)
            message = "Clave Run eliminada."
        except FileNotFoundError:
            message = "La clave Run ya no existía."
        reg.CloseKey(key)
        return True, message
    except Exception as exc:
        return False, f"No se pudo eliminar la clave Run: {type(exc).__name__}: {exc}"


def _startup_task_exists() -> bool:
    try:
        result = _run_schtasks(["/Query", "/TN", STARTUP_TASK_NAME])
        return result.returncode == 0
    except Exception as exc:
        _log_startup_registration(f"startup_task_query_error={type(exc).__name__}: {exc}")
        return False


def _create_startup_task(command: str) -> tuple[bool, str]:
    try:
        result = _run_schtasks([
            "/Create",
            "/TN", STARTUP_TASK_NAME,
            "/TR", command,
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
            "/IT",
            "/DELAY", STARTUP_TASK_DELAY,
            "/F",
        ])
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            return True, output or "Tarea programada de autoarranque creada."
        return False, output or f"schtasks devolvió código {result.returncode}."
    except Exception as exc:
        return False, f"No se pudo crear la tarea programada: {type(exc).__name__}: {exc}"


def _delete_startup_task() -> tuple[bool, str]:
    try:
        result = _run_schtasks([
            "/Delete",
            "/TN", STARTUP_TASK_NAME,
            "/F",
        ])
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            return True, output or "Tarea programada eliminada."
        output_lc = output.lower()
        if "no existe" in output_lc or "cannot find the file" in output_lc:
            return True, output or "La tarea programada ya no existía."
        return False, output or f"schtasks devolvió código {result.returncode}."
    except Exception as exc:
        return False, f"No se pudo eliminar la tarea programada: {type(exc).__name__}: {exc}"


def _get_startup_registration_status() -> dict:
    expected_command = _expected_startup_command()
    registry_command = _query_startup_registry_command()
    registry_match = _normalize_startup_command(registry_command) == _normalize_startup_command(expected_command)
    task_exists = _startup_task_exists() if getattr(sys, 'frozen', False) else False

    enabled = task_exists or registry_match
    if task_exists:
        mode = "task"
    elif registry_match:
        mode = "registry"
    else:
        mode = "disabled"

    return {
        "enabled": enabled,
        "mode": mode,
        "registry_match": registry_match,
        "registry_command": registry_command,
        "task_exists": task_exists,
        "expected_command": expected_command,
    }


def _repair_startup_registration_if_needed():
    status = _get_startup_registration_status()
    if not getattr(sys, 'frozen', False):
        return status
    if not status["enabled"]:
        return status

    if status["task_exists"]:
        success = set_startup(True)
        refreshed = _get_startup_registration_status()
        if success and refreshed["task_exists"]:
            _log_startup_registration("startup_registration_refreshed=task")
        else:
            _log_startup_registration("startup_registration_refresh_failed")
        return refreshed

    success = set_startup(True)
    refreshed = _get_startup_registration_status()
    if success and refreshed["task_exists"]:
        _log_startup_registration("startup_registration_repaired=task")
    else:
        _log_startup_registration("startup_registration_repair_failed")
    return refreshed


def set_startup(run: bool) -> bool:
    expected_command = _expected_startup_command()

    if run:
        if getattr(sys, 'frozen', False):
            task_ok, task_message = _create_startup_task(expected_command)
            _log_startup_registration(f"startup_enable_task={task_ok}; {task_message}")
            if task_ok:
                reg_ok, reg_message = _delete_startup_registry_command()
                _log_startup_registration(f"startup_cleanup_registry={reg_ok}; {reg_message}")
                return _get_startup_registration_status()["enabled"]

        reg_ok, reg_message = _set_startup_registry_command(expected_command)
        _log_startup_registration(f"startup_enable_registry={reg_ok}; {reg_message}")
        return _get_startup_registration_status()["enabled"]

    reg_ok, reg_message = _delete_startup_registry_command()
    task_ok, task_message = _delete_startup_task()
    _log_startup_registration(f"startup_disable_registry={reg_ok}; {reg_message}")
    _log_startup_registration(f"startup_disable_task={task_ok}; {task_message}")
    return not _get_startup_registration_status()["enabled"]


def is_startup_enabled() -> bool:
    return _get_startup_registration_status()["enabled"]


def main(page: ft.Page):
    startup_hidden_requested = "--autorun" in sys.argv
    install_success_requested = "--install-success" in sys.argv
    update_failure_requested = "--update-failed" in sys.argv
    startup_state = {
        "restore_listener_ready": threading.Event(),
        "tray_ready": threading.Event(),
        "tray_failed": threading.Event(),
        "tray_error": None,
        "degraded_reasons": [],
        "boot_status": "booting",
        "sync_startup_status": "not-evaluated",
        "sync_startup_message": None,
    }

    startup_registration = _repair_startup_registration_if_needed()
    saved_auto_startup = startup_registration["enabled"]

    def _log_startup_event(message: str):
        append_runtime_log("startup", message)

    def _set_boot_status(status: str, detail: str | None = None):
        startup_state["boot_status"] = status
        update_runtime_status("boot", status, detail)
        if detail:
            _log_startup_event(f"boot_status={status}; {detail}")
        else:
            _log_startup_event(f"boot_status={status}")

    def _record_sync_startup(status: str, message: str | None = None):
        startup_state["sync_startup_status"] = status
        startup_state["sync_startup_message"] = message
        if message:
            _log_startup_event(f"sync_autostart_status={status}; {message}")
        else:
            _log_startup_event(f"sync_autostart_status={status}")

    def _register_degraded_reason(message: str):
        if message not in startup_state["degraded_reasons"]:
            startup_state["degraded_reasons"].append(message)
        _log_startup_event(message)

    _set_boot_status("booting", f"autorun={startup_hidden_requested}")

    def _on_startup_change(e):
        requested_value = bool(e.control.value)
        success = set_startup(requested_value)
        chk_auto_startup.value = is_startup_enabled()
        chk_auto_startup.update()
        if requested_value and not success:
            _show_message(f"No se pudo registrar el autoarranque. Revisa el log: {get_startup_log_path()}")
        elif not requested_value and chk_auto_startup.value:
            _show_message(f"No se pudo desactivar completamente el autoarranque. Revisa el log: {get_startup_log_path()}")
    _log_startup_event(
        f"startup_registration mode={startup_registration['mode']}; "
        f"registry_match={startup_registration['registry_match']}; task_exists={startup_registration['task_exists']}"
    )
    _log_startup_event(
        f"runtime_context cwd={os.getcwd()}; executable={sys.executable}; frozen={getattr(sys, 'frozen', False)}"
    )

    def _show_message(message: str):
        page.snack_bar = ft.SnackBar(content=ft.Text(message))
        page.snack_bar.open = True
        page.update()

    def _restore_main_window():
        try:
            page.window.visible = True
            page.window.minimized = False
            page.window.focused = True
            page.window.to_front()
            page.update()
        except Exception:
            pass

    def _listen_for_restore_requests():
        startup_state["restore_listener_ready"].set()
        _log_startup_event("restore_listener_ready=true")
        if not restore_window_event:
            return

        while True:
            try:
                result = win32event.WaitForSingleObject(restore_window_event, 1000)
            except Exception:
                break

            if result == win32event.WAIT_OBJECT_0:
                _restore_main_window()
                if restore_window_ack_event:
                    try:
                        win32event.SetEvent(restore_window_ack_event)
                    except Exception:
                        pass

    def _open_config_log(e=None):
        log_path = get_config_log_path()
        if not os.path.exists(log_path):
            _show_message("El log de configuración aún no existe. Se creará automáticamente cuando ocurra un error de persistencia.")
            return
        try:
            os.startfile(log_path)
        except Exception as exc:
            _show_message(f"No se pudo abrir el log de configuración: {exc}")

    sync_access_unlocked = [False]
    SYNC_NAV_INDICES = {3, 18}

    def _hash_sync_password(password: str) -> str:
        return hashlib.sha256((password or "").encode("utf-8")).hexdigest()

    def _lock_sync_access():
        sync_access_unlocked[0] = False

    chk_auto_startup = ft.Checkbox(
        label="Abrir esta aplicación al encender Windows",
        value=saved_auto_startup,
        fill_color={ft.ControlState.SELECTED: ft.colors.BLUE_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
        check_color=ft.colors.WHITE,
        label_style=ft.TextStyle(size=14, color=ft.colors.ON_SURFACE, weight=ft.FontWeight.W_800),
        on_change=_on_startup_change
    )

    def theme_changed(e):
        # Alternar entre los modos
        page.theme_mode = (
            ft.ThemeMode.DARK if page.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        )
        # Actualizar etiqueta del switch
        cambia_modo.label = "Claro" if page.theme_mode == ft.ThemeMode.LIGHT else "Oscuro"
        cambia_modo.thumb_icon = ft.icons.LIGHT_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.icons.DARK_MODE
        cambia_modo.update()
        page.update()

    # Verificar el tema inicial
    cambia_modo = ft.Switch(thumb_icon=ft.icons.DARK_MODE, label="Oscuro", on_change=theme_changed)
    # Configurar la página inicial
    page.theme_mode = ft.ThemeMode.DARK  # Si quieres que el tema inicial sea oscuro




# CONSTRUCCION DE LA PAGINA ----- Agregar elementos a la página

    current_version = get_current_version()
    app_display_title = f"ToolKit SISMED (v{current_version})"
    page.title = app_display_title
    page.horizontal_alignment = ft.CrossAxisAlignment.START
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 1080
    page.window.min_height = 680
    page.padding = 0 # Eliminar márgenes de la ventana para que el menú pegue a los bordes
    page.spacing = 0 # Sin espacios automáticos entre elementos raíz
    
    # Permitir cambiar el tamaño de la ventana
    page.window.resizable = True
    page.window.maximizable = True
    page.window.prevent_close = True # Evita que se cierre de verdad

    threading.Thread(target=_listen_for_restore_requests, daemon=True).start()
    
    # Lógica de System Tray (Bandeja del Sistema)
    tray_icon = None
    updater_controller = None

    def create_image():
        # Crea una imagen simple con Pillow (puedes reemplazarla luego por tu ícono .ico)
        image = Image.new('RGB', (64, 64), color = (0, 188, 212)) # Color Cian
        d = ImageDraw.Draw(image)
        d.text((15, 20), "OGM", fill=(255, 255, 255))
        return image

    def on_show_window(icon, item):
        _restore_main_window()

    def _stop_sync_services():
        sync_tool = get_tool_by_name("Sync SISMED")
        if sync_tool and getattr(sync_tool, "sync_manager", None):
            sync_tool.sync_manager.stop_sync()

    def _stop_tray():
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass

    def on_quit(icon, item):
        # Si la ventana está congelada no recibe el pedido de cierre: a los 3 s se cierra a la
        # fuerza (solo flet.exe) y termina el proceso. Si todo cierra bien antes, no hace nada.
        append_runtime_log("startup", "Cerrar completamente: pedido desde la bandeja.")
        arm_update_exit_watchdog(delay_seconds=3.0, before_exit=kill_flet_views)
        try:
            window_heartbeat.stop()
        except NameError:
            pass  # se cerró antes de que terminara de arrancar
        if updater_controller:
            updater_controller.stop()
        _stop_sync_services()
        _stop_tray()
        _release_single_instance_resources()
        page.window.destroy()

    def _shutdown_after_update():
        append_runtime_log("update", "Cerrando ToolKit SISMED antes de iniciar el instalador.")
        append_runtime_log(
            "update",
            "Se activo el cierre rapido protegido; el proceso anterior terminara en un maximo de 3 segundos.",
        )
        # Solo cierra flet.exe, nunca el instalador que se acaba de abrir.
        arm_update_exit_watchdog(delay_seconds=3.0, before_exit=kill_flet_views)
        try:
            page.window.prevent_close = False
            page.window.visible = False
        except Exception:
            pass
        _stop_sync_services()
        _stop_tray()
        _release_single_instance_resources()
        try:
            page.window.destroy()
        except Exception as exc:
            append_runtime_log(
                "update",
                f"La ventana no se pudo cerrar normalmente: {type(exc).__name__}: {exc}",
            )

    def _notify_update(title: str, message: str):
        if tray_icon:
            try:
                tray_icon.notify(message, title)
            except Exception:
                pass

    def setup_tray():
        nonlocal tray_icon
        try:
            image = create_image()
            menu = pystray.Menu(
                item('Restaurar Ventana', on_show_window, default=True),
                item('Cerrar completamente', on_quit)
            )
            tray_icon = pystray.Icon("toolkit_ogm", image, "ToolKits SISMED (Sincronizando)", menu)
            startup_state["tray_ready"].set()
            _log_startup_event("tray_ready=true")
            tray_icon.run()
        except Exception as exc:
            startup_state["tray_error"] = exc
            startup_state["tray_failed"].set()
            startup_state["tray_ready"].set()
            _register_degraded_reason(f"Fallo inicializando bandeja del sistema: {type(exc).__name__}: {exc}")

    # Iniciar Bandeja en segundo plano
    threading.Thread(target=setup_tray, daemon=True).start()

    def window_event(e):
        if e.data == "close":
            _lock_sync_access()
            try:
                update_sidebar_ui(0)
                update_content(0)
            except Exception:
                pass
            page.window.visible = False
            page.update()
            
    page.window.on_event = window_event

    def _ping_window():
        # Pregunta inofensiva que solo la ventana puede responder: si no contesta, está congelada.
        page._invoke_method(
            "canLaunchUrl", {"url": "https://www.google.com"},
            wait_for_result=True, wait_timeout=HEARTBEAT_TIMEOUT_SECONDS,
        )

    window_heartbeat = WindowHeartbeat(_ping_window, lambda message: append_runtime_log("startup", message))
    window_heartbeat.start()

    sync_tool = get_tool_by_name("Sync SISMED")
    if sync_tool and hasattr(sync_tool, "start_from_saved"):
        try:
            sync_started = sync_tool.start_from_saved(page)
            sync_startup_status = getattr(sync_tool, "last_startup_status", "unknown")
            sync_startup_error = getattr(sync_tool, "last_startup_error", None)
            if sync_started:
                _record_sync_startup("started")
            else:
                _record_sync_startup(sync_startup_status, sync_startup_error)
            if startup_hidden_requested and sync_startup_error:
                _register_degraded_reason(f"Autorun degradado: {sync_startup_error}")
        except Exception as exc:
            _record_sync_startup("failed-exception", str(exc))
            _register_degraded_reason(
                f"Fallo iniciando Sync SISMED automaticamente: {type(exc).__name__}: {exc}"
            )
            _log_startup_event(traceback.format_exc())
    else:
        _record_sync_startup("tool-not-available", "No se encontro la herramienta Sync SISMED.")

    if startup_hidden_requested:
        restore_ready = startup_state["restore_listener_ready"].wait(AUTORUN_READY_TIMEOUT_MS / 1000)
        tray_ready = startup_state["tray_ready"].wait(AUTORUN_READY_TIMEOUT_MS / 1000)

        if not restore_ready:
            _register_degraded_reason("Autorun degradado: el listener de restauracion no estuvo listo a tiempo.")
        if not tray_ready:
            _register_degraded_reason("Autorun degradado: la bandeja del sistema no estuvo lista a tiempo.")
        if startup_state["tray_failed"].is_set() and startup_state["tray_error"]:
            _register_degraded_reason(
                f"Autorun degradado: la bandeja del sistema fallo con {type(startup_state['tray_error']).__name__}."
            )

        if not startup_state["degraded_reasons"]:
            page.window.visible = False
            _set_boot_status(
                "autorun-hidden-ready",
                f"sync_status={startup_state['sync_startup_status']}"
            )
        else:
            _set_boot_status(
                "autorun-degraded-visible",
                " | ".join(startup_state["degraded_reasons"])
            )
    else:
        _set_boot_status(
            "interactive-ready",
            f"sync_status={startup_state['sync_startup_status']}"
        )

    # Función para expandir/colapsar el menú lateral
    def toggle_nav_rail(e):
        is_expanded = menu.width > 100
        new_width = 70 if is_expanded else 200
        menu.width = new_width
        
        for item in nav_items_list:
            item.width = 190 if not is_expanded else 50 # El ancho que tú definiste
            # Capa 2 (Contenido) en el Stack
            inner_container = item.content.controls[1]
            row = inner_container.content
            
            if not is_expanded: # Se va a expandir
                row.alignment = ft.MainAxisAlignment.START
                inner_container.alignment = ft.alignment.center_left
                inner_container.padding = ft.padding.only(left=15)
                row.controls[1].visible = True
            else: # Se va a colapsar
                row.alignment = ft.MainAxisAlignment.CENTER
                inner_container.alignment = ft.alignment.center
                inner_container.padding = ft.padding.only(left=0)
                row.controls[1].visible = False
            
            item.update()
        
        menu.update()

    def _navigate_to_update_settings():
        _restore_main_window()
        update_sidebar_ui(1)
        update_content(1)

    # AppBar Superior (Estilo Docker Desktop)
    updater_controller = AppUpdaterController(
        page,
        on_installer_launched=_shutdown_after_update,
        notify_callback=_notify_update,
        navigate_to_settings=_navigate_to_update_settings,
        startup_hidden=startup_hidden_requested,
    )

    page.appbar = ft.AppBar(
        leading=ft.IconButton(ft.icons.MENU, on_click=toggle_nav_rail, tooltip="Menú principal"),
        leading_width=50,
        title=ft.Row([
            ft.Icon(ft.icons.LAYERS_ROUNDED, color=ft.colors.CYAN_500, size=24),
            ft.Text(app_display_title, size=18, weight=ft.FontWeight.W_800)
        ], spacing=10),
        bgcolor=ft.colors.SURFACE_VARIANT,
        actions=[
            ft.Container(
                content=ft.Row([
                    updater_controller.appbar_button,
                    cambia_modo,
                    ft.Container(width=20),
                    ft.Icon(ft.icons.CODE_ROUNDED, size=16, color=ft.colors.ON_SURFACE_VARIANT),
                    ft.Text("By: Ing. Jordan Chacon Villacis", size=12, color=ft.colors.ON_SURFACE_VARIANT),
                ]),
                padding=ft.padding.only(right=20)
            )
        ]
    )
    
    # Restringir tamaño mínimo de la ventana
    page.window.min_width = 1080
    page.window.min_height = 680





#---------------------------------------------------

# Función para actualizar el contenido
    def update_content(index):
        # Limpiar el contenido anterior
        content.controls.clear()
        if index not in SYNC_NAV_INDICES:
            _lock_sync_access()
        
        def navigate(view_idx):
            # Ahora que están en el sidebar, sí los seleccionamos. Si el view_idx no es visualmente un tooltip lateral (como los index 6 y 7, mantendrá visualmente la categoría principal si existe)
            update_sidebar_ui(view_idx)
            update_content(view_idx)
        
        # Mapa: nombre de herramienta (metadata.nombre) → índice de navegación
        TOOL_NAV_INDEX = {
            "Consul. TFORMDET":        5,
            "Reporte Guías":           8,
            "DBF a EXCEL":             6,
            "Unir EXCEL":              15,
            "Anexar TFORMDET":         19,
            "Generar ICI":             21,
            "Format TFORMDET":         7,
            "Sync SISMED":             18,
            "Stock SISMED":            9,
            "Disponibilidad TFORMDET": 10,
            "Consumo Valorizado":      16,
            "Cambiar Estado Med.":     12,
            "Habilitar Guías":          13,
            "Editor PDF":               14,
        }

        # ── Colores de acento por categoría ──
        CATEGORY_COLORS = {
            "Farmacia":        ft.colors.PINK_400,
            "Herramientas":    ft.colors.TEAL_400,
            "Reports SISMED":  ft.colors.BLUE_400,
            "Sync":            ft.colors.GREEN_500,
            "Edit SISMED":     ft.colors.ORANGE_400,
        }

        # ── Generador dinámico de tarjetas PREMIUM ──
        def make_tool_card(tool):
            if not tool:
                return ft.Container()
            nav_idx    = TOOL_NAV_INDEX.get(tool.metadata.nombre, 0)
            accent     = tool.metadata.color
            cat_color  = CATEGORY_COLORS.get(tool.metadata.categoria, ft.colors.BLUE_400)

            cat_chip = ft.Container(
                content=ft.Text(
                    tool.metadata.categoria, size=11,
                    weight=ft.FontWeight.W_700,
                    color=cat_color,
                ),
                bgcolor=ft.colors.with_opacity(0.12, cat_color),
                border_radius=20,
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
            )

            return ft.Container(
                width=230,
                height=195,
                border_radius=18,
                bgcolor=ft.colors.SURFACE_VARIANT,
                border=ft.border.Border(
                    left=ft.border.BorderSide(4, cat_color)
                ),
                animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
                on_click=lambda e, i=nav_idx: navigate(i),
                on_hover=lambda e: (
                    setattr(e.control, "bgcolor",
                        ft.colors.BLUE_GREY_800 if e.data == "true"
                        else ft.colors.SURFACE_VARIANT
                    ) or e.control.update()
                ),
                padding=ft.padding.only(left=20, right=20, top=22, bottom=18),
                content=ft.Column([
                    # Icono + chip en la misma fila
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(tool.metadata.icono, size=32, color=cat_color),
                            bgcolor=ft.colors.with_opacity(0.12, cat_color),
                            border_radius=12,
                            padding=10,
                        ),
                        ft.Container(expand=True),
                        cat_chip,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(height=14),
                    # Nombre
                    ft.Text(
                        tool.metadata.nombre,
                        size=17, weight=ft.FontWeight.W_800,
                        color=ft.colors.ON_SURFACE,
                        no_wrap=False,
                    ),
                    ft.Container(height=5),
                    # Descripción
                    ft.Text(
                        tool.metadata.descripcion,
                        size=12,
                        color=ft.colors.ON_SURFACE_VARIANT,
                        no_wrap=False,
                        max_lines=2,
                    ),
                ], spacing=0)
            )

        # ── Generador dinámico de Encabezados PREMIUM ──
        def build_premium_header(icon_name, icon_color, title, subtitle=""):
            return ft.Container(
                border_radius=20,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.center_left,
                    end=ft.alignment.center_right,
                    colors=["#0D1B2A", "#111827"],
                ),
                padding=ft.padding.only(top=24, bottom=24, left=30, right=30),
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(icon_name, size=38, color=icon_color),
                        bgcolor=ft.colors.with_opacity(0.14, icon_color),
                        border_radius=14,
                        padding=12,
                    ),
                    ft.Container(width=15),
                    ft.Column([
                        ft.Text(title, size=28, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
                        ft.Text(subtitle, size=13, color=ft.colors.GREY_400) if subtitle else ft.Container(),
                    ], spacing=2)
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )

        def build_sync_access_view(target_index: int):
            saved_hash = (cfg_get("sync_access_password_hash") or "").strip()
            setup_mode = not saved_hash
            password_field = ft.TextField(
                label="Contraseña",
                password=True,
                can_reveal_password=True,
                prefix_icon=ft.icons.LOCK_ROUNDED,
                border_radius=8,
                filled=True,
                autofocus=True,
            )
            confirm_field = ft.TextField(
                label="Confirmar contraseña",
                password=True,
                can_reveal_password=True,
                prefix_icon=ft.icons.LOCK_ROUNDED,
                border_radius=8,
                filled=True,
                visible=setup_mode,
            )
            message_text = ft.Text("", size=12, color=ft.colors.ERROR)

            def _submit_access(e=None):
                password = (password_field.value or "").strip()
                confirm = (confirm_field.value or "").strip()
                if len(password) < 4:
                    message_text.value = "La contraseña debe tener al menos 4 caracteres."
                    message_text.update()
                    return

                if setup_mode:
                    if password != confirm:
                        message_text.value = "Las contraseñas no coinciden."
                        message_text.update()
                        return
                    cfg_set("sync_access_password_hash", _hash_sync_password(password))
                    sync_access_unlocked[0] = True
                    _show_message("Contraseña de Sync SISMED configurada.")
                    update_sidebar_ui(target_index)
                    update_content(target_index)
                    return

                if _hash_sync_password(password) != saved_hash:
                    message_text.value = "Contraseña incorrecta."
                    message_text.update()
                    return

                sync_access_unlocked[0] = True
                update_sidebar_ui(target_index)
                update_content(target_index)

            password_field.on_submit = _submit_access
            confirm_field.on_submit = _submit_access

            return ft.Container(
                padding=40,
                expand=True,
                content=ft.Column([
                    build_premium_header(
                        ft.icons.ADMIN_PANEL_SETTINGS_ROUNDED,
                        CATEGORY_COLORS["Sync"],
                        "Acceso protegido",
                        "Las herramientas Sync guardan URLs y claves sensibles."
                    ),
                    ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                    ft.Container(
                        width=520,
                        bgcolor=ft.colors.SURFACE_VARIANT,
                        border_radius=20,
                        padding=30,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(
                                    ft.icons.VPN_KEY_ROUNDED if setup_mode else ft.icons.LOCK_ROUNDED,
                                    color=CATEGORY_COLORS["Sync"],
                                ),
                                ft.Text(
                                    "Crear contraseña de Sync" if setup_mode else "Ingrese la contraseña de Sync",
                                    size=20,
                                    weight=ft.FontWeight.W_800,
                                ),
                            ]),
                            ft.Text(
                                "Esta contraseña se pedirá para abrir Sync SISMED en esta PC."
                                if setup_mode
                                else "Acceso requerido para ver y editar credenciales de sincronización.",
                                size=13,
                                color=ft.colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Divider(height=18, color=ft.colors.OUTLINE_VARIANT),
                            password_field,
                            confirm_field,
                            message_text,
                            ft.Row([
                                ft.ElevatedButton(
                                    "ENTRAR" if not setup_mode else "GUARDAR Y ENTRAR",
                                    icon=ft.icons.LOGIN_ROUNDED,
                                    on_click=_submit_access,
                                    style=ft.ButtonStyle(
                                        bgcolor={
                                            ft.ControlState.DEFAULT: ft.colors.TEAL_600,
                                            ft.ControlState.HOVERED: ft.colors.TEAL_800,
                                        },
                                        color=ft.colors.WHITE,
                                        padding=ft.padding.symmetric(horizontal=18, vertical=14),
                                        shape=ft.RoundedRectangleBorder(radius=10),
                                    ),
                                ),
                            ], alignment=ft.MainAxisAlignment.END),
                        ], spacing=12),
                    ),
                ], scroll=ft.ScrollMode.AUTO),
            )

        if index in (3, 18) and not sync_access_unlocked[0]:
            content.controls.append(build_sync_access_view(index))
            page.update()
            return

        if index == 0:

            # Contador con referencia mutable para actualizarlo en búsqueda
            count_text = ft.Text(
                f"{len(TOOLS_REGISTRY)} herramientas disponibles",
                size=13, color=ft.colors.GREY_500,
                italic=True,
            )

            # Fila de tarjetas (se reconstruye en cada búsqueda)
            cards_row = ft.Row(
                controls=[make_tool_card(t) for t in TOOLS_REGISTRY],
                wrap=True,
                spacing=16,
                run_spacing=16,
            )

            # Mensaje para cuando no hay resultados
            no_results_msg = ft.Container(
                visible=False,
                padding=ft.padding.only(top=30),
                content=ft.Column([
                    ft.Icon(ft.icons.SEARCH_OFF_ROUNDED, size=64, color=ft.colors.GREY_700),
                    ft.Container(height=10),
                    ft.Text("Sin resultados", size=20,
                            color=ft.colors.GREY_500, weight=ft.FontWeight.W_700),
                    ft.Text("Intenta con otro término: excel, sync, reporte...",
                            size=13, color=ft.colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6)
            )

            # Función que filtra las tarjetas en tiempo real
            def on_search_change(e):
                query = e.control.value.strip().lower()
                if not query:
                    filtered = TOOLS_REGISTRY
                else:
                    filtered = [
                        t for t in TOOLS_REGISTRY
                        if query in " ".join([
                            t.metadata.nombre,
                            t.metadata.descripcion,
                            t.metadata.categoria,
                            " ".join(t.metadata.etiquetas)
                        ]).lower()
                    ]
                count_text.value = (
                    f"{len(filtered)} de {len(TOOLS_REGISTRY)} herramientas"
                    if query else
                    f"{len(TOOLS_REGISTRY)} herramientas disponibles"
                )
                if filtered:
                    cards_row.controls = [make_tool_card(t) for t in filtered]
                    cards_row.visible = True
                    no_results_msg.visible = False
                else:
                    cards_row.controls = []
                    cards_row.visible = False
                    no_results_msg.visible = True
                count_text.update()
                cards_row.update()
                no_results_msg.update()

            # ── Campo de búsqueda glassmorphism ─────────────────────────────────
            search_field = ft.TextField(
                hint_text="  Buscar herramienta...  (ej: excel, sync, tformdet)",
                prefix_icon=ft.icons.SEARCH_ROUNDED,
                border_radius=30,
                filled=True,
                border_color=ft.colors.TRANSPARENT,
                focused_border_color=ft.colors.BLUE_400,
                focused_border_width=2,
                bgcolor=ft.colors.with_opacity(0.07, ft.colors.WHITE),
                content_padding=ft.padding.symmetric(horizontal=20, vertical=16),
                text_size=15,
                on_change=on_search_change,
                width=520,
                suffix=ft.Icon(ft.icons.KEYBOARD_ROUNDED,
                               color=ft.colors.GREY_700, size=18),
            )

            # ── Header inmersivo ─────────────────────────────────────────────────
            header_section = ft.Container(
                border_radius=20,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.center_left,
                    end=ft.alignment.center_right,
                    colors=["#0D1B2A", "#111827"],
                ),
                padding=ft.padding.only(top=30, bottom=28, left=36, right=36),
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ft.icons.DASHBOARD_ROUNDED,
                                            size=40, color=ft.colors.BLUE_400),
                            bgcolor=ft.colors.with_opacity(0.14, ft.colors.BLUE_400),
                            border_radius=14,
                            padding=12,
                        ),
                        ft.Container(width=18),
                        ft.Column([
                            ft.Text("ToolKit SISMED Dashboard",
                                    size=30, weight=ft.FontWeight.W_900,
                                    color=ft.colors.WHITE),
                            ft.Text("Seleccione una herramienta para comenzar",
                                    size=14, color=ft.colors.GREY_400),
                        ], spacing=3),
                        ft.Container(expand=True),
                        # Badge de versión / estado
                        ft.Container(
                            content=ft.Row([
                                ft.Container(
                                    width=8, height=8,
                                    bgcolor=ft.colors.GREEN_400,
                                    border_radius=10,
                                ),
                                ft.Text("Sistema activo", size=12,
                                        color=ft.colors.GREEN_400,
                                        weight=ft.FontWeight.W_600),
                            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            bgcolor=ft.colors.with_opacity(0.12, ft.colors.GREEN_400),
                            border_radius=20,
                            padding=ft.padding.symmetric(horizontal=14, vertical=7),
                        ),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(height=22),
                    # Barra de búsqueda + contador
                    ft.Row([
                        search_field,
                        ft.Container(width=16),
                        count_text,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=0)
            )

            home_ui = ft.Container(
                padding=ft.padding.only(top=30, left=36, right=36, bottom=36),
                expand=True,
                content=ft.Column(
                    controls=[
                        header_section,
                        ft.Container(height=28),
                        # Separador con label
                        ft.Row([
                            ft.Container(height=1, expand=True,
                                         bgcolor=ft.colors.OUTLINE_VARIANT),
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=14),
                                content=ft.Text("HERRAMIENTAS DISPONIBLES",
                                                size=11, weight=ft.FontWeight.W_700,
                                                color=ft.colors.GREY_600,
                                                )
                            ),
                            ft.Container(height=1, expand=True,
                                         bgcolor=ft.colors.OUTLINE_VARIANT),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Container(height=16),
                        cards_row,
                        no_results_msg,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            )
            content.controls.append(home_ui)
            
        elif index == 1:
            settings_view = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column([
                    build_premium_header(
                        ft.icons.SETTINGS_ROUNDED, 
                        ft.colors.BLUE_400, 
                        "Ajustes del Sistema", 
                        "Configuraciones y preferencias globales de ToolKit SISMED"
                    ),
                    ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                    ft.Container(
                        bgcolor=ft.colors.SURFACE_VARIANT,
                        border_radius=20,
                        padding=30,
                        content=ft.Column([
                            ft.Row([ft.Icon(ft.icons.POWER_SETTINGS_NEW_ROUNDED, color=ft.colors.BLUE_400), ft.Text("Comportamiento Automático de Arranque", size=20, weight=ft.FontWeight.W_800)]),
                            ft.Divider(height=25, color=ft.colors.OUTLINE_VARIANT),
                            chk_auto_startup,
                            ft.Container(height=5),
                            ft.Row([
                                ft.Icon(ft.icons.INFO_OUTLINE_ROUNDED, size=16, color=ft.colors.ON_SURFACE_VARIANT),
                                ft.Text("Si se activa, el programa se registrará para arrancar en segundo plano automáticamente al iniciar Windows.", size=13, color=ft.colors.ON_SURFACE_VARIANT)
                            ])
                        ])
                    ),
                    updater_controller.build_settings_card(),
                    ft.Container(
                        bgcolor=ft.colors.SURFACE_VARIANT,
                        border_radius=20,
                        padding=30,
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.icons.DESCRIPTION_ROUNDED, color=ft.colors.CYAN_400),
                                ft.Text("Diagnóstico de Configuración", size=20, weight=ft.FontWeight.W_800)
                            ]),
                            ft.Divider(height=25, color=ft.colors.OUTLINE_VARIANT),
                            ft.Text(
                                "Abre el log de configuración para revisar errores de lectura o escritura cuando la persistencia falle.",
                                size=13,
                                color=ft.colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Container(height=12),
                            ft.ElevatedButton(
                                "Abrir log de configuración",
                                icon=ft.icons.OPEN_IN_NEW_ROUNDED,
                                on_click=_open_config_log,
                                style=ft.ButtonStyle(
                                    bgcolor={ft.ControlState.DEFAULT: ft.colors.CYAN_600, ft.ControlState.HOVERED: ft.colors.CYAN_800},
                                    color=ft.colors.WHITE,
                                    padding=ft.padding.symmetric(horizontal=18, vertical=14),
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                            ),
                            ft.Container(height=8),
                            ft.Text(
                                f"Ruta del log: {get_config_log_path()}",
                                size=12,
                                color=ft.colors.GREY_500,
                                selectable=True,
                            ),
                        ])
                    ),
                    ft.Container(height=20),
                ], scroll=ft.ScrollMode.ALWAYS, expand=True)
            )
            content.controls.append(settings_view)

        elif index == 20:
            farmacia_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        build_premium_header(
                            ft.icons.LOCAL_PHARMACY_ROUNDED,
                            CATEGORY_COLORS["Farmacia"],
                            "Farmacia",
                            "Herramientas para realizar informes mensuales de farmacia"
                        ),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                make_tool_card(get_tool_by_name("Anexar TFORMDET")),
                                make_tool_card(get_tool_by_name("Disponibilidad TFORMDET")),
                                make_tool_card(get_tool_by_name("Generar ICI")),
                            ],
                            wrap=True,
                            spacing=16,
                            run_spacing=16
                        )
                    ]
                )
            )
            content.controls.append(farmacia_ui)

        # VISTAS OCULTAS DEL MENÚ LATERAL (Accesibles mediante las tarjetas de inicio)
        elif index == 2:
            herramientas_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        build_premium_header(
                            ft.icons.HOME_REPAIR_SERVICE_ROUNDED, 
                            CATEGORY_COLORS["Herramientas"], 
                            "Herramientas SISMED", 
                            "Seleccione una sub-herramienta para trabajar:"
                        ),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                make_tool_card(get_tool_by_name("DBF a EXCEL")),
                                make_tool_card(get_tool_by_name("Unir EXCEL")),
                                make_tool_card(get_tool_by_name("Format TFORMDET")),
                                make_tool_card(get_tool_by_name("Editor PDF"))
                            ],
                            wrap=True,
                            spacing=16,
                            run_spacing=16
                        )
                    ]
                )
            )
            content.controls.append(herramientas_ui)

        elif index == 3:
            # Sync SISMED → delegado al objeto SyncSismedTool (POO)
            sync_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        build_premium_header(
                            ft.icons.CLOUD_SYNC_ROUNDED,
                            CATEGORY_COLORS["Sync"],
                            "Sync SISMED",
                            "Seleccione el motor de sincronización que desea configurar:"
                        ),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                make_tool_card(get_tool_by_name("Sync SISMED")),
                            ],
                            wrap=True,
                            spacing=16,
                            run_spacing=16,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            )
            content.controls.append(sync_ui)

        elif index == 18:
            sync_tool = get_tool_by_name("Sync SISMED")
            if sync_tool:
                content.controls.append(sync_tool.build_view(page, navigate))

        
        elif index == 4:
            # Nuevo Dashboard de Reports SISMED
            reports_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        build_premium_header(
                            ft.icons.BAR_CHART_ROUNDED, 
                            CATEGORY_COLORS["Reports SISMED"], 
                            "Reports SISMED", 
                            "Seleccione un reporte para visualizar:"
                        ),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                make_tool_card(get_tool_by_name("Consul. TFORMDET")),
                                make_tool_card(get_tool_by_name("Reporte Guías")),
                                make_tool_card(get_tool_by_name("Stock SISMED")),
                                make_tool_card(get_tool_by_name("Consumo Valorizado")),
                            ],
                            wrap=True,
                            spacing=16,
                            run_spacing=16
                        )
                    ]
                )
            )
            content.controls.append(reports_ui)
            
        elif index == 5:
            # Consulta TFORMDET → delegado al objeto ConsultaTformdetTool (POO)
            consul_tool = get_tool_by_name("Consul. TFORMDET")
            if consul_tool:
                content.controls.append(consul_tool.build_view(page, navigate))
            
        elif index == 8:
            # Reporte Guías → delegado al objeto ReporteGuiasTool (POO)
            guias_tool = get_tool_by_name("Reporte Guías")
            if guias_tool:
                content.controls.append(guias_tool.build_view(page, navigate))
            
        elif index == 6:
            # DBF a Excel View  → delegado al objeto DbfExcelTool (POO)
            dbf_tool = get_tool_by_name("DBF a EXCEL")
            if dbf_tool:
                content.controls.append(dbf_tool.build_view(page, navigate))
            
        elif index == 7:
            # Format TFORMDET View → delegado al objeto FormatTformdetTool (POO)
            fmt_tool = get_tool_by_name("Format TFORMDET")
            if fmt_tool:
                content.controls.append(fmt_tool.build_view(page, navigate))

        elif index == 19:
            append_tool = get_tool_by_name("Anexar TFORMDET")
            if append_tool:
                content.controls.append(append_tool.build_view(page, navigate))

        elif index == 21:
            # Generar ICI → delegado al objeto GenerarIciTool (POO)
            ici_tool = get_tool_by_name("Generar ICI")
            if ici_tool:
                content.controls.append(ici_tool.build_view(page, navigate))

        elif index == 9:
            # Stock SISMED → delegado al objeto StockReportTool (POO)
            stock_tool = get_tool_by_name("Stock SISMED")
            if stock_tool:
                content.controls.append(stock_tool.build_view(page, navigate))

        elif index == 10:
            # Disponibilidad TFORMDET → delegado al objeto DisponibilidadReportTool (POO)
            disp_tool = get_tool_by_name("Disponibilidad TFORMDET")
            if disp_tool:
                content.controls.append(disp_tool.build_view(page, navigate))

        elif index == 16:
            # Consumo Valorizado → delegado al objeto ConsumoValorizadoReportTool (POO)
            consumo_tool = get_tool_by_name("Consumo Valorizado")
            if consumo_tool:
                content.controls.append(consumo_tool.build_view(page, navigate))

        elif index == 11:
            # Nuevo Dashboard de Edit SISMED
            edit_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        build_premium_header(
                            ft.icons.EDIT_NOTE, 
                            CATEGORY_COLORS["Edit SISMED"], 
                            "Edit SISMED", 
                            "Edición directa de bases de datos SISMED:"
                        ),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                make_tool_card(get_tool_by_name("Cambiar Estado Med.")),
                                make_tool_card(get_tool_by_name("Habilitar Guías")),
                            ],
                            wrap=True,
                            spacing=16,
                            run_spacing=16
                        )
                    ]
                )
            )
            content.controls.append(edit_ui)

        elif index == 12:
            # Cambiar Estado Med. → delegado al objeto ChangeMedestTool (POO)
            edit_state_tool = get_tool_by_name("Cambiar Estado Med.")
            if edit_state_tool:
                content.controls.append(edit_state_tool.build_view(page, navigate))

        elif index == 13:
            # Editar Guías (TMOVIM) → delegado al objeto EditTmovimTool (POO)
            tmovim_tool = get_tool_by_name("Habilitar Guías")
            if tmovim_tool:
                content.controls.append(tmovim_tool.build_view(page, navigate))

        elif index == 14:
            # Editor PDF → delegado al objeto PdfTool (POO)
            pdf_tool = get_tool_by_name("Editor PDF")
            if pdf_tool:
                content.controls.append(pdf_tool.build_view(page, navigate))

        elif index == 15:
            # Unir Excel → delegado al objeto ExcelMergeTool (POO)
            merge_tool = get_tool_by_name("Unir EXCEL")
            if merge_tool:
                content.controls.append(merge_tool.build_view(page, navigate))

        page.update()  # Actualiza la página

    # ── DISEÑO PREMIUM: Menú Lateral Personalizado con Tooltips ──
    selected_nav_idx = [0] # Índice de navegación actual

    def update_sidebar_ui(idx):
        selected_nav_idx[0] = idx
        visual_idx = 3 if idx == 18 else idx
        for item in nav_items_list:
            is_selected = (visual_idx == item.data)
            stack = item.content
            # Indicador (control 0 del Stack)
            stack.controls[0].visible = is_selected
            # Row interno (dentro del control 1 del Stack)
            row = stack.controls[1].content
            # Icono (control 0 del Row)
            row.controls[0].color = ft.colors.BLUE_400 if is_selected else ft.colors.GREY_500
            # Texto (control 1 del Row)
            row.controls[1].color = ft.colors.BLUE_400 if is_selected else ft.colors.GREY_500
            row.controls[1].weight = ft.FontWeight.W_800 if is_selected else ft.FontWeight.NORMAL
            # Fondo sutil del contenedor
            item.bgcolor = ft.colors.with_opacity(0.1, ft.colors.WHITE) if is_selected else ft.colors.TRANSPARENT
            item.update()

    def create_nav_item(icon_name, label, index):
        def _on_click(e):
            update_sidebar_ui(index)
            update_content(index)

        # Centrado MILIMÉTRICO con SOMBREADO REDUCIDO
        return ft.Container(
            width=50, # Ancho reducido para que no pegue a los bordes
            height=48,
            border_radius=12,
            tooltip=label,
            data=index, # Guardamos el índice real para identificarlo luego
            on_click=_on_click,
            bgcolor=ft.colors.with_opacity(0.1, ft.colors.WHITE) if index==0 else ft.colors.TRANSPARENT,
            animate=ft.Animation(300, ft.AnimationCurve.DECELERATE),
            content=ft.Stack([
                # Capa 1: Indicador (Se sale un poco del contenedor reducido para tocar el borde)
                ft.Container(
                    width=4, height=48, 
                    bgcolor=ft.colors.BLUE_400, 
                    border_radius=10, 
                    visible=(index==0),
                    alignment=ft.alignment.center_left,
                    offset=ft.Offset(-0.4, 0) # Lo movemos a la izquierda hacia el borde del menú
                ),
                # Capa 2: Contenido
                ft.Container(
                    content=ft.Row([
                        ft.Icon(icon_name, color=ft.colors.BLUE_400 if index==0 else ft.colors.GREY_500, size=24),
                        ft.Text(label, visible=False, size=14, color=ft.colors.GREY_500, no_wrap=True),
                    ], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=15),
                    alignment=ft.alignment.center 
                )
            ]),
            on_hover=lambda e: setattr(
                e.control,
                "bgcolor",
                ft.colors.with_opacity(0.15, ft.colors.WHITE)
                if e.data == "true" or selected_nav_idx[0] == index or (index == 3 and selected_nav_idx[0] == 18)
                else ft.colors.TRANSPARENT,
            ) or e.control.update()
        )

    nav_items_list = [
        create_nav_item(ft.icons.HOME_ROUNDED, "Inicio", 0),
        create_nav_item(ft.icons.LOCAL_PHARMACY_ROUNDED, "Farmacia", 20),
        create_nav_item(ft.icons.HOME_REPAIR_SERVICE_ROUNDED, "Herramientas", 2),
        create_nav_item(ft.icons.BAR_CHART_ROUNDED, "Reports SISMED", 4),
        create_nav_item(ft.icons.EDIT_NOTE, "Edit SISMED", 11),
        create_nav_item(ft.icons.CLOUD_SYNC_ROUNDED, "Sync SISMED", 3),
        create_nav_item(ft.icons.SETTINGS_ROUNDED, "Configuración", 1),
    ]

    menu = ft.Container(
        content=ft.Column(nav_items_list, spacing=15, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        width=70,  # Inicialmente colapsado
        padding=ft.padding.only(top=30),
        bgcolor="#0D0F11", # Un tono casi negro muy profundo para resaltar el contraste
        animate=ft.Animation(300, ft.AnimationCurve.DECELERATE),
    )
    # Contenedor de contenido principal inicializando en Inicio
    content = ft.Column([ft.Text(value="")], expand=True)
    update_content(0)
    
    content_container = ft.Container(content=content, expand=True, padding=ft.padding.only(top=0, right=20, left=20, bottom=20))

    # Estructura de la página
    page.add(
        ft.Row(
            [
                menu,  # Menú lateral colapsable ya con su bgcolor oscuro
                ft.VerticalDivider(width=1, color=ft.colors.OUTLINE_VARIANT),  # Divisor visual sutil
                content_container,  # Contenido dinámico expandible acorde al layout
                
            ],
            expand=True,
            spacing=0, # Eliminar espacio extra entre la barra y el contenido
            vertical_alignment=ft.CrossAxisAlignment.STRETCH # ESTO lo hace ocupar todo el alto
        )
    )

    # Inicializar silenciosamente Sync SISMED para activar su auto-arranque temporal si corresponde
    sync_tool = get_tool_by_name("Sync SISMED")
    if sync_tool:
        sync_tool._init_components(page)

    updater_controller.start()

    if install_success_requested:
        try:
            updater_controller.manager.cleanup_downloads()
        except Exception as exc:
            append_runtime_log(
                "update",
                f"No se pudieron limpiar instaladores anteriores: {type(exc).__name__}: {exc}",
            )
        cfg_set("update_pending_version", "")
        append_runtime_log("update", f"Actualizacion {current_version} instalada correctamente.")
        _show_message("ToolKit SISMED se instaló o actualizó correctamente.")
    elif update_failure_requested:
        cfg_set("update_pending_version", "")
        append_runtime_log(
            "update",
            "La actualizacion no se completo. El auxiliar restauro la instalacion anterior.",
        )
        _show_message(
            "La actualización no pudo completarse. "
            "ToolKit SISMED restauró la versión anterior para proteger la instalación."
        )

if __name__ == "__main__":
    if _acquire_single_instance():
        try:
            ft.app(target=main)
        finally:
            _release_single_instance_resources()
