# Backlog Tecnico de Endurecimiento

## Objetivo

Reducir fallas silenciosas del aplicativo, con prioridad en autoarranque de Windows, restauracion de instancia, Sync SISMED, diagnostico operativo y lecturas DBF inestables o corruptas.

## Fase 1 - Arranque seguro y modo degradado

Prioridad: Critica

### Tareas
- No ocultar la ventana en autorun hasta confirmar listener de restauracion listo.
- No ocultar la ventana en autorun hasta confirmar bandeja del sistema lista.
- Registrar fallas de tray, listener y arranque automatico del Sync en el log actual de configuracion.
- Dejar la app visible si el autorun entra en estado degradado.
- Eliminar capturas silenciosas de excepcion en el arranque automatico del Sync.

### Criterio de salida
- La app no queda invisible si tray o restore fallan.
- La segunda instancia no depende de una ventana aun no lista para restaurarse.
- El autorun deja evidencia en log de por que no se oculto o por que no inicio Sync.

## Fase 2 - Preflight robusto del Sync

Prioridad: Critica

### Tareas
- Validar existencia de carpeta DATOS dentro del directorio SISMED.
- Validar presencia de DBF minimos antes de iniciar auto-sync.
- Distinguir entre auto-sync deshabilitado, configuracion invalida y fallo real.
- Exponer ultimo error de autoarranque del Sync para diagnostico interno.

### Criterio de salida
- El Sync solo arranca automaticamente si la configuracion minima es consistente.
- Los rechazos de arranque quedan clasificados y logueados.

## Fase 3 - Observabilidad operativa

Prioridad: Alta
Estado: En progreso

### Tareas
- Separar eventos de boot y de sync en el log existente o en logs dedicados.
- Persistir ultimo arranque exitoso, ultimo error y ultimo sync exitoso.
- Agregar resumen de salud reutilizable por la UI sin cambiar el diseno.

### Criterio de salida
- Se puede identificar rapidamente si el fallo fue tray, registro, DBF, red o Google Apps Script.

## Fase 4 - Motor de Sync robusto

Prioridad: Alta
Estado: En progreso

### Tareas
- Sustituir la bandera simple por un evento de parada seguro.
- Evitar estados intermedios ambiguos al iniciar y detener el Sync.
- Clasificar fallos de red: timeout, DNS, TLS, proxy, HTTP no 200.
- Evaluar envio por lotes para evitar bloqueos largos o payloads excesivos.

### Criterio de salida
- El Sync responde mejor a detener/cerrar y deja errores accionables.

## Fase 5 - Robustez DBF uniforme

Prioridad: Alta
Estado: Completada

### Tareas
- Extender snapshot y parser tolerante a todos los lectores DBF relevantes.
- Contar registros omitidos o corruptos durante lecturas criticas.
- Definir umbral para abortar una sincronizacion por corrupcion excesiva.

### Criterio de salida
- Un DBF defectuoso no tumba el aplicativo ni genera cargas ciegas.

## Fase 6 - Autoarranque Windows endurecido

Prioridad: Media
Estado: Hecho (2.3.19)

### Tareas
- El arranque lo deja el instalador: acceso directo en la carpeta Inicio con `--autorun` (`toolskit/autostart.py`).
- El Toolkit ya no crea la tarea `ToolkitOGM_Autorun` ni la clave Run `ToolkitOGM_Sync`: Windows Defender lo borraba como `Behavior:Win32/Persistence.A!ml`. La primera vez toma de ellas la preferencia y las borra.
- La casilla guarda la preferencia `auto_startup`; apagada, el Toolkit abierto al encender Windows se cierra sin mostrar nada.

### Criterio de salida
- El autoarranque es mas predecible en laptops lentas o corporativas.

## Fase 7 - Matriz de pruebas de distribucion

Prioridad: Media

### Tareas
- Definir smoke tests para equipo limpio, sin internet, proxy corporativo y DBF bloqueado.
- Validar segunda instancia, tray, autorun oculto y desinstalacion.
- Incorporar estos checks al checklist de release.

### Criterio de salida
- Cada release de Windows se prueba contra escenarios de falla recurrentes.