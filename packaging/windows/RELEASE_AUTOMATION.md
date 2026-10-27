# Publicacion automatica del actualizador

El flujo `.github/workflows/publish-desktop-release.yml` prueba y compila ToolKit SISMED en Windows. Luego publica el instalador y su huella SHA-256 como una GitHub Release publica en `jchaconv94/ToolkitSISMED`.

## Configuracion unica en GitHub

Esta autorizacion se registra una sola vez. No coloque el token dentro del codigo ni lo envie por chat.

1. Ingrese a GitHub con la cuenta propietaria de ambos repositorios.
2. Abra `Settings > Developer settings > Personal access tokens > Fine-grained tokens`.
3. Cree un token limitado al repositorio `jchaconv94/ToolkitSISMED`.
4. En `Repository permissions`, conceda `Contents: Read and write`. El permiso `Metadata: Read` se agrega automaticamente.
5. Copie el token generado.
6. Abra el repositorio `jchaconv94/Toolkit-OGM`.
7. Entre a `Settings > Secrets and variables > Actions`.
8. Presione `New repository secret`.
9. Use exactamente este nombre: `TOOLKITSISMED_RELEASE_TOKEN`.
10. Pegue el token como valor y guarde el secreto.

## Publicar las siguientes versiones

1. Cambie el numero del archivo `VERSION` por uno mayor, por ejemplo de `2.0.14` a `2.0.15`.
2. Haga commit de todos los cambios del aplicativo.
3. Haga push a `main` o a una rama cuyo nombre comience con `release/`.
4. Revise la ejecucion en la pestana `Actions` del repositorio `Toolkit-OGM`.

GitHub ejecutara las pruebas, creara el instalador, verificara la descarga y publicara una Release con la etiqueta `desktop-v<version>`. Las computadoras instaladas detectaran esa Release mediante el actualizador del aplicativo.

Si la misma version ya fue publicada, el flujo se detendra para evitar reemplazar una actualizacion existente. En ese caso debe aumentar nuevamente `VERSION`.

## Actualizaciones de codigo (descargas chicas)

Desde la 2.4.4 el codigo del Toolkit va aparte del programa, en `_internal/app/app.zip` (unos 0,6 MB). Cada version publica, ademas del instalador:

- `ToolkitOGM-app-<version>.zip`: solo el codigo del Toolkit;
- `ToolkitOGM-app-<version>.json`: el manifiesto (version, runtime, huella y tamano del zip);
- `ToolkitOGM-app-<version>.json.sig`: la firma Ed25519 del manifiesto.

Las computadoras que ya tienen el mismo runtime (mismo Python, mismas librerias y mismo arranque) bajan solo el zip a `%LOCALAPPDATA%\ToolkitOGM\app\<version>` y lo abren la proxima vez que arranca el Toolkit, sin instalador ni permiso de Windows. Si el runtime cambio, usan el instalador completo, como antes. El programa verifica la firma en cada arranque; si la version nueva falla, vuelve sola a la anterior. Detalle en `toolskit/app_loader.py` y `toolskit/code_update.py`; prueba de punta a punta en `.github/workflows/probar-actualizacion-codigo.yml`.

Para no esperar al dia siguiente, el Toolkit se reinicia solo, sin mostrar nada, cuando la actualizacion ya esta descargada y verificada, la ventana lleva 20 minutos escondida en la bandeja y no hay nada trabajando (herramientas, envio de Sync SISMED, subida de backups ni el propio actualizador). Revisa cada 5 minutos, vuelve a comprobar justo antes, lo intenta como maximo dos veces por version y con 6 horas de separacion, y el Toolkit nuevo espera a que el anterior termine. Detalle en `toolskit/update_restart.py` y `toolskit/activity.py`.

Para firmar hace falta un segundo secreto, una sola vez:

1. En `jchaconv94/Toolkit-OGM`, entre a `Settings > Secrets and variables > Actions`.
2. Presione `New repository secret`.
3. Nombre: `UPDATE_SIGNING_KEY`.
4. Valor: la clave privada de 64 caracteres que corresponde a `packaging/windows/update_public_key.txt`.

Sin ese secreto, la version se publica solo con el instalador completo (el flujo avisa y no falla). Si alguna vez se pierde o se filtra la clave, se genera otra, se reemplaza `update_public_key.txt` y el secreto: el runtime cambia y la siguiente version llega por el instalador completo.

Para que las descargas sigan chicas, conviene no cambiar las librerias de `toolskit/requirements.txt` ni los archivos del arranque (`launcher.py`, `app_loader.py`, `update_signature.py`, el `.spec`, el `.iss`, `build_windows.ps1`, `build_bootloader.py` y `build-constraints.txt`) sin necesidad: cualquier cambio ahi cambia el runtime.

**Arranque de PyInstaller propio (desde la 2.4.7).** `ToolkitOGM.exe` es el arranque de PyInstaller con el programa detras. El que trae el paquete es el mismo archivo en miles de programas, tambien en programas maliciosos, y Defender lo usa de pista: puso en cuarentena la 2.4.6 como «Trojan:Win32/Bearfoos.A!ml» (falso positivo). Sin certificado de firma, `build_windows.ps1` lo compila desde su codigo en cada compilacion con `build_bootloader.py`: baja de PyPI el codigo de la misma version de PyInstaller (con la huella que publica PyPI), compila con Visual Studio (C++) y reemplaza los cuatro arranques del paquete; falla si no puede, asi que nunca sale una version con el de serie sin que se note. Lo que hizo queda en `build/bootloader/bootloader.json`. El runtime cuenta `build_bootloader.py`, no la huella del arranque (cambia en cada compilacion): el cambio llega una vez con el instalador completo y despues las PC siguen recibiendo solo el codigo. Para compilar en una PC propia hace falta Visual Studio con C++. `probar-defender.yml` (trabajo «lanzador») compila el mismo instalador con el arranque de serie (`-StockBootloader`, solo para comparar) y con el propio, y los instala y abre con Defender encendido. No es una garantia: Defender decide con aprendizaje automatico y sin firma un archivo nuevo siempre empieza sin reputacion; ayuda a no parecerse a los programas maliciosos hechos con PyInstaller.

El runtime sale del contenido de lo que se instala (Python, librerias, sus DLL y datos, Flet), no de lo que hay en el equipo de compilacion (desde la 2.4.4; antes contaban pip y todo lo instalado, y casi cada version salia con otro runtime). Para que no cambie solo, todo esta fijado: Python 3.12.10 en los flujos y cada libreria, PyInstaller incluido, en `packaging/windows/build-constraints.txt` (como regenerarlo, en su cabecera). Cada publicacion compara su runtime con el de la version anterior y lo dice en el resumen del flujo («Mismo runtime…»: las PC reciben solo el codigo; «Runtime distinto…»: llega con el instalador completo). La prueba `probar-actualizacion-codigo.yml` falla si dos compilaciones con distinto numero de version, la segunda en un entorno nuevo como cada publicacion, dan distinto runtime. El `RECORD` de cada libreria no cuenta: pip lo escribe con la huella de los lanzadores `.exe` que arma al instalar, que llevan la hora; por eso la 2.4.5 salio con otro runtime que la 2.4.4 (desde la 2.4.6 ya no). Si una version sale con otro runtime sin haber cambiado nada de lo anterior, `comparar-runtime.yml` instala las dos y dice que archivo cambio.
