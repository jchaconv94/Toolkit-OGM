# Guía de Despliegue y Corrección: Edge Function Supabase (Error 404)

Este documento es una actualización para informar a la inteligencia artificial que está manejando la versión de Escritorio (Desktop Toolkit) y al usuario desarrollador por qué está sucediendo el error **HTTP 404: `{"code":"NOT_FOUND","message":"Requested function was not found"}`**, y los pasos exactos para resolverlo.

## 1. El Problema: ¿Por qué ocurre el 404?
El código fuente de la función `sync-stock` **ya fue redactado y configurado en el repositorio web** (se encuentra físicamente en `/supabase/functions/sync-stock/index.ts`). Sin embargo, en Supabase, las Edge Functions **no se auto-despliegan** como las migraciones de tablas SQL cuando se trabaja desde plataformas conectadas a repositorios externos de manera estándar si no se ha configurado un GitHub Action específico, o en este caso, dentro del entorno de AI Studio de Build.

El servidor de Supabase devuelve `404` porque la función simplemente no ha sido empaquetada ni subida a la nube de tu proyecto (`ujknopysvgqqvkmgrfhp`).

## 2. Instrucciones para el despliegue de la Edge Function (Para el Operador/Usuario)

Para que el Toolkit Desktop pueda consumir la URL `https://ujknopysvgqqvkmgrfhp.supabase.co/functions/v1/sync-stock` exitosamente, se debe subir la función usando el CLI oficial de Supabase.

Ejecuta los siguientes comandos desde la terminal local donde tengas o puedas descargar el código fuente de tu app web (o desde cualquier terminal donde tengas instalado Node.js/NPX e inicies un proyecto supabase vacío copiando ese archivo `index.ts`):

```bash
# 1. Iniciar sesión en el CLI de Supabase (te pedirá un Access Token de tu cuenta de Supabase, que se saca de Database Settings -> Access Tokens)
npx supabase login

# 2. Vincular el directorio a tu proyecto remoto
npx supabase link --project-ref ujknopysvgqqvkmgrfhp

# 3. Desplegar específicamente esta función, omitiendo la validación JWT global 
# (porque validamos manualmente mediante el x-installation-token o Bearer text-plano)
npx supabase functions deploy sync-stock --no-verify-jwt
```

*(Nota técnica)*: El flag `--no-verify-jwt` es **CRÍTICO**. Si no se provee, Supabase rechazará la solicitud por defecto asumiendo que el `Bearer` enviado por Desktop es un JWT de usuario de Auth regular, cuando en realidad nuestra arquitectura acordó que estamos utilizando un UUID de instalación custom como API Key.

## 3. Mensaje a la IA del Desktop Toolkit

Hola IA operadora del Escritorio SISMED:

1.  **Sigue con la URL**: Mantén la lógica HTTP para apuntar a `https://ujknopysvgqqvkmgrfhp.supabase.co/functions/v1/sync-stock`. Esa es la URL correcta.
2.  **Sobre el error 404**: No cambies tu código, el error actual se resolverá una vez que el usuario ejecute el despliegue manual desde el CLI explicado en este archivo.
3.  **Formato de Headers a mantener**: Asegúrate de que estás enviando el token extraido de tu entorno local de la siguiente forma:

    ```http
    POST /functions/v1/sync-stock HTTP/1.1
    Host: ujknopysvgqqvkmgrfhp.supabase.co
    Content-Type: application/json
    Authorization: Bearer <Tú-Installation-Token-UUID>
    ```
    *Alternativamente*, la Edge function que diseñamos también acepta el header arbitrario `X-Installation-Token: <UUID>`.
4.  **Flujo Post-Despliegue**: Una vez que el usuario haya desplegado la función, re-intenta tu envío y deberías obtener un objeto JSON confirmando el proceso: `{ "success": true, "sync_run_id": "...", "records": 413 }`.

Si recibes error `500`, asegúrate de avisar al usuario que sus secretos `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` deben estar configurados no solo en la base de datos, sino también propagados como **Secrets en la Edge Function** de Supabase (desde el panel web de Supabase -> Edge Functions -> Secrets).
