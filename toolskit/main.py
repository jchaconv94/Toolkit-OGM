import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import flet as ft
import os
import pandas as pd
from dbfread import DBF
from datetime import datetime
import time  # Importa time para simular el progreso de la barra
from openpyxl import load_workbook
from openpyxl.styles import Font, Border, Side

from datetime import datetime
import locale
import sys
import os
import winreg as reg
import threading
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import win32event
import win32api
import winerror
from tformdet_report import TformdetManager
from guia_report import GuiaReportManager
from tools.tool_registry import TOOLS_REGISTRY, get_tool_by_name

# ==========================================
# PREVENCIÓN DE MULTI-CLONACIÓN (MUTEX)
# ==========================================
mutex_name = "ToolkitOGM_SingleInstanceMutex_v1"
mutex = win32event.CreateMutex(None, False, mutex_name)
if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
    sys.exit(0) # Si ya hay uno abierto, esta instancia fantasma se suicida inmediatamente


def set_startup(run: bool):
    try:
        key_name = "ToolkitOGM_Sync"
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_ALL_ACCESS)
        if run:
            if getattr(sys, 'frozen', False):
                cmd = f'"{sys.executable}" --autorun'
            else:
                python_exe = sys.executable
                pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
                script_path = os.path.abspath(sys.argv[0])
                cmd = f'"{pythonw_exe}" "{script_path}" --autorun'
            reg.SetValueEx(key, key_name, 0, reg.REG_SZ, cmd)
        else:
            try:
                reg.DeleteValue(key, key_name)
            except FileNotFoundError:
                pass
        reg.CloseKey(key)
    except Exception:
        pass


def main(page: ft.Page):
    
    saved_auto_startup = page.client_storage.get("auto_startup") or False

    def _on_startup_change(e):
        page.client_storage.set("auto_startup", e.control.value)
        set_startup(e.control.value)

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

    page.title = "ToolKits SISMED"
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
    
    # Boot silencioso
    if "--autorun" in sys.argv:
        page.window.visible = False
    
    # Lógica de System Tray (Bandeja del Sistema)
    tray_icon = None

    def create_image():
        # Crea una imagen simple con Pillow (puedes reemplazarla luego por tu ícono .ico)
        image = Image.new('RGB', (64, 64), color = (0, 188, 212)) # Color Cian
        d = ImageDraw.Draw(image)
        d.text((15, 20), "OGM", fill=(255, 255, 255))
        return image

    def on_show_window(icon, item):
        page.window.visible = True
        page.update()

    def on_quit(icon, item):
        sync_tool = get_tool_by_name("Sync SISMED")
        if sync_tool and sync_tool.sync_manager:
            sync_tool.sync_manager.stop_sync()
        icon.stop()
        page.window.destroy()

    def setup_tray():
        nonlocal tray_icon
        image = create_image()
        menu = pystray.Menu(
            item('Restaurar Ventana', on_show_window, default=True),
            item('Cerrar completamente', on_quit)
        )
        tray_icon = pystray.Icon("toolkit_ogm", image, "ToolKits SISMED (Sincronizando)", menu)
        tray_icon.run()

    # Iniciar Bandeja en segundo plano
    threading.Thread(target=setup_tray, daemon=True).start()

    def window_event(e):
        if e.data == "close":
            page.window.visible = False
            page.update()
            
    page.window.on_event = window_event

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

    # AppBar Superior (Estilo Docker Desktop)
    page.appbar = ft.AppBar(
        leading=ft.IconButton(ft.icons.MENU, on_click=toggle_nav_rail, tooltip="Menú principal"),
        leading_width=50,
        title=ft.Row([
            ft.Icon(ft.icons.LAYERS_ROUNDED, color=ft.colors.CYAN_500, size=24),
            ft.Text("ToolKit SISMED", size=18, weight=ft.FontWeight.W_800)
        ], spacing=10),
        bgcolor=ft.colors.SURFACE_VARIANT,
        actions=[
            ft.Container(
                content=ft.Row([
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
        
        def navigate(view_idx):
            # Ahora que están en el sidebar, sí los seleccionamos. Si el view_idx no es visualmente un tooltip lateral (como los index 6 y 7, mantendrá visualmente la categoría principal si existe)
            update_sidebar_ui(view_idx)
            update_content(view_idx)
        
        # Mapa: nombre de herramienta (metadata.nombre) → índice de navegación
        TOOL_NAV_INDEX = {
            "Consul. TFORMDET":  5,
            "Reporte Guías":     8,
            "DBF a EXCEL":       6,
            "Format TFORMDET":   7,
            "Sync SISMED":       3,
            "Stock SISMED":      9,
        }

        # ── Colores de acento por categoría ──
        CATEGORY_COLORS = {
            "Herramientas":    ft.colors.TEAL_400,
            "Reports SISMED":  ft.colors.BLUE_400,
            "Sync":            ft.colors.GREEN_500,
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
                    )
                ])
            )
            content.controls.append(settings_view)

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
                                make_tool_card(get_tool_by_name("Format TFORMDET"))
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

        elif index == 9:
            # Stock SISMED → delegado al objeto StockReportTool (POO)
            stock_tool = get_tool_by_name("Stock SISMED")
            if stock_tool:
                content.controls.append(stock_tool.build_view(page, navigate))

        page.update()  # Actualiza la página

    # ── DISEÑO PREMIUM: Menú Lateral Personalizado con Tooltips ──
    selected_nav_idx = [0] # Índice de navegación actual

    def update_sidebar_ui(idx):
        selected_nav_idx[0] = idx
        for item in nav_items_list:
            is_selected = (idx == item.data)
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
            on_hover=lambda e: setattr(e.control, "bgcolor", ft.colors.with_opacity(0.15, ft.colors.WHITE) if e.data == "true" or selected_nav_idx[0] == index else ft.colors.TRANSPARENT) or e.control.update()
        )

    nav_items_list = [
        create_nav_item(ft.icons.HOME_ROUNDED, "Inicio", 0),
        create_nav_item(ft.icons.HOME_REPAIR_SERVICE_ROUNDED, "Herramientas", 2),
        create_nav_item(ft.icons.BAR_CHART_ROUNDED, "Reports SISMED", 4),
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
        sync_tool.build_view(page, lambda idx: None)

ft.app(target=main)
