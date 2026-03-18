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
    selected_file = ft.TextField(
        label="Ruta DBF origen...", read_only=True, expand=True,
        border_color=ft.colors.TEAL_400, border_radius=8, content_padding=15, prefix_icon=ft.icons.DATA_OBJECT_ROUNDED
    )
    save_location = ft.TextField(
        label="Ubicación de destino XLSX...", read_only=True, expand=True,
        border_color=ft.colors.TEAL_400, border_radius=8, content_padding=15, prefix_icon=ft.icons.FOLDER_SPECIAL_ROUNDED
    )
    result_label = ft.Text(value="", size=14, color=ft.colors.WHITE, weight=ft.FontWeight.W_600)
    progress_bar = ft.ProgressBar(expand=True, visible=False, color=ft.colors.TEAL_400, bgcolor=ft.colors.WHITE24)
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
        if not selected_file.value:
            result_label.value = "Por favor, selecciona un DBF primero."
            result_label.color = ft.colors.RED_400
            page.update()
            return
            
        def _process():
            nonlocal alert_dialog
            convert_button.disabled = True
            pick_file_button.disabled = True
            change_save_location_button.disabled = True
            result_label.value = "Transformando datos (puede tardar unos segundos)..."
            result_label.color = ft.colors.AMBER_400
            progress_bar.visible = True
            progress_bar.value = None # Spinner indeterminado de rendimiento
            page.update()

            dbf_path = selected_file.value
            xlsx_path = save_location.value

            try:
                # Leer el archivo DBF (optimizado directo a marco de datos)
                table = DBF(dbf_path, encoding="latin1")
                df = pd.DataFrame(iter(table))
                df.to_excel(xlsx_path, index=False, engine="openpyxl")

                result_label.value = "✔ Conversión completada."
                result_label.color = ft.colors.GREEN_400
                progress_bar.value = 1
                page.update()

                alert_dialog = ft.AlertDialog(
                    title=ft.Row([ft.Icon(ft.icons.CHECK_CIRCLE_ROUNDED, color=ft.colors.GREEN_500), ft.Text("Conversión Exitosa", weight=ft.FontWeight.W_900)]),
                    content=ft.Text(f"El archivo XLSX ha sido generado en:\n\n{xlsx_path}", size=13),
                    actions=[ft.ElevatedButton("Entendido", on_click=close_alert)],
                    open=True,
                    shape=ft.RoundedRectangleBorder(radius=16)
                )
                page.overlay.append(alert_dialog)
                
            except PermissionError as err:
                result_label.value = f"Error: Archivo en uso. Ciérralo primero. ({err})"
                result_label.color = ft.colors.RED_400
            except Exception as ex:
                result_label.value = f"Error: {str(ex)}"
                result_label.color = ft.colors.RED_400
            finally:
                progress_bar.visible = False
                convert_button.disabled = False
                pick_file_button.disabled = False
                change_save_location_button.disabled = False
                page.update()
                
        threading.Thread(target=_process, daemon=True).start()

    # Función para cerrar el AlertDialog
    def close_alert(e):
        nonlocal alert_dialog
        if alert_dialog:
            alert_dialog.open = False
            selected_file.value = ""
            save_location.value = ""
            result_label.value = ""
            progress_bar.value = 0
            page.update()

 # Botón para convertir archivo
    convert_button = ft.ElevatedButton(
        content=ft.Row([
            ft.Icon(ft.icons.SAVE_ROUNDED, color=ft.colors.WHITE, size=20),
            ft.Text("CONVERTIR A EXCEL", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=13),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
        style=ft.ButtonStyle(
            bgcolor=ft.colors.TEAL_700,
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
        height=45,
        width=250,
        on_click=convert_file,
    )

    # Botón para seleccionar archivo DBF
    pick_file_button = ft.ElevatedButton(
        content=ft.Row([ft.Icon(ft.icons.FILE_OPEN_ROUNDED, size=18, color=ft.colors.WHITE), ft.Text("Seleccionar DBF", weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)]),
        style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_700, shape=ft.RoundedRectangleBorder(radius=10)),
        height=45,
        on_click=lambda _: file_picker.pick_files(allow_multiple=False, allowed_extensions=["dbf"]),
    )

    # Botón para cambiar ubicación de guardado
    change_save_location_button = ft.ElevatedButton(
        content=ft.Row([ft.Icon(ft.icons.CREATE_NEW_FOLDER_ROUNDED, size=18, color=ft.colors.WHITE), ft.Text("Cambiar Destino", weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)]),
        style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_700, shape=ft.RoundedRectangleBorder(radius=10)),
        height=45,
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
    

# ::::::::::::::::: FIN DE EXCEL ::::::::::::::::::::::::::::::::

# ======================================================================
# AURA REPORTS - Reportes de Guías SISMED
# ======================================================================
    
    # --- Selectores de Fecha (Diseño Pro + Manual) ---
    now = datetime.now()
    first_day = now.replace(day=1)
    
    def on_change_picker_ini(e):
        if e.control.value:
            fecha_ini.value = e.control.value.strftime("%d/%m/%Y")
            fecha_ini.update()

    def on_change_picker_fin(e):
        if e.control.value:
            fecha_fin.value = e.control.value.strftime("%d/%m/%Y")
            fecha_fin.update()

    datepicker_ini = ft.DatePicker(
        on_change=on_change_picker_ini,
        first_date=datetime(2020, 1, 1),
        last_date=datetime(2030, 12, 31),
    )
    datepicker_fin = ft.DatePicker(
        on_change=on_change_picker_fin,
        first_date=datetime(2020, 1, 1),
        last_date=datetime(2030, 12, 31),
    )
    page.overlay.extend([datepicker_ini, datepicker_fin])

    fecha_ini = ft.TextField(
        label="Fecha Inicio", 
        value=first_day.strftime("%d/%m/%Y"), 
        hint_text="DD/MM/AAAA",
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.CALENDAR_MONTH,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
    )
    
    fecha_fin = ft.TextField(
        label="Fecha Fin", 
        value=now.strftime("%d/%m/%Y"), 
        hint_text="DD/MM/AAAA",
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.CALENDAR_MONTH,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
    )

    # ── Botones Toggle Custom (full-width, rectangular, premium) ──
    tipo_selected = {"value": "S"}
    modo_selected = {"value": "det"}

    COLOR_SEL   = ft.colors.BLUE_GREY_700  # Seleccionado: fondo sólido gris oscuro
    COLOR_UNSEL = ft.colors.TRANSPARENT    # No seleccionado: sin fondo

    def _toggle_btn(label, icon_name, key, state_dict, row_ref_list, rebuild_fn):
        is_sel = state_dict["value"] == key
        def _on_tap(e, k=key):
            state_dict["value"] = k
            row_ref_list[0].controls = rebuild_fn()
            row_ref_list[0].update()
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=_on_tap,
            expand=True,
            content=ft.Container(
                expand=True,
                height=48,
                bgcolor=COLOR_SEL if is_sel else COLOR_UNSEL,
                border_radius=6,
                border=ft.border.all(1, ft.colors.BLUE_GREY_600 if is_sel else ft.colors.BLUE_GREY_800),
                padding=ft.padding.symmetric(horizontal=12),
                content=ft.Row([
                    ft.Icon(icon_name, size=17, color=ft.colors.WHITE if is_sel else ft.colors.GREY_500),
                    ft.Text(label, size=12,
                            weight=ft.FontWeight.W_600 if is_sel else ft.FontWeight.NORMAL,
                            color=ft.colors.WHITE if is_sel else ft.colors.GREY_500,
                            expand=True, text_align=ft.TextAlign.CENTER),
                    ft.Icon(ft.icons.CHECK_ROUNDED, size=15,
                            color=ft.colors.WHITE if is_sel else ft.colors.TRANSPARENT),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
        )

    # Tipo de Reporte
    tipo_row_ref = [None]
    def _build_tipo():
        return [
            _toggle_btn("Guías de Salida (S)",  ft.icons.OUTBOX_ROUNDED, "S",   tipo_selected, tipo_row_ref, _build_tipo),
            ft.Container(width=4),
            _toggle_btn("Guías de Ingreso (E)", ft.icons.INBOX_ROUNDED,  "E",   tipo_selected, tipo_row_ref, _build_tipo),
        ]
    tipo_row_widget = ft.Row(controls=_build_tipo(), spacing=0, expand=True)
    tipo_row_ref[0] = tipo_row_widget

    # Modo de Detalle
    modo_row_ref = [None]
    def _build_modo():
        return [
            _toggle_btn("Guías detallado por lotes",  ft.icons.LIST_ALT_ROUNDED,  "det", modo_selected, modo_row_ref, _build_modo),
            ft.Container(width=4),
            _toggle_btn("Reporte guías consolidado", ft.icons.SUMMARIZE_ROUNDED, "con", modo_selected, modo_row_ref, _build_modo),
        ]
    modo_row_widget = ft.Row(controls=_build_modo(), spacing=0, expand=True)
    modo_row_ref[0] = modo_row_widget

    # Objeto proxy para compatibilidad con run_report_gen que lee .selected
    class _FakeSeg:
        def __init__(self, s): self._s = s
        @property
        def selected(self): return {self._s["value"]}
    tipo_reporte = _FakeSeg(tipo_selected)
    modo_detalle = _FakeSeg(modo_selected)

    chk_omitir_anulados = ft.Checkbox(label="Omitir guías anuladas", value=True, label_style=ft.TextStyle(size=12))

    def on_report_dir_picked(e: ft.FilePickerResultEvent):
        if e.path:
            input_report_sismed_dir.value = e.path
            # Guardamos para que el sincronizador también lo sepa si desea
            page.client_storage.set("sismed_dir", e.path)
            input_report_sismed_dir.update()

    report_dir_picker = ft.FilePicker(on_result=on_report_dir_picked)
    page.overlay.append(report_dir_picker)

    input_report_sismed_dir = ft.TextField(
        label="Ubicación SISMED actual",
        value=page.client_storage.get("sismed_dir") or "C:\\SISMEDV2",
        expand=True,
        dense=False,
        text_size=15,
        text_align=ft.TextAlign.LEFT,
        prefix_icon=ft.icons.FOLDER,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        content_padding=11,  # Padding uniforme para forzar centrado vertical real
        suffix=ft.IconButton(icon=ft.icons.SEARCH_ROUNDED, on_click=lambda _: report_dir_picker.get_directory_path(), icon_size=18),
    )

    report_log = ft.ListView(expand=True, spacing=5, height=200)

    def log_report(msg):
        report_log.controls.append(ft.Text(f"• {msg}", size=13))
        if len(report_log.controls) > 50: report_log.controls.pop(0)
        page.update()

    def run_report_gen(output_path):
        try:
            d_start = datetime.strptime(fecha_ini.value, "%d/%m/%Y")
            d_end = datetime.strptime(fecha_fin.value, "%d/%m/%Y")
            
            # Validación de Cronología
            if d_start > d_end:
                log_report("❌ Error: La Fecha Inicio no puede ser posterior a la Fecha Fin.")
                page.snack_bar = ft.SnackBar(ft.Text("⚠️ Revisa el rango de fechas."), bgcolor=ft.colors.AMBER_800)
                page.snack_bar.open = True
                page.update()
                return

            t_mov = list(tipo_reporte.selected)[0]
            is_det = "det" in modo_detalle.selected
            omit_anul = chk_omitir_anulados.value
            
            # Obtener el directorio SISMED del input actual
            s_dir = input_report_sismed_dir.value.strip()
            
            mgr = GuiaReportManager(s_dir, log_callback=log_report)
            report_log.controls.clear()
            
            success = mgr.generate_report(d_start, d_end, t_mov, is_det, output_path, exclude_annulled=omit_anul)
            
            if success:
                sismed_banner = """
  ____ ___ ____  __  __ _____ ____  
 / ___|_ _/ ___||  \/  | ____|  _ \\ 
 \\___ \\| |\\___ \\| |\\/| |  _| | | | |
  ___) | | ___) | |  | | |___| |_| |
 |____/___|____/|_|  |_|_____|____/ 
                """
                report_log.controls.append(
                    ft.Text(
                        sismed_banner,
                        size=10,
                        font_family="Consolas",
                        color=ft.colors.GREEN_400,
                        weight=ft.FontWeight.W_500
                    )
                )
                page.snack_bar = ft.SnackBar(ft.Text(f"✅ Reporte guardado en: {output_path}"))
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(ft.Text("❌ Hubo un error al generar el reporte."))
                page.snack_bar.open = True
        except ValueError:
            log_report("❌ Error: Formato de fecha inválido. Use DD/MM/AAAA")
        except Exception as ex:
            log_report(f"❌ Error crítico: {str(ex)}")
        page.update()

    def on_report_save_result(e: ft.FilePickerResultEvent):
        if e.path:
            # Asegurar que el archivo siempre tenga la extensión .xlsx
            report_path = e.path if e.path.lower().endswith(".xlsx") else f"{e.path}.xlsx"
            run_report_gen(report_path)

    report_save_picker = ft.FilePicker(on_result=on_report_save_result)
    page.overlay.append(report_save_picker)

    report_view = ft.Container(
        padding=ft.padding.all(20), expand=True,
        content=ft.Column(expand=True, controls=[
            # Cabecera
            ft.Row([
                ft.Row([
                    ft.Icon(ft.icons.BAR_CHART_ROUNDED, size=38, color=ft.colors.ORANGE_400),
                    ft.Column([
                        ft.Text("Reporte de Guías", size=28, weight=ft.FontWeight.W_900),
                        ft.Text("Generador de Reportes de Guías SISMED (Ingresos/Salidas)", color=ft.colors.ON_SURFACE_VARIANT, size=12)
                    ], spacing=0)
                ], spacing=15),
                ft.Container(expand=True),
                ft.ElevatedButton(
                    content=ft.Row([ft.Icon(ft.icons.ARROW_BACK_ROUNDED, size=18), ft.Text("Volver a Reports SISMED", weight=ft.FontWeight.BOLD)]),
                    style=ft.ButtonStyle(bgcolor=ft.colors.SURFACE_VARIANT, color=ft.colors.ON_SURFACE_VARIANT),
                    on_click=lambda _: [update_sidebar_ui(4), update_content(4)]
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=8, color=ft.colors.TRANSPARENT),

            # Cuerpo: Dos Columnas (izquierda filtros + derecha estado)
            ft.Row([
                # ── COLUMNA IZQUIERDA: Filtros (ancho fijo como en la referencia) ──
                ft.Container(
                    bgcolor=ft.colors.BLUE_GREY_900,
                    padding=ft.padding.only(top=35, bottom=35, left=30, right=30),
                    border_radius=16,
                    width=500,   # Ancho fijo como en la imagen referencia
                    content=ft.Column([

                        # Ubicación SISMED
                        input_report_sismed_dir,

                        ft.Container(height=2),

                        # Fechas con flecha central
                        ft.Row([
                            fecha_ini,
                            ft.Text("→", size=16, color=ft.colors.GREY_500),
                            fecha_fin,
                        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True),

                        ft.Container(height=2),

                        # Tipo
                        ft.Text("Tipo de movimiento:", size=12, color=ft.colors.GREY_400),
                        tipo_row_widget,

                        ft.Container(height=8),

                        # Modo
                        ft.Text("Modo de reporte:", size=12, color=ft.colors.GREY_400),
                        modo_row_widget,

                        ft.Container(height=5),

                        # Checkbox barra (alineado a la derecha)
                        ft.Row([
                            chk_omitir_anulados
                        ], alignment=ft.MainAxisAlignment.END),

                        ft.Container(height=12),

                        # Botón Generar (Elegante y Centrado)
                        ft.Row([
                            ft.ElevatedButton(
                                content=ft.Row([
                                    ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ft.colors.WHITE, size=20),
                                    ft.Text("GENERAR REPORTE EN EXCEL", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=13),
                                ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                                style=ft.ButtonStyle(
                                    bgcolor=ft.colors.GREEN_700,
                                    color=ft.colors.WHITE,
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                    elevation=4,
                                ),
                                height=55,
                                width=350,
                                on_click=lambda _: report_save_picker.save_file(
                                    file_name=(
                                        f"Reporte_Guias_de_{'Salida' if tipo_selected['value'] == 'S' else 'Ingreso'}_"
                                        f"{'por_Lote' if modo_selected['value'] == 'det' else 'consolidado'}_"
                                        f"{datetime.now().strftime('%Y%m%d')}.xlsx"
                                    ),
                                    allowed_extensions=["xlsx"]
                                )
                            )
                        ], alignment=ft.MainAxisAlignment.CENTER),

                    ], spacing=4, tight=True)
                ),

                # ── COLUMNA DERECHA: Estado del Proceso (ocupa el resto) ──
                ft.Container(
                    bgcolor=ft.colors.BLACK,
                    padding=ft.padding.all(22),
                    border_radius=20,
                    expand=True,   # Llena todo el espacio restante
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.GREEN_400, size=22),
                            ft.Text("Estado del Proceso", color=ft.colors.WHITE, size=18, weight=ft.FontWeight.BOLD)
                        ], spacing=8),
                        ft.Divider(color=ft.colors.GREY_900, height=20),
                        report_log
                    ], spacing=4, expand=True)
                )

            ], spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

        ])
    )
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
                            ft.Text("Sync SISMED", size=36, weight=ft.FontWeight.W_900),
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
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 5},
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
                            col={"sm": 12, "md": 12, "lg": 6, "xl": 7},
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
        )
    )

    # ==========================================
    # MÓDULO: CONSULTA TFORMDET
    # ==========================================
    
    tformdet_log = ft.ListView(height=310, spacing=5, auto_scroll=True)
    
    def on_tformdet_log(msg):
        tformdet_log.controls.append(ft.Text(msg, size=13, font_family="Consolas", color=ft.colors.GREEN_400))
        page.update()

    tformdet_mgr = TformdetManager("", log_callback=on_tformdet_log)

    def on_tformdet_dir_picked(e: ft.FilePickerResultEvent):
        if e.path:
            input_sismed_dir_tf.value = e.path
            input_sismed_dir_tf.update()

    tformdet_dir_picker = ft.FilePicker(on_result=on_tformdet_dir_picked)
    
    def run_tformdet_query(e):
        if not input_sismed_dir_tf.value:
            page.snack_bar = ft.SnackBar(ft.Text("❌ Por favor, selecciona la ruta del SISMED."), bgcolor=ft.colors.RED_700)
            page.snack_bar.open = True
            page.update()
            return
            
        periodo_ini = f"{input_anio_ini_tf.value}{dropdown_mes_ini_tf.value}"
        
        if checkbox_mas_periodos.value:
            periodo_fin = f"{input_anio_fin_tf.value}{dropdown_mes_fin_tf.value}"
            if periodo_ini > periodo_fin:
                page.snack_bar = ft.SnackBar(ft.Text("❌ El Periodo Inicial no puede ser mayor al Periodo Final.", color=ft.colors.WHITE), bgcolor=ft.colors.RED_700)
                page.snack_bar.open = True
                page.update()
                return
            file_name_out = f"TFORMDET_Consulta_{periodo_ini}_al_{periodo_fin}.xlsx"
        else:
            periodo_fin = periodo_ini
            file_name_out = f"TFORMDET_Consulta_{periodo_ini}.xlsx"

        tformdet_mgr.sismed_dir = input_sismed_dir_tf.value
        tformdet_log.controls.clear()

        tformdet_save_picker.save_file(
            dialog_title="Guardar archivo de Consulta TFORMDET",
            file_name=file_name_out,
            allowed_extensions=["xlsx"]
        )

    def on_tformdet_save_picked(e: ft.FilePickerResultEvent):
        if e.path:
            periodo_ini = f"{input_anio_ini_tf.value}{dropdown_mes_ini_tf.value}"
            periodo_fin = f"{input_anio_fin_tf.value}{dropdown_mes_fin_tf.value}" if checkbox_mas_periodos.value else periodo_ini
            
            def process():
                btn_run_tformdet.disabled = True
                btn_run_tformdet.update()
                
                success = tformdet_mgr.generate_report(
                    periodo_ini, 
                    periodo_fin, 
                    e.path, 
                    incluir_formulas=checkbox_formulas_tformdet.value
                )
                
                if success:
                    page.snack_bar = ft.SnackBar(ft.Text("✅ Consulta exitosa! Archivo guardado.", color=ft.colors.WHITE), bgcolor=ft.colors.GREEN_700)
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("⚠️ No se generó el archivo o no hubo resultados.", color=ft.colors.WHITE), bgcolor=ft.colors.ORANGE_700)
                    
                page.snack_bar.open = True
                btn_run_tformdet.disabled = False
                btn_run_tformdet.update()
                page.update()

            threading.Thread(target=process, daemon=True).start()

    tformdet_save_picker = ft.FilePicker(on_result=on_tformdet_save_picked)

    # Componentes UI TFORMDET
    input_sismed_dir_tf = ft.TextField(
        label="Ruta carpeta SISMED", 
        value=saved_sismed_dir if saved_sismed_dir else "",
        hint_text="Ej: C:\\SISMED", 
        expand=True, 
        dense=True,
        read_only=True,
        prefix_icon=ft.icons.FOLDER,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        suffix=ft.IconButton(icon=ft.icons.SEARCH_ROUNDED, on_click=lambda _: tformdet_dir_picker.get_directory_path(), icon_size=18),
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8)
    )

    meses_opciones = [
        ("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"), ("04", "Abril"),
        ("05", "Mayo"), ("06", "Junio"), ("07", "Julio"), ("08", "Agosto"),
        ("09", "Septiembre"), ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre")
    ]
    
    dropdown_mes_ini_tf = ft.Dropdown(
        label="Mes Inicio",
        options=[ft.dropdown.Option(k, f"{k} - {v}") for k, v in meses_opciones],
        value=now.strftime("%m"),
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.CALENDAR_MONTH,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
    )
    
    input_anio_ini_tf = ft.TextField(
        label="Año Inicio",
        value=now.strftime("%Y"),
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
    )

    

    dropdown_mes_fin_tf = ft.Dropdown(
        label="Mes Fin",
        options=[ft.dropdown.Option(k, f"{k} - {v}") for k, v in meses_opciones],
        value=now.strftime("%m"),
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.CALENDAR_MONTH,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        visible=False
    )
    
    input_anio_fin_tf = ft.TextField(
        label="Año Fin",
        value=now.strftime("%Y"),
        expand=1,
        dense=True,
        border_radius=4,
        border_color=ft.colors.WHITE38,
        focused_border_color=ft.colors.WHITE,
        text_size=15,
        prefix_icon=ft.icons.DATE_RANGE_ROUNDED,
        content_padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
        visible=False
    )
    
    def on_multi_periodo_change(e):
        show = checkbox_mas_periodos.value
        dropdown_mes_fin_tf.visible = show
        input_anio_fin_tf.visible = show
        
        # El nuevo checkbox de fórmulas solo se muestra si NO hay rango
        if show:
            checkbox_formulas_tformdet.value = False
            checkbox_formulas_tformdet.visible = False
        else:
            checkbox_formulas_tformdet.visible = True
            
        dropdown_mes_fin_tf.update()
        input_anio_fin_tf.update()
        checkbox_formulas_tformdet.update()

    checkbox_mas_periodos = ft.Checkbox(
        label="Incluir rango de periodos",
        value=False,
        on_change=on_multi_periodo_change
    )

    checkbox_formulas_tformdet = ft.Checkbox(
        label="AÑADIR COLUMNAS Y FÓRMULAS DE CÓDIGO ÚNICO",
        value=False,
        visible=True
    )

    btn_run_tformdet = ft.ElevatedButton(
        content=ft.Row([
            ft.Icon(ft.icons.DOWNLOAD_ROUNDED, color=ft.colors.WHITE, size=20),
            ft.Text("CONSULTAR Y DESCARGAR EXCEL", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=13),
        ], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(
            bgcolor=ft.colors.BLUE_700,
            color=ft.colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=4),
            padding=ft.padding.all(15)
        ),
        on_click=run_tformdet_query,
        height=50
    )

    tformdet_view = ft.Container(
        padding=40,
        expand=True,
        content=ft.Column([
            ft.Row([
                ft.Row([
                    ft.Icon(ft.icons.SEARCH_ROUNDED, size=38, color=ft.colors.BLUE_400),
                    ft.Column([
                        ft.Text("Consulta TFORMDET Avanzada", size=24, weight=ft.FontWeight.W_900),
                        ft.Text("Consulta detallada de movimientos SISMED", color=ft.colors.ON_SURFACE_VARIANT, size=12)
                    ], spacing=2)
                ], spacing=15),
                ft.Container(expand=True),
                ft.ElevatedButton(
                    content=ft.Row([ft.Icon(ft.icons.ARROW_BACK_ROUNDED, size=18), ft.Text("Volver a Reports SISMED", weight=ft.FontWeight.BOLD)]),
                    style=ft.ButtonStyle(bgcolor=ft.colors.SURFACE_VARIANT, color=ft.colors.ON_SURFACE_VARIANT),
                    on_click=lambda _: [update_sidebar_ui(4), update_content(4)]
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=8, color=ft.colors.TRANSPARENT),

            ft.Row([
                ft.Container(
                    expand=7,
                    bgcolor=ft.colors.BLUE_GREY_900,
                    border_radius=12,
                    padding=20,
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.icons.SETTINGS_ROUNDED, color=ft.colors.BLUE_400, size=24),
                            ft.Text("Configuración de Consulta", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                        ], spacing=10),
                        ft.Divider(color=ft.colors.WHITE24, height=15),
                        
                        ft.Row([input_sismed_dir_tf]),
                        ft.Row([
                            checkbox_mas_periodos
                        ]),
                        ft.Row([
                            dropdown_mes_ini_tf,
                            input_anio_ini_tf
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([
                            dropdown_mes_fin_tf,
                            input_anio_fin_tf
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([
                            checkbox_formulas_tformdet
                        ]),
                        
                        ft.Container(height=5),
                        ft.Row([btn_run_tformdet], alignment=ft.MainAxisAlignment.CENTER)
                    ], spacing=15)
                ),

                ft.Container(
                    expand=5,
                    bgcolor=ft.colors.BLACK,
                    border_radius=12,
                    padding=20,
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.icons.TERMINAL_ROUNDED, color=ft.colors.BLUE_400, size=22),
                            ft.Text("Consola de Consulta", color=ft.colors.WHITE, size=18, weight=ft.FontWeight.BOLD)
                        ], spacing=10),
                        ft.Divider(color=ft.colors.GREY_900, height=20),
                        tformdet_log
                    ], spacing=10)
                )
            ], spacing=20, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START)
        ])
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


    # Configurar FilePickers
    file_picker2 = ft.FilePicker(on_result=on_xlsx_file_picked2)
    file_picker = ft.FilePicker(on_result=on_file_picked)
    save_picker = ft.FilePicker(on_result=on_save_location_picked)
    page.overlay.append(file_picker)
    page.overlay.append(file_picker2)
    page.overlay.append(save_picker)
    page.overlay.append(sismed_dir_picker)
    page.overlay.append(tformdet_dir_picker)
    page.overlay.append(tformdet_save_picker)

# CONSTRUCCION DE LA PAGINA ----- Agregar elementos a la página

    page.title = "ToolKits OGM"
    page.horizontal_alignment = ft.CrossAxisAlignment.START
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.window.width = 1200
    page.window.height = 800
    page.padding = 0 # Eliminar márgenes de la ventana para que el menú pegue a los bordes
    page.spacing = 0 # Sin espacios automáticos entre elementos raíz
    
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
    page.window.min_width = 1290
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

        if index == 0:
            home_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row([
                            ft.Icon(ft.icons.HOME_ROUNDED, size=45, color=ft.colors.BLUE_400),
                            ft.Text("ToolKit SISMED Dashboard", size=36, weight=ft.FontWeight.W_900),
                        ], alignment=ft.MainAxisAlignment.START, spacing=15),
                        ft.Text("Seleccione una herramienta para comenzar:", size=18, color=ft.colors.ON_SURFACE_VARIANT),
                        ft.Divider(height=40, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                create_card("Consul. TFORMDET", "Consulta detallada de movimientos SISMED", ft.icons.SEARCH_ROUNDED, ft.colors.BLUE_400, 5),
                                create_card("Reporte Guías", "Reportes de Guías SISMED por Fecha e Item", ft.icons.FACT_CHECK_ROUNDED, ft.colors.AMBER_400, 8),
                                create_card("DBF a EXCEL", "Convierte archivos .dbf a formato Excel", ft.icons.SYNC, ft.colors.TEAL_400, 6),
                                create_card("Format TFORMDET", "Dar formato a archivo excel de Tformdet", ft.icons.FORMAT_SHAPES, ft.colors.INDIGO_400, 7),
                                create_card("Sync SISMED", "Sincronizador Automático a Google Sheets", ft.icons.CLOUD_SYNC_ROUNDED, ft.colors.CYAN_500, 3)
                            ],
                            wrap=True,
                            spacing=15,
                            run_spacing=15
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
            herramientas_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row([
                            ft.Icon(ft.icons.HOME_REPAIR_SERVICE_ROUNDED, size=45, color=ft.colors.BLUE_400),
                            ft.Text("Herramientas SISMED", size=36, weight=ft.FontWeight.W_900),
                        ], alignment=ft.MainAxisAlignment.START, spacing=15),
                        ft.Text("Seleccione una sub-herramienta para trabajar:", size=18, color=ft.colors.ON_SURFACE_VARIANT),
                        ft.Divider(height=40, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                create_card("DBF a EXCEL", "Convierte archivos .dbf a formato Excel", ft.icons.SYNC, ft.colors.TEAL_400, 6),
                                create_card("Format TFORMDET", "Dar formato a archivo excel de Tformdet", ft.icons.FORMAT_SHAPES, ft.colors.INDIGO_400, 7)
                            ],
                            wrap=True,
                            spacing=15,
                            run_spacing=15
                        )
                    ]
                )
            )
            content.controls.append(herramientas_ui)

        elif index == 3:
            content.controls.append(aura_sync_view)
        
        elif index == 4:
            # Nuevo Dashboard de Reports SISMED
            reports_ui = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row([
                            ft.Icon(ft.icons.BAR_CHART_ROUNDED, size=45, color=ft.colors.ORANGE_400),
                            ft.Text("Reports SISMED", size=36, weight=ft.FontWeight.W_900),
                        ], alignment=ft.MainAxisAlignment.START, spacing=15),
                        ft.Text("Seleccione un reporte para visualizar:", size=18, color=ft.colors.ON_SURFACE_VARIANT),
                        ft.Divider(height=40, color=ft.colors.TRANSPARENT),
                        ft.Row(
                            controls=[
                                create_card("Consul. TFORMDET", "Consulta detallada de movimientos SISMED", ft.icons.SEARCH_ROUNDED, ft.colors.BLUE_400, 5),
                                create_card("Reporte Guías", "Reportes de Guías SISMED por Fecha e Item", ft.icons.FACT_CHECK_ROUNDED, ft.colors.AMBER_400, 8)
                            ],
                            wrap=True,
                            spacing=15,
                            run_spacing=15
                        )
                    ]
                )
            )
            content.controls.append(reports_ui)
            
        elif index == 5:
            content.controls.append(tformdet_view)
            
        elif index == 8:
            content.controls.append(report_view)
            
        elif index == 6:
            # DBF a Excel View
            dbf_view = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    [
                        # Cabecera
                        ft.Row([
                            ft.Row([
                                ft.Icon(ft.icons.SYNC_ROUNDED, size=38, color=ft.colors.TEAL_400),
                                ft.Column([
                                    ft.Text("Convertidor DBF a Excel", size=24, weight=ft.FontWeight.W_900),
                                    ft.Text("Transformación rápida de datos estructurados", size=12, color=ft.colors.ON_SURFACE_VARIANT)
                                ], spacing=2)
                            ], spacing=15),
                            ft.Container(expand=True),
                            ft.ElevatedButton(
                                content=ft.Row([ft.Icon(ft.icons.ARROW_BACK_ROUNDED, size=18), ft.Text("Volver a Herramientas", weight=ft.FontWeight.BOLD)]),
                                style=ft.ButtonStyle(bgcolor=ft.colors.SURFACE_VARIANT, color=ft.colors.ON_SURFACE_VARIANT),
                                on_click=lambda _: [update_sidebar_ui(2), update_content(2)]
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=10, color=ft.colors.TRANSPARENT),

                        # Panel central tipo tarjeta centrado horizontalmente
                        ft.Row([
                            ft.Container(
                                bgcolor=ft.colors.BLUE_GREY_900,
                                padding=ft.padding.only(top=35, bottom=35, left=40, right=40),
                                border_radius=16,
                                width=800, # Un ancho suficiente para no agobiar los imputs
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.icons.SETTINGS_ROUNDED, color=ft.colors.TEAL_400, size=24),
                                        ft.Text("Parámetros de Conversión", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                                    ], spacing=10),
                                    ft.Divider(color=ft.colors.WHITE24, height=15),
                                    
                                    ft.Text("Archivo DBF a procesar:", size=13, color=ft.colors.GREY_400),
                                    ft.Row([selected_file, pick_file_button], spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                    
                                    ft.Container(height=10),
                                    
                                    ft.Text("Ruta de salida del archivo Excel (.xlsx):", size=13, color=ft.colors.GREY_400),
                                    ft.Row([save_location, change_save_location_button], spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                    
                                    ft.Container(height=40),
                                    
                                    # Barra de progreso y resultados flotantes
                                    progress_bar,
                                    ft.Container(height=5),
                                    
                                    ft.Row([
                                        result_label,
                                        convert_button
                                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                                    
                                ])
                            )
                        ], alignment=ft.MainAxisAlignment.CENTER)
                    ],
                    spacing=10
                )
            )
            content.controls.append(dbf_view)
            
        elif index == 7:
            # Format TFORMDET View
            formattf_view = ft.Container(
                padding=40,
                expand=True,
                content=ft.Column(
                    [
                        ft.Row([
                            ft.Icon(ft.icons.FORMAT_SHAPES, size=38, color=ft.colors.INDIGO_400),
                            ft.Text("Format TFORMDET Excel", size=24, weight=ft.FontWeight.W_900),
                        ], alignment=ft.MainAxisAlignment.START, spacing=15),
                        ft.Divider(height=20, color=ft.colors.TRANSPARENT),
                        ft.Row([
                            ft.IconButton(icon=ft.icons.ARROW_BACK_ROUNDED, on_click=lambda _: navigate(2), tooltip="Volver a Herramientas"),
                            ft.Text("Volver", size=16, color=ft.colors.ON_SURFACE_VARIANT)
                        ]),
                        ft.Container(height=10),
                        ft.Text(value="Dar formato a archivo excel de Tformdet", size=20),
                        ft.Row([archivo_seleccionado, seleccionar_button], spacing=10),
                        ft.Row([status_text, modificar_button], spacing=10),
                        progress_bar,
                    ],
                    spacing=20  # Espaciado entre elementos de la columna
                )
            )
            content.controls.append(formattf_view)
            
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

    # Iniciar auto-sync si estaba marcado
    if saved_auto_sync:
        toggle_sync(None)


ft.app(target=main)
