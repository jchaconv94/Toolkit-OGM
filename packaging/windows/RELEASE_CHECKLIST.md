# Release Checklist - ToolKit SISMED

## Antes del build

- Actualizar VERSION en la raiz del repositorio.
- Confirmar que la app abre desde `toolskit/main.py` sin errores del editor.
- Confirmar que `toolskit/requirements.txt` contiene solo dependencias de runtime.
- Revisar que no existan cambios sin commit ajenos al release.

## Build

- Activar el entorno virtual.
- Ejecutar `powershell -ExecutionPolicy Bypass -File packaging/windows/build_windows.ps1`.
- Verificar la existencia de `dist/ToolkitOGM/ToolkitOGM.exe`.
- Verificar la existencia de `dist/installer/ToolkitOGM-Setup-<version>.exe`.

## Smoke test del instalador

- Instalar en una ruta temporal o en `%LOCALAPPDATA%/Programs/ToolKit SISMED`.
- Confirmar que el ejecutable abre correctamente.
- Confirmar que una segunda ejecucion no deja una segunda instancia persistente.
- Confirmar que el acceso directo del menu Inicio se crea correctamente.
- Confirmar que la desinstalacion elimina la carpeta instalada y el acceso directo.

## Validaciones funcionales minimas

- Revisar apertura de la ventana principal y bandeja del sistema.
- Revisar configuraciones: autoarranque con Windows y acceso al log de configuracion.
- Revisar Sync SISMED con URL valida e invalida.
- Revisar una operacion critica de PDF para confirmar dependencias empaquetadas.

## Cierre de release

- Commit final del release.
- Push a GitHub.
- Crear tag de version si aplica.
- Adjuntar el instalador generado a la distribucion interna.