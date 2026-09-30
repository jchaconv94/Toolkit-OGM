# Clave de envío (Sync SISMED → Google Sheets)

Evita que otra PC —por ejemplo, una copia vieja del SISMED del almacén— reemplace el stock
de un establecimiento en su pestaña de Google Sheets.

## Cómo funciona

1. El informático SISMED genera la clave en **ToolkitSISMED Web → Claves de envío**, una por
   IPRESS o almacén (`030S05-K7QM-4XPA-93RD`). Las claves se gestionan solo ahí, nunca en el
   script de Google.
2. En la PC del establecimiento, en **Sync SISMED**, la pega en el campo «Clave de envío».
3. En el primer envío con esa clave, esa PC queda **vinculada**. Desde entonces es la única
   que puede enviar ese establecimiento. Otra PC —sin clave, con otra clave o con la misma
   copiada— se bloquea, la pestaña no se toca y la web avisa para «Ignorar» o «Cambiar a este
   equipo».

Los establecimientos sin clave envían como siempre.

## Qué manda el Toolkit en cada envío

En la dirección (un `doPost` de Apps Script no puede leer cabeceras):

| Parámetro   | Contenido |
|-------------|-----------|
| `equipo`    | Nombre de la PC, solo para mostrarlo en la web. |
| `equipo_id` | Identificador de la PC (`toolskit/sync_device_id.py`): sale del `MachineGuid` de Windows resumido con SHA-256, así que **no viaja si copian la carpeta o la configuración del Toolkit** a otra PC. |
| `clave`     | La clave configurada, si la hay. Varias se separan con comas. |

Sync SISMED 2.0 (Supabase) no manda ninguno de los tres.

## Qué responde el script

Si rechaza algún establecimiento, la respuesta incluye
`BLOQUEADO: 030S05=OTRO_EQUIPO,06519=SIN_CLAVE`. El Toolkit lo muestra en el log con el motivo
y lo registra como `send-key-blocked`, sin darlo por sincronizado.

| Motivo             | Qué significa |
|--------------------|---------------|
| `SIN_CLAVE`        | El establecimiento tiene clave y esta PC no la tiene configurada. |
| `CLAVE_INCORRECTA` | La clave no es la vigente (se regeneró o está mal copiada). |
| `OTRO_EQUIPO`      | La clave es correcta, pero el establecimiento está vinculado a otra PC. |
