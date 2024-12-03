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

    # Función para cambiar entre tema claro y oscuro
    def theme_changed(e):
        page.theme_mode = (
            ft.ThemeMode.DARK
            if page.theme_mode == ft.ThemeMode.LIGHT
            else ft.ThemeMode.LIGHT
        )
        cambia_modo.label = (
            "Claro" if page.theme_mode == ft.ThemeMode.LIGHT else "Oscuro"
        )
        page.update()
    cambia_modo = ft.Switch(label="Claro", on_change=theme_changed)
    page.theme_mode = ft.ThemeMode.DARK


    # Configurar FilePickers
    file_picker2 = ft.FilePicker(on_result=on_xlsx_file_picked2)
    file_picker = ft.FilePicker(on_result=on_file_picked)
    save_picker = ft.FilePicker(on_result=on_save_location_picked)
    page.overlay.append(file_picker)
    page.overlay.append(file_picker2)
    page.overlay.append(save_picker)

# CONSTRUCCION DE LA PAGINA ----- Agregar elementos a la página

    page.title = "ToolKits OGM - By: Ing. Jordan Chacon Villacis"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START





#---------------------------------------------------

# Función para actualizar el contenido
    def update_content(index):
        # Limpiar el contenido anterior
        content.controls.clear()
        
        if index == 0:
            content.controls.append(ft.Text(value="Bienvenido a la página de Inicio.", size=20))
            
        elif index == 1:
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
 
        elif index == 2:
            content.controls.append(ft.Text(value="Página de Configuración: ajusta tus preferencias aquí.", size=20)) 
        page.update()  # Actualiza la página

    # Barra de menú lateral
    menu = ft.NavigationRail(
        selected_index=0,  # Inicialmente, el primer ítem está seleccionado
        label_type=ft.NavigationRailLabelType.ALL,
        on_change=lambda e: update_content(e.control.selected_index),
        destinations=[
            ft.NavigationRailDestination(icon=ft.icons.HOME, padding=5, label="Inicio"),
            ft.NavigationRailDestination(icon=ft.icons.SETTINGS_SUGGEST_ROUNDED, padding=5, label="Config ICI"),
            ft.NavigationRailDestination(icon=ft.icons.SETTINGS,padding=5, label="Configuración"),
            ],

        # Coloca el botón de alternar tema en la parte inferior del menú
        trailing=ft.Column(
            [
                ft.Row([cambia_modo], alignment=ft.MainAxisAlignment.CENTER),  # Coloca el botón en la parte inferior
            ],
            alignment=ft.MainAxisAlignment.END,  # Alinea el contenido al final
            height=420,  # Puedes ajustar la altura para tener más espacio abajo
        ),
    )
    

    # Contenedor de contenido principal
    content = ft.Column([ft.Text(value="Bienvenido a la página de Inicio.", size=20)])

    # Estructura de la página
    page.add(
        ft.Row(
            [
                menu,  # Menú lateral
                ft.VerticalDivider(),  # Divisor visual
                ft.Container(content=content, expand=True, padding=20),  # Contenido dinámico
                
            ],
            expand=True,
        )
    )

#---------------------------------------------
    

    # page.add(
    #     ft.Column(
    #         [
    #             ft.Row([theme_toggle_button], alignment=ft.MainAxisAlignment.END),  # Coloca el botón en la parte superior derecha
    #             ft.Row([selected_file, pick_file_button], spacing=10),
    #             ft.Row([save_location, change_save_location_button], spacing=10),
    #             convert_button,
    #             result_label,
    #             progress_bar,  # Agregar barra de progreso a la página
    #         ],
    #         spacing=20,
    #         alignment=ft.MainAxisAlignment.CENTER,
    #     ),
    # )
# Ejecutar la aplicación
ft.app(target=main)
