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
                # Si está compilado como ejecutable (Ej: PyInstaller)
                cmd = f'"{sys.executable}" --autorun'
            else:
                # Si es un script de Python crudo
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
    except Exception as e:
        pass

def main(page: ft.Page):
    
    # Variables globales
    selected_file = ft.TextField(label="Archivo seleccionado", read_only=True, expand=True)
    save_location = ft.TextField(label="Ubicación de guardado", read_only=True, expand=True)
    result_label = ft.Text(value="", size=16, color=ft.colors.RED)
    progress_bar = ft.ProgressBar(width=400, visible=False)  # Barra de progreso
    alert_dialog = None  # Variable global para el AlertDialog
    
 #:::::::::::::::::CONVERTIR DBF A EXCEL:::::::::::::::::::::::::::::::::
    # Función: Selección de archivo DBF
    def on_file_picked(e):
        if e.files:
            file_path = e.files[0].path
            
            # Validar si el archivo tiene la extensión .dbf
            if not file_path.lower().endswith(".dbf"):  # Asegurarse de ignorar mayúsculas/minúsculas
                selected_file.value = ""
                save_location.value = ""
                result_label.value = "Por favor, selecciona un archivo con extensión .dbf."
                result_label.color = ft.colors.RED
            else:
                selected_file.value = file_path
                save_location.value = os.path.splitext(file_path)[0] + ".xlsx"
                result_label.value = ""
                result_label.color = ft.colors.BLACK
        else:
            selected_file.value = ""
            save_location.value = ""
            result_label.value = "No se seleccionó ningún archivo."
            result_label.color = ft.colors.RED
        page.update()

    # Función: Cambiar ubicación de guardado
    def on_save_location_picked(e):
        if e.path:
            if not save_location.value.endswith(".xlsx"):
                save_location.value = os.path.join(e.path, "output.xlsx")
            else:
                save_location.value = os.path.join(e.path, os.path.basename(save_location.value))
            result_label.value = f"Ubicación de guardado actualizada: {save_location.value}"
            result_label.color = ft.colors.BLUE
        page.update()

    # Función: Convertir archivo DBF a XLSX
    def convert_file(e):
        nonlocal alert_dialog  # Asegurar que podemos modificar la variable global
        if not selected_file.value:
            result_label.value = "Por favor, selecciona un archivo primero."
            result_label.color = ft.colors.RED
            page.update()
            return

        try:
            # Mostrar mensaje de espera
            result_label.value = "Espere, convirtiendo archivo..."
            result_label.color = ft.colors.YELLOW  
            page.update()

            # Mostrar la barra de progreso
            progress_bar.visible = True
            progress_bar.value = 0  # Iniciar en 0
            page.update()

            # Leer el archivo DBF y convertirlo a XLSX
            dbf_path = selected_file.value
            xlsx_path = save_location.value

            # Leer el archivo DBF
            table = DBF(dbf_path, encoding="latin1")
            df = pd.DataFrame(iter(table))

            # Convertir y guardar el archivo como XLSX
            df.to_excel(xlsx_path, index=False, engine="openpyxl")

            # Simular el progreso de la conversión          
            for i in range(0, 101):
                progress_bar.value = i * 0.01
                time.sleep(0.1)
                page.update()

            # Finalizar la barra de progreso
            progress_bar.value = 100
            page.update()

            # Crear y mostrar el AlertDialog
            alert_dialog = ft.AlertDialog(
                title=ft.Text("¡Conversión Exitosa!"),
                content=ft.Text(f"El archivo se ha guardado en {xlsx_path}."),
                actions=[ft.ElevatedButton("Aceptar", on_click=close_alert)],
                open=True,
            )
            #page.dialog = alert_dialog
            page.overlay.append(alert_dialog)
            page.update()

        except PermissionError as e:
            result_label.value = f"Error: {str(e)}"
            result_label.color = ft.colors.RED
        except Exception as ex:
            result_label.value = f"Error: {str(ex)}"
            result_label.color = ft.colors.RED

        # Ocultar la barra de progreso después de la conversión
        progress_bar.visible = False
        page.update()

    # Función para cerrar el AlertDialog
    def close_alert(e):
        nonlocal alert_dialog  # Asegúrate de usar la variable global
        if alert_dialog:
            alert_dialog.open = False  # Cerrar el diálogo
             # Resetear campos
            selected_file.value = ""
            save_location.value = ""
            result_label.value = ""
            progress_bar.value = 0
            page.update()

 # Botón para convertir archivo
    convert_button = ft.ElevatedButton(
        text="Convertir a .XLSX",
        icon=ft.icons.SAVE,
        style=ft.ButtonStyle(
            bgcolor=ft.colors.LIGHT_BLUE,
            color=ft.colors.WHITE,
        ),
        on_click=convert_file,
    )

    # Botón para seleccionar archivo DBF
    pick_file_button = ft.ElevatedButton(
    text="Seleccionar archivo .DBF",
    icon=ft.icons.FOLDER_OPEN,
    on_click=lambda _: file_picker.pick_files(allow_multiple=False, allowed_extensions=["dbf"]),
    )

    # Botón para cambiar ubicación de guardado
    change_save_location_button = ft.ElevatedButton(
        text="Cambiar ubicación de guardado",
        icon=ft.icons.DRIVE_FOLDER_UPLOAD,
        on_click=lambda _: save_picker.get_directory_path(),
    )
    
#::::::::::::MODIFICAR EXCEL DE TFORMDET:::::::::::::::
    # Variables de la interfaz
    archivo_seleccionado = ft.TextField(label="Archivo seleccionado", read_only=True, expand=True)
    status_text = ft.Text(value="Selecciona un archivo Excel para comenzar", size=16)
    
    # Función para manejar la selección del archivo
    def file_selected(e: ft.FilePickerResultEvent):
        if file_picker2.result and file_picker2.result.files:
            archivo_seleccionado.value = file_picker2.result.files[0].path
            status_text.value = f"Archivo seleccionado: {archivo_seleccionado.value}" 
        else:
            status_text.value = "No se seleccionó ningún archivo."
            status_text.color = ft.colors.RED
        page.update()

    # Función para modificar el archivo
    def modificar_archivo(e):

        # Inhabilitar los botones
        modificar_button.visible = False
        seleccionar_button.disabled = True

        # Mostrar mensaje de espera
        status_text.value = f"Espere..., modificando archivo {file_name}"
        status_text.color = ft.colors.GREEN

        # Mostrar la barra de progreso
        progress_bar.visible = True
        progress_bar.value = 0  # Iniciar en 0

        # Actualizar la página solo una vez
        page.update()

        # Cargar el archivo seleccionado
        archivo = archivo_seleccionado.value
        workbook = load_workbook(archivo)
        sheet = workbook.active
        
        #verificar si es un archivo tformdet

        cod = sheet["A1"].value
        if cod != "CODIGO_EJE":
            status_text.value = "El archivo seleccionado no es un TFORMDET.xlsx."
            status_text.color = ft.colors.RED
            modificar_button.visible = False
            progress_bar.visible = False
            seleccionar_button.disabled = False
            page.update()
            return
        else:            
            
            #obtener el mes del archivo
            locale.setlocale(locale.LC_TIME, "Spanish_Spain")   #Configurar el idioma para fechas en español
            fecha = sheet["D2"].value
            mes = int(fecha) % 100    # Los últimos 2 dígitos son el mes
            fecha_completa = datetime(2000, mes, 1) # Crear una fecha con el día 1 para evitar problemas
            texto_fecha = fecha_completa.strftime("%B").upper()# Convertir la fecha a texto en español
                
            #MODIFICAR LA HOJA
            bold_font = Font(bold=True) # Crear un estilo de fuente con negrita
           
            borde = Border(
                left=Side(border_style="thin"),
                right=Side(border_style="thin"),
                top=Side(border_style="thin"),
                bottom=Side(border_style="thin")
            )#definir los bordes de celdas

            #insertar columnas
            sheet.insert_cols(2, 2)
            sheet.insert_cols(5, 1)# Insertar 1 columnas a partir de la posición 5
            sheet.insert_cols(9, 1)

            headers = {
                "B1": "COD. UNICO MAS CONSUMO SIS",
                "C1": "COD UNICO",
                "E1": "EESS",
                "I1": "DESCRIPCION MED",
            }

            # Aplicar formato y valor a cada celda
            for cell, value in headers.items():
                sheet[cell] = value

            #Eliminar columnas
            sheet.delete_cols(37, 18)  # Empieza en la columna 38 y elimina 55 columnas consecutivas.
            columnas_a_eliminar = [39,34,33,7,6,1]
            for col in columnas_a_eliminar:
                sheet.delete_cols(col) 

            # Copiar datos de columna 34 a columna 7 (LOTE Y REGISTRO SANITARIO)
            sheet.insert_cols(7, 2)
            for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=34, max_col=35):
                sheet.cell(row=row[0].row, column=7, value=row[0].value)
                sheet.cell(row=row[0].row, column=8, value=row[1].value)
            # Eliminar la columna K (si es necesario)
            sheet.delete_cols(34,2)

            sheet.insert_cols(9, 4)
            for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=37, max_col=40):
                sheet.cell(row=row[0].row, column=9, value=row[0].value)
                sheet.cell(row=row[0].row, column=10, value=row[1].value)
                sheet.cell(row=row[0].row, column=11, value=row[2].value)
                sheet.cell(row=row[0].row, column=12, value=row[3].value)
            sheet.delete_cols(37,4)

            sheet.insert_cols(10, 1)
            sheet.cell(row=1, column=10, value="FECHA CON NUMERO")
            
            #porner en negrito y bordes a la cabecera
            target_row = 1  # Fila donde buscar datos
            for col in range(1, sheet.max_column + 1):
                 if sheet.cell(row=target_row, column=col).value is not None:
                    sheet.cell(row=1, column=col).font = bold_font  # Poner en negrita las cabeceras
                    sheet.cell(row=1, column=col).border = borde            

            from openpyxl.styles import NamedStyle

            #CREAR UN ESTILO DE FECHA
            date_style = NamedStyle(name="datetime", number_format="DD/MM/YYYY")

            # Aplicar formato de fecha a la columna I
            for cell in sheet["I"]:  # Cambia "I" por la columna que deseas formatear
                if cell.row == 1:  # Saltar la cabecera
                    continue
                try:
                    if cell.value and isinstance(cell.value, str):
                        cell.value = datetime.strptime(cell.value, "%Y-%m-%d")  # Ajusta el formato si es diferente
                    cell.style = date_style
                except Exception as e:
                    status_text.value = f"Error al procesar la celda {cell.coordinate}: {e}"
                    status_text.color = ft.colors.RED
                    page.update()
            
            # Agregar la fórmula para convertir la fecha de vencimiento en numero
            formula = "=CONCATENATE(YEAR(I2), IF(MONTH(I2)<10, CONCATENATE(0, MONTH(I2)), MONTH(I2)), IF(DAY(I2)<10, CONCATENATE(0, DAY(I2)), DAY(I2)))"
            formula2 = "=CONCATENATE(C2,E2)"
            formula3 ="=CONCATENATE(C2,E2,R2,S2)"
            last_row = sheet.max_row # Obtener el número de la última fila con datos en la columna I
            for row in range(2, last_row + 1):  # Asignar la fórmula a todas las celdas de la columna J
                sheet[f'J{row}'].value = formula.replace('I2', f'I{row}')
                sheet[f'B{row}'].value = formula2
                sheet[f'A{row}'].value = formula3


            # Simular el progreso de la arreglo de tformdet         
            for i in range(0, 101):
                progress_bar.value = i * 0.01
                time.sleep(0.1)
                page.update()

            # Guardar cambios en un nuevo archivo
            nuevo_archivo = archivo.replace(".xlsx", f"-{texto_fecha}.xlsx")
            workbook.save(nuevo_archivo)

           

            # Crear y mostrar el AlertDialog
            nonlocal alert_dialog  # Asegurar que podemos modificar la variable global
            alert_dialog = ft.AlertDialog(
                title=ft.Text("¡Se completó con Éxito!"),
                content=ft.Text(f"El archivo se ha guardado en {nuevo_archivo}."),
                actions=[ft.ElevatedButton("Aceptar", on_click=close_alert2)],
                open=True,
            )
            #page.dialog = alert_dialog
            page.overlay.append(alert_dialog)
            # Ocultar la barra de progreso después de la conversión
            progress_bar.visible = False
            seleccionar_button.disabled = False
            page.update()
            
    #para manejar las validaciones
    def on_xlsx_file_picked2(e):
        global file_name
        if e.files:
            file_path = e.files[0].path
            if not file_path.lower().endswith(".xlsx"):
                archivo_seleccionado.value = ""
                status_text.value = "Por favor, selecciona un archivo con extensión .xlsx."
                status_text.color = ft.colors.RED
                progress_bar.visible = False
                modificar_button.visible = False
            else:
                archivo_seleccionado.value = file_path
                archivo_seleccionado.color = ft.colors.BLUE_200
                file_name = os.path.basename(file_path)
                status_text.value = f"ARCHIVO A MODIFICAR: {file_name}"
                status_text.color = ft.colors.GREEN
                status_text.style = ft.TextStyle(weight=ft.FontWeight.BOLD)
                modificar_button.visible = True  # Mostrar botón si el archivo es válido

        else:
            archivo_seleccionado.value = "No se seleccionó ningún archivo."
            archivo_seleccionado.color = ft.colors.RED
            status_text.value ="Selecciona un archivo Excel para comenzar"
            status_text.color = ft.colors.BLUE
            modificar_button.visible = False 
        page.update()


    # Elementos para modificar un archivo de excel
    seleccionar_button = ft.ElevatedButton(
    "Seleccionar archivo",
    icon=ft.icons.FOLDER_OPEN,
        style=ft.ButtonStyle(
            bgcolor=ft.colors.LIGHT_BLUE_ACCENT,
            color=ft.colors.WHITE,
        ),
    on_click=lambda _: file_picker2.pick_files(allow_multiple=False, allowed_extensions=["xlsx"]),


    )
    modificar_button = ft.ElevatedButton(
        "Modificar archivo",
        icon=ft.icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED,
        style=ft.ButtonStyle(
            bgcolor=ft.colors.GREEN_ACCENT_700,
            color=ft.colors.WHITE,
        ),
        on_click=modificar_archivo,
        visible=False,
    )

        # Función para cerrar el AlertDialog
    def close_alert2(e):
        nonlocal alert_dialog  # Asegúrate de usar la variable global
        if alert_dialog:
            alert_dialog.open = False  # Cerrar el diálogo
                # Resetear campos
            archivo_seleccionado.value = ""
            status_text.value ="Selecciona un archivo Excel para comenzar"
            status_text.color = ft.colors.WHITE
            modificar_button.visible = False 
        page.update()
    

#:::::::::::::::::FIN DE EXCEL::::::::::::::::::::::::::::::::

# ======================================================================
# AURA SYNC - Sincronizador de SISMED
# ======================================================================
    try:
        from sismed_sync import SismedSyncManager
    except ImportError:
        pass # Por si acaso

    sync_logs = ft.ListView(expand=True, spacing=5, auto_scroll=True, height=210)
    
    def on_sync_log(msg):
        # Protected against 'Page Disconnected' Flet errors when quitting from Tray
        try:
            sync_logs.controls.append(ft.Text(value=msg, size=14, font_family="Consolas"))
            if len(sync_logs.controls) > 100:
                del sync_logs.controls[:len(sync_logs.controls)-100]
            page.update()
        except:
            pass
        
    def on_sync_stopped():
        btn_toggle_sync.text = "Iniciar Sincronización"
        btn_toggle_sync.icon = ft.icons.PLAY_ARROW
        btn_toggle_sync.style.bgcolor = ft.colors.GREEN_600
        btn_toggle_sync.disabled = False
        page.update()
        
    sync_manager = SismedSyncManager(log_callback=on_sync_log, on_stop_callback=on_sync_stopped)
    
    # --- Cargar Preferencias Guardadas ---
    saved_sismed_dir = page.client_storage.get("sismed_dir")
    if saved_sismed_dir: sync_manager.base_dir = saved_sismed_dir
    
    saved_interval = page.client_storage.get("sync_interval")
    if saved_interval: sync_manager.intervalo_minutos = int(saved_interval)
    
    saved_consolidado = page.client_storage.get("consolidado")
    if saved_consolidado is not None: sync_manager.modo_consolidado = saved_consolidado
    
    saved_url = page.client_storage.get("apps_script_url")
    if saved_url: sync_manager.apps_script_url = saved_url
    
    saved_auto_sync = page.client_storage.get("auto_sync") or False
    saved_auto_startup = page.client_storage.get("auto_startup") or False

    def on_startup_chk_change(e):
        page.client_storage.set("auto_startup", e.control.value)
        set_startup(e.control.value)
        
    chk_auto_startup = ft.Checkbox(
        label="Abrir esta aplicación al encender Windows",
        value=saved_auto_startup,
        fill_color={ft.ControlState.SELECTED: ft.colors.BLUE_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
        check_color=ft.colors.WHITE,
        label_style=ft.TextStyle(size=14, color=ft.colors.ON_SURFACE, weight=ft.FontWeight.W_800),
        on_change=on_startup_chk_change
    )

    chk_auto_sync = ft.Checkbox(
        label="Iniciar Sincronización al encender la app", 
        value=saved_auto_sync, 
        fill_color={ft.ControlState.SELECTED: ft.colors.GREEN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
        check_color=ft.colors.WHITE,
        label_style=ft.TextStyle(size=13, color=ft.colors.CYAN_500, weight=ft.FontWeight.W_800),
        on_change=lambda e: page.client_storage.set("auto_sync", e.control.value)
    )

    # Controles de Configuración
    switch_consolidado = ft.Checkbox(
        label="Sumar stock de farmacias", 
        value=sync_manager.modo_consolidado, 
        fill_color={ft.ControlState.SELECTED: ft.colors.CYAN_500, ft.ControlState.DEFAULT: ft.colors.TRANSPARENT},
        check_color=ft.colors.WHITE,
        label_style=ft.TextStyle(size=13, color=ft.colors.ON_SURFACE)
    )
    opciones_intervalo = [ft.dropdown.Option(str(i)) for i in range(5, 65, 5)]
    val_intervalo = str(sync_manager.intervalo_minutos)
    if val_intervalo not in [opt.key for opt in opciones_intervalo]:
        val_intervalo = "5"
        
    input_intervalo = ft.Dropdown(
        label="Intervalo sugerido (minutos)", 
        options=opciones_intervalo,
        value=val_intervalo, 
        width=250, 
        border_radius=8,
        filled=True,
        border_color=ft.colors.OUTLINE_VARIANT,
        prefix_icon=ft.icons.TIMER_ROUNDED,
        content_padding=10,
        text_size=14,
        menu_height=200
    )
    def toggle_url_lock(e):
        # Invertir el estado de solo lectura y modo contraseña
        input_apps_script.read_only = not input_apps_script.read_only
        input_apps_script.password = input_apps_script.read_only
        
        # Actualizar visualmente el candado y el borde
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
        value=sync_manager.apps_script_url, 
        expand=True,
        border_radius=8,
        filled=True,
        border_color=ft.colors.OUTLINE_VARIANT,
        prefix_icon=ft.icons.LINK_ROUNDED,
        read_only=True,
        password=True,
        can_reveal_password=False,
        suffix=ft.IconButton(
            icon=ft.icons.LOCK_ROUNDED, 
            tooltip="Desbloquear URL para editar", 
            icon_color=ft.colors.ON_SURFACE_VARIANT,
            on_click=toggle_url_lock
        )
    )

    def on_sismed_dir_picked(e: ft.FilePickerResultEvent):
        if e.path:
            input_sismed_dir.value = e.path
            input_sismed_dir.update()

    sismed_dir_picker = ft.FilePicker(on_result=on_sismed_dir_picked)
    
    input_sismed_dir = ft.TextField(
        label="Directorio SISMED", 
        value=sync_manager.base_dir, 
        expand=True,
        border_radius=8,
        filled=True,
        border_color=ft.colors.OUTLINE_VARIANT,
        prefix_icon=ft.icons.FOLDER_ROUNDED,
        suffix=ft.IconButton(
            icon=ft.icons.FOLDER_OPEN_ROUNDED,
            icon_color=ft.colors.CYAN_500,
            tooltip="Buscar carpeta SISMED",
            on_click=lambda _: sismed_dir_picker.get_directory_path()
        )
    )

    def toggle_sync(e):
        if not sync_manager.is_running:
            # Iniciar
            sync_logs.controls.clear()
            try:
                mins = int(input_intervalo.value)
                # Validación extrema por si acaso (Loop prevent)
                if mins < 1: mins = 5
                sync_manager.intervalo_minutos = mins
            except (ValueError, TypeError):
                sync_manager.intervalo_minutos = 5
            sync_manager.modo_consolidado = switch_consolidado.value
            sync_manager.apps_script_url = input_apps_script.value.strip()
            sync_manager.base_dir = input_sismed_dir.value.strip()
            
            # Guardar preferencias globalmente
            page.client_storage.set("sismed_dir", sync_manager.base_dir)
            page.client_storage.set("sync_interval", str(sync_manager.intervalo_minutos))
            page.client_storage.set("consolidado", sync_manager.modo_consolidado)
            page.client_storage.set("apps_script_url", sync_manager.apps_script_url)
            

            btn_toggle_sync.content = ft.Row([ft.Icon(ft.icons.STOP_ROUNDED, size=24, color=ft.colors.WHITE), ft.Text("DETENER", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)], alignment=ft.MainAxisAlignment.CENTER)
            btn_toggle_sync.style.bgcolor = {ft.ControlState.DEFAULT: ft.colors.ERROR, ft.ControlState.HOVERED: ft.colors.RED_700}
            
            sync_manager.start_sync()
        else:
            # Detener
            sync_manager.stop_sync()
            btn_toggle_sync.content = ft.Row([ft.Icon(ft.icons.HOURGLASS_EMPTY, size=24, color=ft.colors.WHITE), ft.Text("DETENIENDO...", size=18, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)], alignment=ft.MainAxisAlignment.CENTER)
            btn_toggle_sync.disabled = True
        page.update()

    btn_toggle_sync = ft.ElevatedButton(
        content=ft.Row(
            [ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE), ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: ft.colors.CYAN_600, ft.ControlState.HOVERED: ft.colors.CYAN_800},
            color=ft.colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.padding.symmetric(horizontal=20, vertical=15),
        ),
        on_click=toggle_sync,
        width=180
    )

    def on_sync_stopped():
        btn_toggle_sync.content = ft.Row([ft.Icon(ft.icons.PLAY_ARROW_ROUNDED, size=24, color=ft.colors.WHITE), ft.Text("INICIAR", size=16, weight=ft.FontWeight.W_900, color=ft.colors.WHITE)], alignment=ft.MainAxisAlignment.CENTER)
        btn_toggle_sync.style.bgcolor = {ft.ControlState.DEFAULT: ft.colors.CYAN_600, ft.ControlState.HOVERED: ft.colors.CYAN_800}
        btn_toggle_sync.disabled = False
        page.update()
        
    sync_manager.on_stop_callback = on_sync_stopped

    # ==========================================
    # Diseño Premium para Aura Sync
    # ==========================================
    aura_sync_view = ft.Container(
        padding=ft.padding.only(top=10, left=40, right=40, bottom=40),
        expand=True,
        content=ft.Column(
            controls=[
                # Cabecera
                ft.Row(
                    controls=[
                        ft.Icon(ft.icons.CLOUD_SYNC_ROUNDED, size=50, color=ft.colors.CYAN_500),
                        ft.Column([
                            ft.Text("Aura Sync SISMED", size=36, weight=ft.FontWeight.W_900),
                            ft.Text("Sincronización Inteligente de stock del SISMED a Google Sheets", size=16, color=ft.colors.ON_SURFACE_VARIANT)
                        ], spacing=2)
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=20
                ),
                ft.Divider(height=30, color=ft.colors.TRANSPARENT),
                
                # Layout en dos columnas
                ft.ResponsiveRow(
                    controls=[
                        # Panel Izquierdo
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 5, "xl": 4},
                            padding=ft.padding.only(top=38, bottom=40, left=40, right=40),
                            bgcolor=ft.colors.SURFACE_VARIANT,
                            border_radius=20,
                            content=ft.Column(
                                controls=[
                                    ft.Row([ft.Icon(ft.icons.TUNE_ROUNDED, color=ft.colors.CYAN_400), ft.Text("Preferencias del Sistema", size=20, weight=ft.FontWeight.W_800)]),
                                    ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                                    
                                    ft.Container(content=input_sismed_dir, padding=ft.padding.only(top=5, bottom=0)),
                                    ft.Container(content=switch_consolidado, padding=ft.padding.only(bottom=5)),
                                    ft.Container(content=input_intervalo, padding=ft.padding.symmetric(vertical=8)),
                                    ft.Container(content=input_apps_script, padding=ft.padding.symmetric(vertical=8)),
                                    ft.Divider(height=20, color=ft.colors.OUTLINE_VARIANT),
                                    ft.Container(content=chk_auto_sync, padding=ft.padding.only(top=5))
                                ], 
                                spacing=8,
                                horizontal_alignment=ft.CrossAxisAlignment.START,
                            )
                        ),
                        
                        # Panel Derecho
                        ft.Container(
                            col={"sm": 12, "md": 12, "lg": 7, "xl": 8},
                            padding=30,
                            bgcolor=ft.colors.SURFACE_VARIANT,
                            border_radius=20,
                            content=ft.Column([
                                ft.Row(
                                    controls=[
                                        ft.Row([
                                            ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400),
                                            ft.Text("Consola de Actividad", size=18, weight=ft.FontWeight.BOLD)
                                        ]),
                                        btn_toggle_sync
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                                ),
                                ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                                ft.Container(
                                    content=sync_logs,
                                    bgcolor=ft.colors.BACKGROUND,
                                    border_radius=10,
                                    padding=15,
                                    height=350  # Un alto fijo decente para que no colapse en pantallas pequeñas
                                )
                            ])
                        )
                    ],
                    spacing=30
                )
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO, # Añadimos scroll a la vista principal por si colapsa verticalmente
        )
    )

    # Función para cambiar entre tema claro y oscuro
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


    # Configurar FilePickers
    file_picker2 = ft.FilePicker(on_result=on_xlsx_file_picked2)
    file_picker = ft.FilePicker(on_result=on_file_picked)
    save_picker = ft.FilePicker(on_result=on_save_location_picked)
    page.overlay.append(file_picker)
    page.overlay.append(file_picker2)
    page.overlay.append(save_picker)
    page.overlay.append(sismed_dir_picker)

# CONSTRUCCION DE LA PAGINA ----- Agregar elementos a la página

    page.title = "ToolKits OGM"
    page.horizontal_alignment = ft.CrossAxisAlignment.START
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.window.width = 1200
    page.window.height = 800
    
    # Restringir cambiar tamaño de la ventana
    page.window.resizable = False
    page.window.maximizable = False
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
        sync_manager.stop_sync()
        icon.stop()
        page.window.destroy()

    def setup_tray():
        nonlocal tray_icon
        image = create_image()
        menu = pystray.Menu(
            item('Restaurar Ventana', on_show_window, default=True),
            item('Cerrar completamente', on_quit)
        )
        tray_icon = pystray.Icon("toolkit_ogm", image, "ToolKits OGM (Sincronizando)", menu)
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
        menu.extended = not menu.extended
        menu.update()

    # AppBar Superior (Estilo Docker Desktop)
    page.appbar = ft.AppBar(
        leading=ft.IconButton(ft.icons.MENU, on_click=toggle_nav_rail, tooltip="Menú principal"),
        leading_width=50,
        title=ft.Row([
            ft.Icon(ft.icons.LAYERS_ROUNDED, color=ft.colors.CYAN_500, size=24),
            ft.Text("ToolKit OGM", size=18, weight=ft.FontWeight.W_800)
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
    page.window.min_width = 950
    page.window.min_height = 680





#---------------------------------------------------

# Función para actualizar el contenido
    def update_content(index):
        # Limpiar el contenido anterior
        content.controls.clear()
        
        if index == 0:
            def navigate(view_idx):
                # Deseleccionamos todo en el menú lateral porque las opciones 
                # internas no están en el sidebar.
                menu.selected_index = None 
                menu.update()
                update_content(view_idx)
            
            def create_card(title, desc, icon, color, idx):
                return ft.Card(
                    elevation=5,
                    shape=ft.RoundedRectangleBorder(radius=20),
                    content=ft.Container(
                        padding=20,
                        width=250,
                        height=200,
                        ink=True,
                        on_click=lambda e, i=idx: navigate(i),
                        content=ft.Column(
                            controls=[
                                ft.Icon(icon, size=55, color=color),
                                ft.Container(height=5),
                                ft.Text(title, size=20, weight=ft.FontWeight.W_900, text_align=ft.TextAlign.CENTER),
                                ft.Text(desc, size=13, color=ft.colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER
                        )
                    )
                )

            home_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row([
                            ft.Icon(ft.icons.HOME_ROUNDED, size=45, color=ft.colors.BLUE_400),
                            ft.Text("ToolKit OGM Dashboard", size=36, weight=ft.FontWeight.W_900),
                        ], alignment=ft.MainAxisAlignment.START, spacing=15),
                        ft.Text("Seleccione una herramienta para comenzar:", size=18, color=ft.colors.ON_SURFACE_VARIANT),
                        ft.Divider(height=40, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                create_card("Herram. SISMED", "Conversión a Excel y Procesos TFORMDET", ft.icons.DATA_OBJECT_ROUNDED, ft.colors.BLUE_400, 2), # Índice de vista interno 2
                                create_card("Aura Sync", "Sincronizador Automático a Google Sheets", ft.icons.CLOUD_SYNC_ROUNDED, ft.colors.CYAN_500, 3) # Índice de vista interno 3
                            ],
                            wrap=True,
                            spacing=40
                        )
                    ]
                )
            )
            content.controls.append(home_ui)
            
        elif index == 1:
            settings_view = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.icons.SETTINGS_ROUNDED, size=45, color=ft.colors.BLUE_400),
                        ft.Text("Ajustes del Sistema", size=36, weight=ft.FontWeight.W_900),
                    ], alignment=ft.MainAxisAlignment.START, spacing=15),
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
            # Agregar pestañas tabs
            tabs = ft.Tabs(
                tabs=[
                    ft.Tab(
                        text="DBF a Excel",
                        icon=ft.icons.SYNC,
                        content=ft.Column(
                            [
                                ft.Container(height=20),
                                ft.Text(value="Convierte archivos .dbf a excel.", size=20),
                                ft.Row([selected_file, pick_file_button], spacing=10),
                                ft.Row([save_location, change_save_location_button], spacing=10),
                                convert_button,
                                result_label,
                                progress_bar,  # Barra de progreso
                            ],
                            spacing=20  # Espaciado entre elementos de la columna
                        ),
                    ),
                    ft.Tab(
                        text="Format TFORMDET",
                        icon=ft.icons.FORMAT_SHAPES,
                        content=ft.Column(
                            [
                                ft.Container(height=20),  # Espacio vacío entre título y contenido
                                ft.Text(value="Dar formato a archivo excel de Tformdet", size=20),
                                ft.Row([archivo_seleccionado, seleccionar_button], spacing=10),
                                ft.Row([status_text, modificar_button], spacing=10),
                                progress_bar,
                            ],
                            spacing=20  # Espaciado entre elementos de la columna
                        ),
                    ),
                ]
            )          
            #content.controls.append(column_content)  # Agregar el nuevo Column
            content.controls.append(tabs)

        elif index == 3:
            content.controls.append(aura_sync_view)
            
        page.update()  # Actualiza la página

    # Barra de menú lateral (Estilo Colapsable)
    menu = ft.NavigationRail(
        selected_index=0,
        extended=False,  # Inicialmente colapsado
        min_width=70,
        min_extended_width=200,
        label_type=ft.NavigationRailLabelType.NONE, # Oculta texto al colapsar
        on_change=lambda e: update_content(e.control.selected_index),
        destinations=[
            ft.NavigationRailDestination(icon=ft.icons.HOME_OUTLINED, selected_icon=ft.icons.HOME_ROUNDED, padding=5, label="Inicio"),
            ft.NavigationRailDestination(icon=ft.icons.SETTINGS_OUTLINED, selected_icon=ft.icons.SETTINGS_ROUNDED, padding=5, label="Configuración"),
        ]
    )
    # Contenedor de contenido principal inicializando en Inicio
    content = ft.Column([ft.Text(value="")])
    update_content(0)
    
    content_container = ft.Container(content=content, expand=True, padding=ft.padding.only(top=0, right=20, left=20, bottom=20))

    # Estructura de la página
    page.add(
        ft.Row(
            [
                menu,  # Menú lateral colapsable
                ft.VerticalDivider(width=1, color=ft.colors.OUTLINE_VARIANT),  # Divisor visual sutil
                content_container,  # Contenido dinámico expandible acorde al layout
                
            ],
            expand=True,
            spacing=0, # Eliminar espacio extra entre la barra y el contenido
        )
    )

    # Iniciar auto-sync si estaba marcado
    if saved_auto_sync:
        toggle_sync(None)


ft.app(target=main)
