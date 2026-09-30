# Release Checklist - ToolKit SISMED

## Antes del build

- Actualizar VERSION en la raiz del repositorio.
  Regla de numeracion (acordada el 2026-09-30): el ultimo numero llega hasta 10 y luego
  sube el del medio; el del medio llega hasta 10 y luego sube el primero.
  Ejemplos: 2.1.10 -> 2.2.0 -> 2.2.1 ... 2.10.10 -> 3.0.0. El actualizador compara las
  versiones como numeros, asi que 2.2.0 se reconoce como mas nueva que 2.1.10.
- Confirmar que la app abre desde `toolskit/main.py` sin errores del editor.
- Confirmar que `toolskit/requirements.txt` contiene solo dependencias de runtime.
- Revisar que no existan cambios sin commit ajenos al release.

## Build

- Activar el entorno virtual.
- Ejecutar `powershell -ExecutionPolicy Bypass -File packaging/windows/build_windows.ps1`.
- Verificar la existencia de `dist/ToolkitOGM/ToolkitOGM.exe`.
- Verificar la existencia de `dist/installer/ToolkitOGM-Setup-<version>.exe`.
- Verificar la existencia del checksum `dist/installer/ToolkitOGM-Setup-<version>.exe.sha256`.

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
- Confirmar una sola vez que existe el secreto `TOOLKITSISMED_RELEASE_TOKEN`, segun `RELEASE_AUTOMATION.md`.
- Hacer push a `main` o a una rama `release/**`.
- Esperar que la accion `Publicar actualizador de escritorio` finalice correctamente.
- Confirmar que la accion creo la Release publica `desktop-v<version>` en `jchaconv94/ToolkitSISMED`.
- Confirmar que la API publica de Releases muestra el instalador antes de distribuir la version.
