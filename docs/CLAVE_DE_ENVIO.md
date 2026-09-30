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

## Dónde se verifica: en el propio Toolkit

Antes de subir el stock, el Toolkit pregunta a ToolkitSISMED (`app_send_key_check` en
Supabase) si esta PC puede enviar cada establecimiento (`toolskit/send_key_check.py`). Lo
que no puede, **no se envía** —ni para reemplazar ni para vaciar la pestaña— y el log dice
el motivo. El ciclo queda como `send-key-blocked`.

**No se toca el script de Google de ninguna UNGET.** La regla llega a todas las PC con la
actualización automática del Toolkit.

| Motivo             | Qué significa |
|--------------------|---------------|
| `SIN_CLAVE`        | El establecimiento tiene clave y esta PC no la tiene configurada. |
| `CLAVE_INCORRECTA` | La clave no es la vigente (se regeneró o está mal copiada). |
| `OTRO_EQUIPO`      | La clave es correcta, pero el establecimiento está vinculado a otra PC. |
| `SIN_VERIFICAR`    | La web no respondió y esta PC no es la última que la web aprobó. |

Si la web no responde, pasa solo lo que la web aprobó la última vez a esta PC con esta
clave; lo que nunca tuvo clave se envía como siempre.

## También en el script de Google (v3)

El Toolkit verifica antes de enviar, pero eso no impide que alguien mande datos a mano a la
dirección del script, o que lo haga un Toolkit anterior a la 2.1.10. Para eso está el script
v3 (`docs/apps-script/sync_sismed_google_sheets.gs`): antes de escribir la pestaña de un
establecimiento con clave, pregunta a la web (`app_send_key_verify`, en
`SUPABASE_CLAVE_ENVIO_SCRIPT.sql` de ToolkitSISMED) si la clave y la PC del envío son las
vigentes. Si no lo son, no toca la pestaña y responde `BLOQUEADO: código=motivo`, que el
Toolkit ya sabe mostrar.

- Esa consulta solo lee: no vincula PC ni anota intentos (eso lo hace el Toolkit).
- Una sola consulta por envío. Un código que no tiene clave se recuerda 5 minutos sin
  volver a preguntar.
- Si la web no responde, el envío pasa como siempre (decisión del 2026-09-30).
- Sin propiedades que configurar: la clave pública va escrita en el código
  (`WEB_CLAVE_PUBLICA`). En el repositorio queda como `__CLAVE_PUBLICA__`; mientras siga así,
  el script funciona igual que la versión 2.

**Instalación en cada UNGET, una sola vez:** pegar el código, **Implementar → Administrar
implementaciones → editar → Versión: nueva versión → Implementar**. Google pide autorizar
«conectarse a un servicio externo» la primera vez. La dirección del script no cambia.

## Clave pública de Supabase

El Toolkit necesita la clave pública de Supabase (la «Publishable key», la misma que ya usa
la web). No va en el código: el flujo de publicación la toma del secreto
`SUPABASE_ANON_KEY` del repositorio y genera `toolskit/send_key_config.py` (ignorado por
git). Sin ese secreto el Toolkit no verifica nada y envía como antes. Para pruebas locales
se puede usar la variable de entorno `TOOLKIT_SUPABASE_ANON_KEY`.

## Versión del Toolkit (pestaña «Equipos» de la web)

Desde la 2.2.0, la misma consulta de la clave manda también `p_version`. La web anota qué PC
envía cada establecimiento y con qué versión (`SUPABASE_EQUIPOS_TOOLKIT.sql` en
ToolkitSISMED). Si la base todavía no tiene esa consulta, el Toolkit repite la pregunta sin
versión y la clave de envío sigue funcionando igual.
