# ToolKit SISMED OGM

Herramienta interna para la gestión, reportes y sincronización de datos de la plataforma SISMED.

## 🚀 Requisitos e Instalación

Para levantar este proyecto en una máquina nueva, sigue estos pasos:

### 0. Requisitos del Sistema
- **Python 3.13.x** (Recomendado para asegurar compatibilidad total).

### 1. Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/Toolkit-OGM.git
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

## 🛠️ Herramientas Incluidas

- **Editor de Estados (MEDEST)**: Modifica directamente el campo MEDEST en MMEDICAM.DBF de forma segura.
- **Reporte de Disponibilidad**: Genera pivots de consumo y stock desde TFORMDET.
- **Sync SISMED**: Sincronización automática de bases de datos.
- **Consultas TFORMDET / Guías / Stock**: Generación de reportes avanzados a Excel.

## 📌 Notas
- Asegúrate de tener acceso a las rutas donde se encuentran los archivos `.DBF` del SISMED (usualmente `C:\SISMEDV2`).
- El proyecto utiliza **Flet v0.27.6** para garantizar la compatibilidad de los componentes visuales personalizados. Es crucial usar el `requirements.txt` para mantener esta versión.