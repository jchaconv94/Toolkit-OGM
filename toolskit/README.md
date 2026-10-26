# ToolKit SISMED OGM

Herramienta interna para la gestión, reportes y sincronización de datos de la plataforma SISMED.

## 🚀 Requisitos e Instalación

Para levantar este proyecto en una máquina nueva, sigue estos pasos:

### 0. Requisitos del Sistema
- **Python 3.13.x** (Recomendado para asegurar compatibilidad total).

### 1. Clonar el repositorio
```bash
git clone https://github.com/jchaconv94/Toolkit-OGM.git
cd Toolkit-OGM/toolskit
```

### 2. Crear un entorno virtual (Recomendado)
```bash
python -m venv .venv
# Activar en Windows
.venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Ejecutar la aplicación
```bash
python main.py
```

## 📦 Build e Instalador para Windows

El repositorio incluye una ruta de empaquetado para generar un `.exe` con PyInstaller y un instalador con Inno Setup.

### 1. Preparar entorno de build
```powershell
cd Toolkit-OGM
.venv\Scripts\activate
pip install -r toolskit\requirements.txt
pip install pyinstaller
```

### 2. Generar ejecutable e instalador
```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1
```

La version de release se toma del archivo `VERSION` en la raiz del repositorio.

### 3. Salidas esperadas
- Ejecutable: `dist\ToolkitOGM\ToolkitOGM.exe`
- Instalador: `dist\installer\ToolkitOGM-Setup-<version>.exe`
- Huella de seguridad: `dist\installer\ToolkitOGM-Setup-<version>.exe.sha256`

## Actualizaciones automaticas

La aplicacion consulta las Releases publicas de `jchaconv94/ToolkitSISMED` y busca
archivos con el nombre exacto `ToolkitOGM-Setup-<version>.exe`. Las Releases de la
aplicacion web que no contengan ese archivo son ignoradas.

Para publicar una actualizacion:

1. Generar el instalador con `packaging\windows\build_windows.ps1`.
2. Crear una Release publica con una version superior a la instalada.
3. Adjuntar el `.exe` y el `.exe.sha256` generados, conservando sus nombres.
4. Publicar la Release. Las instalaciones comprobaran novedades al iniciar y cada
   12 horas. Si la descarga automatica esta activa, verificaran SHA-256 antes de
   ofrecer la instalacion.
5. Si la comprobacion o la descarga fallan por falta de internet, la aplicacion
   reintentara automaticamente cada 5 minutos hasta recuperar la conexion.

### 4. Requisito adicional para el instalador
- Instalar Inno Setup 6 si deseas generar el `.exe` instalable final. Si no está instalado, el script dejará al menos el ejecutable empaquetado listo.

## 🛠️ Herramientas Incluidas

- **Editor de Estados (MEDEST)**: Modifica directamente el campo MEDEST en MPRODUCTO.DBF de forma segura.
- **Reporte de Disponibilidad**: Genera pivots de consumo y stock desde TFORMDET.
- **Sync SISMED**: Sincronización automática de bases de datos.
- **Consultas TFORMDET / Guías / Stock**: Generación de reportes avanzados a Excel.

## 📌 Notas
- Asegúrate de tener acceso a las rutas donde se encuentran los archivos `.DBF` del SISMED (usualmente `C:\SISMEDV2`).
- El proyecto utiliza **Flet v0.27.6** para garantizar la compatibilidad de los componentes visuales personalizados. Es crucial usar el `requirements.txt` para mantener esta versión.
- La configuración de usuario se guarda en `%APPDATA%\ToolkitOGM` y mantiene respaldo automático del archivo principal de configuración.
