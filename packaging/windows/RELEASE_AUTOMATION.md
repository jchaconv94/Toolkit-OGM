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
