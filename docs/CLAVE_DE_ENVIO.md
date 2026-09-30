# Clave de envío de Sync SISMED

Desde la versión 2.2 del script de Google (`docs/apps-script/sync_sismed_google_sheets.gs`),
cada PC puede mandar una **clave de envío** junto con el stock. La clave es **por
establecimiento** (`06519-3f9a2c7d41b8e605`) y solo permite escribir en las pestañas de ese
código.

## Por qué

- Una PC con una copia vieja del SISMED de otro lugar (por ejemplo, del almacén) pisaba la
  pestaña de ese lugar con datos antiguos y con la hora de esa PC.
- El script está publicado para «Cualquiera»: sin clave, quien conozca la dirección puede
  reemplazar o vaciar el stock de cualquier establecimiento.

## Cómo se calcula

`clave = CÓDIGO + "-" + primeros 16 hex de HMAC-SHA256(CÓDIGO, secreto de la UNGET)`.

El secreto vive en las propiedades del script de cada UNGET (`SECRETO_CLAVES`) y nunca se
muestra. No hay lista de claves que mantener: el script recalcula la clave de cada código.
Si el secreto se borra o cambia, **todas** las claves de esa UNGET dejan de valer.

El Toolkit manda la clave y el nombre del equipo en la dirección (`?clave=...&equipo=...`)
porque un `doPost` de Apps Script no puede leer cabeceras HTTP. Sync SISMED 2.0 (Supabase)
no los manda: se autentica con su token de instalación.

## Despliegue sin cortar el envío

1. **Script en modo «registrar».** Pegar el script, guardar, ejecutar `configurarRegistro()`
   y `configurarClaves()`, y publicar como *Nueva versión* de la implementación existente
   (nunca «Nueva implementación»: cambiaría la dirección). Todo se sigue aceptando; el
   registro de envíos anota si cada código llegó con clave válida, inválida o sin clave.
2. **Claves en las PC.** Ejecutar `generarClavesDeTodasLasPestanas()`: el registro de
   ejecución muestra la clave de cada establecimiento. Instalar el Toolkit nuevo en cada PC
   y pegar su clave en Sync SISMED → «Clave de envío». Para un establecimiento que aún no
   tiene pestaña, usar `generarClaveDeUnCodigo()` cambiando el código dentro de la función.
3. **Exigir.** Cuando el registro ya no muestre «sin clave», ejecutar `exigirClave()`. Desde
   ahí los códigos sin clave válida se descartan sin tocar su pestaña, y el Toolkit muestra
   «Envío parcial» o el error con el motivo. Si algo sale mal, `volverAModoRegistro()`.
