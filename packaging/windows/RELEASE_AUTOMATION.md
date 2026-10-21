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

Para firmar hace falta un segundo secreto, una sola vez:

1. En `jchaconv94/Toolkit-OGM`, entre a `Settings > Secrets and variables > Actions`.
2. Presione `New repository secret`.
3. Nombre: `UPDATE_SIGNING_KEY`.
4. Valor: la clave privada de 64 caracteres que corresponde a `packaging/windows/update_public_key.txt`.

Sin ese secreto, la version se publica solo con el instalador completo (el flujo avisa y no falla). Si alguna vez se pierde o se filtra la clave, se genera otra, se reemplaza `update_public_key.txt` y el secreto: el runtime cambia y la siguiente version llega por el instalador completo.

Para que las descargas sigan chicas, conviene no cambiar las librerias de `toolskit/requirements.txt` ni los archivos del arranque (`launcher.py`, `app_loader.py`, `update_signature.py`, el `.spec`, el `.iss` y `build_windows.ps1`) sin necesidad: cualquier cambio ahi cambia el runtime.
