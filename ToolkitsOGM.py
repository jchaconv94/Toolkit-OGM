import flet as ft
import os
import pandas as pd
from dbfread import DBF
from datetime import datetime
import time  # Importa time para simular el progreso de la barra
from openpyxl import load_workbook


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
            result_label.color = ft.colors.YELLOW  # Puedes usar otro color si lo prefieres
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
            page.dialog = alert_dialog
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

#:::::::::::::::FIN CONVERTIR DBF A EXCEL::::::::::::::::::::::::::::::::
    
#::::::::::::EXCEL Función: Selección de archivo XLXS:::::::::::::::
    # Variables de la interfaz
    archivo_seleccionado = ft.TextField(label="Archivo seleccionado", read_only=True)
    status_text = ft.Text(value="Selecciona un archivo Excel para comenzar", size=16)


    # Función para manejar la selección del archivo
    def file_selected(e: ft.FilePickerResultEvent):
        if file_picker2.result and file_picker2.result.files:
            archivo_seleccionado.value = file_picker2.result.files[0].path
            status_text.value = f"Archivo seleccionado: {archivo_seleccionado.value}"
        else:
            status_text.value = "No se seleccionó ningún archivo."
        page.update()

    # Función para modificar el archivo
    def modificar_archivo(e):
        if not archivo_seleccionado.value:
            status_text.value = "Por favor, selecciona un archivo primero."
            page.update()
            return

        try:
            # Cargar el archivo seleccionado
            archivo = archivo_seleccionado.value
            workbook = load_workbook(archivo)
            sheet = workbook.active

            # Ejemplo: Eliminar columna D
            sheet.delete_cols(4)

            # Guardar cambios en un nuevo archivo
            nuevo_archivo = archivo.replace(".xlsx", "_modificado.xlsx")
            workbook.save(nuevo_archivo)

            status_text.value = f"Archivo modificado guardado como: {nuevo_archivo}"
        except Exception as ex:
            status_text.value = f"Error al modificar el archivo: {ex}"

        page.update()

        # Crear y mostrar el AlertDialog
        alert_dialog = ft.AlertDialog(
            title=ft.Text("¡Conversión Exitosa!"),
            content=ft.Text(f"El archivo se ha guardado en {nuevo_archivo}."),
            actions=[ft.ElevatedButton("Aceptar", on_click=close_alert2)],
            open=True,
        )
        page.dialog = alert_dialog
        page.update()


    #para manejar las validaciones
    def on_xlsx_file_picked2(e):
        if e.files:
            file_path = e.files[0].path
            if not file_path.lower().endswith(".xlsx"):
                archivo_seleccionado.value = ""
                status_text.value = "Por favor, selecciona un archivo con extensión .xlsx."
            else:
                archivo_seleccionado.value = file_path
                status_text.value = f"Archivo seleccionado: {file_path}"
        else:
            archivo_seleccionado.value = "No se seleccionó ningún archivo."
        page.update()


    # Elementos para modificar un archivo de excel
    seleccionar_button = ft.ElevatedButton(
    "Seleccionar archivo",
    on_click=lambda _: file_picker2.pick_files(allow_multiple=False, allowed_extensions=["xlsx"]),
    )
    modificar_button = ft.ElevatedButton("Modificar archivo", on_click=modificar_archivo)

        # Función para cerrar el AlertDialog
    def close_alert2(e):
        nonlocal alert_dialog  # Asegúrate de usar la variable global
        if alert_dialog:
            alert_dialog.open = False  # Cerrar el diálogo
                # Resetear campos
            archivo_seleccionado.value = ""
            status_text.value =""
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

    page.title = "ToolKits SISMED - By: Ing. Jordan Chacon Villacis"
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
                        icon=ft.icons.SETTINGS,
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
                        text="Config TFORMDET",
                        content=ft.Column(
                            [
                                ft.Container(height=20),  # Espacio vacío entre título y contenido
                                ft.Text(value="Dar formato a archivo excel de Tformdet", size=20),
                                ft.Row([seleccionar_button, modificar_button], spacing=10),
                                archivo_seleccionado,
                                status_text,
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
            ft.NavigationRailDestination(icon=ft.icons.LOOP, padding=5, label=".DBF A .XLSX"),
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
